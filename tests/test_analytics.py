"""Tests for the analytics module."""

from datetime import datetime, timedelta, timezone

import pytest

from src.analytics import (
    DEFAULT_WEIGHTS,
    LearningState,
    MIN_POSTS_FOR_LEARNING,
    _apply_qualitative_feedback,
    _average_engagement_score,
    _infer_strong_dimension,
    infer_implicit_feedback,
    get_best_hook_pattern,
    parse_feedback_from_issue_body,
    parse_feedback_from_reactions,
    parse_analytics_from_comment,
    parse_feedback_from_comment,
    should_apply_feedback,
    update_learning_state,
)
from src.models import AnalyticsSnapshot, Post, PostFeedback, PostStatus


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


class TestParseFeedbackFromComment:
    VALID_COMMENT = """
## Post Feedback — 2024-02-05

- Published: no
- If not published, why: quality
- What would make it better: more concrete numbers
- Rating (1-5): 3
    """

    def test_parses_valid_comment(self):
        fb = parse_feedback_from_comment(self.VALID_COMMENT, "post-abc")
        assert fb is not None
        assert fb.post_id == "post-abc"
        assert fb.published is False
        assert "quality" in fb.not_published_reason
        assert fb.rating == 3

    def test_returns_none_for_non_feedback_comment(self):
        fb = parse_feedback_from_comment("Just a regular comment", "post-abc")
        assert fb is None

    def test_parses_shorthand_publish_comment(self):
        fb = parse_feedback_from_comment("publish", "post-abc")
        assert fb is not None
        assert fb.published is True

    def test_parses_shorthand_rewrite_comment(self):
        fb = parse_feedback_from_comment("rewrite", "post-abc")
        assert fb is not None
        assert fb.published is False
        assert fb.not_published_reason == "needs_rewrite"

    def test_published_yes(self):
        comment = "## Post Feedback — 2024-01-01\n- Published: yes\n- Rating (1-5): 5"
        fb = parse_feedback_from_comment(comment, "post-xyz")
        assert fb is not None
        assert fb.published is True
        assert fb.rating == 5

    def test_improvement_notes_captured(self):
        comment = (
            "## Post Feedback — 2024-01-01\n"
            "- Published: no\n"
            "- What would make it better: shorter and punchier\n"
        )
        fb = parse_feedback_from_comment(comment, "post-xyz")
        assert fb is not None
        assert "shorter" in fb.improvement_notes

    def test_missing_rating_is_none(self):
        comment = "## Post Feedback — 2024-01-01\n- Published: yes"
        fb = parse_feedback_from_comment(comment, "post-abc")
        assert fb is not None
        assert fb.rating is None

    def test_unfilled_template_returns_none(self):
        # The backfill template (all fields are placeholders) must not be treated
        # as real feedback — no field has been meaningfully filled in.
        template = (
            "## Post Feedback\n\n"
            "- Published: yes / no\n"
            "- If not published, why: quality / style / not relevant / too long / too technical / other\n"
            "- What would make it better: \n"
            "- Rating (1-5): \n"
        )
        fb = parse_feedback_from_comment(template, "post-abc")
        assert fb is None

    def test_published_yes_slash_no_is_not_parsed(self):
        # "yes / no" must not be parsed as published=True
        comment = "## Post Feedback\n- Published: yes / no\n- Rating (1-5): 4"
        fb = parse_feedback_from_comment(comment, "post-abc")
        assert fb is not None
        assert fb.published is None
        assert fb.rating == 4

    def test_slash_separated_not_published_reason_is_ignored(self):
        # A slash-separated option list for the reason field should not be stored
        comment = (
            "## Post Feedback\n"
            "- Published: no\n"
            "- If not published, why: quality / style / not relevant / too long / too technical / other\n"
        )
        fb = parse_feedback_from_comment(comment, "post-abc")
        assert fb is not None
        assert fb.published is False
        assert fb.not_published_reason is None  # placeholder, not filled


