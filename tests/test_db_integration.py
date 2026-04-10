"""Integration tests for the NeonDB dashboard push module.

These tests hit the REAL NeonDB instance. They:
- Insert test data with a unique prefix
- Verify data round-trips correctly
- Clean up test data after each test

Requires NEON_DATABASE_URL environment variable.
Skip if not set (CI without DB access).
"""

from __future__ import annotations

import os
import uuid

import pytest

# Skip entire module if no DB configured
pytestmark = pytest.mark.skipif(
    not os.environ.get("NEON_DATABASE_URL"),
    reason="NEON_DATABASE_URL not set — skipping DB integration tests",
)


def _test_id() -> str:
    """Generate a unique test post ID to avoid collisions."""
    return f"test-{uuid.uuid4().hex[:12]}"


def _cleanup_post(post_id: str):
    """Remove test data from DB."""
    try:
        import psycopg2
        conn = psycopg2.connect(os.environ["NEON_DATABASE_URL"], connect_timeout=10)
        with conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM agent_scores WHERE post_id = %s", (post_id,))
                cur.execute("DELETE FROM feedback WHERE post_id = %s", (post_id,))
                cur.execute("DELETE FROM posts WHERE id = %s", (post_id,))
        conn.close()
    except Exception:
        pass


def _fetch_post(post_id: str) -> dict | None:
    """Fetch a post from DB by ID."""
    import psycopg2
    conn = psycopg2.connect(os.environ["NEON_DATABASE_URL"], connect_timeout=10)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM posts WHERE id = %s", (post_id,))
            row = cur.fetchone()
            if not row:
                return None
            cols = [desc[0] for desc in cur.description]
            return dict(zip(cols, row))
    finally:
        conn.close()


def _fetch_agent_scores(post_id: str) -> list[dict]:
    """Fetch agent scores for a post."""
    import psycopg2
    conn = psycopg2.connect(os.environ["NEON_DATABASE_URL"], connect_timeout=10)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM agent_scores WHERE post_id = %s ORDER BY created_at",
                (post_id,),
            )
            cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def _fetch_feedback(post_id: str) -> list[dict]:
    """Fetch feedback entries for a post."""
    import psycopg2
    conn = psycopg2.connect(os.environ["NEON_DATABASE_URL"], connect_timeout=10)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM feedback WHERE post_id = %s ORDER BY recorded_at",
                (post_id,),
            )
            cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


class TestPushPost:
    """push_post should insert/upsert a post into the dashboard DB."""

    def test_inserts_new_post(self):
        from src.db import push_post

        pid = _test_id()
        try:
            push_post(
                post_id=pid,
                sha="abc123def456",
                repo="nadvolod/magic-social",
                lesson="Test lesson from integration test",
                linkedin_post="This is a test post.\n\n    code_block = True\n\nWhat do you think?",
                hook_pattern="result",
                tags=["ai", "distributed-systems"],
                status="draft",
                rubric_score=82.5,
                rubric_breakdown={"hook": 18, "structure": 16, "proof": 20, "cta": 18, "clarity": 10.5},
                rubric_issues=["Tighten sentence length"],
                rewrite_attempts=1,
                experiment_id=None,
                experiment_variant=None,
                issue_number=999,
            )

            row = _fetch_post(pid)
            assert row is not None, "Post was not inserted"
            assert row["sha"] == "abc123def456"
            assert row["repo"] == "nadvolod/magic-social"
            assert row["hook_pattern"] == "result"
            assert float(row["rubric_score"]) == pytest.approx(82.5, abs=0.1)
            assert row["issue_number"] == 999
            assert row["status"] == "draft"
        finally:
            _cleanup_post(pid)

    def test_upserts_on_conflict(self):
        from src.db import push_post

        pid = _test_id()
        try:
            # Insert
            push_post(
                post_id=pid, sha="aaa", repo="r", lesson="v1", linkedin_post="v1",
                hook_pattern="result", tags=[], status="draft",
                rubric_score=60.0, rubric_breakdown=None, rubric_issues=None,
                rewrite_attempts=0, experiment_id=None, experiment_variant=None,
                issue_number=100,
            )
            # Upsert with new score
            push_post(
                post_id=pid, sha="aaa", repo="r", lesson="v1", linkedin_post="v1",
                hook_pattern="result", tags=[], status="published",
                rubric_score=85.0, rubric_breakdown=None, rubric_issues=None,
                rewrite_attempts=0, experiment_id=None, experiment_variant=None,
                issue_number=100,
            )

            row = _fetch_post(pid)
            assert row is not None
            assert float(row["rubric_score"]) == pytest.approx(85.0, abs=0.1)
            assert row["status"] == "published"
        finally:
            _cleanup_post(pid)


