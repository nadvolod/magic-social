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
from datetime import datetime, timedelta, timezone
from typing import Optional

from .analytics import (
    LearningState,
    fetch_issue_analytics,
    get_analytics_prompt,
    get_best_hook_pattern,
    update_learning_state,
)
from .commit_scanner import scan_commits
from .experiments import ExperimentManager
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
    repo: str,
    token: str,
    since: Optional[str] = None,
    branch: str = "main",
    max_posts: int = 3,
    learning_state_path: str = DEFAULT_LEARNING_STATE_PATH,
    experiments_path: str = DEFAULT_EXPERIMENTS_PATH,
    dry_run: bool = False,
) -> list[Post]:
    """
    Run a full commit scan → post generation → GitHub Issue creation cycle.

    Args:
        repo:                 Full repo name (owner/repo).
        token:                GitHub token with repo + issues write access.
        since:                ISO 8601 date string; only scan commits after this.
        branch:               Branch to scan.
        max_posts:            Maximum posts to generate per run.
        learning_state_path:  Path to the learning state JSON file.
        experiments_path:     Path to the experiments JSON file.
        dry_run:              If True, print posts but don't create issues.

    Returns:
        List of generated Post objects.
    """
    if since is None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=DEFAULT_SCAN_DAYS)
        since = cutoff.isoformat()

    logger.info("Starting commit scan for %s (since=%s)", repo, since)

    # Load persistent state
    learning_state = LearningState.load(learning_state_path)
    experiments = ExperimentManager(experiments_path)

    # Get or start an experiment
    active_exp = experiments.get_active_experiment()
    if active_exp is None:
        active_exp = experiments.start_next_experiment()

    # Pick the best hook pattern from learning state
    best_hook = get_best_hook_pattern(learning_state)

    # Scan commits
    source_commits = scan_commits(repo, token, since=since, branch=branch)
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
    1. Checks if an analytics comment has been added.
    2. If yes: updates the learning state and experiment results.
    3. If no: prints a prompt asking the user to enter analytics.
    """
    learning_state = LearningState.load(learning_state_path)
    experiments = ExperimentManager(experiments_path)

    for post in posts:
        if post.github_issue_number is None:
            continue
        if post.status != PostStatus.PUBLISHED:
            continue

        analytics = fetch_issue_analytics(repo, token, post.github_issue_number, post.id)

        if analytics is None:
            # No analytics yet — prompt the user
            print(get_analytics_request_message(post, post.github_issue_number, repo))
            continue

        # Update learning state
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

  # Collect analytics for published posts (posts provided via stdin JSON)
  python -m src.agent analytics --repo owner/repo --posts posts.json

  # Show experiment summary
  python -m src.agent experiments
        """,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # scan command
    scan_parser = subparsers.add_parser("scan", help="Scan commits and generate posts")
    scan_parser.add_argument("--repo", required=True, help="GitHub repo (owner/repo)")
    scan_parser.add_argument("--branch", default="main", help="Branch to scan")
    scan_parser.add_argument("--since", help="ISO 8601 date (e.g. 2024-01-01T00:00:00Z)")
    scan_parser.add_argument("--max-posts", type=int, default=3, help="Max posts per run")
    scan_parser.add_argument("--dry-run", action="store_true", help="Print posts, don't create issues")
    scan_parser.add_argument("--threshold", type=float, default=SCORE_THRESHOLD, help="Min score threshold")

    # analytics command
    analytics_parser = subparsers.add_parser("analytics", help="Collect analytics for published posts")
    analytics_parser.add_argument("--repo", required=True)
    analytics_parser.add_argument("--posts", help="JSON file containing list of Post objects")

    # experiments command
    experiments_parser = subparsers.add_parser("experiments", help="Show experiment summary")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    token = os.environ.get("GITHUB_TOKEN")
    if args.command != "experiments" and not token:
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


if __name__ == "__main__":
    main()
