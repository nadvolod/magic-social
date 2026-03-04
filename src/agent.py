"""
GitHub Commit → Social Post Agent

Main orchestrator that runs the full pipeline:
  1. Scan recent commits for lesson-worthy content
  2. Score and filter commits
  3. Generate LinkedIn-first posts (with X thread + IG caption)
  4. Store each post as a GitHub Issue
  5. Request analytics for published posts
  6. Update learning state from collected analytics
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from .analytics import (
    LearningState,
    _apply_qualitative_feedback,
    fetch_issue_analytics,
    fetch_issue_feedback,
    get_analytics_prompt,
    get_best_hook_pattern,
    update_learning_state,
)
from .commit_scanner import scan_all_user_commits, scan_commits
from .experiments import ExperimentManager, EXPERIMENT_PLAN
from .github_storage import (
    add_analytics_comment,
    create_post_issue,
    get_analytics_request_message,
    update_issue_status,
)
from .models import Post, PostStatus
from .post_generator import HOOK_PATTERNS, generate_post
from .scoring import SCORE_THRESHOLD

logger = logging.getLogger(__name__)

# Default paths for persistent state files
DEFAULT_LEARNING_STATE_PATH = "learning_state.json"
DEFAULT_EXPERIMENTS_PATH = "experiments.json"

# How many days back to scan for commits when no 'since' date is provided
DEFAULT_SCAN_DAYS = 7
DEFAULT_MAX_OPEN_UNPUBLISHED = 10
DEFAULT_MAX_STALE_UNPUBLISHED = 4
DEFAULT_STALE_DAYS = 7


@dataclass
class BacklogStats:
    """Backlog health summary for open social-post issues."""

    total_open_social: int = 0
    open_unpublished: int = 0
    stale_unpublished: int = 0


def _issue_status_from_labels(labels: list[dict]) -> Optional[str]:
    """Return the issue status from status:* labels."""
    for label in labels:
        name = label.get("name", "")
        if name.startswith("status:"):
            return name.split(":", 1)[1]
    return None


def _parse_iso_datetime(value: str) -> Optional[datetime]:
    """Parse ISO timestamp into timezone-aware datetime."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def fetch_social_post_backlog(
    repo: str,
    token: str,
    stale_days: int = DEFAULT_STALE_DAYS,
) -> BacklogStats:
    """
    Fetch open social-post issues and compute backlog health stats.

    Unpublished backlog includes `status:draft` and `status:approved`.
    Stale backlog includes unpublished issues older than `stale_days`.
    """
    import requests as _requests  # noqa: PLC0415

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    stats = BacklogStats()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=stale_days)

    page = 1
    while True:
        url = f"https://api.github.com/repos/{repo}/issues"
        resp = _requests.get(
            url,
            headers=headers,
            params={"state": "open", "labels": "social-post", "per_page": 100, "page": page},
            timeout=30,
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break

        for issue in batch:
            if "pull_request" in issue:
                continue
            stats.total_open_social += 1
            status = _issue_status_from_labels(issue.get("labels", [])) or "draft"
            if status not in (PostStatus.DRAFT.value, PostStatus.APPROVED.value):
                continue

            stats.open_unpublished += 1
            created_at = _parse_iso_datetime(issue.get("created_at", ""))
            if created_at is not None and created_at <= cutoff:
                stats.stale_unpublished += 1

        if len(batch) < 100:
            break
        page += 1

    return stats


def _get_openai_client():
    """Return an openai.OpenAI client if the API key is set, else None."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        logger.warning("OPENAI_API_KEY not set — posts will use placeholder content")
        return None
    try:
        import openai  # noqa: PLC0415
        return openai.OpenAI(api_key=api_key)
    except ImportError:
        logger.warning("openai package not installed — posts will use placeholder content")
        return None


def run_scan(
    repo: Optional[str] = None,
    token: str = "",
    since: Optional[str] = None,
    branch: str = "main",
    max_posts: int = 10,
    learning_state_path: str = DEFAULT_LEARNING_STATE_PATH,
    experiments_path: str = DEFAULT_EXPERIMENTS_PATH,
    dry_run: bool = False,
    username: Optional[str] = None,
    threshold: float = SCORE_THRESHOLD,
    backlog_throttle_enabled: bool = True,
    max_open_unpublished: int = DEFAULT_MAX_OPEN_UNPUBLISHED,
    max_stale_unpublished: int = DEFAULT_MAX_STALE_UNPUBLISHED,
    stale_days: int = DEFAULT_STALE_DAYS,
) -> list[Post]:
    """
    Run a full commit scan → post generation → GitHub Issue creation cycle.

    Args:
        repo:                 Full repo name (owner/repo).  Mutually exclusive with username.
        token:                GitHub token with repo + issues write access.
        since:                ISO 8601 date string; only scan commits after this.
        branch:               Branch to scan.
        max_posts:            Maximum posts to generate per run.
        learning_state_path:  Path to the learning state JSON file.
        experiments_path:     Path to the experiments JSON file.
        dry_run:              If True, print posts but don't create issues.
        username:             GitHub username — scan ALL repos for this user.
        threshold:            Minimum commit score to qualify for post generation.
        backlog_throttle_enabled:
                              If True, pause generation when draft backlog is too high.
        max_open_unpublished: Maximum allowed open unpublished social-post issues.
        max_stale_unpublished:
                              Maximum allowed stale unpublished issues before pausing.
        stale_days:           Age threshold (days) for stale unpublished issues.

    Returns:
        List of generated Post objects.
    """
    if not repo and not username:
        raise ValueError("Either 'repo' or 'username' must be provided.")
    if since is None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=DEFAULT_SCAN_DAYS)
        since = cutoff.isoformat()

    logger.info("Starting commit scan (since=%s)", since)

    # Backlog throttle: pause generation when too many unpublished drafts accumulate.
    if backlog_throttle_enabled and not dry_run and repo:
        backlog = fetch_social_post_backlog(repo, token, stale_days=stale_days)
        if (
            backlog.open_unpublished >= max_open_unpublished
            or backlog.stale_unpublished >= max_stale_unpublished
        ):
            logger.warning(
                "Backlog throttle activated for %s: open_unpublished=%d (limit=%d), "
                "stale_unpublished=%d (limit=%d).",
                repo,
                backlog.open_unpublished,
                max_open_unpublished,
                backlog.stale_unpublished,
                max_stale_unpublished,
            )
            print(
                "⏸ Backlog throttle activated — skipping new draft generation.\n"
                f"Open unpublished: {backlog.open_unpublished} (limit {max_open_unpublished})\n"
                f"Stale unpublished (>{stale_days}d): {backlog.stale_unpublished} "
                f"(limit {max_stale_unpublished})"
            )
            return []

    # Load persistent state
    learning_state = LearningState.load(learning_state_path)
    experiments = ExperimentManager(experiments_path)

    # Get or start an experiment
    active_exp = experiments.get_active_experiment()
    if active_exp is None:
        active_exp = experiments.start_next_experiment()

    # Pick the best hook pattern from learning state
    best_hook = get_best_hook_pattern(learning_state)

    # Scan commits — either a single repo or all repos for a user
    if username:
        logger.info("Scanning all repositories for user %s", username)
        source_commits = scan_all_user_commits(
            username, token, since=since, branch=branch, threshold=threshold
        )
    else:
        logger.info("Scanning commits for %s (branch=%s)", repo, branch)
        source_commits = scan_commits(
            repo, token, since=since, branch=branch, threshold=threshold  # type: ignore[arg-type]
        )
    if not source_commits:
        logger.info("No lesson-worthy commits found.")
        return []

    # Generate posts
    openai_client = _get_openai_client()
    generated_posts: list[Post] = []

    for source in source_commits[:max_posts]:
        # Determine hook pattern: use experiment variant if active, else best from learning
        hook_pattern = best_hook
        experiment_id = None
        experiment_variant = None

        if active_exp is not None:
            from .models import ExperimentVariable  # noqa: PLC0415
            if active_exp.variable == ExperimentVariable.HOOK_STYLE:
                experiment_variant = experiments.assign_variant(active_exp)
                hook_pattern = experiment_variant
                experiment_id = active_exp.id

        post = generate_post(
            source=source,
            hook_pattern=hook_pattern,
            experiment_id=experiment_id,
            experiment_variant=experiment_variant,
            openai_client=openai_client,
        )

        if dry_run:
            print("\n" + "=" * 60)
            print(f"DRY RUN — Post for commit {source.sha[:8]}")
            print("=" * 60)
            print(post.linkedin_post)
            print("\n--- X Thread ---")
            print(post.x_thread)
            print("\n--- IG Caption ---")
            print(post.ig_caption)
            generated_posts.append(post)
            continue

        # Store as GitHub Issue
        issue_number = create_post_issue(post, repo, token)
        post.github_issue_number = issue_number
        generated_posts.append(post)

        logger.info("Created post %s → Issue #%d", post.id, issue_number)

    return generated_posts


def run_analytics_collection(
    repo: str,
    token: str,
    posts: list[Post],
    learning_state_path: str = DEFAULT_LEARNING_STATE_PATH,
    experiments_path: str = DEFAULT_EXPERIMENTS_PATH,
) -> None:
    """
    Check for analytics on published posts and update the learning state.

    For each post with a GitHub Issue, this:
    1. Collects qualitative feedback regardless of post status or analytics presence.
       (Rejections are the most important signal — we need to know *why* posts
       weren't published even when no engagement data exists.)
    2. For published posts that have analytics: runs the full quantitative learning loop.
    3. For published posts without analytics yet: prints a prompt asking the user to enter them.
    """
    learning_state = LearningState.load(learning_state_path)
    experiments = ExperimentManager(experiments_path)

    for post in posts:
        if post.github_issue_number is None:
            continue

        # --- Pass 1: collect qualitative feedback for every post ---
        # This runs regardless of status so that rejection reasons from
        # non-published (draft/archived) posts are also captured.
        feedback = fetch_issue_feedback(repo, token, post.github_issue_number, post.id)
        if feedback is not None:
            _apply_qualitative_feedback(learning_state, feedback)
            learning_state.save(learning_state_path)

        # --- Pass 2: quantitative analytics (published posts only) ---
        if post.status != PostStatus.PUBLISHED:
            continue

        analytics = fetch_issue_analytics(repo, token, post.github_issue_number, post.id)

        if analytics is None:
            # No analytics yet — prompt the user
            print(get_analytics_request_message(post, post.github_issue_number, repo))
            continue

        # Update learning state with quantitative data (feedback already applied above)
        learning_state = update_learning_state(learning_state, post, analytics)
        learning_state.save(learning_state_path)

        # Record experiment results
        if post.experiment_id and post.experiment_variant:
            for exp in experiments.experiments:
                if exp.id == post.experiment_id:
                    experiments.record_result(
                        exp,
                        post.id,
                        post.experiment_variant,
                        analytics.engagement_score,
                    )
                    break

        # Mark analytics as collected on the issue
        add_analytics_comment(repo, token, post.github_issue_number, analytics)
        update_issue_status(repo, token, post.github_issue_number, PostStatus.PUBLISHED)

        logger.info(
            "Analytics processed for post %s (score=%.1f, rate=%.2f%%)",
            post.id,
            analytics.engagement_score,
            analytics.engagement_rate,
        )


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="GitHub Commit → Social Post Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Scan commits and generate posts (dry run)
  python -m src.agent scan --repo owner/repo --dry-run

  # Scan and create GitHub Issues
  python -m src.agent scan --repo owner/repo

  # Pause generation automatically if draft backlog is high
  python -m src.agent scan --repo owner/repo --max-open-unpublished 8 --max-stale-unpublished 3

  # Collect analytics for published posts (posts provided via stdin JSON)
  python -m src.agent analytics --repo owner/repo --posts posts.json

  # Show experiment summary
  python -m src.agent experiments

  # Show learning state summary (feedback, ratings, not-published reasons)
  python -m src.agent feedback --summary
        """,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # scan command
    scan_parser = subparsers.add_parser("scan", help="Scan commits and generate posts")
    repo_group = scan_parser.add_mutually_exclusive_group(required=True)
    repo_group.add_argument("--repo", help="GitHub repo (owner/repo)")
    repo_group.add_argument("--username", help="GitHub username — scan ALL repos for this user")
    scan_parser.add_argument("--branch", default="main", help="Branch to scan")
    scan_parser.add_argument("--since", help="ISO 8601 date (e.g. 2024-01-01T00:00:00Z)")
    scan_parser.add_argument("--max-posts", type=int, default=10, help="Max posts per run")
    scan_parser.add_argument("--dry-run", action="store_true", help="Print posts, don't create issues")
    scan_parser.add_argument("--threshold", type=float, default=SCORE_THRESHOLD, help="Min score threshold")
    scan_parser.add_argument(
        "--disable-backlog-throttle",
        action="store_true",
        help="Disable backlog throttle and always generate drafts",
    )
    scan_parser.add_argument(
        "--max-open-unpublished",
        type=int,
        default=DEFAULT_MAX_OPEN_UNPUBLISHED,
        help="Backlog throttle limit for open unpublished draft issues",
    )
    scan_parser.add_argument(
        "--max-stale-unpublished",
        type=int,
        default=DEFAULT_MAX_STALE_UNPUBLISHED,
        help="Backlog throttle limit for stale unpublished draft issues",
    )
    scan_parser.add_argument(
        "--stale-days",
        type=int,
        default=DEFAULT_STALE_DAYS,
        help="Issue age threshold in days for stale backlog detection",
    )

    # analytics command
    analytics_parser = subparsers.add_parser("analytics", help="Collect analytics for published posts")
    analytics_parser.add_argument("--repo", required=True)
    analytics_parser.add_argument("--posts", help="JSON file containing list of Post objects")

    # experiments command
    subparsers.add_parser("experiments", help="Show experiment summary")

    # feedback command
    feedback_parser = subparsers.add_parser(
        "feedback",
        help="Show feedback summary from the learning state",
    )
    feedback_parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a summary of collected feedback and learning signals",
    )
    feedback_parser.add_argument(
        "--state",
        default=DEFAULT_LEARNING_STATE_PATH,
        help="Path to the learning state JSON file",
    )

    # metrics command
    metrics_parser = subparsers.add_parser(
        "metrics",
        help="Generate METRICS.md dashboard from current learning state",
    )
    metrics_parser.add_argument(
        "--output",
        default="METRICS.md",
        help="Output file path (default: METRICS.md)",
    )
    metrics_parser.add_argument(
        "--state",
        default=DEFAULT_LEARNING_STATE_PATH,
        help="Path to the learning state JSON file",
    )
    metrics_parser.add_argument(
        "--experiments",
        default=DEFAULT_EXPERIMENTS_PATH,
        help="Path to the experiments JSON file",
    )

    # backfill-feedback command
    backfill_parser = subparsers.add_parser(
        "backfill-feedback",
        help="Post a minimal feedback request comment on all open social-post issues that don't have one yet",
    )
    backfill_parser.add_argument("--repo", required=True, help="GitHub repo (owner/repo)")
    backfill_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print which issues would receive a comment without actually posting",
    )

    # linkedin-poll command
    linkedin_parser = subparsers.add_parser(
        "linkedin-poll",
        help="Poll LinkedIn API for post engagement metrics and follower count",
    )
    linkedin_parser.add_argument(
        "--max-posts",
        type=int,
        default=10,
        help="Maximum number of recent posts to fetch engagement for (default: 10)",
    )
    linkedin_parser.add_argument(
        "--output",
        default="linkedin_metrics.json",
        help="Path to write the snapshot history (default: linkedin_metrics.json)",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    token = os.environ.get("GITHUB_TOKEN")
    if args.command not in ("experiments", "feedback", "metrics", "linkedin-poll") and not token:
        print("Error: GITHUB_TOKEN environment variable is required", file=sys.stderr)
        sys.exit(1)

    if args.command == "scan":
        posts = run_scan(
            repo=args.repo,
            token=token,
            since=args.since,
            branch=args.branch,
            max_posts=args.max_posts,
            dry_run=args.dry_run,
            username=args.username,
            threshold=args.threshold,
            backlog_throttle_enabled=not args.disable_backlog_throttle,
            max_open_unpublished=args.max_open_unpublished,
            max_stale_unpublished=args.max_stale_unpublished,
            stale_days=args.stale_days,
        )
        print(f"\n✅ Generated {len(posts)} post(s).")

    elif args.command == "analytics":
        import json as _json  # noqa: PLC0415
        posts = []
        if args.posts:
            with open(args.posts) as f:
                posts_data = _json.load(f)
            from .models import Post as _Post  # noqa: PLC0415
            posts = [_Post.from_dict(p) for p in posts_data]
        run_analytics_collection(repo=args.repo, token=token, posts=posts)

    elif args.command == "experiments":
        manager = ExperimentManager()
        print(manager.summary())

    elif args.command == "feedback":
        _print_feedback_summary(getattr(args, "state", DEFAULT_LEARNING_STATE_PATH))

    elif args.command == "metrics":
        output = generate_metrics_report(
            learning_state_path=getattr(args, "state", DEFAULT_LEARNING_STATE_PATH),
            experiments_path=getattr(args, "experiments", DEFAULT_EXPERIMENTS_PATH),
        )
        out_file = getattr(args, "output", "METRICS.md")
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"✅ METRICS.md written to {out_file}")

    elif args.command == "backfill-feedback":
        count = backfill_feedback_comments(
            repo=args.repo,
            token=token,
            dry_run=args.dry_run,
        )
        verb = "Would comment on" if args.dry_run else "Commented on"
        print(f"\n✅ {verb} {count} issue(s).")

    elif args.command == "linkedin-poll":
        linkedin_token = os.environ.get("LINKEDIN_ACCESS_TOKEN")
        if not linkedin_token:
            print(
                "Error: LINKEDIN_ACCESS_TOKEN environment variable is required.\n"
                "Set it to your LinkedIn OAuth 2.0 access token.\n"
                "See README.md for setup instructions.",
                file=sys.stderr,
            )
            sys.exit(1)
        run_linkedin_poll(
            access_token=linkedin_token,
            max_posts=args.max_posts,
            output=args.output,
        )