class TestPushAgentScore:
    """push_agent_score should insert agent evaluation results."""

    def test_inserts_agent_scores(self):
        from src.db import push_post, push_agent_score

        pid = _test_id()
        try:
            # Need a post first (FK constraint)
            push_post(
                post_id=pid, sha="s", repo="r", lesson="l", linkedin_post="p",
                hook_pattern="result", tags=[], status="draft",
                rubric_score=75.0, rubric_breakdown=None, rubric_issues=None,
                rewrite_attempts=0, experiment_id=None, experiment_variant=None,
                issue_number=None,
            )

            push_agent_score(
                post_id=pid,
                agent_name="quality_reviewer",
                scores={"specificity": 16, "hook_strength": 14},
                verdict="pass",
                details="Good specificity, decent hook",
            )
            push_agent_score(
                post_id=pid,
                agent_name="bar_raiser",
                scores={"quality_score": 72},
                verdict="conditional",
            )

            scores = _fetch_agent_scores(pid)
            assert len(scores) == 2
            assert scores[0]["agent_name"] == "quality_reviewer"
            assert scores[0]["verdict"] == "pass"
            assert scores[1]["agent_name"] == "bar_raiser"
            assert scores[1]["verdict"] == "conditional"
        finally:
            _cleanup_post(pid)


class TestPushFeedback:
    """push_feedback should insert feedback entries."""

    def test_inserts_explicit_feedback(self):
        from src.db import push_post, push_feedback

        pid = _test_id()
        try:
            push_post(
                post_id=pid, sha="s", repo="r", lesson="l", linkedin_post="p",
                hook_pattern="result", tags=[], status="draft",
                rubric_score=75.0, rubric_breakdown=None, rubric_issues=None,
                rewrite_attempts=0, experiment_id=None, experiment_variant=None,
                issue_number=None,
            )

            push_feedback(
                post_id=pid,
                source="explicit",
                rating=3,
                reason="skip",
                improvement_notes="Needs stronger hook",
            )

            fb = _fetch_feedback(pid)
            assert len(fb) == 1
            assert fb[0]["source"] == "explicit"
            assert fb[0]["rating"] == 3
            assert fb[0]["reason"] == "skip"
            assert fb[0]["improvement_notes"] == "Needs stronger hook"
        finally:
            _cleanup_post(pid)

    def test_inserts_implicit_feedback(self):
        from src.db import push_post, push_feedback

        pid = _test_id()
        try:
            push_post(
                post_id=pid, sha="s", repo="r", lesson="l", linkedin_post="p",
                hook_pattern="result", tags=[], status="draft",
                rubric_score=75.0, rubric_breakdown=None, rubric_issues=None,
                rewrite_attempts=0, experiment_id=None, experiment_variant=None,
                issue_number=None,
            )

            push_feedback(
                post_id=pid,
                source="no_feedback_72h",
                rating=2,
                reason="no_feedback_72h",
            )

            fb = _fetch_feedback(pid)
            assert len(fb) == 1
            assert fb[0]["source"] == "no_feedback_72h"
            assert fb[0]["rating"] == 2
        finally:
            _cleanup_post(pid)


class TestNoDbGracefulDegradation:
    """All push functions should no-op when DB is not configured."""

    def test_push_post_noop_without_db(self, monkeypatch):
        real_url = os.environ.get("NEON_DATABASE_URL", "")
        monkeypatch.setenv("NEON_DATABASE_URL", "")
        # Force module to re-read env
        import src.db
        src.db._db_url = None
        src.db._warned = False

        # Should not raise
        src.db.push_post(
            post_id="noop-test", sha="s", repo="r", lesson="l", linkedin_post="p",
            hook_pattern="result", tags=[], status="draft",
            rubric_score=75.0, rubric_breakdown=None, rubric_issues=None,
            rewrite_attempts=0, experiment_id=None, experiment_variant=None,
            issue_number=None,
        )

        # Restore real URL to verify nothing was inserted
        monkeypatch.setenv("NEON_DATABASE_URL", real_url)
        src.db._db_url = None
        row = _fetch_post("noop-test")
        assert row is None
