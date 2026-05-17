"""Data-driven retrospective for LinkedIn drafts.

Compares top vs bottom performers across two cohorts:
  1. The user's own published posts (real LinkedIn analytics from
     ``learning_state.json``).
  2. Externally-uploaded reference screenshots classified by
     ``screenshot_learning.py`` into top_10_percent / bottom_90_percent.

A single LLM call distills both cohorts into ``playbook/retrospective.md``
with explicit "Do this / Avoid this" rules. The artifact is then:

  * read by ``idea_generator._load_retrospective_block`` and injected
    into the draft prompt as ``{retrospective_block}``,
  * posted as a comment on the Issue when drafts are generated so the
    reasoning is visible,
  * snapshotted to ``drafts/<date>_<slug>/retrospective_snapshot.md``
    so every Issue carries the evidence that shaped its variants.

Git history of ``playbook/retrospective.md`` IS the retrospective history —
no bespoke versioning required.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

from . import writing_client
from .screenshot_learning import (
    DEFAULT_SCREENSHOT_STATE_PATH,
    ScreenshotExample,
    ScreenshotLearningState,
)

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPT_PATH = REPO_ROOT / "prompts" / "retrospective.md"
PLAYBOOK_RETROSPECTIVE_PATH = REPO_ROOT / "playbook" / "retrospective.md"
DEFAULT_LEARNING_STATE_PATH = REPO_ROOT / "learning_state.json"

DEFAULT_TOP_N = 5
DEFAULT_BOTTOM_N = 5


# ---------------------------------------------------------------------------
# Cohort gathering
# ---------------------------------------------------------------------------


@dataclass
class PostRecord:
    """A normalized record of one post, source-agnostic."""

    source: str  # "own" or "reference"
    identifier: str  # "#92" for own posts, "ref #92" for reference
    score: float  # engagement_score (higher = better)
    metrics: dict = field(default_factory=dict)
    text_excerpt: str = ""
    signals: dict = field(default_factory=dict)
    extras: dict = field(default_factory=dict)

    def to_prompt_dict(self) -> dict:
        return {
            "identifier": self.identifier,
            "source": self.source,
            "engagement_score": round(self.score, 2),
            "metrics": self.metrics,
            "text_excerpt": self.text_excerpt,
            "signals": self.signals,
            **self.extras,
        }


@dataclass
class CohortBundle:
    """Top + bottom slices of one source, with a short summary string."""

    source_name: str  # "own published posts" or "external reference posts"
    top: list[PostRecord]
    bottom: list[PostRecord]
    total: int
    summary: str

    def is_empty(self) -> bool:
        return self.total == 0

    def top_block(self) -> str:
        return _format_records_block(self.top)

    def bottom_block(self) -> str:
        return _format_records_block(self.bottom)


def _format_records_block(records: Sequence[PostRecord]) -> str:
    if not records:
        return "(none)"
    return json.dumps([r.to_prompt_dict() for r in records], indent=2)


def gather_published_cohort(
    *,
    lookback_days: Optional[int] = None,
    state_path: Path = DEFAULT_LEARNING_STATE_PATH,
    top_n: int = DEFAULT_TOP_N,
    bottom_n: int = DEFAULT_BOTTOM_N,
) -> CohortBundle:
    """Build a CohortBundle from the user's own published posts.

    Reads ``learning_state.json``'s ``best_performing_posts``. Each entry is
    expected to carry analytics in ``analytics`` / ``metrics`` and a
    ``recorded_at`` / ``published_at`` ISO timestamp for lookback filtering.
    Until the publish→analytics loop populates this list, the cohort is empty
    and the retrospective gracefully degrades to a reference-only run.
    """
    path = Path(state_path)
    if not path.exists():
        return CohortBundle(
            source_name="own published posts",
            top=[],
            bottom=[],
            total=0,
            summary="(no learning_state.json yet — no published-post data)",
        )

    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read %s: %s", path, exc)
        return CohortBundle(
            source_name="own published posts",
            top=[],
            bottom=[],
            total=0,
            summary="(learning_state.json unreadable)",
        )

    raw_posts = state.get("best_performing_posts") or []
    cutoff = _lookback_cutoff(lookback_days)
    records: list[PostRecord] = []
    for raw in raw_posts:
        record = _normalize_published_post(raw)
        if record is None:
            continue
        if cutoff is not None:
            ts = _parse_timestamp(raw.get("recorded_at") or raw.get("published_at"))
            if ts is not None and ts < cutoff:
                continue
        records.append(record)

    if not records:
        return CohortBundle(
            source_name="own published posts",
            top=[],
            bottom=[],
            total=0,
            summary="(no published-post analytics in window)",
        )

    records.sort(key=lambda r: r.score, reverse=True)
    top = records[:top_n]
    bottom = records[-bottom_n:] if len(records) > top_n else []
    summary = f"{len(records)} posts in window; top score {top[0].score:.1f}, bottom score {records[-1].score:.1f}"
    return CohortBundle(
        source_name="own published posts",
        top=top,
        bottom=bottom,
        total=len(records),
        summary=summary,
    )


def gather_reference_cohort(
    *,
    state_path: str = DEFAULT_SCREENSHOT_STATE_PATH,
    top_n: int = DEFAULT_TOP_N,
    bottom_n: int = DEFAULT_BOTTOM_N,
) -> CohortBundle:
    """Build a CohortBundle from screenshot_learning.json."""
    state = ScreenshotLearningState.load(state_path)
    if not state.examples:
        return CohortBundle(
            source_name="external reference posts",
            top=[],
            bottom=[],
            total=0,
            summary="(no screenshot examples yet)",
        )

    by_score = sorted(state.examples, key=lambda e: e.engagement_score, reverse=True)
    top_classified = [e for e in by_score if e.classification == "top_10_percent"]
    bottom_classified = [
        e for e in reversed(by_score) if e.classification != "top_10_percent"
    ]

    top = [_record_from_screenshot(e) for e in top_classified[:top_n]]
    bottom = [_record_from_screenshot(e) for e in bottom_classified[:bottom_n]]

    summary = (
        f"{len(state.examples)} screenshots "
        f"({state.top_10_count} top, {state.bottom_90_count} bottom); "
        f"top engagement_score {by_score[0].engagement_score:.1f}, "
        f"bottom {by_score[-1].engagement_score:.1f}"
    )
    return CohortBundle(
        source_name="external reference posts",
        top=top,
        bottom=bottom,
        total=len(state.examples),
        summary=summary,
    )


def _record_from_screenshot(example: ScreenshotExample) -> PostRecord:
    return PostRecord(
        source="reference",
        identifier=f"ref #{example.issue_number}",
        score=float(example.engagement_score),
        metrics=dict(example.metrics or {}),
        text_excerpt=(example.hook_excerpt or example.summary or "")[:400],
        signals=dict(example.signals or {}),
        extras={
            "percentile": round(float(example.percentile), 3),
            "classification": example.classification,
            "summary": example.summary,
        },
    )


def _normalize_published_post(raw: dict) -> Optional[PostRecord]:
    """Best-effort normalization. Tolerates the rolling schema's evolution."""
    if not isinstance(raw, dict):
        return None
    issue_no = raw.get("github_issue_number") or raw.get("issue_number")
    sha = raw.get("source_commit_sha") or raw.get("commit_sha")
    identifier = f"#{issue_no}" if issue_no else (sha[:7] if isinstance(sha, str) else "(unknown)")

    analytics = raw.get("analytics") or raw.get("metrics") or {}
    score = (
        raw.get("engagement_score")
        or raw.get("engagement_rate")
        or _engagement_from_metrics(analytics)
    )
    try:
        score = float(score or 0.0)
    except (TypeError, ValueError):
        score = 0.0

    text = raw.get("post_text") or raw.get("body") or raw.get("hook") or ""
    return PostRecord(
        source="own",
        identifier=identifier,
        score=score,
        metrics={
            "impressions": analytics.get("impressions", 0),
            "reactions": analytics.get("reactions", 0),
            "comments": analytics.get("comments", 0),
            "reposts": analytics.get("reposts", 0),
            "saves": analytics.get("saves", 0),
        },
        text_excerpt=(text or "")[:600],
        signals=raw.get("signals") or {},
        extras={"recorded_at": raw.get("recorded_at") or raw.get("published_at")},
    )