class TestApplyQualitativeFeedback:
    def test_increments_feedback_count(self):
        state = LearningState()
        fb = PostFeedback(post_id="post-abc", published=True, rating=4)
        _apply_qualitative_feedback(state, fb)
        assert state.total_feedback_received == 1

    def test_tracks_not_published_reason(self):
        state = LearningState()
        fb = PostFeedback(post_id="post-abc", published=False, not_published_reason="quality")
        _apply_qualitative_feedback(state, fb)
        assert "quality" in state.not_published_reasons
        assert state.not_published_reasons["quality"] == 1

    def test_average_rating_updated(self):
        state = LearningState()
        _apply_qualitative_feedback(state, PostFeedback(post_id="p1", rating=4))
        _apply_qualitative_feedback(state, PostFeedback(post_id="p2", rating=2))
        assert state.average_rating == pytest.approx(3.0)

    def test_feedback_integrated_in_update_learning_state(self):
        state = LearningState()
        post = _make_post()
        analytics = _make_analytics()
        fb = PostFeedback(post_id=post.id, published=False, not_published_reason="style", rating=2)
        new_state = update_learning_state(state, post, analytics, feedback=fb)
        assert new_state.total_feedback_received == 1
        assert "style" in new_state.not_published_reasons


class TestReactionAndCheckboxFeedback:
    def test_parses_issue_body_publish_checkbox(self):
        body = "- [x] Publish\n- [ ] Rewrite\n- [ ] Skip"
        fb = parse_feedback_from_issue_body(body, "post-abc")
        assert fb is not None
        assert fb.published is True

    def test_parses_issue_body_negative_checkbox(self):
        body = "- [ ] Publish\n- [x] Too long"
        fb = parse_feedback_from_issue_body(body, "post-abc")
        assert fb is not None
        assert fb.published is False
        assert fb.not_published_reason == "too_long"

    def test_parses_reaction_feedback(self):
        fb = parse_feedback_from_reactions({"rocket": 1}, "post-abc")
        assert fb is not None
        assert fb.published is True
        assert fb.rating == 5

    def test_publish_to_linkedin_checkbox_not_quick_feedback(self):
        # A publishing checklist item like "- [x] Publish to LinkedIn" must NOT
        # be parsed as quick-publish feedback — the regex is intentionally strict.
        body = "- [x] Publish to LinkedIn\n- [ ] Rewrite"
        fb = parse_feedback_from_issue_body(body, "post-abc")
        assert fb is None or not fb.published


class TestShorthandWordBoundary:
    def test_bad_inside_longer_word_not_matched(self):
        # "bad" as a substring of "badge" must not trigger negative feedback.
        fb = parse_feedback_from_comment("badge", "post-abc")
        assert fb is None

    def test_bad_with_trailing_punctuation_still_matches(self):
        # "bad." should still be recognised because \b matches before punctuation.
        fb = parse_feedback_from_comment("bad.", "post-abc")
        assert fb is not None
        assert fb.published is False

    def test_rewrite_inside_longer_word_not_matched(self):
        # "rewrite" as a prefix/infix should not match inside a composite word.
        fb = parse_feedback_from_comment("rewritten", "post-abc")
        assert fb is None

    def test_skip_exact_match(self):
        fb = parse_feedback_from_comment("skip", "post-abc")
        assert fb is not None
        assert fb.published is False
        assert fb.not_published_reason == "skip"


class TestFeedbackDeduplication:
    def test_deduplicates_same_feedback(self):
        state = LearningState()
        fb = PostFeedback(
            post_id="post-abc",
            published=False,
            not_published_reason="quality",
            rating=1,
            recorded_at="2026-03-04T00:00:00+00:00",
        )
        assert should_apply_feedback(state, "post-abc", fb) is True
        assert should_apply_feedback(state, "post-abc", fb) is False


class TestImplicitFeedback:
    def test_infers_no_feedback_after_72h(self):
        state = LearningState()
        post = _make_post(post_id="post-abc")
        post.status = PostStatus.DRAFT
        post.created_at = (datetime.now(timezone.utc) - timedelta(hours=80)).isoformat()
        inferred = infer_implicit_feedback(state, post, has_explicit_feedback=False)
        event_keys = {event for event, _ in inferred}
        assert "no_feedback_72h" in event_keys

    def test_infers_stale_unpublished_after_7d(self):
        state = LearningState()
        post = _make_post(post_id="post-abc")
        post.status = PostStatus.DRAFT
        post.created_at = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
        inferred = infer_implicit_feedback(state, post, has_explicit_feedback=False)
        event_keys = {event for event, _ in inferred}
        assert "stale_unpublished_7d" in event_keys

    def test_implicit_events_are_one_time(self):
        state = LearningState()
        post = _make_post(post_id="post-abc")
        post.status = PostStatus.DRAFT
        post.created_at = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
        first = infer_implicit_feedback(state, post, has_explicit_feedback=False)
        second = infer_implicit_feedback(state, post, has_explicit_feedback=False)
        assert first
        assert second == []
