"""Integration tests for screenshot learning signal protection.

Verifies that the quality fixes actually prevent the contradictions
that caused post quality regression:
- has_code is protected (not overridden by screenshot learning)
- has_numbers is protected
- Minimum support threshold filters noise
- Low-confidence qualifier appears with few examples
- Prompt guidance doesn't contain contradictory signals
"""

from __future__ import annotations

from src.screenshot_learning import (
    ScreenshotLearningState,
    ScreenshotExample,
    build_signal_balance,
    build_prompt_guidance,
    PROTECTED_SIGNAL_KEYS,
)


def _make_examples(
    top_signals_list: list[dict],
    bottom_signals_list: list[dict],
) -> ScreenshotLearningState:
    """Build a state with top_10 and bottom_90 examples."""
    examples = []
    for i, signals in enumerate(top_signals_list):
        examples.append(ScreenshotExample(
            issue_number=100 + i,
            issue_url=f"u{100 + i}",
            image_url=f"img{100 + i}",
            recorded_at=f"2026-04-0{i+1}T00:00:00Z",
            classification="top_10_percent",
            signals=signals,
        ))
    for i, signals in enumerate(bottom_signals_list):
        examples.append(ScreenshotExample(
            issue_number=200 + i,
            issue_url=f"u{200 + i}",
            image_url=f"img{200 + i}",
            recorded_at=f"2026-04-0{i+1}T00:00:00Z",
            classification="bottom_90_percent",
            signals=signals,
        ))
    return ScreenshotLearningState(examples=examples)


class TestProtectedSignals:
    """has_code and has_numbers must never appear in signal guidance."""

    def test_has_code_excluded_from_negative_signals(self):
        """Reproduces the exact bug: all has_code=true posts in bottom_90."""
        state = _make_examples(
            top_signals_list=[
                {"hook_style": "personal story", "has_code": False},
                {"hook_style": "announcement", "has_code": False},
                {"hook_style": "personal story", "has_code": False},
            ],
            bottom_signals_list=[
                {"hook_style": "tutorial", "has_code": True},
                {"hook_style": "tutorial", "has_code": True},
                {"hook_style": "informative", "has_code": True},
                {"hook_style": "informative", "has_code": True},
            ],
        )
        pos, neg = build_signal_balance(state)
        # has_code must NOT appear in either list
        all_signals = pos + neg
        assert not any("has_code" in s for s in all_signals), \
            f"has_code should be protected but found in signals: {all_signals}"

    def test_has_numbers_excluded_from_signals(self):
        """Reproduces the contradiction: has_numbers=true AND has_numbers=false both in avoid."""
        state = _make_examples(
            top_signals_list=[
                {"has_numbers": True},
                {"has_numbers": False},
            ],
            bottom_signals_list=[
                {"has_numbers": True},
                {"has_numbers": False},
                {"has_numbers": True},
            ],
        )
        pos, neg = build_signal_balance(state)
        all_signals = pos + neg
        assert not any("has_numbers" in s for s in all_signals), \
            f"has_numbers should be protected but found in signals: {all_signals}"

    def test_protected_keys_constant_includes_both(self):
        assert "has_code" in PROTECTED_SIGNAL_KEYS
        assert "has_numbers" in PROTECTED_SIGNAL_KEYS


class TestMinimumSupportThreshold:
    """Signals with < 2 examples in either bucket should be filtered."""

    def test_single_example_signal_excluded(self):
        """A signal seen only once should not influence generation."""
        state = _make_examples(
            top_signals_list=[
                {"tone": "educational"},  # only 1 example of this
            ],
            bottom_signals_list=[
                {"tone": "professional"},
                {"tone": "professional"},
            ],
        )
        pos, neg = build_signal_balance(state)
        # "tone=educational" has only 1 top example — below threshold
        assert "tone=educational" not in pos
        # "tone=professional" has 2 bottom examples — above threshold
        assert "tone=professional" in neg

    def test_two_examples_included(self):
        """A signal with 2+ examples should be included."""
        state = _make_examples(
            top_signals_list=[
                {"cta_type": "question"},
                {"cta_type": "question"},
            ],
            bottom_signals_list=[
                {"cta_type": "link"},
                {"cta_type": "link"},
            ],
        )
        pos, neg = build_signal_balance(state)
        assert "cta_type=question" in pos
        assert "cta_type=link" in neg


class TestLowConfidenceQualifier:
    """With < 20 examples, guidance should be marked as low-confidence."""

    def test_few_examples_shows_qualifier(self):
        state = _make_examples(
            top_signals_list=[
                {"tone": "informative"},
                {"tone": "informative"},
            ],
            bottom_signals_list=[
                {"tone": "professional"},
                {"tone": "professional"},
            ],
        )
        guidance = build_prompt_guidance(state)
        assert "Low-confidence signals" in guidance
        assert "4 examples" in guidance

    def test_many_examples_no_qualifier(self):
        # Create 20+ examples
        tops = [{"tone": "informative"}] * 10
        bottoms = [{"tone": "professional"}] * 12
        state = _make_examples(tops, bottoms)
        guidance = build_prompt_guidance(state)
        assert "Low-confidence" not in guidance
        assert "Screenshot-derived" in guidance


class TestRealDataIntegration:
    """Test with the actual screenshot_learning.json from the repo."""

    def test_real_data_no_has_code_in_guidance(self):
        """Load the real screenshot data and verify no has_code contradiction."""
        state = ScreenshotLearningState.load("screenshot_learning.json")
        guidance = build_prompt_guidance(state)
        assert "has_code=true" not in guidance
        assert "has_code=false" not in guidance

    def test_real_data_no_has_numbers_contradiction(self):
        """Real data should not have both has_numbers=true and has_numbers=false."""
        state = ScreenshotLearningState.load("screenshot_learning.json")
        pos, neg = build_signal_balance(state)
        all_signals = pos + neg
        assert not ("has_numbers=true" in all_signals and "has_numbers=false" in all_signals), \
            "Contradictory has_numbers signals found"

    def test_real_data_has_low_confidence_qualifier(self):
        """With 11 examples, guidance should show low-confidence qualifier."""
        state = ScreenshotLearningState.load("screenshot_learning.json")
        guidance = build_prompt_guidance(state)
        assert "Low-confidence" in guidance
