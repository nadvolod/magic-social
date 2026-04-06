"""Tests for the weekly learning cycle module."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.analytics import LearningState
from src.models import Post, PostStatus
from src.weekly_learner import (
    auto_save_published_post,
    compute_kpis,
    generate_prompt_patches,
    load_prompt_patches,
    render_weekly_report,
    save_prompt_patches,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_post(
    post_id: str = "post-001",
    status: PostStatus = PostStatus.DRAFT,
    created_at: str | None = None,
    published_at: str | None = None,
    hook: str = "result",
    lesson: str = "Temporal activities must be idempotent",
) -> Post:
    """Create a minimal Post for testing."""
    now = datetime.now(timezone.utc)
    return Post(
        id=post_id,
        source_commit_sha="abc123",
        repo="owner/repo",
        lesson=lesson,
        linkedin_post="Hook\n\nBody\n\nQuestion?",
        x_thread="1/ Hook",
        ig_caption="Caption",
        hook_pattern=hook,
        status=status,
        created_at=created_at or now.isoformat(),
        published_at=published_at,
    )


def _published_post(
    post_id: str = "post-pub",
    days_to_publish: float = 2.0,
) -> Post:
    """Create a published post with a known time-to-publish gap."""
    now = datetime.now(timezone.utc)
    created = now - timedelta(days=days_to_publish)
    return _make_post(
        post_id=post_id,
        status=PostStatus.PUBLISHED,
        created_at=created.isoformat(),
        published_at=now.isoformat(),
    )


def _write_linkedin_metrics(path: Path, this_week: dict, last_week: dict) -> str:
    """Write a minimal linkedin_metrics.json with two weekly snapshots."""
    history = [last_week, this_week]
    filepath = path / "linkedin_metrics.json"
    filepath.write_text(json.dumps(history, indent=2), encoding="utf-8")
    return str(filepath)


def _learning_state_with_reasons(
    current_reasons: dict | None = None,
    last_week_reasons: dict | None = None,
) -> LearningState:
    """Build a LearningState with fingerprints that have proper timestamps."""
    state = LearningState()
    now = datetime.now(timezone.utc)
    idx = 0
    if current_reasons:
        state.not_published_reasons = dict(current_reasons)
        for reason, count in current_reasons.items():
            for i in range(count):
                ts = (now - timedelta(days=2, hours=idx)).isoformat()
                state.applied_feedback_fingerprints[f"post-curr-{idx}"] = f"False|{reason}||2|{ts}"
                idx += 1
    if last_week_reasons:
        for reason, count in last_week_reasons.items():
            for i in range(count):
                ts = (now - timedelta(days=10, hours=idx)).isoformat()
                state.applied_feedback_fingerprints[f"post-prev-{idx}"] = f"False|{reason}||2|{ts}"
                idx += 1
    return state


# ===================================================================
# KPI computation
# ===================================================================

class TestPublishRate:
    """compute_kpis → publish_rate."""

    def test_publish_rate_with_published_posts(self, tmp_path):
        """2 published out of 6 total → 33.3%."""
        posts = [
            _make_post(post_id=f"draft-{i}", status=PostStatus.DRAFT) for i in range(4)
        ] + [
            _published_post(post_id=f"pub-{i}") for i in range(2)
        ]
        metrics_path = _write_linkedin_metrics(
            tmp_path,
            this_week={"follower_count": 100, "recorded_at": datetime.now(timezone.utc).isoformat()},
            last_week={"follower_count": 100, "recorded_at": (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()},
        )
        state = LearningState()
        kpis = compute_kpis(posts, state, metrics_path)
        assert kpis["publish_rate"] == pytest.approx(33.3, abs=0.1)

    def test_publish_rate_zero_when_no_posts(self, tmp_path):
        """No posts at all → publish_rate is 0%."""
        metrics_path = _write_linkedin_metrics(
            tmp_path,
            this_week={"follower_count": 100, "recorded_at": datetime.now(timezone.utc).isoformat()},
            last_week={"follower_count": 100, "recorded_at": (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()},
        )
        state = LearningState()
        kpis = compute_kpis([], state, metrics_path)
        assert kpis["publish_rate"] == 0.0


class TestFeedbackConvergence:
    """compute_kpis → feedback_convergence."""

    def test_feedback_convergence_counts_repeats(self, tmp_path):
        """Reasons present in both current and archived weeks are counted."""
        state = _learning_state_with_reasons(
            current_reasons={"too_long": 3, "quality": 1},
            last_week_reasons={"too_long": 2, "style": 1},
        )
        metrics_path = _write_linkedin_metrics(
            tmp_path,
            this_week={"follower_count": 100, "recorded_at": datetime.now(timezone.utc).isoformat()},
            last_week={"follower_count": 100, "recorded_at": (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()},
        )
        kpis = compute_kpis([], state, metrics_path)
        convergence = kpis["feedback_convergence"]
        # "too_long" appears in both weeks → should be counted as a converging reason
        assert convergence >= 1


class TestTimeToPublish:
    """compute_kpis → time_to_publish_days."""

    def test_time_to_publish_averages_correctly(self, tmp_path):
        """Average of 1-day and 3-day publish times → 2.0 days."""
        posts = [
            _published_post(post_id="fast", days_to_publish=1.0),
            _published_post(post_id="slow", days_to_publish=3.0),
        ]
        metrics_path = _write_linkedin_metrics(
            tmp_path,
            this_week={"follower_count": 100, "recorded_at": datetime.now(timezone.utc).isoformat()},
            last_week={"follower_count": 100, "recorded_at": (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()},
        )
        state = LearningState()
        kpis = compute_kpis(posts, state, metrics_path)
        assert kpis["time_to_publish_days"] == pytest.approx(2.0, abs=0.1)


class TestEngagementGrowth:
    """compute_kpis → engagement_growth_pct."""

    def test_engagement_growth_zero_when_no_data(self, tmp_path):
        """No hook pattern data → engagement growth is 0."""
        metrics_path = _write_linkedin_metrics(
            tmp_path,
            this_week={"follower_count": 100, "recorded_at": datetime.now(timezone.utc).isoformat()},
            last_week={"follower_count": 100, "recorded_at": (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()},
        )
        state = LearningState()
        kpis = compute_kpis([], state, metrics_path)
        assert kpis["engagement_growth_pct"] == 0.0

    def test_follower_delta_computed(self, tmp_path):
        """Follower delta computed from LinkedIn metrics snapshots."""
        now = datetime.now(timezone.utc)
        metrics_path = _write_linkedin_metrics(
            tmp_path,
            this_week={"follower_count": 110, "recorded_at": now.isoformat()},
            last_week={"follower_count": 100, "recorded_at": (now - timedelta(days=8)).isoformat()},
        )
        state = LearningState()
        kpis = compute_kpis([], state, metrics_path)
        assert kpis["follower_delta"] == 10


# ===================================================================
# Prompt patches
# ===================================================================

class TestGeneratePromptPatches:
    """generate_prompt_patches produces rule patches from repeated reasons."""

    def test_generates_patch_for_repeated_reason(self):
        """A reason appearing 2+ times in recent feedback → patch created."""
        state = _learning_state_with_reasons(
            current_reasons={"too_long": 4, "quality": 1},
        )
        recent_reasons = Counter(["too_long", "too_long", "too_long", "quality"])
        patches = generate_prompt_patches(state, recent_reasons)
        # "too_long" appeared 3 times → should generate a patch
        assert len(patches) >= 1
        assert any("too_long" in p.get("reason", "") for p in patches)

    def test_no_patch_for_single_occurrence(self):
        """A reason appearing only once → no patch generated."""
        state = _learning_state_with_reasons(current_reasons={"style": 1})
        recent_reasons = Counter(["style"])
        patches = generate_prompt_patches(state, recent_reasons)
        # "style" appeared only once → no patch
        assert not any("style" in p.get("reason", "") for p in patches)

    def test_patch_format_has_required_fields(self):
        """Each patch dict must contain type, rule, reason, and added."""
        state = _learning_state_with_reasons(current_reasons={"too_long": 5})
        recent_reasons = Counter(["too_long", "too_long", "too_long"])
        patches = generate_prompt_patches(state, recent_reasons)
        assert len(patches) >= 1
        for patch in patches:
            assert "type" in patch
            assert "rule" in patch
            assert "reason" in patch
            assert "added" in patch


class TestPatchPersistence:
    """save_prompt_patches / load_prompt_patches round-trip."""

    def test_save_and_load_round_trip(self, tmp_path):
        """Saved patches can be loaded back identically."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        patches = [
            {
                "type": "constraint",
                "rule": "Keep LinkedIn posts under 1200 characters",
                "reason": "too_long",
                "added": today,
            },
            {
                "type": "style",
                "rule": "Use shorter sentences",
                "reason": "too_long",
                "added": today,
            },
        ]
        path = str(tmp_path / "patches.json")
        save_prompt_patches(patches, path)
        loaded = load_prompt_patches(path)
        assert len(loaded) == 2
        assert loaded[0]["rule"] == patches[0]["rule"]
        assert loaded[1]["rule"] == patches[1]["rule"]

    def test_old_patches_archived(self, tmp_path):
        """Patches older than 30 days are removed on load or save cycle."""
        old_date = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
        recent_date = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        patches = [
            {
                "type": "constraint",
                "rule": "Old rule",
                "reason": "quality",
                "added": old_date,
            },
            {
                "type": "style",
                "rule": "Recent rule",
                "reason": "too_long",
                "added": recent_date,
            },
        ]
        path = str(tmp_path / "patches.json")
        save_prompt_patches(patches, path)
        loaded = load_prompt_patches(path)
        # Only the recent patch should survive
        assert len(loaded) == 1
        assert loaded[0]["rule"] == "Recent rule"


