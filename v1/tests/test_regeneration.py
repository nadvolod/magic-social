"""Tests for the feedback-driven regeneration system."""

import pytest
from src.models import Post, PostFeedback, PostStatus, SourceCommit
from src.regeneration import (
    classify_feedback,
    extract_feedback_keywords,
    matches_niche_directive,
    rank_commits_for_feedback,
    should_regenerate,
    _feedback_summary,
)


def _make_post(**overrides) -> Post:
    defaults = dict(
        id="post-abc123",
        source_commit_sha="abc123def456",
        repo="nadvolod/LifeNotes",
        lesson="Test lesson about AI agents",
        linkedin_post="We built an AI agent that does X.",
        x_thread="Thread about AI agents",
        ig_caption="AI agent caption",
        hook_pattern="result",
        status=PostStatus.DRAFT,
        tags=["ai", "distributed-systems"],
    )
    defaults.update(overrides)
    return Post(**defaults)


def _make_feedback(**overrides) -> PostFeedback:
    defaults = dict(post_id="post-abc123", published=False)
    defaults.update(overrides)
    return PostFeedback(**defaults)


def _make_commit(**overrides) -> SourceCommit:
    defaults = dict(
        sha="commit123",
        repo="nadvolod/LifeNotes",
        message="fix: improve AI agent retry logic",
        author="nadvolod",
        timestamp="2026-04-06T00:00:00Z",
        files_changed=["src/agent.py"],
        diff_summary="Added retry with exponential backoff",
        score=50.0,
    )
    defaults.update(overrides)
    return SourceCommit(**defaults)


# --- classify_feedback tests ---

class TestClassifyFeedback:
    def test_abandon_from_reason(self):
        fb = _make_feedback(not_published_reason="abandon")
        assert classify_feedback(fb, _make_post()) == "abandon"

    def test_abandon_from_notes(self):
        fb = _make_feedback(improvement_notes="just abandon this, not worth it")
        assert classify_feedback(fb, _make_post()) == "abandon"

    def test_generic_directive(self):
        fb = _make_feedback(
            improvement_notes="All posts should focus on AI agentic workflows and Temporal distributed systems. This is my niche."
        )
        assert classify_feedback(fb, _make_post()) == "generic"

    def test_generic_needs_length_and_directive(self):
        # Short text shouldn't be generic even with directive language
        fb = _make_feedback(improvement_notes="focus on AI")
        assert classify_feedback(fb, _make_post()) != "generic"

    def test_post_specific_with_reason(self):
        fb = _make_feedback(not_published_reason="weak_hook")
        assert classify_feedback(fb, _make_post()) == "post_specific"

    def test_post_specific_with_low_rating(self):
        fb = _make_feedback(rating=1)
        assert classify_feedback(fb, _make_post()) == "post_specific"

    def test_none_no_signal(self):
        fb = _make_feedback(published=None, not_published_reason=None, rating=None)
        assert classify_feedback(fb, _make_post()) == "none"

    def test_published_is_not_rejection(self):
        fb = _make_feedback(published=True, rating=5)
        assert classify_feedback(fb, _make_post()) == "none"


# --- extract_feedback_keywords tests ---

class TestExtractKeywords:
    def test_extracts_from_notes(self):
        fb = _make_feedback(improvement_notes="needs concrete latency numbers and AI focus")
        keywords = extract_feedback_keywords(fb)
        assert "latency" in keywords
        assert "concrete" in keywords

    def test_extracts_relevant_topics(self):
        fb = _make_feedback(improvement_notes="should focus on temporal workflows and distributed systems")
        keywords = extract_feedback_keywords(fb)
        assert "temporal" in keywords
        assert "distributed" in keywords

    def test_excludes_stop_words(self):
        fb = _make_feedback(improvement_notes="the post should be about more things")
        keywords = extract_feedback_keywords(fb)
        assert "the" not in keywords
        assert "should" not in keywords


# --- matches_niche_directive tests ---

class TestMatchesNiche:
    def test_matching_tags(self):
        post = _make_post(tags=["ai", "temporal"], linkedin_post="Built a Temporal workflow")
        assert matches_niche_directive(post, ["temporal", "ai"]) is True

    def test_not_matching(self):
        post = _make_post(tags=["css", "frontend"], linkedin_post="CSS grid is great", lesson="CSS layout")
        assert matches_niche_directive(post, ["temporal", "ai", "distributed"]) is False

    def test_empty_directive_matches_all(self):
        assert matches_niche_directive(_make_post(), []) is True