def _engagement_from_metrics(metrics: dict) -> float:
    """Same weighting used by screenshot_learning.engagement_score."""
    if not isinstance(metrics, dict):
        return 0.0

    def _val(key: str) -> float:
        try:
            return float(metrics.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    return _val("saves") * 4.0 + _val("reposts") * 3.0 + _val("comments") * 3.0 + _val("reactions")


def _parse_timestamp(value) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _lookback_cutoff(lookback_days: Optional[int]) -> Optional[datetime]:
    if lookback_days is None or lookback_days <= 0:
        return None
    now_ts = datetime.now(timezone.utc).timestamp()
    return datetime.fromtimestamp(now_ts - lookback_days * 86400, tz=timezone.utc)


# ---------------------------------------------------------------------------
# Prompt assembly + LLM call
# ---------------------------------------------------------------------------


def _split_prompt(template: str) -> tuple[str, str]:
    system = re.search(r"^##\s+SYSTEM\s*$", template, re.MULTILINE)
    user = re.search(r"^##\s+USER\s*$", template, re.MULTILINE)
    if not system or not user:
        raise ValueError("prompts/retrospective.md must contain ## SYSTEM and ## USER")
    return template[system.end():user.start()].strip(), template[user.end():].strip()


def build_retrospective_prompts(
    published: CohortBundle,
    reference: CohortBundle,
    *,
    lookback_days: Optional[int] = None,
) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) ready to send to the writing client."""
    if not PROMPT_PATH.exists():
        raise FileNotFoundError(f"Prompt template missing: {PROMPT_PATH}")
    template = PROMPT_PATH.read_text(encoding="utf-8")
    system_template, user_template = _split_prompt(template)

    window = "all published posts" if not lookback_days else f"last {lookback_days} days"
    user_prompt = user_template.format(
        lookback_window=window,
        published_cohort_summary=published.summary,
        published_top_block=published.top_block(),
        published_bottom_block=published.bottom_block(),
        reference_cohort_summary=reference.summary,
        reference_top_block=reference.top_block(),
        reference_bottom_block=reference.bottom_block(),
    )
    return system_template, user_prompt


@dataclass
class RetrospectiveReport:
    markdown: str
    published: CohortBundle
    reference: CohortBundle
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def generate_retrospective(
    published: CohortBundle,
    reference: CohortBundle,
    *,
    lookback_days: Optional[int] = None,
    client=None,
) -> RetrospectiveReport:
    """One LLM call — returns the structured Markdown plus the cohort context."""
    if published.is_empty() and reference.is_empty():
        return RetrospectiveReport(
            markdown=_empty_retrospective_markdown(lookback_days),
            published=published,
            reference=reference,
        )

    if client is None:
        client = writing_client.get_client()
    if client is None:
        raise RuntimeError(
            "OpenAI writing client unavailable. Set OPENAI_API_KEY and install openai."
        )

    system_prompt, user_prompt = build_retrospective_prompts(
        published, reference, lookback_days=lookback_days
    )
    markdown = writing_client.generate_text(client, system_prompt, user_prompt)
    return RetrospectiveReport(
        markdown=markdown.strip() + "\n",
        published=published,
        reference=reference,
    )


def _empty_retrospective_markdown(lookback_days: Optional[int]) -> str:
    window = "all published posts" if not lookback_days else f"last {lookback_days} days"
    return (
        f"# LinkedIn Retrospective — {window}\n\n"
        "## Snapshot\n\n"
        "No cohort data yet. Publish posts so analytics-update can collect them, "
        "or upload reference screenshots via the `social-screenshot` Issue template. "
        "Drafts will fall back to the voice + patterns playbooks until this populates.\n"
    )


# ---------------------------------------------------------------------------
# Writing artifacts
# ---------------------------------------------------------------------------


def write_retrospective(
    report: RetrospectiveReport,
    *,
    target_path: Path = PLAYBOOK_RETROSPECTIVE_PATH,
) -> Path:
    """Write the markdown to playbook/retrospective.md (overwriting)."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(report.markdown, encoding="utf-8")
    logger.info("Wrote retrospective: %s", target_path)
    return target_path