# ===================================================================
# Auto-save published posts
# ===================================================================

class TestAutoSavePublishedPost:
    """auto_save_published_post writes published posts to good-social-posts/."""

    def test_saves_published_post_to_file(self, tmp_path):
        """A published post is saved as good-social-posts/post-N.md."""
        good_dir = tmp_path / "good-social-posts"
        good_dir.mkdir()
        post = _published_post(post_id="post-42")
        result = auto_save_published_post(post, str(good_dir))
        assert result is True
        saved_files = list(good_dir.glob("*.md"))
        assert len(saved_files) == 1
        content = saved_files[0].read_text(encoding="utf-8")
        assert post.linkedin_post in content

    def test_skips_non_published_post(self, tmp_path):
        """Draft posts are not saved."""
        good_dir = tmp_path / "good-social-posts"
        good_dir.mkdir()
        post = _make_post(post_id="draft-99", status=PostStatus.DRAFT)
        result = auto_save_published_post(post, str(good_dir))
        assert result is False
        saved_files = list(good_dir.glob("*.md"))
        assert len(saved_files) == 0

    def test_skips_already_saved(self, tmp_path):
        """A post whose ID is already in the directory is not duplicated."""
        good_dir = tmp_path / "good-social-posts"
        good_dir.mkdir()
        post = _published_post(post_id="post-42")
        # Save once
        auto_save_published_post(post, str(good_dir))
        # Save again — should skip
        result = auto_save_published_post(post, str(good_dir))
        assert result is False
        saved_files = list(good_dir.glob("*.md"))
        assert len(saved_files) == 1


