"""Tests for the analytics module."""

import pytest

from src.analytics import (
    DEFAULT_WEIGHTS,
    LearningState,
    MIN_POSTS_FOR_LEARNING,
    _average_engagement_score,
    _infer_strong_dimension,
    get_best_hook_pattern,
    parse_analytics_from_comment,
    update_learning_state,
)
from src.models import AnalyticsSnapshot, Post, PostStatus


def _make_post(post_id="post-abc", hook="result", tags=None, experiment_id=None, variant=None):
    return Post(
        id=post_id,
        source_commit_sha="abc123",
        repo="owner/repo",
        lesson="Temporal activities must be idempotent",
        linkedin_post="Hook\n\nBody\n\nQuestion?",
        x_thread="1/ Hook",
        ig_caption="Caption",
        hook_pattern=hook,
        status=PostStatus.PUBLISHED,
        tags=tags or ["ai"],
        experiment_id=experiment_id,
        experiment_variant=variant,
    )


def _make_analytics(post_id="post-abc", issue=1, score_override=None, **kwargs):
    defaults = {
        "impressions": 1000,
        "reactions": 50,
        "comments": 20,
        "reposts": 10,
        "saves": 30,
        "follower_delta": 5,
        "click_through": 15,
    }
    defaults.update(kwargs)
    snap = AnalyticsSnapshot(post_id=post_id, github_issue_number=issue, **defaults)
    return snap


class TestParseAnalyticsFromComment:
    VALID_COMMENT = """
## Analytics Update — 2024-02-01

- Impressions: 5,432
- Reactions: 123
- Comments: 45
- Reposts: 22
- Saves: 67
- Follower delta: +8
- Click-through: 30
- Notes: good post
    """

    def test_parses_valid_comment(self):
        snap = parse_analytics_from_comment(self.VALID_COMMENT, "post-abc", 1)
        assert snap is not None
        assert snap.impressions == 5432
        assert snap.reactions == 123
        assert snap.comments == 45
        assert snap.reposts == 22
        assert snap.saves == 67
        assert snap.follower_delta == 8
        assert snap.click_through == 30

    def test_returns_none_for_non_analytics_comment(self):
        snap = parse_analytics_from_comment("Just a regular comment", "post-abc", 1)
        assert snap is None

    def test_handles_missing_metrics_as_zero(self):
        comment = "## Analytics Update — 2024-02-01\n\n- Impressions: 100"
        snap = parse_analytics_from_comment(comment, "post-abc", 1)
        assert snap is not None
        assert snap.impressions == 100
        assert snap.reactions == 0
        assert snap.saves == 0

    def test_post_id_and_issue_number_stored(self):
        snap = parse_analytics_from_comment(self.VALID_COMMENT, "post-xyz", 99)
        assert snap.post_id == "post-xyz"
        assert snap.github_issue_number == 99


class TestLearningState:
    def test_default_weights(self):
        state = LearningState()
        assert state.scoring_weights == DEFAULT_WEIGHTS

    def test_save_and_load_roundtrip(self, tmp_path):
        state = LearningState()
        state.scoring_weights["proof"] = 1.5
        path = str(tmp_path / "state.json")
        state.save(path)
        loaded = LearningState.load(path)
        assert loaded.scoring_weights["proof"] == pytest.approx(1.5)

    def test_load_missing_file_returns_default(self, tmp_path):
        state = LearningState.load(str(tmp_path / "nonexistent.json"))
        assert state.scoring_weights == DEFAULT_WEIGHTS
        assert state.total_posts_analyzed == 0

    def test_to_dict_and_from_dict(self):
        state = LearningState()
        state.hook_pattern_scores["result"] = {"count": 5, "total_score": 100.0}
        restored = LearningState.from_dict(state.to_dict())
        assert restored.hook_pattern_scores == state.hook_pattern_scores


class TestUpdateLearningState:
    def test_increments_posts_analyzed(self):
        state = LearningState()
        post = _make_post()
        analytics = _make_analytics()
        new_state = update_learning_state(state, post, analytics)
        assert new_state.total_posts_analyzed == 1

    def test_records_hook_pattern_score(self):
        state = LearningState()
        post = _make_post(hook="result")
        analytics = _make_analytics()
        new_state = update_learning_state(state, post, analytics)
        assert "result" in new_state.hook_pattern_scores
        assert new_state.hook_pattern_scores["result"]["count"] == 1

    def test_records_topic_score(self):
        state = LearningState()
        post = _make_post(tags=["ai", "distributed-systems"])
        analytics = _make_analytics()
        new_state = update_learning_state(state, post, analytics)
        assert "ai" in new_state.topic_scores
        assert "distributed-systems" in new_state.topic_scores

    def test_tracks_best_performing_posts(self):
        state = LearningState()
        post = _make_post()
        analytics = _make_analytics(saves=100)  # high engagement
        new_state = update_learning_state(state, post, analytics)
        assert post.id in new_state.best_performing_posts

    def test_weight_adjustment_only_after_min_posts(self):
        state = LearningState()
        original_weights = dict(state.scoring_weights)
        post = _make_post()
        analytics = _make_analytics()
        # Run fewer iterations than MIN_POSTS_FOR_LEARNING
        for _ in range(MIN_POSTS_FOR_LEARNING - 1):
            state = update_learning_state(state, post, analytics)
        assert state.scoring_weights == original_weights

    def test_weight_stays_within_guardrails(self):
        from src.analytics import MAX_WEIGHT_MULTIPLIER, MIN_WEIGHT_MULTIPLIER
        state = LearningState()
        post = _make_post(hook="result", tags=["ai"])
        # Simulate many high-performing posts to push weights up
        analytics = _make_analytics(saves=1000, comments=500)
        for _ in range(50):
            state = update_learning_state(state, post, analytics)
        for weight in state.scoring_weights.values():
            assert MIN_WEIGHT_MULTIPLIER <= weight <= MAX_WEIGHT_MULTIPLIER


class TestGetBestHookPattern:
    def test_returns_default_when_no_data(self):
        state = LearningState()
        assert get_best_hook_pattern(state) == "result"

    def test_returns_highest_avg_pattern(self):
        state = LearningState()
        state.hook_pattern_scores = {
            "result": {"count": 3, "total_score": 300.0},    # avg 100
            "story": {"count": 3, "total_score": 150.0},     # avg 50
            "contrarian": {"count": 2, "total_score": 80.0}, # avg 40
        }
        assert get_best_hook_pattern(state) == "result"
