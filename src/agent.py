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

    Returns:
        List of generated Post objects.
    """
    if not repo and not username:
        raise ValueError("Either 'repo' or 'username' must be provided.")
    if since is None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=DEFAULT_SCAN_DAYS)
        since = cutoff.isoformat()

    logger.info("Starting commit scan (since=%s)", since)

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

        # Collect qualitative feedback if available
        feedback = fetch_issue_feedback(repo, token, post.github_issue_number, post.id)

        # Update learning state
        learning_state = update_learning_state(learning_state, post, analytics, feedback=feedback)
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

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    token = os.environ.get("GITHUB_TOKEN")
    if args.command not in ("experiments", "feedback", "metrics") and not token:
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


def generate_metrics_report(
    learning_state_path: str = DEFAULT_LEARNING_STATE_PATH,
    experiments_path: str = DEFAULT_EXPERIMENTS_PATH,
) -> str:
    """
    Generate a Markdown metrics dashboard from the current learning state and experiments.

    Returns the full Markdown string — caller decides where to write it.
    """
    state = LearningState.load(learning_state_path)
    experiments = ExperimentManager(experiments_path)
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

    # ------------------------------------------------- next improvements
    lines += [
        "## 🚀 Next Improvements",
        "",
        "Prioritized by expected impact on post publish rate and engagement.",
        "",
        "### 🔴 High Priority (do this now)",
        "",
        "- [ ] **Collect your first batch of feedback** — review the 5 most recent generated posts,",
        "      add a `## Post Feedback` comment to each (published? why not? rating 1–5)",
        "- [ ] **Add good-post examples** — drop any LinkedIn post that performed well into",
        "      `good-social-posts/post-N.md` under `## Final LinkedIn Post`",
        "- [ ] **Run the first experiment** — publish at least 3 posts, then compare hook pattern scores",
        "",
        "### 🟡 Medium Priority (this sprint)",
        "",
        "- [ ] **Add more curated examples** to `good-social-posts/` to improve few-shot quality",
        "- [ ] **Enable the analytics workflow** — enter impressions/saves/comments 48 h after each publish",
        "- [ ] **Review scoring weights** — after 5+ posts, run `python -m src.agent metrics` to see",
        "      which dimensions correlate with high engagement",
        "",
        "### 🟢 Roadmap (Phase 2)",
        "",
        "- [ ] LinkedIn API — auto-fetch real impression + reaction data (no manual entry)",
        "- [ ] Publish rate tracker — automatically detect when a post was published via LinkedIn API",
        "- [ ] Automated weekly metrics report committed to `METRICS.md` via GitHub Actions",
        "- [ ] Slack/email alert when a post is ready for review",
        "- [ ] Topic gap analysis — highlight topics not covered in the last 30 days",
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
        "# Regenerate and write to a custom path",
        "python -m src.agent metrics --output path/to/METRICS.md",
        "",
        "# Collect analytics (updates learning state, then regenerate)",
        "python -m src.agent analytics --repo owner/repo --posts posts.json",
        "python -m src.agent metrics",
        "```",
        "",
        "> **Tip:** Add `python -m src.agent metrics` as the last step in",
        "> `.github/workflows/analytics-update.yml` to auto-commit an updated dashboard.",
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