# ===================================================================
# Weekly report rendering
# ===================================================================

class TestRenderWeeklyReport:
    """render_weekly_report returns a markdown report with key sections."""

    @pytest.fixture()
    def sample_kpis(self) -> dict:
        return {
            "publish_rate": 33.3,
            "feedback_convergence": 2,
            "time_to_publish_days": 2.5,
            "engagement_growth_pct": 15.0,
            "follower_delta": 8,
        }

    @pytest.fixture()
    def sample_patches(self) -> list[dict]:
        return [
            {
                "type": "constraint",
                "rule": "Keep posts under 1200 chars",
                "reason": "too_long",
                "added": "2026-03-01T00:00:00+00:00",
            },
        ]

    @pytest.fixture()
    def sample_lessons(self) -> list[str]:
        return [
            "Shorter hooks get 2x more engagement",
            "Technical depth resonates with senior audience",
        ]

    @pytest.fixture()
    def sample_activity_stats(self) -> dict:
        return {
            "posts_generated": 6,
            "feedback_count": 4,
            "published_count": 2,
        }

    def test_report_contains_kpi_table(
        self, sample_kpis, sample_patches, sample_lessons, sample_activity_stats,
    ):
        """The markdown report contains a KPI dashboard section."""
        report = render_weekly_report(
            sample_kpis, sample_patches, sample_lessons, sample_activity_stats,
        )
        assert "publish_rate" in report.lower() or "publish rate" in report.lower()
        assert "33.3" in report
        assert "engagement" in report.lower()

    def test_report_contains_activity_stats(
        self, sample_kpis, sample_patches, sample_lessons, sample_activity_stats,
    ):
        """The report shows posts generated and feedback count."""
        report = render_weekly_report(
            sample_kpis, sample_patches, sample_lessons, sample_activity_stats,
        )
        assert "6" in report  # posts_generated
        assert "4" in report  # feedback_count

    def test_report_contains_lessons(
        self, sample_kpis, sample_patches, sample_lessons, sample_activity_stats,
    ):
        """The report includes the lessons learned."""
        report = render_weekly_report(
            sample_kpis, sample_patches, sample_lessons, sample_activity_stats,
        )
        for lesson in sample_lessons:
            assert lesson in report
