"""Bar Raiser meta-agent that enforces continuously rising quality standards.

Final agent in the post-generation pipeline.  Evaluates every post against
a dynamic quality bar that ratchets upward on successes and drifts down
slowly on rejections, forcing the system to improve over time.

All evaluation logic is purely deterministic -- no LLM calls.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dimension display labels
# ---------------------------------------------------------------------------
_DIMENSION_LABELS = {
    "specificity": "Specificity",
    "insight_depth": "Insight Depth",
    "hook_strength": "Hook Strength",
    "code_relevance": "Code Relevance",
    "shareability": "Shareability",
}

_DIMENSION_FLOOR = 10
_BAR_MIN = 50.0
_BAR_MAX = 90.0
_BAR_RAISE = 0.5
_BAR_LOWER = 0.25
_HISTORY_CAP = 50


# ---------------------------------------------------------------------------
# Persistent state
# ---------------------------------------------------------------------------

@dataclass
class BarRaiserState:
    """Persistent state for the Bar Raiser agent."""

    bar_level: float = 60.0  # Current quality bar (50-90 range)
    post_history: list = field(default_factory=list)  # Last 50 posts with all scores
    total_posts_evaluated: int = 0  # Lifetime counter (never reset, used for retrospective cadence)
    retrospective_count: int = 0
    last_retrospective_at: str = ""

    @classmethod
    def load(cls, path: str = "bar_raiser_state.json") -> BarRaiserState:
        """Load state from a JSON file, returning defaults if missing or corrupt."""
        filepath = Path(path)
        if not filepath.exists():
            logger.debug("Bar Raiser state not found at %s — using defaults.", path)
            return cls()
        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                logger.warning("Bar Raiser state is not a dict — using defaults.")
                return cls()
            raw_bar = float(data.get("bar_level", 60.0))
            return cls(
                bar_level=max(_BAR_MIN, min(_BAR_MAX, raw_bar)),
                post_history=list(data.get("post_history", [])),
                total_posts_evaluated=int(data.get("total_posts_evaluated", 0)),
                retrospective_count=int(data.get("retrospective_count", 0)),
                last_retrospective_at=str(data.get("last_retrospective_at", "")),
            )
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            logger.warning("Failed to load Bar Raiser state from %s: %s", path, exc)
            return cls()

    def save(self, path: str = "bar_raiser_state.json") -> None:
        """Persist current state to a JSON file."""
        data = {
            "bar_level": self.bar_level,
            "post_history": self.post_history,
            "total_posts_evaluated": self.total_posts_evaluated,
            "retrospective_count": self.retrospective_count,
            "last_retrospective_at": self.last_retrospective_at,
        }
        try:
            Path(path).write_text(
                json.dumps(data, indent=2, default=str) + "\n",
                encoding="utf-8",
            )
            logger.info("Saved Bar Raiser state to %s.", path)
        except OSError as exc:
            logger.error("Failed to save Bar Raiser state to %s: %s", path, exc)


# ---------------------------------------------------------------------------
# Core evaluation
# ---------------------------------------------------------------------------

def raise_the_bar(
    quality_review: dict,
    resonance: dict,
    prediction: dict,
    state: BarRaiserState,
) -> dict:
    """Evaluate a post against the current quality bar and update state.

    Parameters
    ----------
    quality_review:
        Output from the quality reviewer agent.  Expected keys:
        ``total_score``, ``dimensions`` (each with ``score``).
    resonance:
        Output from the resonance checker agent.  Expected key: ``icp_match``.
    prediction:
        Output from the predictor agent.  Expected keys:
        ``post_id``, ``publish_probability``, ``engagement_tier``.
    state:
        The current :class:`BarRaiserState` (mutated in-place).

    Returns
    -------
    Verdict dict with evaluation results, failures, and next-bar info.
    """
    previous_bar = state.bar_level

    # ------------------------------------------------------------------
    # 1. Extract scores from agent outputs
    # ------------------------------------------------------------------
    quality_score = int(quality_review.get("total_score", 0))

    dimensions: dict[str, int] = {}
    raw_dims = quality_review.get("dimensions", {})
    for dim_key in _DIMENSION_LABELS:
        entry = raw_dims.get(dim_key, {})
        if isinstance(entry, dict):
            dimensions[dim_key] = int(entry.get("score", 0))
        elif isinstance(entry, (int, float)):
            dimensions[dim_key] = int(entry)
        else:
            dimensions[dim_key] = 0

    icp_match = bool(resonance.get("icp_match", False))
    publish_probability = int(prediction.get("publish_probability", 0))
    engagement_tier = prediction.get("engagement_tier", "medium")
    post_id = prediction.get("post_id", "post-unknown")
    resonance_level = resonance.get("resonance", "medium")

    # ------------------------------------------------------------------
    # 2. Evaluate against bars
    # ------------------------------------------------------------------
    failures: list[dict] = []

    if quality_score < state.bar_level:
        failures.append({
            "metric": "Quality Score",
            "value": quality_score,
            "bar": state.bar_level,
            "status": "below_bar",
        })

    for dim_key, label in _DIMENSION_LABELS.items():
        score = dimensions.get(dim_key, 0)
        if score < _DIMENSION_FLOOR:
            failures.append({
                "metric": label,
                "value": score,
                "bar": _DIMENSION_FLOOR,
                "status": "below_floor",
            })

    if not icp_match:
        failures.append({
            "metric": "ICP Match",
            "value": False,
            "bar": True,
            "status": "not_matched",
        })

    if publish_probability < 50:
        failures.append({
            "metric": "Publish Probability",
            "value": publish_probability,
            "bar": 50,
            "status": "below_threshold",
        })

    # ------------------------------------------------------------------
    # 3. Determine verdict
    # ------------------------------------------------------------------
    failure_count = len(failures)
    if failure_count == 0:
        verdict = "pass"
    elif failure_count <= 2:
        verdict = "conditional"
    else:
        verdict = "reject"

    # ------------------------------------------------------------------
    # 4. Update bar
    # ------------------------------------------------------------------
    if verdict == "pass":
        state.bar_level = min(_BAR_MAX, state.bar_level + _BAR_RAISE)
    elif verdict == "reject":
        state.bar_level = max(_BAR_MIN, state.bar_level - _BAR_LOWER)
    # conditional: bar stays same

    # ------------------------------------------------------------------
    # 5. Build action message
    # ------------------------------------------------------------------
    if verdict == "pass":
        action = f"Bar raised to {state.bar_level:.4g} for next post."
    elif verdict == "conditional":
        failing_dims = [f["metric"] for f in failures]
        action = (
            f"Conditional pass. Address: {', '.join(failing_dims)}. "
            f"Bar remains at {state.bar_level:.4g}."
        )
    else:
        failing_dims = [f["metric"] for f in failures]
        action = (
            f"This post does not meet the quality bar. "
            f"Recommend regeneration with focus on: {', '.join(failing_dims)}."
        )

    # ------------------------------------------------------------------
    # 6. Add to post_history (keep last 50)
    # ------------------------------------------------------------------
    history_entry = {
        "post_id": post_id,
        "quality_score": quality_score,
        "dimensions": dimensions,
        "icp_match": icp_match,
        "resonance": resonance_level,
        "publish_probability": publish_probability,
        "engagement_tier": engagement_tier,
        "verdict": verdict,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    state.post_history.append(history_entry)
    state.total_posts_evaluated += 1
    if len(state.post_history) > _HISTORY_CAP:
        state.post_history = state.post_history[-_HISTORY_CAP:]

    logger.info(
        "Bar Raiser verdict: %s (score=%d, bar=%.1f, failures=%d)",
        verdict.upper(),
        quality_score,
        state.bar_level,
        failure_count,
    )

    return {
        "verdict": verdict,
        "bar_level": state.bar_level,
        "previous_bar": previous_bar,
        "quality_score": quality_score,
        "dimensions": dimensions,
        "icp_match": icp_match,
        "publish_probability": publish_probability,
        "failures": failures,
        "action": action,
    }


# ---------------------------------------------------------------------------
# Comment formatting
# ---------------------------------------------------------------------------

def format_bar_raiser_comment(result: dict) -> str:
    """Format a Bar Raiser verdict as a GitHub issue comment in markdown.

    Parameters
    ----------
    result:
        The dict returned by :func:`raise_the_bar`.
    """
    verdict = result.get("verdict", "unknown")
    bar_level = result.get("bar_level", 0)
    previous_bar = result.get("previous_bar", 0)
    quality_score = result.get("quality_score", 0)
    dimensions = result.get("dimensions", {})
    icp_match = result.get("icp_match", False)
    publish_probability = result.get("publish_probability", 0)
    failures = result.get("failures", [])
    action = result.get("action", "")

    # Build a set of failing metrics for quick lookup
    failing_metrics = {f["metric"] for f in failures}

    # Verdict header
    verdict_upper = verdict.upper()
    if verdict == "pass":
        verdict_emoji = "\u2705"
    elif verdict == "conditional":
        verdict_emoji = "\u26a0\ufe0f"
    else:
        verdict_emoji = "\u274c"

    bar_delta = bar_level - previous_bar
    if bar_delta > 0:
        bar_arrow = f"\u2191{bar_delta:.4g}"
    elif bar_delta < 0:
        bar_arrow = f"\u2193{abs(bar_delta):.4g}"
    else:
        bar_arrow = "\u2192 no change"

    lines = [
        "## Bar Raiser",
        "",
        f"**Verdict: {verdict_upper}** {verdict_emoji} | "
        f"**Bar: {previous_bar:.1f}/100** ({bar_arrow} from last)",
        "",
        "| Metric | This Post | Bar | Status |",
        "|--------|-----------|-----|--------|",
    ]

    # Quality Score row
    qs_status = "\u2705 Above" if "Quality Score" not in failing_metrics else "\u274c Below"
    lines.append(
        f"| Quality Score | {quality_score} | {previous_bar:.1f} | {qs_status} |"
    )

    # Dimension rows
    for dim_key, label in _DIMENSION_LABELS.items():
        score = dimensions.get(dim_key, 0)
        dim_status = "\u2705" if label not in failing_metrics else "\u274c Below floor"
        lines.append(f"| {label} | {score}/20 | \u226510 | {dim_status} |")

    # ICP Match row
    icp_label = "Yes" if icp_match else "No"
    icp_status = "\u2705" if "ICP Match" not in failing_metrics else "\u274c"
    lines.append(f"| ICP Match | {icp_label} | Required | {icp_status} |")

    # Publish Probability row
    pp_status = "\u2705" if "Publish Probability" not in failing_metrics else "\u274c Below"
    lines.append(f"| Publish Prob | {publish_probability}% | \u226550% | {pp_status} |")

    # Action blockquote
    lines.append("")
    lines.append(f"> {action}")

    # For REJECT, add bold action line
    if verdict == "reject":
        failing_dims = [f["metric"] for f in failures]
        lines.append("")
        lines.append(
            f"**Action:** This post does not meet the quality bar. "
            f"Recommend regeneration with focus on {', '.join(failing_dims)}."
        )

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Retrospective
# ---------------------------------------------------------------------------

def generate_retrospective(state: BarRaiserState) -> Optional[str]:
    """Generate a periodic retrospective every 10 posts.

    Uses ``state.total_posts_evaluated`` (lifetime counter) to trigger,
    not ``len(post_history)`` which is capped at 50.  Compares the last
    10 posts against the previous 10 (if available) to surface trends.

    Parameters
    ----------
    state:
        The current :class:`BarRaiserState`.

    Returns
    -------
    A markdown-formatted retrospective string, or ``None`` if conditions
    are not met (fewer than 10 posts in history).
    """
    total = len(state.post_history)
    if total < 10:
        return None

    last_10 = state.post_history[-10:]
    prev_10 = state.post_history[-20:-10] if total >= 20 else []

    now = datetime.now(timezone.utc).isoformat()
    state.retrospective_count += 1
    state.last_retrospective_at = now

    # ------------------------------------------------------------------
    # Compute averages for last 10
    # ------------------------------------------------------------------
    def _avg_dimensions(posts: list[dict]) -> dict[str, float]:
        totals: dict[str, float] = {}
        counts: dict[str, int] = {}
        for post in posts:
            dims = post.get("dimensions", {})
            for dim_key in _DIMENSION_LABELS:
                val = dims.get(dim_key, 0)
                totals[dim_key] = totals.get(dim_key, 0) + val
                counts[dim_key] = counts.get(dim_key, 0) + 1
        return {
            k: totals.get(k, 0) / max(counts.get(k, 1), 1)
            for k in _DIMENSION_LABELS
        }

    def _avg_quality(posts: list[dict]) -> float:
        if not posts:
            return 0.0
        return sum(p.get("quality_score", 0) for p in posts) / len(posts)

    def _verdict_counts(posts: list[dict]) -> dict[str, int]:
        counts = {"pass": 0, "conditional": 0, "reject": 0}
        for p in posts:
            v = p.get("verdict", "unknown")
            if v in counts:
                counts[v] += 1
        return counts

    last_10_dims = _avg_dimensions(last_10)
    last_10_quality = _avg_quality(last_10)
    last_10_verdicts = _verdict_counts(last_10)

    prev_10_dims = _avg_dimensions(prev_10) if prev_10 else {}
    prev_10_quality = _avg_quality(prev_10) if prev_10 else 0.0

    # ------------------------------------------------------------------
    # Trend arrows
    # ------------------------------------------------------------------
    def _arrow(current: float, previous: float) -> str:
        diff = current - previous
        if diff > 0.5:
            return "\u2191"
        elif diff < -0.5:
            return "\u2193"
        return "\u2192"

    lines = [
        "## Bar Raiser Retrospective",
        "",
        f"_Retrospective #{state.retrospective_count} | "
        f"Posts evaluated: {total} | Generated: {now}_",
        "",
    ]

    # Quality overview
    lines += [
        "### Quality Overview",
        "",
        f"- **Average quality (last 10):** {last_10_quality:.1f}/100",
    ]
    if prev_10:
        quality_arrow = _arrow(last_10_quality, prev_10_quality)
        lines.append(
            f"- **Average quality (prev 10):** {prev_10_quality:.1f}/100 "
            f"{quality_arrow}"
        )
    lines.append(f"- **Current bar level:** {state.bar_level:.1f}")
    lines.append(
        f"- **Verdicts (last 10):** "
        f"{last_10_verdicts['pass']} pass, "
        f"{last_10_verdicts['conditional']} conditional, "
        f"{last_10_verdicts['reject']} reject"
    )
    lines.append("")

    # Dimension trends table
    lines += [
        "### Dimension Trends",
        "",
        "| Dimension | Last 10 Avg | Prev 10 Avg | Trend |",
        "|-----------|-------------|-------------|-------|",
    ]
    for dim_key, label in _DIMENSION_LABELS.items():
        current_avg = last_10_dims.get(dim_key, 0)
        if prev_10:
            prev_avg = prev_10_dims.get(dim_key, 0)
            arrow = _arrow(current_avg, prev_avg)
            lines.append(
                f"| {label} | {current_avg:.1f} | {prev_avg:.1f} | {arrow} |"
            )
        else:
            lines.append(f"| {label} | {current_avg:.1f} | N/A | \u2014 |")

    lines.append("")

    # What's working / what needs work
    if prev_10:
        improving = []
        declining = []
        for dim_key, label in _DIMENSION_LABELS.items():
            diff = last_10_dims.get(dim_key, 0) - prev_10_dims.get(dim_key, 0)
            if diff > 0.5:
                improving.append(f"{label} (+{diff:.1f})")
            elif diff < -0.5:
                declining.append(f"{label} ({diff:.1f})")

        if improving:
            lines.append("### What's Working")
            lines.append("")
            for item in improving:
                lines.append(f"- {item}")
            lines.append("")

        if declining:
            lines.append("### What Needs Work")
            lines.append("")
            for item in declining:
                lines.append(f"- {item}")
            lines.append("")

        if not improving and not declining:
            lines.append("### Trend Summary")
            lines.append("")
            lines.append("- All dimensions stable (within \u00b10.5 of previous period)")
            lines.append("")

    # Agent health (based on available data)
    lines += [
        "### Agent Health",
        "",
        "| Agent | Signal | Status |",
        "|-------|--------|--------|",
    ]

    # Quality reviewer health: are quality scores trending up?
    if prev_10:
        quality_delta = last_10_quality - prev_10_quality
        if quality_delta > 2:
            qr_status = "\u2705 Improving"
        elif quality_delta < -2:
            qr_status = "\u26a0\ufe0f Declining"
        else:
            qr_status = "\u2705 Stable"
        lines.append(
            f"| Quality Reviewer | Avg score {last_10_quality:.1f} "
            f"(delta {quality_delta:+.1f}) | {qr_status} |"
        )
    else:
        lines.append(
            f"| Quality Reviewer | Avg score {last_10_quality:.1f} | "
            "\u2705 Baseline |"
        )

    # Resonance checker health: ICP match rate
    icp_hits = sum(1 for p in last_10 if p.get("icp_match", False))
    icp_rate = icp_hits / len(last_10) * 100
    icp_status = "\u2705 On target" if icp_rate >= 80 else "\u26a0\ufe0f Low ICP match rate"
    lines.append(f"| Resonance Checker | ICP match {icp_rate:.0f}% | {icp_status} |")

    # Predictor health: average publish probability
    avg_pp = sum(p.get("publish_probability", 0) for p in last_10) / len(last_10)
    pp_status = "\u2705 Healthy" if avg_pp >= 50 else "\u26a0\ufe0f Low confidence"
    lines.append(f"| Predictor | Avg publish prob {avg_pp:.0f}% | {pp_status} |")

    # Bar Raiser health: pass rate
    pass_rate = last_10_verdicts["pass"] / len(last_10) * 100
    if pass_rate >= 70:
        br_status = "\u2705 High pass rate"
    elif pass_rate >= 40:
        br_status = "\u2705 Moderate pass rate"
    else:
        br_status = "\u26a0\ufe0f Low pass rate — bar may be too high"
    lines.append(f"| Bar Raiser | Pass rate {pass_rate:.0f}% | {br_status} |")

    lines.append("")

    logger.info(
        "Generated retrospective #%d covering %d posts.",
        state.retrospective_count,
        total,
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Agent performance dashboard (for METRICS.md)
# ---------------------------------------------------------------------------

def render_agent_dashboard(state: BarRaiserState) -> str:
    """Generate the Agent Performance Dashboard markdown section.

    Suitable for inclusion in a ``METRICS.md`` or similar reporting file.

    Parameters
    ----------
    state:
        The current :class:`BarRaiserState`.

    Returns
    -------
    Markdown string with quality bar trends, dimension trends, agent health,
    and pass/conditional/reject rate breakdown.
    """
    history = state.post_history
    total = len(history)

    lines = [
        "## Agent Performance Dashboard",
        "",
    ]

    if total == 0:
        lines.append("_No posts evaluated yet._")
        lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Quality Bar Trend table
    # ------------------------------------------------------------------
    last_10 = history[-10:] if total >= 10 else history
    last_30 = history[-30:] if total >= 30 else history

    def _avg_score(posts: list[dict]) -> float:
        if not posts:
            return 0.0
        return sum(p.get("quality_score", 0) for p in posts) / len(posts)

    def _pass_rate(posts: list[dict]) -> float:
        if not posts:
            return 0.0
        passes = sum(1 for p in posts if p.get("verdict") == "pass")
        return passes / len(posts) * 100

    lines += [
        "### Quality Bar Trend",
        "",
        "| Period | Posts | Avg Score | Pass Rate | Bar Level |",
        "|--------|-------|-----------|-----------|-----------|",
        f"| Last 10 | {len(last_10)} | {_avg_score(last_10):.1f} | "
        f"{_pass_rate(last_10):.0f}% | {state.bar_level:.1f} |",
    ]
    if total >= 30:
        lines.append(
            f"| Last 30 | {len(last_30)} | {_avg_score(last_30):.1f} | "
            f"{_pass_rate(last_30):.0f}% | \u2014 |"
        )
    lines.append(
        f"| All Time | {total} | {_avg_score(history):.1f} | "
        f"{_pass_rate(history):.0f}% | \u2014 |"
    )
    lines.append("")

    # ------------------------------------------------------------------
    # Dimension Trends table (last 10 vs previous 10)
    # ------------------------------------------------------------------
    def _avg_dimensions(posts: list[dict]) -> dict[str, float]:
        totals: dict[str, float] = {}
        counts: dict[str, int] = {}
        for post in posts:
            dims = post.get("dimensions", {})
            for dim_key in _DIMENSION_LABELS:
                val = dims.get(dim_key, 0)
                totals[dim_key] = totals.get(dim_key, 0) + val
                counts[dim_key] = counts.get(dim_key, 0) + 1
        return {
            k: totals.get(k, 0) / max(counts.get(k, 1), 1)
            for k in _DIMENSION_LABELS
        }

    current_dims = _avg_dimensions(last_10)

    if total >= 20:
        prev_10 = history[-20:-10]
        prev_dims = _avg_dimensions(prev_10)

        lines += [
            "### Dimension Trends (Last 10 vs Previous 10)",
            "",
            "| Dimension | Current | Previous | Trend |",
            "|-----------|---------|----------|-------|",
        ]
        for dim_key, label in _DIMENSION_LABELS.items():
            curr = current_dims.get(dim_key, 0)
            prev = prev_dims.get(dim_key, 0)
            diff = curr - prev
            if diff > 0.5:
                arrow = "\u2191"
            elif diff < -0.5:
                arrow = "\u2193"
            else:
                arrow = "\u2192"
            lines.append(f"| {label} | {curr:.1f} | {prev:.1f} | {arrow} |")
    else:
        lines += [
            "### Dimension Averages",
            "",
            "| Dimension | Avg Score |",
            "|-----------|-----------|",
        ]
        for dim_key, label in _DIMENSION_LABELS.items():
            lines.append(f"| {label} | {current_dims.get(dim_key, 0):.1f} |")

    lines.append("")

    # ------------------------------------------------------------------
    # Agent Health table
    # ------------------------------------------------------------------
    icp_hits = sum(1 for p in last_10 if p.get("icp_match", False))
    icp_rate = icp_hits / len(last_10) * 100
    avg_pp = sum(p.get("publish_probability", 0) for p in last_10) / len(last_10)
    avg_quality = _avg_score(last_10)

    lines += [
        "### Agent Health",
        "",
        "| Agent | Key Metric | Value | Status |",
        "|-------|------------|-------|--------|",
        f"| Quality Reviewer | Avg Score | {avg_quality:.1f} | "
        f"{'✅' if avg_quality >= state.bar_level else '⚠️'} |",
        f"| Resonance Checker | ICP Match Rate | {icp_rate:.0f}% | "
        f"{'✅' if icp_rate >= 80 else '⚠️'} |",
        f"| Predictor | Avg Publish Prob | {avg_pp:.0f}% | "
        f"{'✅' if avg_pp >= 50 else '⚠️'} |",
        f"| Bar Raiser | Current Bar | {state.bar_level:.1f} | "
        f"{'✅' if state.bar_level <= 80 else '⚠️ High'} |",
        "",
    ]

    # ------------------------------------------------------------------
    # Pass / Conditional / Reject breakdown
    # ------------------------------------------------------------------
    pass_count = sum(1 for p in history if p.get("verdict") == "pass")
    cond_count = sum(1 for p in history if p.get("verdict") == "conditional")
    rej_count = sum(1 for p in history if p.get("verdict") == "reject")

    lines += [
        "### Verdict Breakdown (All Time)",
        "",
        "| Verdict | Count | Rate |",
        "|---------|-------|------|",
        f"| Pass | {pass_count} | {pass_count / total * 100:.0f}% |",
        f"| Conditional | {cond_count} | {cond_count / total * 100:.0f}% |",
        f"| Reject | {rej_count} | {rej_count / total * 100:.0f}% |",
        f"| **Total** | **{total}** | |",
        "",
    ]

    return "\n".join(lines)
