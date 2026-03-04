"""Tests for agent-level learning guardrails."""

from src.agent import apply_learning_guardrails
from src.analytics import LearningState


def test_apply_learning_guardrails_no_bad_batch_keeps_inputs():
    state = LearningState()
    threshold, max_posts = apply_learning_guardrails(state, threshold=20.0, max_posts=10)
    assert threshold == 20.0
    assert max_posts == 10


def test_apply_learning_guardrails_tightens_with_bad_batch_signal():
    state = LearningState(
        not_published_reasons={
            "historical_batch_bad_practice_pre_2026-03-03_2359_est": 37
        }
    )
    threshold, max_posts = apply_learning_guardrails(state, threshold=15.0, max_posts=10)
    assert threshold == 40.0
    assert max_posts == 3


def test_apply_learning_guardrails_preserves_stricter_existing_values():
    state = LearningState(
        not_published_reasons={
            "historical_batch_bad_practice_pre_2026-03-03_2359_est": 50
        }
    )
    threshold, max_posts = apply_learning_guardrails(state, threshold=55.0, max_posts=2)
    assert threshold == 55.0
    assert max_posts == 2
