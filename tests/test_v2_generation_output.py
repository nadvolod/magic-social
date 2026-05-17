"""Tier C acceptance tests — generation output checks.

These run against the latest drafts folder for Issue #422. They verify
the v2 generation actually produced drafts that:
  C1 — reference named entities from the Raw Idea
  C2 — do not force code on an EXPERIENCE topic
  C3 — do not copy reference posts verbatim
  C4 — include a retrospective comment with competitive framing
  C5 — have a per-Issue retrospective snapshot file

The "Issue #422" slug is `temporal_replay_conference_review`. If no
matching drafts folder exists yet (i.e. drafts haven't been
re-generated under the v2 model), the tests are skipped with a clear
reason.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
DRAFTS_ROOT = REPO_ROOT / "drafts"
ISSUE_422_SLUG = "temporal_replay_conference_review"

# Named entities from the Raw Idea body of Issue #422.
ISSUE_422_NAMED_ENTITIES = [
    "Replay",
    "Mason",
    "Melissa",
    "Nexus",
    "Tiki",
    "cotton candy",
    "Netflix",
    "OpenAI",
]


def _latest_drafts_dir_for_422() -> Path | None:
    if not DRAFTS_ROOT.exists():
        return None
    candidates = [p for p in DRAFTS_ROOT.iterdir() if p.is_dir() and p.name.endswith(ISSUE_422_SLUG)]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.name)


@pytest.fixture(scope="module")
def drafts_dir() -> Path:
    d = _latest_drafts_dir_for_422()
    if d is None:
        pytest.skip(
            "No drafts directory for Issue #422 — re-trigger generation first. "
            f"Looking under {DRAFTS_ROOT}/*_{ISSUE_422_SLUG}/"
        )
    return d


@pytest.fixture(scope="module")
def variant_paths(drafts_dir: Path) -> list[Path]:
    return sorted(drafts_dir.glob("variant_*.md"))


def test_c1_raw_idea_fidelity(variant_paths: list[Path]):
    """C1 — every variant cites at least 2 named entities from the Raw Idea."""
    assert variant_paths, "expected at least one variant_*.md"
    for path in variant_paths:
        text = path.read_text(encoding="utf-8")
        hits = [e for e in ISSUE_422_NAMED_ENTITIES if e.lower() in text.lower()]
        assert len(hits) >= 2, (
            f"{path.name} mentions only {hits} from the Raw Idea — "
            f"v2 requires at least 2 named entities (had: {ISSUE_422_NAMED_ENTITIES})"
        )


_INDENTED_CODE_BLOCK = re.compile(r"(?m)^\s{4}[^\s].+(?:\n\s{4}.+)*")


def test_c2_no_forced_code_on_experience_topic(variant_paths: list[Path]):
    """C2 — no variant contains a 4-space-indented code block.

    Issue #422 is an EXPERIENCE topic. v2 must not invent code for it.
    Skip the body of any variant_*.md file's metadata section (the file
    starts with "# variant_N — angle" and metadata bullets); only check
    the post body, which is everything after the first '---' separator.
    """
    for path in variant_paths:
        full = path.read_text(encoding="utf-8")
        # Variant files structure: "# variant_N — angle\n\n**...**\n\n---\n\n<post body>"
        parts = full.split("\n---\n", 1)
        body = parts[1] if len(parts) == 2 else full
        m = _INDENTED_CODE_BLOCK.search(body)
        assert m is None, (
            f"{path.name} contains a 4-space-indented code block for an EXPERIENCE topic:\n"
            f"{m.group(0)[:200]}…"
        )


def _load_reference_excerpts() -> list[str]:
    state_path = REPO_ROOT / "screenshot_learning.json"
    if not state_path.exists():
        return []
    state = json.loads(state_path.read_text(encoding="utf-8"))
    excerpts = []
    for ex in state.get("examples", []):
        for key in ("hook_excerpt", "summary"):
            value = (ex.get(key) or "").strip()
            if value:
                excerpts.append(value)
    return excerpts


def _normalize_words(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def _has_long_shared_substring(needle: str, haystack: str, *, min_words: int = 12) -> bool:
    needle_words = _normalize_words(needle)
    haystack_words = _normalize_words(haystack)
    if len(needle_words) < min_words or len(haystack_words) < min_words:
        return False
    haystack_str = " " + " ".join(haystack_words) + " "
    for i in range(0, len(needle_words) - min_words + 1):
        window = " " + " ".join(needle_words[i : i + min_words]) + " "
        if window in haystack_str:
            return True
    return False


def test_c3_no_reference_verbatim(variant_paths: list[Path]):
    """C3 — no variant shares a >12-word substring with any reference excerpt."""
    refs = _load_reference_excerpts()
    if not refs:
        pytest.skip("No reference excerpts available in screenshot_learning.json")

    for path in variant_paths:
        text = path.read_text(encoding="utf-8")
        for ref in refs:
            assert not _has_long_shared_substring(text, ref, min_words=12), (
                f"{path.name} shares a >12-word substring with a reference post — "
                "imitation, not exceedance.\n"
                f"Reference excerpt: {ref[:200]}"
            )


def test_c5_per_issue_snapshot_exists(drafts_dir: Path):
    """C5 — drafts/<latest>/retrospective_snapshot.md exists and is non-empty."""
    snap = drafts_dir / "retrospective_snapshot.md"
    assert snap.exists(), f"missing per-Issue retrospective snapshot at {snap}"
    text = snap.read_text(encoding="utf-8")
    assert text.strip(), "snapshot must not be empty"


# C4 is a check on the live Issue comment; can't be verified from the file system.
# It's covered indirectly by:
#   - tests/test_v2_baseline.py::test_retrospective_injection_uses_competitive_prefix (A7)
#   - tests/test_retrospective.py::test_build_issue_comment_extracts_snapshot_do_avoid
# Tier D's judge_report.md will further validate the comment shape after re-triggering.
