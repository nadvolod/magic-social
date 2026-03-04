"""Tests for the commit scoring algorithm."""

import pytest

from src.scoring import (
    SCORE_THRESHOLD,
    ScoreBreakdown,
    is_low_value,
    is_sensitive,
    score_commit,
    score_impact,
    score_novelty,
    score_proof,
    score_relevance,
    score_teachability,
)


class TestSensitiveFilter:
    def test_detects_api_key(self):
        assert is_sensitive("added api_key = 'abc123'")

    def test_detects_secret(self):
        assert is_sensitive("secret_key = os.environ.get('SECRET')")

    def test_detects_password(self):
        assert is_sensitive("password=hunter2")

    def test_detects_token(self):
        assert is_sensitive("auth_token: Bearer xyz")

    def test_clean_message_passes(self):
        assert not is_sensitive("refactor temporal workflow retry logic")

    def test_case_insensitive(self):
        assert is_sensitive("API_KEY = 'abc'")


class TestLowValueFilter:
    def test_merge_commit(self):
        assert is_low_value("Merge branch 'feature' into main")

    def test_wip_commit(self):
        assert is_low_value("wip: fixing tests")

    def test_bump_version(self):
        assert is_low_value("bump version 1.2.3")

    def test_typo_fix(self):
        assert is_low_value("typo in README")

    def test_lint(self):
        assert is_low_value("fix linting issues")

    def test_meaningful_commit_not_filtered(self):
        assert not is_low_value("implement retry logic for Temporal workflow activities")

    def test_initial_commit_filtered(self):
        assert is_low_value("Initial commit")


class TestIndividualScorers:
    def test_novelty_rewards_insight_words(self):
        score = score_novelty("discovered a gotcha in Temporal.io saga patterns", "")
        assert score > 0

    def test_novelty_caps_at_20(self):
        long_msg = " ".join(["discovered gotcha insight trick hack workaround"] * 5)
        score = score_novelty(long_msg, "")
        assert score <= 20.0

    def test_impact_detects_fix(self):
        score = score_impact("fix retry overflow bug in distributed queue", "", [])
        assert score > 0

    def test_impact_rewards_multiple_files(self):
        score = score_impact("refactor", "", ["a.py", "b.py", "c.py", "d.py", "e.py"])
        assert score > 0

    def test_teachability_rewards_long_message(self):
        long_msg = "refactor workflow because it was causing timeout failures in the saga"
        score = score_teachability(long_msg, "diff context here")
        assert score > 0

    def test_relevance_detects_ai_topic(self):
        score = score_relevance("add rag pipeline for llm retrieval", "", [])
        assert score > 0

    def test_relevance_detects_temporal(self):
        score = score_relevance("fix temporal workflow activity timeout", "", [])
        assert score > 0

    def test_proof_detects_percentage(self):
        score = score_proof("reduce latency by 40%", "")
        assert score > 0

    def test_proof_detects_before_after(self):
        score = score_proof("cut p99 from 2000ms to 200ms", "")
        assert score > 0

    def test_proof_caps_at_20(self):
        msg = "reduce by 50% cut from 1000 to 500 improve by 30% save 10 hours prevent 5 bugs"
        score = score_proof(msg, "")
        assert score <= 20.0


class TestScoreCommit:
    def test_sensitive_commit_scores_zero(self):
        total, breakdown = score_commit("add api_key = 'abc'")
        assert total == 0.0
        assert breakdown.total == 0.0

    def test_low_value_commit_scores_zero(self):
        total, breakdown = score_commit("Merge branch 'main' into feature")
        assert total == 0.0

    def test_high_quality_commit_scores_above_threshold(self):
        total, breakdown = score_commit(
            message="fix Temporal.io workflow saga timeout: reduce p99 latency by 60% because activities were not idempotent",
            diff_summary="refactored retry logic +45 lines, -12 lines",
            files_changed=["workflow/saga.go", "workflow/activity.go", "tests/integration_test.go"],
        )
        assert total >= SCORE_THRESHOLD
        assert breakdown.total == total

    def test_score_breakdown_sums_correctly(self):
        total, breakdown = score_commit(
            message="implement distributed tracing for AI agent workflows",
            diff_summary="add opentelemetry spans +80 lines, -5 lines",
            files_changed=["agent/tracer.py", "agent/workflow.py"],
        )
        expected_total = (
            breakdown.novelty
            + breakdown.impact
            + breakdown.teachability
            + breakdown.relevance
            + breakdown.proof
        )
        assert abs(breakdown.total - expected_total) < 0.01

    def test_returns_score_breakdown_dataclass(self):
        _, breakdown = score_commit("refactor temporal workflow")
        assert isinstance(breakdown, ScoreBreakdown)

    def test_files_changed_none_defaults_to_empty(self):
        total, _ = score_commit("fix AI agent retry logic", files_changed=None)
        assert isinstance(total, float)

    def test_total_score_capped_at_100(self):
        total, _ = score_commit(
            message="discovered gotcha insight trick hack workaround in temporal workflow ai agent rag llm",
            diff_summary="fix improve reduce latency by 50% from 1000 to 500ms save 10 hours",
            files_changed=["ai.py", "temporal.py", "distributed.py", "agent.py", "test.py"],
        )
        assert total <= 100.0
