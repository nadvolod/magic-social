"""Tests for the post generator."""

import src.post_generator as pg
import pytest

from src.models import Post, PostStatus, SourceCommit
from src.post_generator import (
    HOOK_PATTERNS,
    QUALITY_GATE_DEFAULT_MAX_REWRITES,
    QUALITY_GATE_DEFAULT_THRESHOLD,
    QualityScore,
    _extract_lesson,
    _extract_linkedin_section,
    _infer_tags,
    _load_good_posts_examples,
    _placeholder_ig,
    _placeholder_linkedin,
    _placeholder_x_thread,
    _post_id,
    generate_post,
    generate_post_with_quality_gate,
    score_linkedin_post_quality,
)


def _make_source(sha="abc123def456", message="fix Temporal workflow timeout by making activities idempotent"):
    return SourceCommit(
        sha=sha,
        repo="owner/repo",
        message=message,
        author="Alice",
        timestamp="2024-01-01T10:00:00Z",
        files_changed=["workflow/saga.go", "workflow/activity.go"],
        diff_summary="+45 lines, -12 lines; touches: def retry, def execute",
        score=72.0,
        score_breakdown={"novelty": 15, "impact": 18, "teachability": 14, "relevance": 16, "proof": 9},
    )


class TestExtractLesson:
    def test_returns_first_line(self):
        source = _make_source(message="First line\nSecond line")
        assert _extract_lesson(source) == "First line"

    def test_truncates_long_messages(self):
        source = _make_source(message="x" * 300)
        assert len(_extract_lesson(source)) <= 200

    def test_handles_empty_message(self):
        source = _make_source(message="")
        assert isinstance(_extract_lesson(source), str)


class TestPostId:
    def test_deterministic(self):
        source = _make_source()
        assert _post_id(source) == _post_id(source)

    def test_uses_sha_prefix(self):
        source = _make_source(sha="deadbeef1234")
        assert "deadbeef1234" in _post_id(source)

    def test_different_shas_give_different_ids(self):
        s1 = _make_source(sha="aaa111")
        s2 = _make_source(sha="bbb222")
        assert _post_id(s1) != _post_id(s2)


class TestInferTags:
    def test_detects_ai_tag(self):
        source = _make_source(message="implement rag pipeline for llm")
        tags = _infer_tags(source)
        assert "ai" in tags

    def test_detects_distributed_systems_tag(self):
        source = _make_source(message="fix temporal workflow saga timeout")
        tags = _infer_tags(source)
        assert "distributed-systems" in tags

    def test_detects_testing_tag(self):
        source = SourceCommit(
            sha="x", repo="r", message="add playwright tests", author="a", timestamp="t",
            files_changed=["spec/test.py"], diff_summary="", score=0, score_breakdown={}
        )
        tags = _infer_tags(source)
        assert "testing" in tags

    def test_defaults_to_engineering(self):
        source = _make_source(message="update schema")
        tags = _infer_tags(source)
        assert tags  # at least one tag


class TestPlaceholderGenerators:
    def test_placeholder_linkedin_contains_commit_message(self):
        source = _make_source()
        post = _placeholder_linkedin(source, "result")
        assert "fix Temporal workflow timeout" in post

    def test_placeholder_linkedin_follows_post_structure(self):
        """Placeholder should read like a real post, not dump raw data."""
        source = _make_source()
        post = _placeholder_linkedin(source, "story")
        # Should NOT contain raw data markers or internal metadata
        assert "[DRAFT" not in post
        assert "Lesson score:" not in post
        assert "Score:" not in post
        # Should have a human-readable hook and a CTA question
        lines = [l for l in post.splitlines() if l.strip()]
        assert lines[0]  # hook line exists
        assert "?" in post  # ends with a question (CTA)

    def test_placeholder_linkedin_no_commit_metadata(self):
        """Placeholder should not include raw commit metadata like line counts."""
        source = _make_source()
        post = _placeholder_linkedin(source, "result")
        assert "+45 lines" not in post
        assert "-12 lines" not in post
        assert "touches:" not in post
        assert source.diff_summary not in post

    def test_placeholder_linkedin_shows_file_names(self):
        """Placeholder should show readable file names, not line count metadata."""
        source = _make_source()
        post = _placeholder_linkedin(source, "result")
        assert "workflow/saga.go" in post

    def test_placeholder_x_thread_has_tweet_numbers(self):
        linkedin = "Hook line\n\nBody paragraph\n\nClosing question?"
        thread = _placeholder_x_thread(linkedin)
        assert "1/" in thread

    def test_placeholder_ig_has_hashtags(self):
        linkedin = "Hook\n\nBody\n\nQuestion?"
        caption = _placeholder_ig(linkedin)
        assert "#" in caption


