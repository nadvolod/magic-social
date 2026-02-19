"""Tests for the data models."""

import json
import pytest

from src.models import (
    AnalyticsSnapshot,
    Experiment,
    ExperimentStatus,
    ExperimentVariable,
    Post,
    PostStatus,
    SourceCommit,
)


class TestSourceCommit:
    def _make(self, **kwargs):
        defaults = {
            "sha": "abc123def456",
            "repo": "owner/repo",
            "message": "fix temporal workflow timeout",
            "author": "Alice",
            "timestamp": "2024-01-01T10:00:00Z",
        }
        defaults.update(kwargs)
        return SourceCommit(**defaults)

    def test_to_dict_and_from_dict_roundtrip(self):
        commit = self._make(files_changed=["a.py", "b.py"], score=55.0)
        data = commit.to_dict()
        restored = SourceCommit.from_dict(data)
        assert restored.sha == commit.sha
        assert restored.score == commit.score
        assert restored.files_changed == commit.files_changed

    def test_to_json_is_valid_json(self):
        commit = self._make()
        payload = commit.to_json()
        parsed = json.loads(payload)
        assert parsed["sha"] == commit.sha

    def test_default_fields(self):
        commit = self._make()
        assert commit.files_changed == []
        assert commit.diff_summary == ""
        assert commit.score == 0.0
        assert commit.score_breakdown == {}


class TestPost:
    def _make(self, **kwargs):
        defaults = {
            "id": "post-abc123def456",
            "source_commit_sha": "abc123def456",
            "repo": "owner/repo",
            "lesson": "Temporal activities must be idempotent",
            "linkedin_post": "Hook\n\nBody\n\nQuestion?",
            "x_thread": "1/ Hook\n\n2/ Body",
            "ig_caption": "Caption #engineering",
            "hook_pattern": "result",
        }
        defaults.update(kwargs)
        return Post(**defaults)

    def test_default_status_is_draft(self):
        post = self._make()
        assert post.status == PostStatus.DRAFT

    def test_to_dict_serializes_status_as_string(self):
        post = self._make(status=PostStatus.PUBLISHED)
        d = post.to_dict()
        assert d["status"] == "published"

    def test_from_dict_roundtrip(self):
        post = self._make(tags=["ai", "distributed-systems"])
        restored = Post.from_dict(post.to_dict())
        assert restored.id == post.id
        assert restored.lesson == post.lesson
        assert restored.tags == post.tags
        assert restored.status == post.status

    def test_to_json_is_valid_json(self):
        post = self._make()
        payload = post.to_json()
        parsed = json.loads(payload)
        assert parsed["id"] == post.id

    def test_from_dict_with_string_status(self):
        post = self._make()
        d = post.to_dict()
        d["status"] = "approved"
        restored = Post.from_dict(d)
        assert restored.status == PostStatus.APPROVED


class TestAnalyticsSnapshot:
    def _make(self, **kwargs):
        defaults = {
            "post_id": "post-abc123",
            "github_issue_number": 42,
            "impressions": 1000,
            "reactions": 50,
            "comments": 20,
            "reposts": 10,
            "saves": 30,
            "follower_delta": 5,
            "click_through": 15,
        }
        defaults.update(kwargs)
        return AnalyticsSnapshot(**defaults)

    def test_engagement_score_weights_saves_highest(self):
        # A post with saves should score higher than one with same total reactions
        high_saves = self._make(saves=10, reposts=0, comments=0, reactions=0, click_through=0)
        high_reactions = self._make(saves=0, reposts=0, comments=0, reactions=10, click_through=0)
        assert high_saves.engagement_score > high_reactions.engagement_score

    def test_engagement_score_formula(self):
        snap = self._make(
            impressions=1000,
            reactions=10,
            comments=5,
            reposts=3,
            saves=2,
            click_through=4,
        )
        expected = 10 * 1.0 + 5 * 3.0 + 3 * 3.0 + 2 * 4.0 + 4 * 2.0
        assert snap.engagement_score == pytest.approx(expected)

    def test_engagement_rate_calculation(self):
        snap = self._make(impressions=1000, reactions=10, comments=5, reposts=3, saves=2)
        expected_rate = (10 + 5 + 3 + 2) / 1000 * 100
        assert snap.engagement_rate == pytest.approx(expected_rate)

    def test_engagement_rate_zero_when_no_impressions(self):
        snap = self._make(impressions=0)
        assert snap.engagement_rate == 0.0

    def test_roundtrip_serialization(self):
        snap = self._make()
        restored = AnalyticsSnapshot.from_dict(snap.to_dict())
        assert restored.post_id == snap.post_id
        assert restored.saves == snap.saves


class TestExperiment:
    def _make(self, **kwargs):
        defaults = {
            "id": "exp-001",
            "variable": ExperimentVariable.HOOK_STYLE,
            "variants": ["result", "story", "contrarian"],
            "hypothesis": "Result hooks drive more saves",
        }
        defaults.update(kwargs)
        return Experiment(**defaults)

    def test_default_status_is_running(self):
        exp = self._make()
        assert exp.status == ExperimentStatus.RUNNING

    def test_to_dict_serializes_enums(self):
        exp = self._make()
        d = exp.to_dict()
        assert d["variable"] == "hook_style"
        assert d["status"] == "running"

    def test_from_dict_roundtrip(self):
        exp = self._make()
        restored = Experiment.from_dict(exp.to_dict())
        assert restored.id == exp.id
        assert restored.variable == exp.variable
        assert restored.status == exp.status
        assert restored.variants == exp.variants
