"""Tests for src/voice_deriver.py."""

from __future__ import annotations

from pathlib import Path

from src import voice_deriver
from src.screenshot_learning import ScreenshotExample, ScreenshotLearningState


def _make_example(*, issue_number: int, classification: str, score: float) -> ScreenshotExample:
    return ScreenshotExample(
        issue_number=issue_number,
        issue_url=f"https://example/issues/{issue_number}",
        image_url="https://example/img.png",
        recorded_at="2026-04-01T00:00:00+00:00",
        metrics={"reactions": int(score), "comments": 0, "reposts": 0, "saves": 0},
        engagement_score=score,
        percentile=0.95 if classification == "top_10_percent" else 0.3,
        classification=classification,
        signals={"hook_style": "story" if classification == "top_10_percent" else "promo"},
        summary=f"Example {issue_number}",
        hook_excerpt=f"Hook {issue_number}",
    )


# ---------------------------------------------------------------------------
# Source gathering
# ---------------------------------------------------------------------------


def test_gather_voice_sources_uses_top_screenshots_only(tmp_path, monkeypatch):
    """Only top_10_percent examples should reach the voice deriver."""
    state = ScreenshotLearningState(
        examples=[
            _make_example(issue_number=1, classification="top_10_percent", score=400),
            _make_example(issue_number=2, classification="bottom_90_percent", score=5),
            _make_example(issue_number=3, classification="top_10_percent", score=200),
        ]
    )
    state_path = tmp_path / "screenshot_learning.json"
    state.save(str(state_path))

    # Stub out _load_good_posts_examples so the test doesn't depend on disk content.
    monkeypatch.setattr(voice_deriver, "_load_good_posts_examples", lambda: ["GOOD EXAMPLE 1"])

    sources = voice_deriver.gather_voice_sources(
        screenshot_state_path=str(state_path), top_n=5
    )

    issue_numbers = {e.issue_number for e in sources.top_reference_examples}
    assert issue_numbers == {1, 3}  # bottom excluded
    assert sources.good_examples == ["GOOD EXAMPLE 1"]


def test_gather_voice_sources_respects_top_n(tmp_path, monkeypatch):
    state = ScreenshotLearningState(
        examples=[
            _make_example(issue_number=i, classification="top_10_percent", score=100 - i)
            for i in range(10)
        ]
    )
    state_path = tmp_path / "screenshot_learning.json"
    state.save(str(state_path))
    monkeypatch.setattr(voice_deriver, "_load_good_posts_examples", lambda: [])

    sources = voice_deriver.gather_voice_sources(
        screenshot_state_path=str(state_path), top_n=3
    )
    assert len(sources.top_reference_examples) == 3
    # Sorted by score desc, so issue_numbers 0,1,2 (highest scores)
    assert {e.issue_number for e in sources.top_reference_examples} == {0, 1, 2}


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------


def test_build_voice_prompts_substitutes_all_placeholders():
    sources = voice_deriver.VoiceSources(
        top_reference_examples=[
            _make_example(issue_number=42, classification="top_10_percent", score=100),
        ],
        good_examples=["A good example post about Temporal."],
    )
    system, user = voice_deriver.build_voice_prompts(sources)

    assert "synthesize" in system.lower() or "voice" in system.lower()
    assert "ref #42" in user
    assert "A good example post about Temporal." in user
    assert "1 top reference posts, 1 curated examples" in user
    # All placeholders consumed:
    assert "{top_reference_block}" not in user
    assert "{good_examples_block}" not in user
    assert "{generated_at}" not in user
    assert "{source_counts}" not in user


# ---------------------------------------------------------------------------
# Generation + write
# ---------------------------------------------------------------------------


class _StubClient:
    def __init__(self, response_text: str):
        self.response_text = response_text
        self.calls = []
        outer = self

        class _Completions:
            def create(self, **kwargs):
                outer.calls.append(kwargs)
                return type(
                    "Resp",
                    (),
                    {
                        "choices": [
                            type(
                                "Choice",
                                (),
                                {"message": type("Msg", (), {"content": outer.response_text})()},
                            )()
                        ]
                    },
                )()

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()


def test_derive_voice_calls_client_with_split_prompt():
    sources = voice_deriver.VoiceSources(
        top_reference_examples=[
            _make_example(issue_number=42, classification="top_10_percent", score=100),
        ],
        good_examples=["Example body."],
    )
    stub = "# Voice Guide — synthesized 2026-01-01\n\n## Tone\n- direct\n\n_footer_\n"
    client = _StubClient(stub)

    md = voice_deriver.derive_voice(sources, client=client)

    assert "Voice Guide" in md
    assert len(client.calls) == 1
    # The user message must include source counts placeholder substitution
    messages = client.calls[0]["messages"]
    assert any("ref #42" in m["content"] for m in messages if isinstance(m["content"], str))


def test_run_refresh_skips_llm_when_no_sources(tmp_path, monkeypatch):
    """Empty sources → empty-voice fallback, no LLM call."""
    monkeypatch.setattr(
        voice_deriver,
        "gather_voice_sources",
        lambda: voice_deriver.VoiceSources(top_reference_examples=[], good_examples=[]),
    )

    target = tmp_path / "voice.md"
    markdown = voice_deriver.run_refresh(target_path=target)

    assert "0 top reference posts" in markdown
    assert "0 curated examples" in markdown
    assert target.exists()
    # File contains the empty-voice placeholder, not an LLM-generated guide
    assert "_No source data available yet" in target.read_text(encoding="utf-8")


def test_write_voice_overwrites_target_path(tmp_path):
    target = tmp_path / "playbook" / "voice.md"
    voice_deriver.write_voice("# Initial\n", target_path=target)
    voice_deriver.write_voice("# Replaced\n", target_path=target)
    assert target.read_text(encoding="utf-8") == "# Replaced\n"
