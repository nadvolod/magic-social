"""Optional NeonDB push module for the magic-social dashboard.

All writes are no-ops if NEON_DATABASE_URL is not set, so the pipeline
works fine without a database configured.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_db_url: Optional[str] = None
_warned = False


def _get_url() -> Optional[str]:
    global _db_url  # noqa: PLW0603
    if _db_url is None:
        _db_url = os.environ.get("NEON_DATABASE_URL", "") or ""
    return _db_url or None


def _get_conn():
    """Return a psycopg2 connection or None if DB is not configured."""
    global _warned  # noqa: PLW0603
    url = _get_url()
    if not url:
        if not _warned:
            logger.debug("NEON_DATABASE_URL not set — dashboard DB writes disabled.")
            _warned = True
        return None
    try:
        import psycopg2  # noqa: PLC0415
        return psycopg2.connect(url, connect_timeout=10)
    except Exception:  # noqa: BLE001
        logger.warning("Failed to connect to NeonDB (non-fatal)", exc_info=True)
        return None


def push_post(
    post_id: str,
    sha: str,
    repo: str,
    lesson: str,
    linkedin_post: str,
    hook_pattern: str,
    tags: list[str],
    status: str,
    rubric_score: Optional[float],
    rubric_breakdown: Optional[dict],
    rubric_issues: Optional[list[str]],
    rewrite_attempts: int,
    experiment_id: Optional[str],
    experiment_variant: Optional[str],
    issue_number: Optional[int],
) -> None:
    """Insert or update a post in the dashboard database."""
    conn = _get_conn()
    if conn is None:
        return
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO posts (
                        id, sha, repo, lesson, linkedin_post, hook_pattern, tags,
                        status, rubric_score, rubric_breakdown, rubric_issues,
                        rewrite_attempts, experiment_id, experiment_variant, issue_number
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        rubric_score = EXCLUDED.rubric_score,
                        rubric_breakdown = EXCLUDED.rubric_breakdown,
                        rubric_issues = EXCLUDED.rubric_issues,
                        issue_number = EXCLUDED.issue_number,
                        status = EXCLUDED.status
                    """,
                    (
                        post_id, sha, repo, lesson, linkedin_post, hook_pattern,
                        tags, status,
                        rubric_score,
                        json.dumps(rubric_breakdown) if rubric_breakdown else None,
                        rubric_issues,
                        rewrite_attempts, experiment_id, experiment_variant, issue_number,
                    ),
                )
        logger.debug("Pushed post %s to dashboard DB.", post_id)
    except Exception:  # noqa: BLE001
        logger.warning("Failed to push post %s to DB (non-fatal)", post_id, exc_info=True)
    finally:
        conn.close()


def push_agent_score(
    post_id: str,
    agent_name: str,
    scores: dict,
    verdict: Optional[str] = None,
    details: Optional[str] = None,
) -> None:
    """Insert an agent score entry for a post."""
    conn = _get_conn()
    if conn is None:
        return
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO agent_scores (post_id, agent_name, scores, verdict, details)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (post_id, agent_name, json.dumps(scores), verdict, details),
                )
        logger.debug("Pushed %s score for %s to dashboard DB.", agent_name, post_id)
    except Exception:  # noqa: BLE001
        logger.warning("Failed to push agent score (non-fatal)", exc_info=True)
    finally:
        conn.close()


def push_feedback(
    post_id: str,
    source: str,
    rating: Optional[int] = None,
    reason: Optional[str] = None,
    improvement_notes: Optional[str] = None,
) -> None:
    """Insert a feedback entry for a post."""
    conn = _get_conn()
    if conn is None:
        return
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO feedback (post_id, source, rating, reason, improvement_notes)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (post_id, source, rating, reason, improvement_notes),
                )
        logger.debug("Pushed feedback for %s to dashboard DB.", post_id)
    except Exception:  # noqa: BLE001
        logger.warning("Failed to push feedback (non-fatal)", exc_info=True)
    finally:
        conn.close()


def update_post_feedback(
    post_id: str,
    user_rating: Optional[int] = None,
    user_verdict: Optional[str] = None,
    user_notes: Optional[str] = None,
) -> None:
    """Update user feedback fields on a post."""
    conn = _get_conn()
    if conn is None:
        return
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE posts SET
                        user_rating = COALESCE(%s, user_rating),
                        user_verdict = COALESCE(%s, user_verdict),
                        user_notes = COALESCE(%s, user_notes)
                    WHERE id = %s
                    """,
                    (user_rating, user_verdict, user_notes, post_id),
                )
        logger.debug("Updated feedback for %s in dashboard DB.", post_id)
    except Exception:  # noqa: BLE001
        logger.warning("Failed to update post feedback (non-fatal)", exc_info=True)
    finally:
        conn.close()


def push_metrics_snapshot(snapshot: dict) -> None:
    """Insert a daily metrics snapshot."""
    conn = _get_conn()
    if conn is None:
        return
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO metrics_snapshots (snapshot) VALUES (%s)",
                    (json.dumps(snapshot),),
                )
        logger.debug("Pushed metrics snapshot to dashboard DB.")
    except Exception:  # noqa: BLE001
        logger.warning("Failed to push metrics snapshot (non-fatal)", exc_info=True)
    finally:
        conn.close()


def push_weekly_metrics(
    week_start: str,
    posts_generated: int = 0,
    quality_gate_pass_rate: Optional[float] = None,
    avg_rubric_score: Optional[float] = None,
    avg_agent_score: Optional[float] = None,
    bar_raiser_pass_rate: Optional[float] = None,
    explicit_ratings_count: int = 0,
    avg_explicit_rating: Optional[float] = None,
    posts_published: int = 0,
    posts_rejected: int = 0,
) -> None:
    """Insert or update weekly aggregate metrics."""
    conn = _get_conn()
    if conn is None:
        return
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO weekly_metrics (
                        week_start, posts_generated, quality_gate_pass_rate,
                        avg_rubric_score, avg_agent_score, bar_raiser_pass_rate,
                        explicit_ratings_count, avg_explicit_rating,
                        posts_published, posts_rejected
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (week_start) DO UPDATE SET
                        posts_generated = EXCLUDED.posts_generated,
                        quality_gate_pass_rate = EXCLUDED.quality_gate_pass_rate,
                        avg_rubric_score = EXCLUDED.avg_rubric_score,
                        avg_agent_score = EXCLUDED.avg_agent_score,
                        bar_raiser_pass_rate = EXCLUDED.bar_raiser_pass_rate,
                        explicit_ratings_count = EXCLUDED.explicit_ratings_count,
                        avg_explicit_rating = EXCLUDED.avg_explicit_rating,
                        posts_published = EXCLUDED.posts_published,
                        posts_rejected = EXCLUDED.posts_rejected
                    """,
                    (
                        week_start, posts_generated, quality_gate_pass_rate,
                        avg_rubric_score, avg_agent_score, bar_raiser_pass_rate,
                        explicit_ratings_count, avg_explicit_rating,
                        posts_published, posts_rejected,
                    ),
                )
        logger.debug("Pushed weekly metrics for %s to dashboard DB.", week_start)
    except Exception:  # noqa: BLE001
        logger.warning("Failed to push weekly metrics (non-fatal)", exc_info=True)
    finally:
        conn.close()
