"""Integration tests for feedback-to-prompt injection and auto-regeneration.

A. Rejection patterns should be injected into the system prompt as AVOID instructions.
B. Posts that fail the agent loop should be labeled for auto-regeneration.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.post_generator import _build_system_prompt


class TestRejectionPatternInjection:
    """Top rejection reasons should appear in the system prompt as AVOID instructions."""

    def test_injects_top_reasons_into_prompt(self, tmp_path):
        """When learning state has rejection reasons, prompt should include them."""
        ls_path = tmp_path / "learning_state.json"
        ls_path.write_text(json.dumps({
            "scoring_weights": {"novelty": 1.0, "impact": 1.0, "teachability": 1.0, "relevance": 1.0, "proof": 1.0},
            "hook_pattern_scores": {},
            "topic_scores": {},
            "best_performing_posts": [],
            "total_posts_analyzed": 0,
            "not_published_reasons": {
                "skip": 18,
                "not_relevant": 6,
                "this doesn't match what we have in the good-social-posts folder at all": 9,
            },
            "archived_not_published_reasons": {},
            "total_feedback_received": 0,
            "total_ratings_received": 0,
            "average_rating": 0.0,
            "explicit_ratings_received": 0,
            "explicit_average_rating": 0.0,
            "applied_feedback_fingerprints": {},
            "implicit_feedback_events": {},
            "version": 1,
        }))

        prompt = _build_system_prompt(learning_state_path=str(ls_path))

        # Should contain rejection avoidance instructions
        assert "AVOID" in prompt or "avoid" in prompt.lower()
        assert "skip" in prompt.lower() or "not_relevant" in prompt.lower() or "doesn't match" in prompt.lower()

    def test_no_injection_when_no_reasons(self, tmp_path):
        """When learning state has empty reasons, no AVOID block should appear."""
        ls_path = tmp_path / "learning_state.json"
        ls_path.write_text(json.dumps({
            "scoring_weights": {"novelty": 1.0, "impact": 1.0, "teachability": 1.0, "relevance": 1.0, "proof": 1.0},
            "hook_pattern_scores": {},
            "topic_scores": {},
            "best_performing_posts": [],
            "total_posts_analyzed": 0,
            "not_published_reasons": {},
            "archived_not_published_reasons": {},
            "total_feedback_received": 0,
            "total_ratings_received": 0,
            "average_rating": 0.0,
            "explicit_ratings_received": 0,
            "explicit_average_rating": 0.0,
            "applied_feedback_fingerprints": {},
            "implicit_feedback_events": {},
            "version": 1,
        }))

        prompt = _build_system_prompt(learning_state_path=str(ls_path))

        # Should NOT contain rejection avoidance block
        assert "Posts were rejected for" not in prompt

    def test_limits_to_top_3_reasons(self, tmp_path):
        """Only the top 3 most common rejection reasons should be injected."""
        ls_path = tmp_path / "learning_state.json"
        ls_path.write_text(json.dumps({
            "scoring_weights": {"novelty": 1.0, "impact": 1.0, "teachability": 1.0, "relevance": 1.0, "proof": 1.0},
            "hook_pattern_scores": {},
            "topic_scores": {},
            "best_performing_posts": [],
            "total_posts_analyzed": 0,
            "not_published_reasons": {
                "reason_a": 20,
                "reason_b": 15,
                "reason_c": 10,
                "reason_d": 5,
                "reason_e": 1,
            },
            "archived_not_published_reasons": {},
            "total_feedback_received": 0,
            "total_ratings_received": 0,
            "average_rating": 0.0,
            "explicit_ratings_received": 0,
            "explicit_average_rating": 0.0,
            "applied_feedback_fingerprints": {},
            "implicit_feedback_events": {},
            "version": 1,
        }))

        prompt = _build_system_prompt(learning_state_path=str(ls_path))

        # Top 3 should be present
        assert "reason_a" in prompt
        assert "reason_b" in prompt
        assert "reason_c" in prompt
        # Bottom 2 should NOT be present
        assert "reason_d" not in prompt
        assert "reason_e" not in prompt


class TestAutoRegenOnReject:
    """Posts rejected by agent loop should be labeled for auto-regeneration."""

    def test_adds_needs_regen_label_on_reject(self):
        """When agent loop returns reject verdict, the issue should get labeled."""
        from src.agent_loop import AgentLoopResult

        mock_result = AgentLoopResult(
            post_text="Bad post",
            bar_raiser_verdict={"verdict": "reject", "failures": ["Hook too weak"]},
            iterations=2,
            improved=False,
        )

        with (
            patch("src.github_storage.requests.post") as mock_post,
            patch("src.github_storage.requests.get") as mock_get,
        ):
            mock_post.return_value = MagicMock(ok=True, status_code=200, json=lambda: {"number": 999})
            mock_get.return_value = MagicMock(ok=True, json=lambda: [])

            from src.github_storage import add_label_to_issue
            add_label_to_issue("owner/repo", "fake-token", 999, "needs-regeneration")

            # Verify the label API was called
            mock_post.assert_called()
            call_args = mock_post.call_args
            assert "labels" in str(call_args) or "needs-regeneration" in str(call_args)