class TestGeneratePost:
    def test_returns_post_object(self):
        source = _make_source()
        post = generate_post(source, hook_pattern="result", openai_client=None)
        assert isinstance(post, Post)

    def test_post_status_is_draft(self):
        source = _make_source()
        post = generate_post(source, openai_client=None)
        assert post.status == PostStatus.DRAFT

    def test_post_id_uses_sha(self):
        source = _make_source(sha="abc123def456")
        post = generate_post(source, openai_client=None)
        assert source.sha[:12] in post.id

    def test_post_has_all_platform_variants(self):
        source = _make_source()
        post = generate_post(source, openai_client=None)
        assert post.linkedin_post
        assert post.x_thread
        assert post.ig_caption

    def test_unknown_hook_pattern_defaults_to_result(self):
        source = _make_source()
        post = generate_post(source, hook_pattern="nonexistent_pattern", openai_client=None)
        assert post.hook_pattern == "result"

    def test_experiment_fields_stored(self):
        source = _make_source()
        post = generate_post(
            source,
            experiment_id="exp-001",
            experiment_variant="story",
            openai_client=None,
        )
        assert post.experiment_id == "exp-001"
        assert post.experiment_variant == "story"

    def test_valid_hook_patterns(self):
        source = _make_source()
        for pattern in HOOK_PATTERNS:
            post = generate_post(source, hook_pattern=pattern, openai_client=None)
            assert post.hook_pattern == pattern

    def test_post_lesson_not_empty(self):
        source = _make_source()
        post = generate_post(source, openai_client=None)
        assert post.lesson


class TestExtractLinkedInSection:
    def test_extracts_section_content(self):
        md = "# Title\n\n## Final LinkedIn Post\n\nHook line.\n\nBody paragraph.\n\n## How to Post\n\nIgnore this."
        result = _extract_linkedin_section(md)
        assert "Hook line." in result
        assert "Body paragraph." in result
        assert "How to Post" not in result

    def test_stops_at_horizontal_rule(self):
        md = "## Final LinkedIn Post\n\nPost content here.\n\n---\n\nAfter separator."
        result = _extract_linkedin_section(md)
        assert "Post content here." in result
        assert "After separator." not in result

    def test_returns_empty_if_no_section(self):
        md = "# Title\n\nSome content without the expected heading."
        result = _extract_linkedin_section(md)
        assert result == ""

    def test_strips_whitespace(self):
        md = "## Final LinkedIn Post\n\n  \n\nActual post.\n\n  \n"
        result = _extract_linkedin_section(md)
        assert result.strip() == result


class TestLoadGoodPostsExamples:
    def test_returns_list(self):
        examples = _load_good_posts_examples()
        assert isinstance(examples, list)

    def test_examples_are_non_empty_strings(self):
        examples = _load_good_posts_examples()
        for ex in examples:
            assert isinstance(ex, str)
            assert len(ex) > 0

    def test_loads_from_good_posts_dir(self, tmp_path):
        # Temporarily override the directory to a tmp location
        original = pg._GOOD_POSTS_DIR
        tmp_dir = tmp_path / "good-social-posts"
        tmp_dir.mkdir()
        (tmp_dir / "test-post.md").write_text(
            "# Test\n\n## Final LinkedIn Post\n\nHook.\n\nBody.\n\n---\n",
            encoding="utf-8",
        )
        pg._GOOD_POSTS_DIR = tmp_dir
        try:
            examples = _load_good_posts_examples()
            assert len(examples) == 1
            assert "Hook." in examples[0]
        finally:
            pg._GOOD_POSTS_DIR = original

    def test_missing_dir_returns_empty_list(self, tmp_path):
        original = pg._GOOD_POSTS_DIR
        pg._GOOD_POSTS_DIR = tmp_path / "nonexistent"
        try:
            examples = _load_good_posts_examples()
            assert examples == []
        finally:
            pg._GOOD_POSTS_DIR = original