# --- rank_commits_for_feedback tests ---

class TestRankCommits:
    def test_excludes_rejected_sha(self):
        rejected = _make_post(source_commit_sha="sha_rejected")
        fb = _make_feedback(improvement_notes="better content")
        commits = [
            _make_commit(sha="sha_rejected", score=90.0),
            _make_commit(sha="sha_good", score=50.0),
        ]
        ranked = rank_commits_for_feedback(commits, fb, rejected)
        assert len(ranked) == 1
        assert ranked[0].sha == "sha_good"

    def test_boosts_keyword_matches(self):
        rejected = _make_post(source_commit_sha="sha_old")
        fb = _make_feedback(improvement_notes="needs latency metrics")
        commits = [
            _make_commit(sha="sha_a", message="fix: CSS styling issue", score=50.0),
            _make_commit(sha="sha_b", message="fix: reduce API latency by 50%", score=50.0),
        ]
        ranked = rank_commits_for_feedback(commits, fb, rejected)
        # sha_b should rank higher due to keyword boost ("latency" matches)
        assert ranked[0].sha == "sha_b"

    def test_boosts_different_repo(self):
        rejected = _make_post(source_commit_sha="sha_old", repo="nadvolod/LifeNotes")
        fb = _make_feedback(improvement_notes="something")
        commits = [
            _make_commit(sha="sha_a", repo="nadvolod/LifeNotes", score=50.0),
            _make_commit(sha="sha_b", repo="nadvolod/temporal-learning", score=50.0),
        ]
        ranked = rank_commits_for_feedback(commits, fb, rejected)
        # sha_b from different repo gets diversity bonus
        assert ranked[0].sha == "sha_b"


# --- should_regenerate tests ---

class TestShouldRegenerate:
    def test_eligible_draft(self):
        post = _make_post(regeneration_attempt=0)
        assert should_regenerate(post) is True

    def test_at_max_attempts(self):
        post = _make_post(regeneration_attempt=3)
        assert should_regenerate(post) is False

    def test_published_not_eligible(self):
        post = _make_post(status=PostStatus.PUBLISHED, regeneration_attempt=0)
        assert should_regenerate(post) is False

    def test_abandoned_not_eligible(self):
        post = _make_post(status=PostStatus.ABANDONED, regeneration_attempt=0)
        assert should_regenerate(post) is False


# --- _feedback_summary tests ---

class TestFeedbackSummary:
    def test_reason_only(self):
        fb = _make_feedback(not_published_reason="weak_hook")
        assert "weak hook" in _feedback_summary(fb)

    def test_reason_and_notes(self):
        fb = _make_feedback(not_published_reason="too_long", improvement_notes="cut to 800 chars")
        summary = _feedback_summary(fb)
        assert "too long" in summary
        assert "cut to 800 chars" in summary

    def test_truncates_long_notes(self):
        fb = _make_feedback(improvement_notes="x" * 200)
        summary = _feedback_summary(fb)
        assert len(summary) < 150


# --- Post model lineage tests ---

class TestPostLineage:
    def test_new_fields_default(self):
        post = _make_post()
        assert post.parent_issue_number is None
        assert post.regeneration_attempt == 0
        assert post.regeneration_feedback is None

    def test_from_dict_with_lineage(self):
        data = _make_post().to_dict()
        data["parent_issue_number"] = 45
        data["regeneration_attempt"] = 2
        data["regeneration_feedback"] = "weak hook"
        post = Post.from_dict(data)
        assert post.parent_issue_number == 45
        assert post.regeneration_attempt == 2
        assert post.regeneration_feedback == "weak hook"

    def test_from_dict_ignores_unknown_keys(self):
        data = _make_post().to_dict()
        data["some_future_field"] = "value"
        post = Post.from_dict(data)  # should not raise
        assert post.id == "post-abc123"

    def test_abandoned_status(self):
        post = _make_post(status=PostStatus.ABANDONED)
        assert post.status == PostStatus.ABANDONED
        assert post.to_dict()["status"] == "abandoned"
