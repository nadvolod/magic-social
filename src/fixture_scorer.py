"""Score fixture posts (known winners and losers) to validate scorer calibration.

Used by `python -m src.agent score-fixtures` to verify that:
  - The 5 verified `good-social-posts/` average rubric ≥ 75/100
  - Bottom-90% screenshots from screenshot_learning.json average ≤ 50/100

If the scorer drifts (e.g. averages winners at 60), the calibration anchors in
src/agents/quality_reviewer.py need sharpening.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .post_generator import score_linkedin_post_quality

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
GOOD_POSTS_DIR = REPO_ROOT / "good-social-posts"
SCREENSHOT_STATE_PATH = REPO_ROOT / "screenshot_learning.json"


@dataclass
class FixtureScore:
    label: str
    name: str
    rubric_total: float


def _extract_good_post_body(content: str) -> str:
    in_section = False
    lines: list[str] = []
    for line in content.splitlines():
        if "## Final LinkedIn Post" in line:
            in_section = True
            continue
        if in_section:
            if line.startswith("## ") or line.startswith("---"):
                if lines:
                    break
            lines.append(line)
    return "\n".join(lines).strip()


def load_good_posts() -> list[tuple[str, str]]:
    """Return [(filename, post_body)] for all verified high-performers."""
    if not GOOD_POSTS_DIR.exists():
        return []
    result: list[tuple[str, str]] = []
    for md in sorted(GOOD_POSTS_DIR.glob("*.md")):
        try:
            body = _extract_good_post_body(md.read_text(encoding="utf-8"))
        except OSError:
            continue
        if body:
            result.append((md.name, body))
    return result


def load_bottom_90_samples(limit: int = 5) -> list[tuple[str, str]]:
    """Return [(label, text)] for up to `limit` bottom-90% screenshot samples.

    Reads screenshot_learning.json — only items classified as bottom-tier with
    extracted text. Returns empty list if no such data exists yet.
    """
    if not SCREENSHOT_STATE_PATH.exists():
        return []
    try:
        data = json.loads(SCREENSHOT_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    samples: list[tuple[str, str]] = []
    # screenshot_learning.json schema may store entries under various keys.
    # We probe the most common shapes without over-fitting.
    candidates = []
    if isinstance(data, dict):
        candidates.extend(data.get("screenshots", []) or [])
        candidates.extend(data.get("entries", []) or [])
        classifications = data.get("classifications") or {}
        if isinstance(classifications, dict):
            for label, items in classifications.items():
                if "bottom" in label.lower() and isinstance(items, list):
                    candidates.extend(items)

    for entry in candidates:
        if not isinstance(entry, dict):
            continue
        classification = (entry.get("classification") or entry.get("tier") or "").lower()
        if classification and "bottom" not in classification:
            continue
        text = entry.get("post_text") or entry.get("extracted_text") or entry.get("text")
        if not text:
            continue
        name = entry.get("filename") or entry.get("id") or f"bottom_{len(samples)+1}"
        samples.append((name, text))
        if len(samples) >= limit:
            break

    return samples


def score_fixtures() -> dict:
    """Score known winners and losers, return a structured report."""
    winners = load_good_posts()
    losers = load_bottom_90_samples()

    winner_scores = [
        FixtureScore("winner", name, score_linkedin_post_quality(body).total)
        for name, body in winners
    ]
    loser_scores = [
        FixtureScore("loser", name, score_linkedin_post_quality(text).total)
        for name, text in losers
    ]

    def _avg(items: list[FixtureScore]) -> Optional[float]:
        if not items:
            return None
        return round(sum(i.rubric_total for i in items) / len(items), 2)

    winner_avg = _avg(winner_scores)
    loser_avg = _avg(loser_scores)

    return {
        "winners": [s.__dict__ for s in winner_scores],
        "losers": [s.__dict__ for s in loser_scores],
        "winner_avg": winner_avg,
        "loser_avg": loser_avg,
        "winner_gate_pass": winner_avg is not None and winner_avg >= 75.0,
        "loser_gate_pass": loser_avg is None or loser_avg <= 50.0,
    }


def format_report(report: dict) -> str:
    lines = ["# Fixture Scorer Report", ""]
    lines.append("## Verified winners (good-social-posts/)")
    if not report["winners"]:
        lines.append("_No winners loaded._")
    for entry in report["winners"]:
        lines.append(f"- `{entry['name']}`: {entry['rubric_total']:.1f}/100")
    avg = report["winner_avg"]
    lines.append(f"\n**Winner average:** {avg if avg is not None else 'N/A'}/100 "
                 f"(gate: ≥ 75 → {'PASS' if report['winner_gate_pass'] else 'FAIL'})\n")

    lines.append("## Bottom-90% samples (screenshot_learning.json)")
    if not report["losers"]:
        lines.append("_No bottom-90% samples available — this gate is skipped._")
    for entry in report["losers"]:
        lines.append(f"- `{entry['name']}`: {entry['rubric_total']:.1f}/100")
    avg = report["loser_avg"]
    lines.append(f"\n**Loser average:** {avg if avg is not None else 'N/A'}/100 "
                 f"(gate: ≤ 50 → {'PASS' if report['loser_gate_pass'] else 'FAIL'})")
    return "\n".join(lines)
