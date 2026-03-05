"""Weekly self-improvement loop for tuning generation settings."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests
from ruamel.yaml import YAML

from .analytics import LearningState

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


@dataclass
class ImprovementContext:
    """Signals extracted from issue backlog and learning state."""

    total_social_issues: int = 0
    open_social_issues: int = 0
    open_unpublished: int = 0
    stale_unpublished_7d: int = 0
    old_unreviewed_72h: int = 0


def _github_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def fetch_social_post_issues(repo: str, token: str, state: str = "all") -> list[dict]:
    """Fetch social-post issues from GitHub (excluding pull requests)."""
    issues: list[dict] = []
    page = 1
    while True:
        resp = requests.get(
            f"{GITHUB_API}/repos/{repo}/issues",
            headers=_github_headers(token),
            params={"state": state, "labels": "social-post", "per_page": 100, "page": page},
            timeout=30,
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        for issue in batch:
            if "pull_request" not in issue:
                issues.append(issue)
        if len(batch) < 100:
            break
        page += 1
    return issues


def _parse_iso(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _status_from_labels(issue: dict) -> str:
    for label in issue.get("labels", []):
        name = label.get("name", "")
        if name.startswith("status:"):
            return name.split(":", 1)[1]
    return "draft"


def build_improvement_context(issues: list[dict], now: Optional[datetime] = None) -> ImprovementContext:
    """Build a compact health summary from social post issues."""
    if now is None:
        now = datetime.now(timezone.utc)

    ctx = ImprovementContext(total_social_issues=len(issues))
    for issue in issues:
        is_open = issue.get("state") == "open"
        if is_open:
            ctx.open_social_issues += 1

        status = _status_from_labels(issue)
        is_unpublished = status in {"draft", "approved"}
        if is_open and is_unpublished:
            ctx.open_unpublished += 1

            created_at = _parse_iso(issue.get("created_at", ""))
            updated_at = _parse_iso(issue.get("updated_at", ""))
            age_anchor = created_at or updated_at

            if age_anchor and now - age_anchor >= timedelta(days=7):
                ctx.stale_unpublished_7d += 1

            # Old and untouched issues are weak garbage signals.
            comments = int(issue.get("comments", 0) or 0)
            if age_anchor and now - age_anchor >= timedelta(hours=72) and comments == 0:
                ctx.old_unreviewed_72h += 1

    return ctx


def _reason_count(state: LearningState, keys: list[str]) -> int:
    total = 0
    normalized = {k.lower().strip(): v for k, v in state.not_published_reasons.items()}
    for key in keys:
        total += int(normalized.get(key.lower(), 0))
    return total


def apply_config_tunings(config_path: str, state: LearningState, ctx: ImprovementContext) -> list[str]:
    """
    Apply deterministic tuning rules to config.yaml and return change notes.

    The rules are intentionally conservative to avoid destabilizing generation.
    """
    path = Path(config_path)
    if not path.exists():
        logger.warning("Config path not found: %s", config_path)
        return []

    ryaml = YAML()
    ryaml.preserve_quotes = True
    with path.open(encoding="utf-8") as fh:
        config = ryaml.load(fh) or {}

    agent = config.setdefault("agent", {})
    post_gen = config.setdefault("post_generation", {})

    changes: list[str] = []

    score_threshold = float(agent.get("score_threshold", 15.0))
    max_posts = int(agent.get("max_posts_per_run", 10))
    max_chars = int(post_gen.get("linkedin_max_chars", 1500))

    too_long_count = _reason_count(state, ["too long", "too_long"])
    not_relevant_count = _reason_count(state, ["not relevant", "not_relevant"])
    stale_signal_count = _reason_count(state, ["stale_unpublished_7d"])

    if (ctx.stale_unpublished_7d >= 3 or stale_signal_count >= 3) and score_threshold < 40:
        new_threshold = min(40.0, score_threshold + 5.0)
        if new_threshold != score_threshold:
            agent["score_threshold"] = round(new_threshold, 1)
            changes.append(f"Raised `agent.score_threshold` from {score_threshold:.1f} to {new_threshold:.1f}")
            score_threshold = new_threshold

    if (ctx.open_unpublished >= 12 or ctx.old_unreviewed_72h >= 6) and max_posts > 5:
        new_max_posts = max(5, max_posts - 2)
        if new_max_posts != max_posts:
            agent["max_posts_per_run"] = new_max_posts
            changes.append(f"Reduced `agent.max_posts_per_run` from {max_posts} to {new_max_posts}")
            max_posts = new_max_posts

    if too_long_count >= 3 and max_chars > 1200:
        new_max_chars = max(1200, max_chars - 150)
        if new_max_chars != max_chars:
            post_gen["linkedin_max_chars"] = new_max_chars
            changes.append(f"Reduced `post_generation.linkedin_max_chars` from {max_chars} to {new_max_chars}")
            max_chars = new_max_chars

    if not_relevant_count >= 3 and score_threshold < 45:
        new_threshold = min(45.0, score_threshold + 5.0)
        if new_threshold != score_threshold:
            agent["score_threshold"] = round(new_threshold, 1)
            changes.append(f"Raised `agent.score_threshold` from {score_threshold:.1f} to {new_threshold:.1f}")

    if changes:
        with path.open("w", encoding="utf-8") as fh:
            ryaml.dump(config, fh)

    return changes


def render_self_improvement_report(
    state: LearningState,
    ctx: ImprovementContext,
    changes: list[str],
    config_path: str,
) -> str:
    """Render a markdown report for weekly self-improvement PRs."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    reasons = sorted(state.not_published_reasons.items(), key=lambda x: -x[1])[:8]
    reason_lines = "\n".join(f"- `{reason}`: {count}" for reason, count in reasons) or "- None yet"
    change_lines = "\n".join(f"- {c}" for c in changes) or "- No config changes this run"

    return "\n".join(
        [
            "# Weekly Self-Improvement Report",
            "",
            f"_Generated: {now}_",
            "",
            "## Backlog Signals",
            "",
            f"- Total social post issues: **{ctx.total_social_issues}**",
            f"- Open social post issues: **{ctx.open_social_issues}**",
            f"- Open unpublished issues: **{ctx.open_unpublished}**",
            f"- Stale unpublished (>=7d): **{ctx.stale_unpublished_7d}**",
            f"- Old unreviewed (>=72h, no comments): **{ctx.old_unreviewed_72h}**",
            "",
            "## Not-Published Reasons (Top)",
            "",
            reason_lines,
            "",
            f"## Config Updates ({config_path})",
            "",
            change_lines,
            "",
            "## Next Focus",
            "",
            "- Keep collecting quick mobile feedback (reactions + short comments)",
            "- If stale backlog keeps growing, tighten commit selection and reduce post volume",
            "- Promote winning hook and topic patterns from recent analytics",
            "",
        ]
    )


def run_self_improvement_cycle(
    repo: str,
    token: str,
    learning_state_path: str = "learning_state.json",
    config_path: str = "config.yaml",
    report_output: str = "SELF_IMPROVEMENT.md",
    apply: bool = False,
) -> tuple[list[str], ImprovementContext]:
    """
    Run the weekly self-improvement cycle.

    Returns:
      (applied_changes, context)
    """
    state = LearningState.load(learning_state_path)
    issues = fetch_social_post_issues(repo, token, state="all")
    ctx = build_improvement_context(issues)

    changes: list[str] = []
    if apply:
        changes = apply_config_tunings(config_path, state, ctx)

    report = render_self_improvement_report(state, ctx, changes, config_path=config_path)
    Path(report_output).write_text(report, encoding="utf-8")
    logger.info("Wrote self-improvement report to %s", report_output)

    return changes, ctx
