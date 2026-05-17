"""Tier A acceptance tests — static & configuration checks.

These verify the v2 baseline state of the repo: v1 artifacts archived,
v2-schema files in place, prompt templates updated, v1 loaders severed.

All tests are deterministic — no LLM calls. Runs in <1s.
"""

from __future__ import annotations

import inspect
import json
import re
from pathlib import Path

from src import idea_generator


REPO_ROOT = Path(__file__).resolve().parent.parent
ARCHIVE = REPO_ROOT / "archive" / "v1"
PLAYBOOK = REPO_ROOT / "playbook"
PROMPTS = REPO_ROOT / "prompts"


V1_FILENAMES = [
    "LESSONS_LEARNED.md",
    "prompt_patches.json",
    "linkedin_metrics.json",
    "learning_state.json",
    "voice.md",
]


def test_v1_artifacts_archived():
    """A1 — archive/v1/ contains every v1 artifact; root no longer holds them.

    Note: learning_state.json is intentionally re-created at root with a v2 schema
    (A2 verifies its shape). voice.md is re-created at playbook/voice.md from
    data (A3 verifies that). Both filenames still exist in fresh form, but the
    v1 originals must live in archive/v1/.
    """
    for name in V1_FILENAMES:
        assert (ARCHIVE / name).exists(), f"missing archive/v1/{name}"

    # Files that should be GONE from the repo root entirely
    for name in ("LESSONS_LEARNED.md", "prompt_patches.json", "linkedin_metrics.json"):
        assert not (REPO_ROOT / name).exists(), f"{name} should have been moved to archive/v1/"


def test_learning_state_is_v2_schema():
    """A2 — root learning_state.json carries v2 schema, none of the v1 fields."""
    state_path = REPO_ROOT / "learning_state.json"
    assert state_path.exists(), "root learning_state.json must exist as v2 reset"
    state = json.loads(state_path.read_text(encoding="utf-8"))

    assert state.get("version") == 2, "version must be 2"
    assert state.get("best_performing_posts") == []

    # v1-only keys must be absent
    for v1_key in (
        "applied_feedback_fingerprints",
        "not_published_reasons",
        "archived_not_published_reasons",
        "total_feedback_received",
        "explicit_ratings_received",
    ):
        assert v1_key not in state, f"v1 field '{v1_key}' must not be present in v2 schema"


def test_voice_md_is_data_derived():
    """A3 — playbook/voice.md is non-empty and carries a provenance footer."""
    voice_path = PLAYBOOK / "voice.md"
    assert voice_path.exists(), "playbook/voice.md must exist (data-derived)"
    text = voice_path.read_text(encoding="utf-8")
    assert text.strip(), "voice.md must not be empty"
    assert re.search(
        r"_Synthesized from \d+ top reference posts?, \d+ curated examples? on \d{4}-\d{2}-\d{2}\._",
        text,
    ), "voice.md must end with provenance footer"


def test_generate_post_template_has_competition_clause():
    """A4 — generate_post.md tells the model to treat references as competition."""
    text = (PROMPTS / "generate_post.md").read_text(encoding="utf-8")
    assert "competition to beat" in text.lower()
    assert "Raw Idea is your subject" in text


def test_retrospective_template_has_exceed_section():
    """A5 — retrospective.md uses the new "How to exceed this cohort" framing."""
    text = (PROMPTS / "retrospective.md").read_text(encoding="utf-8")
    assert "## How to exceed this cohort" in text
    assert "## Shaping the next draft" not in text, "old prescriptive section must be gone"


def test_rejection_block_does_not_load_v1_lessons():
    """A6 — _rejection_block source no longer calls the v1 external lessons loader."""
    src = inspect.getsource(idea_generator._rejection_block)
    assert "_load_external_social_lessons" not in src
    # Also confirm the import line is gone
    mod_src = Path(idea_generator.__file__).read_text(encoding="utf-8")
    # The function name should NOT appear as an import (it may appear in a comment)
    import_pattern = re.compile(r"^\s*_load_external_social_lessons,?\s*$", re.MULTILINE)
    assert not import_pattern.search(mod_src), \
        "_load_external_social_lessons import line must be gone"


def test_retrospective_injection_uses_competitive_prefix(tmp_path, monkeypatch):
    """A7 — _load_retrospective_block injects with the COMPETITIVE LANDSCAPE prefix."""
    fake = tmp_path / "retrospective.md"
    fake.write_text("# Some content\n", encoding="utf-8")
    monkeypatch.setattr(idea_generator, "RETROSPECTIVE_PATH", fake)

    block = idea_generator._load_retrospective_block()
    assert block.startswith("COMPETITIVE LANDSCAPE")
    assert "Raw Idea is the subject" in block


def test_archive_readme_documents_cutover():
    """A8 — archive/v1/README.md records the cutover date and Issue link."""
    readme = (ARCHIVE / "README.md").read_text(encoding="utf-8")
    assert "422" in readme
    assert "2026-05-17" in readme
