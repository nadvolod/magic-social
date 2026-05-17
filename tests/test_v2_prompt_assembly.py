"""Tier B acceptance tests — prompt assembly checks.

Builds the full v2 system prompt without an LLM call and inspects it.
Catches contamination introduced by future changes to the template,
the loaders, or the retrospective injection.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src import idea_generator


def _sample_payload() -> dict:
    return {
        "number": 1,
        "title": "[Idea] Sample",
        "body": (
            "### Raw idea\n\nA short idea about Temporal and AI agents.\n\n"
            "### Audience\n\nSenior engineers.\n"
        ),
        "html_url": "",
        "labels": [{"name": "content_idea"}],
    }


def test_v2_system_prompt_contains_competition_framing():
    """B1 — assembled system prompt tells the model references are competition."""
    idea = idea_generator.parse_issue_payload(_sample_payload())
    system, _user = idea_generator.build_prompts(idea, variant_count=3)
    assert "competition to beat" in system.lower()
    assert "Raw Idea is your subject" in system


def test_v2_system_prompt_omits_v1_external_lessons():
    """B2 — the v1 'EXTERNAL LESSONS:' header must not appear in the v2 prompt."""
    idea = idea_generator.parse_issue_payload(_sample_payload())
    system, _user = idea_generator.build_prompts(idea, variant_count=3)
    assert "EXTERNAL LESSONS:" not in system


def test_v2_system_prompt_contains_competitive_landscape_when_retro_present(tmp_path, monkeypatch):
    """B3 — when playbook/retrospective.md exists, the COMPETITIVE LANDSCAPE prefix flows in."""
    fake_retro = tmp_path / "retrospective.md"
    fake_retro.write_text("# Test retrospective\n\n## Do this\n- Be specific\n", encoding="utf-8")
    monkeypatch.setattr(idea_generator, "RETROSPECTIVE_PATH", fake_retro)

    idea = idea_generator.parse_issue_payload(_sample_payload())
    system, _user = idea_generator.build_prompts(idea, variant_count=3)
    assert "COMPETITIVE LANDSCAPE" in system
    assert "Test retrospective" in system


def test_v2_system_prompt_falls_back_gracefully_without_retro(tmp_path, monkeypatch):
    """B4 — no retrospective → prompt still assembles using the placeholder text."""
    monkeypatch.setattr(idea_generator, "RETROSPECTIVE_PATH", tmp_path / "absent.md")
    idea = idea_generator.parse_issue_payload(_sample_payload())
    system, _user = idea_generator.build_prompts(idea, variant_count=3)
    assert "no retrospective yet" in system
    # Even without the retro, the competition framing from generate_post.md is still present
    assert "competition to beat" in system.lower()
