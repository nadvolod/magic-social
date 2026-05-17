"""Tests for src/idea_generator.py — issue parsing, draft writing, summary."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src import idea_generator


SAMPLE_ISSUE_BODY = """
### Raw idea

Most engineers retry API calls with exponential backoff. They miss that retries without idempotency are a liability, not a safety net.

### Audience

Engineers running AI agents in production

### Primary goal

Authority / credibility

### Preferred angle (optional)

Contrarian technical authority

### References, notes, links (optional)

See reference_posts/replay_2026/ for pattern context.

### Supporting notes

_No response_
"""


def _make_payload(body: str = SAMPLE_ISSUE_BODY) -> dict:
    return {
        "number": 42,
        "title": "[Idea] Retries without idempotency",
        "body": body,
        "html_url": "https://github.com/example/magic-social/issues/42",
        "labels": [{"name": "content_idea"}, {"name": "needs_generation"}],
    }


# ---------------------------------------------------------------------------
# Issue parsing
# ---------------------------------------------------------------------------


def test_parse_issue_extracts_all_template_fields():
    idea = idea_generator.parse_issue_payload(_make_payload())

    assert idea.number == 42
    assert idea.title == "[Idea] Retries without idempotency"
    assert "exponential backoff" in idea.raw_idea
    assert idea.audience == "Engineers running AI agents in production"
    assert idea.goal == "Authority / credibility"
    assert idea.angle == "Contrarian technical authority"
    assert "replay_2026" in idea.references
    assert idea.supporting_notes == ""  # _No response_ filtered to empty
    assert "content_idea" in idea.labels


def test_parse_issue_handles_free_form_body():
    """A messy body with no template structure should fall back to using the whole body as raw_idea."""
    idea = idea_generator.parse_issue_payload(
        {
            "number": 7,
            "title": "[Idea] Free form",
            "body": "Just a quick thought about durable execution and AI agents.",
            "html_url": "",
            "labels": [],
        }
    )
    assert idea.raw_idea == "Just a quick thought about durable execution and AI agents."
    assert idea.audience == ""
    assert idea.goal == ""


def test_parse_issue_handles_missing_optional_sections():
    body = "### Raw idea\n\nCore idea text here.\n"
    idea = idea_generator.parse_issue_payload(
        {"number": 1, "title": "[Idea] Sparse", "body": body, "html_url": "", "labels": []}
    )
    assert idea.raw_idea == "Core idea text here."
    assert idea.audience == ""


def test_parse_issue_extracts_image_urls_from_body():
    body = (
        "### Raw idea\n\nGreat conference experience.\n\n"
        "### References, notes, links (optional)\n\n"
        '<img width="500" alt="Image" src="https://example.com/a.png" />\n'
        '<img src="https://example.com/b.jpg" alt="b">\n\n'
        "### Supporting notes\n\n"
        "Photo: ![scene](https://example.com/c.jpeg)\n"
        '<img src="https://example.com/a.png" alt="dup">\n'  # duplicate must be ignored
    )
    idea = idea_generator.parse_issue_payload(
        {"number": 9, "title": "x", "body": body, "html_url": "", "labels": []}
    )
    assert idea.image_urls == [
        "https://example.com/a.png",
        "https://example.com/b.jpg",
        "https://example.com/c.jpeg",
    ]


def test_parse_issue_caps_image_urls():
    imgs = "\n".join(f'<img src="https://x/{i}.png"/>' for i in range(30))
    body = f"### Raw idea\n\nLots of pics.\n\n### Supporting notes\n\n{imgs}\n"
    idea = idea_generator.parse_issue_payload(
        {"number": 9, "title": "x", "body": body, "html_url": "", "labels": []}
    )
    assert len(idea.image_urls) == idea_generator.MAX_IMAGES_PER_ISSUE


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------


def test_build_prompts_substitutes_all_placeholders():
    idea = idea_generator.parse_issue_payload(_make_payload())
    system, user = idea_generator.build_prompts(idea, variant_count=5)

    # System prompt should include voice content
    assert "ICP" in system or "ideal" in system.lower() or "audience" in system.lower()
    # User prompt should contain idea details
    assert "exponential backoff" in user
    assert "Engineers running AI agents in production" in user
    assert "5" in user  # variant_count was substituted


def test_build_prompts_uses_defaults_when_fields_missing():
    minimal = idea_generator.parse_issue_payload(
        {"number": 99, "title": "[Idea] Minimal", "body": "### Raw idea\n\nJust this.\n",
         "html_url": "", "labels": []}
    )
    system, user = idea_generator.build_prompts(minimal)
    # Default ICP must be injected
    assert "Default ICP" in user or "Temporal" in user


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------


def test_extract_json_handles_plain_object():
    assert idea_generator._extract_json('{"variant_1": {"post": "hello"}}') == {
        "variant_1": {"post": "hello"}
    }


def test_extract_json_handles_fenced_code_block():
    text = '```json\n{"variant_1": {"post": "hi"}}\n```'
    assert idea_generator._extract_json(text) == {"variant_1": {"post": "hi"}}


def test_extract_json_handles_surrounding_text():
    text = 'Sure! Here is the JSON: {"variant_1": {"post": "x"}} Done.'
    assert idea_generator._extract_json(text) == {"variant_1": {"post": "x"}}


# ---------------------------------------------------------------------------
# Slug / draft dir
# ---------------------------------------------------------------------------


def test_slugify_strips_idea_prefix_and_punctuation():
    assert idea_generator._slugify("[Idea] Retries without idempotency!") == "retries_without_idempotency"


def test_draft_dir_includes_date_and_slug(tmp_path, monkeypatch):
    monkeypatch.setattr(idea_generator, "DRAFTS_DIR", tmp_path)
    idea = idea_generator.parse_issue_payload(_make_payload())
    fixed = datetime(2026, 5, 15, tzinfo=timezone.utc)
    path = idea_generator.draft_dir_for(idea, now=fixed)
    assert path.name == "2026_05_15_retries_without_idempotency"
    assert path.parent == tmp_path


# ---------------------------------------------------------------------------
# Write drafts
# ---------------------------------------------------------------------------


SAMPLE_VARIANTS = {
    "variant_1": {
        "angle": "contrarian",
        "hook": "Most engineers retry API calls with exponential backoff.",
        "body": "They miss the real problem.",
        "post": (
            "Most engineers retry failed API calls with exponential backoff.\n\n"
            "They miss the real problem.\n\n"
            "I spent 3 days debugging a payment pipeline that was 'working' — "
            "retries firing, requests succeeding on retry. But we charged customers twice.\n\n"
            "The fix was 4 lines:\n\n"
            "    activity_options = ActivityOptions(\n"
            "        retry_policy=RetryPolicy(max_attempts=3),\n"
            "        idempotency_key=f'payment-{order_id}-{attempt}',\n"
            "    )\n\n"
            "Duplicate charges dropped from ~2% to 0%.\n\n"
            "The lesson: retries without idempotency are a liability, not a safety net.\n\n"
            "What's the most expensive retry bug you've shipped?"
        ),
        "intended_audience": "AI engineers using Temporal",
        "why_it_may_perform": "Contrarian hook + real code + measurable result",
        "risks": "Audience may already know this",
    },
    "variant_5": {
        "angle": "short engagement",
        "post": "Retries without idempotency are a liability. Change my mind.\n\nWhat have you shipped that bit you?",
    },
}


def test_write_drafts_produces_expected_files(tmp_path):
    idea = idea_generator.parse_issue_payload(_make_payload())
    paths = idea_generator.write_drafts(idea, SAMPLE_VARIANTS, tmp_path)

    assert {p.name for p in paths} == {"variant_1.md", "variant_5.md"}
    assert (tmp_path / "scores.json").exists()
    assert (tmp_path / "metadata.json").exists()
    assert (tmp_path / "source_issue.md").exists()

    scores = json.loads((tmp_path / "scores.json").read_text())
    assert "variant_1" in scores
    assert "rubric_total" in scores["variant_1"]
    assert scores["variant_1"]["angle"] == "contrarian"

    metadata = json.loads((tmp_path / "metadata.json").read_text())
    assert metadata["issue_number"] == 42
    assert metadata["variant_count"] == 2


def test_pick_top_variant_returns_highest_score():
    scores = {
        "variant_1": {"rubric_total": 72.0, "angle": "contrarian"},
        "variant_2": {"rubric_total": 88.0, "angle": "story"},
        "variant_3": {"rubric_total": 55.0, "angle": "tactical"},
    }
    assert idea_generator.pick_top_variant(scores) == "variant_2"


def test_pick_top_variant_handles_empty():
    assert idea_generator.pick_top_variant({}) is None


def test_build_summary_comment_includes_top_recommendation(tmp_path):
    idea = idea_generator.parse_issue_payload(_make_payload())
    paths = idea_generator.write_drafts(idea, SAMPLE_VARIANTS, tmp_path)
    scores = json.loads((tmp_path / "scores.json").read_text())
    summary = idea_generator.build_summary_comment(idea, tmp_path, scores, paths)

    assert "Top by rubric" in summary
    assert "variant_1" in summary or "variant_5" in summary
    assert "Ranked rubric" in summary


def test_build_variant_comment_renders_post_and_metadata():
    variant = SAMPLE_VARIANTS["variant_1"]
    score = {"rubric_total": 87.3, "angle": variant["angle"]}
    body = idea_generator.build_variant_comment("variant_1", variant, score)

    assert "Variant 1" in body
    assert variant["angle"] in body
    assert "87.3/100" in body
    assert "retries without idempotency" in body.lower()
    assert variant["intended_audience"] in body
    assert variant["risks"] in body
    assert "React" in body  # voting affordance present