class TestQualityRubric:
    def test_scores_high_quality_post_higher(self):
        post = """
I thought retry logic was solved.

Then one Temporal workflow doubled charges during activity retries.

I fixed it by enforcing idempotency keys before every write:

    if payment_exists(workflow_id):
        return existing_payment
    save_payment(workflow_id, amount)

p99 latency dropped from 2000ms to 220ms after removing duplicate writes.

That one guard fixed correctness and performance at once.

Have you had a bug that looked like one problem but was two?
""".strip()
        score = score_linkedin_post_quality(post)
        assert score.total >= 75.0

    def test_scores_low_quality_post_lower(self):
        post = "I am excited to share this journey. We improved things. Great stuff."
        score = score_linkedin_post_quality(post)
        assert score.total < 75.0
        assert score.issues


class TestQualityGateGeneration:
    def test_rejects_low_quality_placeholder_when_no_openai(self):
        source = _make_source()
        post = generate_post_with_quality_gate(
            source=source,
            openai_client=None,
            quality_threshold=95.0,
        )
        assert post is None

    def test_returns_post_when_initial_quality_passes(self, monkeypatch):
        source = _make_source()
        base_post = generate_post(source, openai_client=None)

        monkeypatch.setattr(
            pg,
            "generate_post",
            lambda *args, **kwargs: base_post,
        )
        monkeypatch.setattr(
            pg,
            "score_linkedin_post_quality",
            lambda *args, **kwargs: QualityScore(total=90.0, breakdown={}, issues=[]),
        )

        result = generate_post_with_quality_gate(
            source=source,
            openai_client=object(),
        )
        assert result is base_post

    def test_rewrites_until_quality_passes(self, monkeypatch):
        source = _make_source()
        base_post = generate_post(source, openai_client=None)
        base_post.linkedin_post = "Weak draft."
        base_post.x_thread = "old thread"
        base_post.ig_caption = "old caption"

        monkeypatch.setattr(pg, "generate_post", lambda *args, **kwargs: base_post)

        scores = [
            QualityScore(total=40.0, breakdown={}, issues=["needs proof"]),
            QualityScore(total=85.0, breakdown={}, issues=[]),
            QualityScore(total=85.0, breakdown={}, issues=[]),
        ]

        def fake_score(*args, **kwargs):
            return scores.pop(0)

        monkeypatch.setattr(pg, "score_linkedin_post_quality", fake_score)

        calls: list[str] = []

        def fake_openai(client, model, system, user):
            calls.append(user)
            if "Rewrite this LinkedIn post" in user:
                return "Improved draft with proof.\n\nHave you seen this?"
            if "Convert this LinkedIn post into a tight X (Twitter) thread." in user:
                return "1/ better thread"
            if "Create an Instagram caption based on this LinkedIn post." in user:
                return "better caption"
            return "unexpected"

        monkeypatch.setattr(pg, "_generate_with_openai", fake_openai)

        result = generate_post_with_quality_gate(
            source=source,
            openai_client=object(),
            quality_threshold=75.0,
            max_rewrites=QUALITY_GATE_DEFAULT_MAX_REWRITES,
        )

        assert result is not None
        assert result.linkedin_post.startswith("Improved draft")
        assert result.x_thread == "1/ better thread"
        assert result.ig_caption == "better caption"

    def test_returns_none_when_rewrites_still_fail(self, monkeypatch):
        source = _make_source()
        base_post = generate_post(source, openai_client=None)
        monkeypatch.setattr(pg, "generate_post", lambda *args, **kwargs: base_post)
        monkeypatch.setattr(
            pg,
            "score_linkedin_post_quality",
            lambda *args, **kwargs: QualityScore(total=30.0, breakdown={}, issues=["weak"]),
        )
        monkeypatch.setattr(pg, "_generate_with_openai", lambda *args, **kwargs: "still weak")

        result = generate_post_with_quality_gate(
            source=source,
            openai_client=object(),
            quality_threshold=75.0,
            max_rewrites=2,
        )
        assert result is None