def backfill_feedback_comments(repo: str, token: str, dry_run: bool = False) -> int:
    """
    Find all open GitHub Issues with the 'social-post' label and post a minimal
    feedback request comment on any that don't already have one.

    Returns the number of issues that received (or would receive) a comment.
    """
    import requests as _requests  # noqa: PLC0415

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    # Fetch all open issues with the social-post label
    issues: list[dict] = []
    page = 1
    while True:
        url = f"https://api.github.com/repos/{repo}/issues"
        resp = _requests.get(
            url,
            headers=headers,
            params={"state": "open", "labels": "social-post", "per_page": 100, "page": page},
            timeout=30,
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        issues.extend(batch)
        page += 1

    logger.info("Found %d open social-post issues in %s", len(issues), repo)

    # Minimal feedback template — as short as possible while still being parseable
    feedback_template = (
        "## Post Feedback\n\n"
        "Add your feedback by editing this comment or replying below — "
        "it takes under 30 seconds:\n\n"
        "```\n"
        "## Post Feedback\n\n"
        "- Published: yes / no\n"
        "- If not published, why: quality / style / not relevant / too long / too technical / other\n"
        "- What would make it better: \n"
        "- Rating (1-5): \n"
        "```\n\n"
        "_Your feedback is used to improve future post generation. "
        "Every rating helps — even a simple 1–5 number is valuable._"
    )

    count = 0
    for issue in issues:
        issue_number = issue["number"]
        title = issue.get("title", "")

        # Check if a feedback comment already exists
        comments_url = f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments"
        comments_resp = _requests.get(comments_url, headers=headers, params={"per_page": 100}, timeout=30)
        comments_resp.raise_for_status()
        existing_comments = comments_resp.json()

        already_has_feedback = any(
            "Post Feedback" in c.get("body", "")
            for c in existing_comments
        )
        # Also check the issue body itself (new issues already have the template)
        if "Post Feedback" in issue.get("body", ""):
            already_has_feedback = True

        if already_has_feedback:
            logger.debug("Issue #%d already has a feedback section — skipping", issue_number)
            continue

        if dry_run:
            print(f"  [dry-run] Would post feedback request on #{issue_number}: {title[:70]}")
        else:
            post_resp = _requests.post(
                comments_url,
                headers=headers,
                json={"body": feedback_template},
                timeout=30,
            )
            post_resp.raise_for_status()
            print(f"  ✓ Posted feedback request on #{issue_number}: {title[:70]}")
            logger.info("Posted feedback comment on issue #%d", issue_number)

        count += 1

    return count


def run_linkedin_poll(
    access_token: str,
    max_posts: int = 10,
    output: str = "linkedin_metrics.json",
) -> None:
    """
    Poll the LinkedIn API, save the snapshot, and print a summary.
    """
    from .linkedin_api import poll_linkedin, save_snapshot  # noqa: PLC0415

    snapshot = poll_linkedin(access_token, max_posts=max_posts)
    save_snapshot(snapshot, path=output)

    print("\n📊 LinkedIn Metrics Snapshot")
    print("=" * 50)
    print(f"Recorded at:         {snapshot.recorded_at[:19].replace('T', ' ')} UTC")
    print(f"Followers/connections: {snapshot.follower_count:,}")
    print(f"Posts fetched:       {len(snapshot.post_metrics)}")
    if snapshot.post_metrics:
        print("\nPost engagement:")
        for pm in snapshot.post_metrics:
            print(
                f"  {pm.created_at[:10]}  likes={pm.likes}  comments={pm.comments}  "
                f"shares={pm.shares}  impressions={pm.impressions}  "
                f"score={pm.engagement_score:.0f}"
            )
    print(f"\nSaved to: {output}")


def generate_metrics_report(
    learning_state_path: str = DEFAULT_LEARNING_STATE_PATH,
    experiments_path: str = DEFAULT_EXPERIMENTS_PATH,
    linkedin_metrics_path: str = "linkedin_metrics.json",
) -> str:
    """
    Generate a Markdown metrics dashboard from the current learning state and experiments.

    Returns the full Markdown string — caller decides where to write it.
    """
    from .linkedin_api import load_latest_snapshot  # noqa: PLC0415

    state = LearningState.load(learning_state_path)
    experiments = ExperimentManager(experiments_path)
    linkedin = load_latest_snapshot(linkedin_metrics_path)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines: list[str] = []

    # ------------------------------------------------------------------ header
    lines += [
        "# 📊 magic-social — Metrics Dashboard",
        "",
        f"> Last updated: **{now}**  ",
        "> Auto-generated by `python -m src.agent metrics`",
        "",
        "---",
        "",
    ]

    # ------------------------------------------------- high-level scorecard
    avg_rating_str = f"{state.average_rating:.1f} / 5" if state.total_ratings_received > 0 else "n/a (no ratings yet)"
    total_posts = state.total_posts_analyzed
    total_feedback = state.total_feedback_received

    lines += [
        "## 🏆 Current Scorecard",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Posts analyzed | {total_posts} |",
        f"| Feedback received | {total_feedback} |",
        f"| Average post rating | {avg_rating_str} |",
        f"| Best performing posts (rolling 20) | {len(state.best_performing_posts)} |",
    ]

    if linkedin:
        lines += [
            f"| LinkedIn followers/connections | {linkedin.follower_count:,} |",
            f"| LinkedIn posts tracked | {len(linkedin.post_metrics)} |",
            f"| LinkedIn metrics last updated | {linkedin.recorded_at[:10]} |",
        ]
    else:
        lines.append("| LinkedIn metrics | _not yet polled — run `linkedin-poll`_ |")

    lines += [
        "",
        "> **Goal:** average rating ≥ 4.0 / 5, engagement score ≥ 100 per post",
        "",
        "---",
        "",
    ]

    # ------------------------------------------------- direction / momentum
    lines += [
        "## 🧭 Direction",
        "",
        "We are optimizing for **LinkedIn posts that Nikolay actually publishes**.",
        "",
        "The two key signals that drive every decision:",
        "",
        "1. **Qualitative** — Did you publish it? If not, why? Rating 1–5.",
        "2. **Quantitative** — Saves, comments, reposts, impressions (entered after 48 h).",
        "",
        "Current blockers (from `not_published_reasons`):",
        "",
    ]

    if state.not_published_reasons:
        sorted_reasons = sorted(state.not_published_reasons.items(), key=lambda x: -x[1])
        for reason, count in sorted_reasons:
            bar = "█" * count
            lines.append(f"- **{reason}** — {count}× {bar}")
    else:
        lines.append("- _No feedback collected yet. Add a `## Post Feedback` comment to any issue._")

    lines += ["", "---", ""]

    # ------------------------------------------------- hook pattern leaderboard
    lines += [
        "## 🪝 Hook Pattern Leaderboard",
        "",
        "Ranked by average engagement score (saves×4 + reposts×3 + comments×3 + reactions×1 + ctr×2).",
        "",
        "| Rank | Hook Pattern | Avg Score | Posts (n) | Trend |",
        "|------|-------------|-----------|-----------|-------|",
    ]

    if state.hook_pattern_scores:
        ranked = sorted(
            state.hook_pattern_scores.items(),
            key=lambda kv: kv[1]["total_score"] / max(kv[1]["count"], 1),
            reverse=True,
        )
        for i, (pattern, data) in enumerate(ranked, 1):
            avg = data["total_score"] / max(data["count"], 1)
            medal = ["🥇", "🥈", "🥉"][i - 1] if i <= 3 else f"#{i}"
            # Trend is rank-based (top half vs bottom half), not time-series data
            trend = "↑" if i <= len(ranked) / 2 else "↓"
            lines.append(f"| {medal} | `{pattern}` | {avg:.1f} | {data['count']} | {trend} |")
    else:
        lines.append("| — | _No data yet_ | — | 0 | — |")

    if state.hook_pattern_scores:
        best_hook = max(
            state.hook_pattern_scores,
            key=lambda k: state.hook_pattern_scores[k]["total_score"] / max(state.hook_pattern_scores[k]["count"], 1),
        )
        best_hook_label = f"`{best_hook}`"
    else:
        best_hook_label = "_learning…_"

    lines += [
        "",
        f"> **Current best hook:** {best_hook_label}",
        "",
        "---",
        "",
    ]

    # ------------------------------------------------- topic leaderboard
    lines += [
        "## 🏷 Topic Leaderboard",
        "",
        "| Rank | Topic | Avg Score | Posts (n) |",
        "|------|-------|-----------|-----------|",
    ]

    if state.topic_scores:
        ranked_topics = sorted(
            state.topic_scores.items(),
            key=lambda kv: kv[1]["total_score"] / max(kv[1]["count"], 1),
            reverse=True,
        )
        for i, (topic, data) in enumerate(ranked_topics, 1):
            avg = data["total_score"] / max(data["count"], 1)
            lines.append(f"| #{i} | `{topic}` | {avg:.1f} | {data['count']} |")
    else:
        lines.append("| — | _No data yet_ | — | 0 |")

    lines += ["", "---", ""]

    # ------------------------------------------------- scoring weights
    lines += [
        "## ⚖️ Scoring Weights (Learning Loop)",
        "",
        "These weights are automatically adjusted: dimensions that correlate with high engagement get a boost.",
        "",
        "| Dimension | Weight | Direction |",
        "|-----------|--------|-----------|",
    ]
    for dim, weight in state.scoring_weights.items():
        direction = "↑" if weight > 1.0 else ("↓" if weight < 1.0 else "—")
        bar_len = int(weight * 10)
        bar = "█" * bar_len
        lines.append(f"| {dim} | {weight:.3f} {bar} | {direction} |")

    lines += ["", "---", ""]

    # ------------------------------------------------- experiments
    lines += [
        "## 🧪 Experiment Tracker",
        "",
        "Sequential A/B experiments, each running until ≥3 posts per variant.",
        "",
        "| # | Variable | Variants | Hypothesis | Status | Winner |",
        "|---|----------|----------|------------|--------|--------|",
    ]

    completed_vars = {
        e.variable.value if hasattr(e.variable, "value") else e.variable
        for e in experiments.experiments
    }
    active_exp = experiments.get_active_experiment()

    for i, plan in enumerate(EXPERIMENT_PLAN, 1):
        var = plan["variable"].value if hasattr(plan["variable"], "value") else str(plan["variable"])
        variants_str = ", ".join(f"`{v}`" for v in plan["variants"])
        hypothesis = plan["hypothesis"]

        # Find matching experiment result
        matching = [
            e for e in experiments.experiments
            if (e.variable.value if hasattr(e.variable, "value") else e.variable) == var
        ]
        if matching:
            exp = matching[-1]
            status_icon = {"running": "🔄 Running", "concluded": "✅ Done", "paused": "⏸ Paused"}.get(
                exp.status.value if hasattr(exp.status, "value") else exp.status, "❓"
            )
            winner = f"**{exp.winner}**" if exp.winner else "—"
        elif active_exp is None and var not in completed_vars:
            status_icon = "⏳ Next up"
            winner = "—"
        else:
            status_icon = "⬜ Queued"
            winner = "—"

        lines.append(f"| {i} | {var} | {variants_str} | {hypothesis} | {status_icon} | {winner} |")

    lines += ["", "---", ""]

    # ------------------------------------------------- qualitative feedback
    lines += [
        "## 💬 Qualitative Feedback",
        "",
        "Parsed from `## Post Feedback` comments on GitHub Issues.",
        "",
        f"- Total feedback comments received: **{state.total_feedback_received}**",
        f"- Posts rated: **{state.total_ratings_received}**",
        f"- Average rating: **{avg_rating_str}**",
        "",
        "**Improvement themes** (from 'What would make it better?'):",
        "",
        "_Add a `## Post Feedback` comment to any post issue to contribute data here._",
        "",
        "### How to Give Feedback",
        "",
        "On any generated GitHub Issue, add a comment:",
        "",
        "```",
        "## Post Feedback — YYYY-MM-DD",
        "",
        "- Published: yes / no",
        "- If not published, why: quality / style / not relevant / too long / too technical / other",
        "- What would make it better: ",
        "- Rating (1-5): ",
        "```",
        "",
        "---",
        "",
    ]

    # ------------------------------------------------- linkedin metrics
    lines += [
        "## 🔗 LinkedIn Metrics",
        "",
    ]

    if linkedin:
        lines += [
            f"_Data from poll on {linkedin.recorded_at[:10]}_",
            "",
            f"**Followers / connections:** {linkedin.follower_count:,}",
            "",
        ]
        if linkedin.post_metrics:
            lines += [
                "| Date | Likes | Comments | Shares | Impressions | Engagement Score |",
                "|------|-------|----------|--------|-------------|-----------------|",
            ]
            for pm in sorted(linkedin.post_metrics, key=lambda p: p.created_at, reverse=True):
                lines.append(
                    f"| {pm.created_at[:10]} | {pm.likes} | {pm.comments} | "
                    f"{pm.shares} | {pm.impressions} | {pm.engagement_score:.0f} |"
                )
            lines.append("")
        else:
            lines.append("_No post metrics in the latest snapshot._")
            lines.append("")
    else:
        lines += [
            "_LinkedIn metrics not yet collected._",
            "",
            "To start tracking follower count and post engagement, run:",
            "```bash",
            "# One-time setup: add LINKEDIN_ACCESS_TOKEN to GitHub secrets",
            "# Then poll manually or let the daily workflow do it:",
            "python -m src.agent linkedin-poll",
            "```",
            "",
            "See **LinkedIn API Setup** in the README for OAuth instructions.",
            "",
        ]

    lines += ["---", ""]

    # ------------------------------------------------- next improvements
    lines += [
        "## 🚀 Next Improvements",
        "",
        "Prioritized by expected impact on post publish rate and engagement.",
        "",
        "### 🔴 High Priority (do this now)",
        "",
        "- [ ] **Collect your first batch of feedback** — run `python -m src.agent backfill-feedback --repo owner/repo`",
        "      to post a feedback request on every existing open issue in one command",
        "- [ ] **Add good-post examples** — drop any LinkedIn post that performed well into",
        "      `good-social-posts/post-N.md` under `## Final LinkedIn Post`",
        "- [ ] **Set up LinkedIn API polling** — add `LINKEDIN_ACCESS_TOKEN` secret and run",
        "      `python -m src.agent linkedin-poll` to start tracking follower count + post engagement daily",
        "",
        "### 🟡 Medium Priority (this sprint)",
        "",
        "- [ ] **Add more curated examples** to `good-social-posts/` to improve few-shot quality",
        "- [ ] **Enable the analytics workflow** — enter impressions/saves/comments 48 h after each publish",
        "- [ ] **Review scoring weights** — after 5+ posts, run `python -m src.agent metrics` to see",
        "      which dimensions correlate with high engagement",
        "- [ ] **Run the first experiment** — publish at least 3 posts, then compare hook pattern scores",
        "",
        "### 🟢 Roadmap (Phase 2)",
        "",
        "- [ ] Auto-commit `METRICS.md` and `linkedin_metrics.json` via GitHub Actions after each daily poll",
        "- [ ] Publish rate tracker — detect published posts via LinkedIn API, no manual status updates",
        "- [ ] Slack/email alert when a post is ready for review",
        "- [ ] Topic gap analysis — highlight topics not covered in the last 30 days",
        "- [ ] Follower growth trend chart (sparkline from `linkedin_metrics.json` history)",
        "",
        "---",
        "",
    ]

    # ------------------------------------------------- how to update
    lines += [
        "## 🔁 How to Update This Dashboard",
        "",
        "```bash",
        "# Regenerate METRICS.md from current learning state + experiments",
        "python -m src.agent metrics",
        "",
        "# Post feedback requests on all existing open issues (run once)",
        "python -m src.agent backfill-feedback --repo owner/repo",
        "",
        "# Poll LinkedIn API for post metrics + follower count",
        "python -m src.agent linkedin-poll",
        "",
        "# Collect analytics (updates learning state, then regenerate)",
        "python -m src.agent analytics --repo owner/repo --posts posts.json",
        "python -m src.agent metrics",
        "```",
        "",
        "> **Tip:** The daily LinkedIn poll workflow (`.github/workflows/linkedin-poll.yml`) runs",
        "> automatically and commits updated metrics to `linkedin_metrics.json`.",
        "",
    ]

    return "\n".join(lines)


def _print_feedback_summary(learning_state_path: str) -> None:
    """Print a human-readable summary of collected feedback and learning signals."""
    state = LearningState.load(learning_state_path)

    print("\n📊 Feedback & Learning Summary")
    print("=" * 50)
    print(f"Total posts analyzed:    {state.total_posts_analyzed}")
    print(f"Total feedback received: {state.total_feedback_received}")
    avg = f"{state.average_rating:.1f}/5" if state.average_rating > 0 else "n/a"
    print(f"Average post rating:     {avg}")

    if state.not_published_reasons:
        print("\n❌ Reasons posts were NOT published:")
        for reason, count in sorted(state.not_published_reasons.items(), key=lambda x: -x[1]):
            print(f"  • {reason}: {count}")
    else:
        print("\n❌ No 'not published' feedback recorded yet.")

    if state.hook_pattern_scores:
        print("\n🪝 Hook pattern performance (avg engagement score):")
        for pattern, data in sorted(
            state.hook_pattern_scores.items(),
            key=lambda kv: kv[1]["total_score"] / max(kv[1]["count"], 1),
            reverse=True,
        ):
            avg_score = data["total_score"] / max(data["count"], 1)
            print(f"  • {pattern}: {avg_score:.1f} (n={data['count']})")

    if state.topic_scores:
        print("\n🏷  Topic performance (avg engagement score):")
        for topic, data in sorted(
            state.topic_scores.items(),
            key=lambda kv: kv[1]["total_score"] / max(kv[1]["count"], 1),
            reverse=True,
        ):
            avg_score = data["total_score"] / max(data["count"], 1)
            print(f"  • {topic}: {avg_score:.1f} (n={data['count']})")

    print()


if __name__ == "__main__":
    main()
