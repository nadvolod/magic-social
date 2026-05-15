"""Integration tests for the pre-creation agent quality loop.

Tests verify the full agent loop pipeline:
- Passes good posts through without rewriting
- Rewrites rejected posts using agent-specific feedback
- Respects max_iterations limit
- Returns agent results for downstream use (issue comments)
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from src.agent_loop import agent_quality_loop, AgentLoopResult


def _mock_openai(content: str):
    """Create a mock OpenAI client that returns the given content."""
    mock_choice = MagicMock()
    mock_choice.message.content = content
    mock_resp = MagicMock()
    mock_resp.choices = [mock_choice]
    client = MagicMock()
    client.chat.completions.create.return_value = mock_resp
    return client


def _make_learning_state():
    """Create a minimal learning state for tests."""
    state = MagicMock()
    state.topic_scores = {}
    state.to_dict.return_value = {"scoring_weights": {}, "average_rating": 0.0}
    return state


# -- Quality review mock that returns scores as a dict
_GOOD_QUALITY = {
    "specificity": 18, "insight_depth": 16, "hook_strength": 17,
    "code_relevance": 15, "shareability": 16,
}
_BAD_QUALITY = {
    "specificity": 8, "insight_depth": 6, "hook_strength": 5,
    "code_relevance": 10, "shareability": 7,
}


class TestAgentLoopPassesGoodPost:
    """When all agents pass, the post should come through unchanged."""

    def test_returns_original_text_when_bar_raiser_passes(self):
        client = _mock_openai("rewritten post (should not be used)")
        ls = _make_learning_state()

        with (
            patch("src.agents.quality_reviewer.review_quality", return_value=_GOOD_QUALITY),
            patch("src.agents.resonance_checker.check_resonance", return_value={"icp_match": "strong", "icp_match_score": 18}),
            patch("src.agents.predictor.predict_outcome", return_value={"publish_probability": 80, "engagement_tier": "high"}),
            patch("src.agents.predictor.load_predictions_log", return_value=[]),
            patch("src.agents.bar_raiser.raise_the_bar", return_value={"verdict": "pass", "quality_score": 82}),
            patch("src.agents.bar_raiser.BarRaiserState.load", return_value=MagicMock()),
        ):
            result = agent_quality_loop(
                post_text="Original good post with code:\n    def hello(): pass\n\nWhat do you think?",
                commit_message="add retry logic",
                commit_diff="+ retry_policy = RetryPolicy(max_attempts=3)",
                tags=["distributed-systems"],
                hook_pattern="result",
                openai_client=client,
                learning_state=ls,
            )

        assert isinstance(result, AgentLoopResult)
        assert result.post_text == "Original good post with code:\n    def hello(): pass\n\nWhat do you think?"
        assert result.bar_raiser_verdict.get("verdict") == "pass"
        assert result.improved is False
        assert result.iterations == 0

    def test_returns_quality_review_for_issue_comments(self):
        client = _mock_openai("unused")
        ls = _make_learning_state()

        with (
            patch("src.agents.quality_reviewer.review_quality", return_value=_GOOD_QUALITY),
            patch("src.agents.resonance_checker.check_resonance", return_value={"icp_match": "strong"}),
            patch("src.agents.predictor.predict_outcome", return_value={"publish_probability": 90}),
            patch("src.agents.predictor.load_predictions_log", return_value=[]),
            patch("src.agents.bar_raiser.raise_the_bar", return_value={"verdict": "pass"}),
            patch("src.agents.bar_raiser.BarRaiserState.load", return_value=MagicMock()),
        ):
            result = agent_quality_loop(
                post_text="Good post", commit_message="msg", commit_diff="diff",
                tags=[], hook_pattern="result", openai_client=client, learning_state=ls,
            )

        # Agent results should be available for posting as issue comments
        assert result.quality_review == _GOOD_QUALITY
        assert result.resonance.get("icp_match") == "strong"
        assert result.prediction.get("publish_probability") == 90


class TestAgentLoopRewritesOnReject:
    """When the bar raiser rejects, the loop should rewrite and re-evaluate."""

    def test_rewrites_post_on_first_reject_then_passes(self):
        # The OpenAI client returns a "rewritten" post when called for rewrite
        rewritten = "Improved post with better hook and code:\n    retry_policy = RetryPolicy()\n\nThoughts?"
        client = _mock_openai(rewritten)
        ls = _make_learning_state()

        call_count = {"n": 0}

        def bar_raiser_side_effect(qr, res, pred, state):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return {"verdict": "reject", "failures": ["Hook Strength below threshold"]}
            return {"verdict": "pass", "quality_score": 78}

        with (
            patch("src.agents.quality_reviewer.review_quality", return_value=_BAD_QUALITY),
            patch("src.agents.resonance_checker.check_resonance", return_value={"icp_match": "weak"}),
            patch("src.agents.predictor.predict_outcome", return_value={"publish_probability": 30}),
            patch("src.agents.predictor.load_predictions_log", return_value=[]),
            patch("src.agents.bar_raiser.raise_the_bar", side_effect=bar_raiser_side_effect),
            patch("src.agents.bar_raiser.BarRaiserState.load", return_value=MagicMock()),
        ):
            result = agent_quality_loop(
                post_text="Bad post with weak hook",
                commit_message="msg", commit_diff="diff",
                tags=[], hook_pattern="result",
                openai_client=client, learning_state=ls,
                max_iterations=2,
            )

        # Post should be rewritten
        assert result.post_text == rewritten
        assert result.improved is True
        assert result.iterations == 1
        assert result.bar_raiser_verdict.get("verdict") == "pass"

    def test_respects_max_iterations(self):
        client = _mock_openai("rewrite attempt")
        ls = _make_learning_state()

        # Bar raiser always rejects
        with (
            patch("src.agents.quality_reviewer.review_quality", return_value=_BAD_QUALITY),
            patch("src.agents.resonance_checker.check_resonance", return_value={}),
            patch("src.agents.predictor.predict_outcome", return_value={}),
            patch("src.agents.predictor.load_predictions_log", return_value=[]),
            patch("src.agents.bar_raiser.raise_the_bar", return_value={"verdict": "reject", "failures": ["too weak"]}),
            patch("src.agents.bar_raiser.BarRaiserState.load", return_value=MagicMock()),
        ):
            result = agent_quality_loop(
                post_text="Persistently bad post",
                commit_message="msg", commit_diff="diff",
                tags=[], hook_pattern="result",
                openai_client=client, learning_state=ls,
                max_iterations=2,
            )

        # Should stop after max_iterations, returning best effort
        assert result.bar_raiser_verdict.get("verdict") == "reject"
        assert result.iterations == 2


class TestAgentLoopResilience:
    """Agent failures should not crash the loop."""

    def test_continues_when_individual_agent_fails(self):
        client = _mock_openai("unused")
        ls = _make_learning_state()

        with (
            patch("src.agents.quality_reviewer.review_quality", side_effect=RuntimeError("API timeout")),
            patch("src.agents.resonance_checker.check_resonance", return_value={"icp_match": "strong"}),
            patch("src.agents.predictor.predict_outcome", return_value={"publish_probability": 70}),
            patch("src.agents.predictor.load_predictions_log", return_value=[]),
            patch("src.agents.bar_raiser.raise_the_bar", return_value={"verdict": "pass"}),
            patch("src.agents.bar_raiser.BarRaiserState.load", return_value=MagicMock()),
        ):
            result = agent_quality_loop(
                post_text="Post text",
                commit_message="msg", commit_diff="diff",
                tags=[], hook_pattern="result",
                openai_client=client, learning_state=ls,
            )

        # Loop should still complete even with one agent down
        assert result.post_text == "Post text"
        assert result.quality_review == {}  # Failed agent returns empty
        assert result.resonance.get("icp_match") == "strong"