def snapshot_for_issue(
    target_dir: Path,
    *,
    retrospective_path: Path = PLAYBOOK_RETROSPECTIVE_PATH,
) -> Optional[Path]:
    """Freeze the current retrospective alongside an Issue's drafts.

    Returns the snapshot path, or None if no retrospective exists yet.
    """
    if not retrospective_path.exists():
        return None
    target_dir.mkdir(parents=True, exist_ok=True)
    dest = target_dir / "retrospective_snapshot.md"
    shutil.copyfile(retrospective_path, dest)
    return dest


# ---------------------------------------------------------------------------
# Issue comment formatting (called by idea_generator.run)
# ---------------------------------------------------------------------------


_DO_THIS_RE = re.compile(r"^##\s+Do this\s*$.*?(?=^##\s|\Z)", re.MULTILINE | re.DOTALL)
_AVOID_RE = re.compile(r"^##\s+Avoid this\s*$.*?(?=^##\s|\Z)", re.MULTILINE | re.DOTALL)
_SNAPSHOT_RE = re.compile(r"^##\s+Snapshot\s*$.*?(?=^##\s|\Z)", re.MULTILINE | re.DOTALL)


def build_issue_comment(retrospective_markdown: str, repo_relative_path: str = "playbook/retrospective.md") -> str:
    """Compose the per-Issue retrospective comment.

    We pull the Snapshot + Do this + Avoid this sections (the load-bearing
    parts) and link to the full file. Full body of the retrospective lives
    in playbook/retrospective.md.
    """
    snapshot = _section_or_empty(_SNAPSHOT_RE, retrospective_markdown, "Snapshot")
    do_this = _section_or_empty(_DO_THIS_RE, retrospective_markdown, "Do this")
    avoid = _section_or_empty(_AVOID_RE, retrospective_markdown, "Avoid this")

    parts = [
        "### Retrospective driving these drafts",
        "",
        f"_Distilled from past published posts + uploaded reference screenshots. Full file: `{repo_relative_path}`._",
        "",
    ]
    if snapshot:
        parts.extend([snapshot.strip(), ""])
    if do_this:
        parts.extend([do_this.strip(), ""])
    if avoid:
        parts.extend([avoid.strip(), ""])
    return "\n".join(parts).strip() + "\n"


def _section_or_empty(pattern: re.Pattern[str], text: str, fallback_heading: str) -> str:
    match = pattern.search(text or "")
    if not match:
        return ""
    return match.group(0).strip()


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------


def run_refresh(
    *,
    lookback_days: Optional[int] = 60,
    client=None,
    dry_run: bool = False,
    target_path: Path = PLAYBOOK_RETROSPECTIVE_PATH,
) -> RetrospectiveReport:
    """Gather → generate → write. Returns the report.

    When dry_run is True, the report is computed but nothing is written.
    """
    published = gather_published_cohort(lookback_days=lookback_days)
    reference = gather_reference_cohort()
    report = generate_retrospective(
        published, reference, lookback_days=lookback_days, client=client
    )
    if not dry_run:
        write_retrospective(report, target_path=target_path)
    return report
