"""Tests for src/reference_posts.py — extraction, parsing, analysis aggregation."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src import reference_posts


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------


def test_parse_extraction_plain_json():
    raw = '{"author": "Coworker A", "post_text": "hello", "visible_likes": 10}'
    parsed = reference_posts._parse_extraction(raw)
    assert parsed["author"] == "Coworker A"
    assert parsed["visible_likes"] == 10


def test_parse_extraction_fenced_json():
    raw = '```json\n{"author": "X"}\n```'
    assert reference_posts._parse_extraction(raw) == {"author": "X"}


def test_parse_extraction_with_surrounding_text():
    raw = 'Sure! {"author": "Y", "visible_likes": null} Done.'
    assert reference_posts._parse_extraction(raw) == {"author": "Y", "visible_likes": None}


# ---------------------------------------------------------------------------
# Event paths
# ---------------------------------------------------------------------------


def test_event_paths_structure(tmp_path, monkeypatch):
    monkeypatch.setattr(reference_posts, "REFERENCE_POSTS_DIR", tmp_path)
    paths = reference_posts.EventPaths.for_slug("replay_2026")
    paths.ensure()
    assert paths.root == tmp_path / "replay_2026"
    assert paths.raw.exists()
    assert paths.extracted.exists()
    assert paths.analysis.exists()


# ---------------------------------------------------------------------------
# Single screenshot extraction (mocked client)
# ---------------------------------------------------------------------------


def _mock_openai_response(json_payload: dict) -> MagicMock:
    """Build a mock openai.OpenAI client whose chat completions return given JSON."""
    client = MagicMock()
    message = MagicMock()
    message.content = json.dumps(json_payload)
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    client.chat.completions.create.return_value = response
    return client


def test_extract_one_screenshot_uses_multimodal_call(tmp_path):
    # Create a 1×1 PNG so the encoder has something real to read.
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
        "890000000d49444154789c63000100000005000100"
        "5dcc35a40000000049454e44ae426082"
    )
    img_path = tmp_path / "post.png"
    img_path.write_bytes(png)

    client = _mock_openai_response(
        {
            "author": "Coworker A",
            "post_text": "Replay changed how I debug.",
            "visible_likes": 128,
            "visible_comments": 34,
        }
    )

    result = reference_posts.extract_one_screenshot(img_path, openai_client=client, model="gpt-4o-mini")

    assert result["author"] == "Coworker A"
    assert result["visible_likes"] == 128
    assert result["source_file"] == "post.png"
    assert "extracted_at" in result

    # Verify the multimodal payload shape was correct
    call_kwargs = client.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "gpt-4o-mini"
    user_content = call_kwargs["messages"][0]["content"]
    assert any(c.get("type") == "image_url" for c in user_content)
    assert any(c.get("type") == "text" for c in user_content)


# ---------------------------------------------------------------------------
# load_extracted
# ---------------------------------------------------------------------------


def test_load_extracted_returns_all_json(tmp_path, monkeypatch):
    monkeypatch.setattr(reference_posts, "REFERENCE_POSTS_DIR", tmp_path)
    paths = reference_posts.EventPaths.for_slug("event_x")
    paths.ensure()
    (paths.extracted / "a.json").write_text(json.dumps({"author": "A"}), encoding="utf-8")
    (paths.extracted / "b.json").write_text(json.dumps({"author": "B"}), encoding="utf-8")

    result = reference_posts.load_extracted("event_x")
    assert [r["author"] for r in result] == ["A", "B"]


def test_load_extracted_empty_when_no_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(reference_posts, "REFERENCE_POSTS_DIR", tmp_path)
    assert reference_posts.load_extracted("nonexistent") == []


# ---------------------------------------------------------------------------
# Playbook append
# ---------------------------------------------------------------------------


def test_append_durable_lessons_appends_to_playbook(tmp_path, monkeypatch):
    playbook = tmp_path / "patterns.md"
    playbook.write_text("# Patterns\n\nExisting content.\n", encoding="utf-8")
    monkeypatch.setattr(reference_posts, "PLAYBOOK_PATTERNS_PATH", playbook)

    report = (
        "# Pattern Analysis Report\n\n"
        "## Performance summary\n\nSomething.\n\n"
        "## Durable lessons for the playbook\n\n"
        "- Contrarian hooks beat neutral hooks 2:1 [hook]\n"
        "- Posts with 1 code block out-save posts with 0 [structure]\n\n"
        "## Originality guardrails\n\n- Don't copy A's story.\n"
    )

    reference_posts._append_durable_lessons_to_playbook("replay_2026", report)

    final = playbook.read_text(encoding="utf-8")
    assert "Existing content." in final
    assert "Harvested from `replay_2026`" in final
    assert "Contrarian hooks beat neutral hooks 2:1 [hook]" in final


def test_append_durable_lessons_noop_when_section_missing(tmp_path, monkeypatch):
    playbook = tmp_path / "patterns.md"
    original = "# Patterns\n\nOriginal.\n"
    playbook.write_text(original, encoding="utf-8")
    monkeypatch.setattr(reference_posts, "PLAYBOOK_PATTERNS_PATH", playbook)

    reference_posts._append_durable_lessons_to_playbook(
        "slug", "# Report\n\n## Some other section\n\nNothing here.\n"
    )
    assert playbook.read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# Analyze prompt split
# ---------------------------------------------------------------------------


def test_split_analysis_prompt_returns_system_and_user():
    system, user = reference_posts._split_analysis_prompt()
    assert "senior linkedin content strategist" in system.lower()
    assert "{posts_json}" in user
