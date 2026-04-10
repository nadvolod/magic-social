#!/usr/bin/env python3
"""Backfill NeonDB dashboard from existing GitHub Issues and JSON state files.

Usage:
    NEON_DATABASE_URL=... GITHUB_TOKEN=... python scripts/backfill_db.py

Reads:
  - GitHub Issues from nadvolod/magic-social (label: social-post)
  - learning_state.json (feedback data)
  - screenshot_learning.json (screenshot examples)

Writes to NeonDB tables: posts, feedback, weekly_metrics
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.db import push_post, push_feedback, push_weekly_metrics  # noqa: E402
from src.post_generator import score_linkedin_post_quality  # noqa: E402


def load_learning_state() -> dict:
    path = Path("learning_state.json")
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def backfill_from_github_issues():
    """Load posts from GitHub Issues and push to NeonDB."""
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("GITHUB_TOKEN not set — skipping GitHub backfill.")
        return

    try:
        from src.github_storage import load_posts_from_issues  # noqa: PLC0415
    except ImportError:
        print("Cannot import github_storage — skipping GitHub backfill.")
        return

    repo = "nadvolod/magic-social"
    print(f"Loading posts from {repo}...")

    for state in ["open", "closed"]:
        posts = load_posts_from_issues(repo, token, state=state)
        print(f"  Found {len(posts)} {state} posts.")

        for post in posts:
            rubric = score_linkedin_post_quality(post.linkedin_post) if post.linkedin_post else None
            push_post(
                post_id=post.id,
                sha=post.source_commit_sha,
                repo=post.repo,
                lesson=post.lesson,
                linkedin_post=post.linkedin_post,
                hook_pattern=post.hook_pattern,
                tags=post.tags,
                status=post.status.value,
                rubric_score=rubric.total if rubric else None,
                rubric_breakdown=rubric.breakdown if rubric else None,
                rubric_issues=rubric.issues if rubric else None,
                rewrite_attempts=post.regeneration_attempt,
                experiment_id=post.experiment_id,
                experiment_variant=post.experiment_variant,
                issue_number=post.github_issue_number,
                created_at=post.created_at or None,
                published_at=post.published_at or None,
            )
            print(f"    Pushed {post.id} (issue #{post.github_issue_number})")


def backfill_feedback():
    """Push feedback from learning_state.json to NeonDB."""
    ls = load_learning_state()
    fingerprints = ls.get("applied_feedback_fingerprints", {})
    implicit = ls.get("implicit_feedback_events", {})

    print(f"Backfilling {len(fingerprints)} feedback entries...")
    for post_id, fingerprint in fingerprints.items():
        parts = fingerprint.split("|")
        if len(parts) >= 5:
            _published, reason, notes, rating_str, date_str = parts[0], parts[1], parts[2], parts[3], parts[4]
            rating = int(rating_str) if rating_str.isdigit() else None
            source = "explicit" if post_id not in implicit else "implicit"
            push_feedback(
                post_id=post_id,
                source=source,
                rating=rating,
                reason=reason or None,
                improvement_notes=notes or None,
                recorded_at=date_str or None,
            )

    print("  Done.")


def backfill_weekly_metrics():
    """Compute weekly aggregates from backfilled data and push to weekly_metrics."""
    import psycopg2  # noqa: PLC0415

    url = os.environ.get("NEON_DATABASE_URL", "")
    if not url:
        print("NEON_DATABASE_URL not set — skipping weekly metrics.")
        return

    conn = psycopg2.connect(url, connect_timeout=10)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    date_trunc('week', created_at)::date as week_start,
                    COUNT(*) as posts_generated,
                    COUNT(*) FILTER (WHERE rubric_score >= 75)::float /
                        NULLIF(COUNT(*), 0) as quality_gate_pass_rate,
                    AVG(rubric_score) as avg_rubric_score,
                    NULL::float as avg_agent_score,
                    NULL::float as bar_raiser_pass_rate,
                    COUNT(user_rating) as explicit_ratings_count,
                    AVG(user_rating) as avg_explicit_rating,
                    COUNT(*) FILTER (WHERE status = 'published') as posts_published,
                    COUNT(*) FILTER (WHERE status IN ('rejected', 'abandoned')) as posts_rejected
                FROM posts
                GROUP BY date_trunc('week', created_at)::date
                ORDER BY week_start
            """)
            rows = cur.fetchall()
            print(f"Computing weekly metrics for {len(rows)} weeks...")
            for row in rows:
                push_weekly_metrics(
                    week_start=str(row[0]),
                    posts_generated=row[1] or 0,
                    quality_gate_pass_rate=float(row[2]) if row[2] is not None else None,
                    avg_rubric_score=float(row[3]) if row[3] is not None else None,
                    avg_agent_score=float(row[4]) if row[4] is not None else None,
                    bar_raiser_pass_rate=float(row[5]) if row[5] is not None else None,
                    explicit_ratings_count=row[6] or 0,
                    avg_explicit_rating=float(row[7]) if row[7] is not None else None,
                    posts_published=row[8] or 0,
                    posts_rejected=row[9] or 0,
                )
                print(f"  Week {row[0]}: {row[1]} posts")
    finally:
        conn.close()
    print("  Done.")


def main():
    if not os.environ.get("NEON_DATABASE_URL"):
        print("Error: NEON_DATABASE_URL environment variable is required.")
        sys.exit(1)

    print("=== Backfilling Dashboard DB ===\n")
    backfill_from_github_issues()
    print()
    backfill_feedback()
    print()
    backfill_weekly_metrics()
    print("\n=== Backfill complete ===")


if __name__ == "__main__":
    main()
