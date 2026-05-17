"""Tests for src/retrospective.py + idea_generator wiring."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src import idea_generator, retrospective
from src.screenshot_learning import ScreenshotExample, ScreenshotLearningState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_learning_state(tmp_path: Path, posts: list[dict]) -> Path:
    state = {
        "best_performing_posts": posts,
        "total_posts_analyzed": len(posts),
        "version": 1,
    }
    target = tmp_path / "learning_state.json"
    target.write_text(json.dumps(state), encoding="utf-8")
    return target


def _make_published_post(
    *,
    issue_number: int,
    saves: int = 0,
    reposts: int = 0,
    comments: int = 0,
    reactions: int = 0,
    days_old: int = 1,
    text: str = "Post body excerpt.",
) -> dict:
    recorded = (datetime.now(timezone.utc) - timedelta(days=days_old)).isoformat()
    return {
        "github_issue_number": issue_number,
        "analytics": {
            "saves": saves,
            "reposts": reposts,
            "comments": comments,
            "reactions": reactions,
            "impressions": 1000,
        },
        "post_text": text,
        "recorded_at": recorded,
    }


def _make_screenshot_example(
    *,
    issue_number: int,
    classification: str,
    score: float,
    summary: str = "",
) -> ScreenshotExample:
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
        summary=summary or f"Example {issue_number}",
        hook_excerpt=f"Hook excerpt {issue_number}",
    )


# ---------------------------------------------------------------------------
# Cohort gathering
# ---------------------------------------------------------------------------


def test_gather_published_cohort_respects_lookback(tmp_path):
    posts = [
        _make_published_post(issue_number=1, saves=10, days_old=5),
        _make_published_post(issue_number=2, saves=1, days_old=90),  # outside window
        _make_published_post(issue_number=3, saves=5, days_old=20),
    ]
    state_path = _write_learning_state(tmp_path, posts)

    cohort = retrospective.gather_published_cohort(
        lookback_days=60, state_path=state_path, top_n=2, bottom_n=2
    )

    assert cohort.total == 2  # post #2 filtered out
    identifiers = {r.identifier for r in cohort.top}
    assert identifiers <= {"#1", "#3"}
    # Top sorted by score: #1 (10*4=40) > #3 (5*4=20)
    assert cohort.top[0].identifier == "#1"


def test_gather_published_cohort_handles_missing_file(tmp_path):
    cohort = retrospective.gather_published_cohort(
        lookback_days=60, state_path=tmp_path / "missing.json"
    )
    assert cohort.is_empty()
    assert "no learning_state" in cohort.summary or "no published-post" in cohort.summary


def test_gather_published_cohort_handles_empty_list(tmp_path):
    state_path = _write_learning_state(tmp_path, [])
    cohort = retrospective.gather_published_cohort(lookback_days=60, state_path=state_path)
    assert cohort.is_empty()


def test_gather_reference_cohort_separates_top_bottom(tmp_path):
    state = ScreenshotLearningState(
        examples=[
            _make_screenshot_example(issue_number=100, classification="top_10_percent", score=400),
            _make_screenshot_example(issue_number=101, classification="top_10_percent", score=200),
            _make_screenshot_example(issue_number=102, classification="bottom_90_percent", score=5),
            _make_screenshot_example(issue_number=103, classification="bottom_90_percent", score=10),
        ]
    )
    state_path = str(tmp_path / "screenshot_learning.json")
    state.save(state_path)

    cohort = retrospective.gather_reference_cohort(state_path=state_path, top_n=2, bottom_n=2)

    assert cohort.total == 4
    assert {r.identifier for r in cohort.top} == {"ref #100", "ref #101"}
    assert {r.identifier for r in cohort.bottom} == {"ref #102", "ref #103"}
    # Top sorted high-to-low
    assert cohort.top[0].score >= cohort.top[1].score


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------


def test_build_retrospective_prompts_substitutes_all_placeholders(tmp_path):
    state_path = _write_learning_state(
        tmp_path,
        [_make_published_post(issue_number=1, saves=10, days_old=5)],
    )
    published = retrospective.gather_published_cohort(lookback_days=60, state_path=state_path)
    reference = retrospective.CohortBundle(
        source_name="external reference posts",
        top=[],
        bottom=[],
        total=0,
        summary="(none)",
    )
    system, user = retrospective.build_retrospective_prompts(
        published, reference, lookback_days=60
    )

    assert "ICP" in system or "strategist" in system.lower()
    assert "last 60 days" in user
    assert "#1" in user  # the published post identifier made it in


# ---------------------------------------------------------------------------
# Generation + write
# ---------------------------------------------------------------------------


class _StubClient:
    def __init__(self, response_text: str):
        self.response_text = response_text
        self.calls = []
        # Mimic openai client shape: client.chat.completions.create(...)
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


def test_generate_retrospective_with_empty_cohorts_skips_llm(tmp_path):
    empty_pub = retrospective.CohortBundle("own published posts", [], [], 0, "(empty)")
    empty_ref = retrospective.CohortBundle("external reference posts", [], [], 0, "(empty)")

    # No client passed → must NOT raise, must NOT call any LLM.
    report = retrospective.generate_retrospective(empty_pub, empty_ref, lookback_days=60)
    assert "no cohort data yet" in report.markdown.lower()


def test_generate_retrospective_calls_client_when_data_exists(tmp_path):
    stub_md = (
        "# LinkedIn Retrospective — last 60 days\n\n"
        "## Snapshot\n\nShort snapshot text.\n\n"
        "## Do this\n- Open with a contrarian hook [ref #100]\n\n"
        "## Avoid this\n- Avoid generic openings [ref #102]\n"
    )
    client = _StubClient(stub_md)
    ref_cohort = retrospective.CohortBundle(
        source_name="external reference posts",
        top=[
            retrospective.PostRecord(
                source="reference",
                identifier="ref #100",
                score=400,
                metrics={"reactions": 400},
                text_excerpt="hook",
                signals={"hook_style": "story"},
            )
        ],
        bottom=[],
        total=1,
        summary="1 example",
    )
    empty_pub = retrospective.CohortBundle("own published posts", [], [], 0, "(empty)")

    report = retrospective.generate_retrospective(
        empty_pub, ref_cohort, lookback_days=60, client=client
    )
    assert "Do this" in report.markdown
    assert len(client.calls) == 1


def test_write_retrospective_writes_target_path(tmp_path):
    report = retrospective.RetrospectiveReport(
        markdown="# Test retrospective\n\nbody\n",
        published=retrospective.CohortBundle("own", [], [], 0, ""),
        reference=retrospective.CohortBundle("ref", [], [], 0, ""),
    )
    target = tmp_path / "playbook" / "retrospective.md"
    written = retrospective.write_retrospective(report, target_path=target)
    assert written == target
    assert target.read_text(encoding="utf-8").startswith("# Test retrospective")


# ---------------------------------------------------------------------------
# Snapshot per-Issue
# ---------------------------------------------------------------------------


def test_snapshot_for_issue_copies_current_retrospective(tmp_path):
    source = tmp_path / "retrospective.md"
    source.write_text("# Source retrospective\n", encoding="utf-8")
    target_dir = tmp_path / "drafts" / "2026_05_17_slug"

    out = retrospective.snapshot_for_issue(target_dir, retrospective_path=source)
    assert out is not None
    assert out == target_dir / "retrospective_snapshot.md"
    assert out.read_text(encoding="utf-8") == "# Source retrospective\n"


def test_snapshot_for_issue_returns_none_when_missing(tmp_path):
    out = retrospective.snapshot_for_issue(
        tmp_path / "drafts" / "x", retrospective_path=tmp_path / "nope.md"
    )
    assert out is None


# ---------------------------------------------------------------------------
# Issue comment formatting
# ---------------------------------------------------------------------------


def test_build_issue_comment_extracts_snapshot_do_avoid():
    md = (
        "# Retrospective\n\n"
        "## Snapshot\n\nA tight snapshot.\n\n"
        "## Top performers\n- one\n\n"
        "## Do this\n- Rule A [ref #1]\n- Rule B [own #2]\n\n"
        "## Avoid this\n- Anti-pattern [ref #3]\n"
    )
    comment = retrospective.build_issue_comment(md)
    assert "Retrospective driving these drafts" in comment
    assert "Snapshot" in comment
    assert "Rule A" in comment
    assert "Anti-pattern" in comment
    # Top performers section is intentionally NOT pulled in (too long for a comment)
    assert "Top performers" not in comment


def test_build_issue_comment_tolerates_missing_sections():
    md = "# Retrospective\n\nbody but no expected sections\n"
    comment = retrospective.build_issue_comment(md)
    assert "Retrospective driving these drafts" in comment


# ---------------------------------------------------------------------------
# idea_generator wiring
# ---------------------------------------------------------------------------


def test_load_retrospective_block_empty_when_missing(monkeypatch, tmp_path):
    """If playbook/retrospective.md is absent the block falls back to empty."""
    monkeypatch.setattr(idea_generator, "RETROSPECTIVE_PATH", tmp_path / "nope.md")
    assert idea_generator._load_retrospective_block() == ""


def test_load_retrospective_block_returns_text_when_present(monkeypatch, tmp_path):
    fake = tmp_path / "retrospective.md"
    fake.write_text("# Sample retrospective\n\n## Snapshot\n\nx\n", encoding="utf-8")
    monkeypatch.setattr(idea_generator, "RETROSPECTIVE_PATH", fake)
    block = idea_generator._load_retrospective_block()
    assert "COMPETITIVE LANDSCAPE" in block
    assert "Raw Idea" in block
    assert "Sample retrospective" in block


def test_build_prompts_includes_retrospective_placeholder(monkeypatch, tmp_path):
    """Sanity check that build_prompts still substitutes — even with a real retro file."""
    fake = tmp_path / "retrospective.md"
    fake.write_text(
        "# Retrospective\n\n## Do this\n- Test rule [ref #1]\n", encoding="utf-8"
    )
    monkeypatch.setattr(idea_generator, "RETROSPECTIVE_PATH", fake)

    payload = {
        "number": 1,
        "title": "[Idea] X",
        "body": "### Raw idea\n\nA thing about Temporal.\n",
        "html_url": "",
        "labels": [],
    }
    idea = idea_generator.parse_issue_payload(payload)
    system, _user = idea_generator.build_prompts(idea, variant_count=2)
    assert "Test rule" in system
    assert "{retrospective_block}" not in system  # placeholder substituted
