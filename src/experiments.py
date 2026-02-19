"""A/B experiment management for post variables."""

from __future__ import annotations

import json
import logging
import random
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import Experiment, ExperimentStatus, ExperimentVariable

logger = logging.getLogger(__name__)

# Minimum posts per variant before declaring a winner
MIN_SAMPLES_PER_VARIANT = 3

# Pre-defined experiment plans to run sequentially
EXPERIMENT_PLAN = [
    {
        "variable": ExperimentVariable.HOOK_STYLE,
        "variants": ["result", "contrarian", "story", "number"],
        "hypothesis": "The 'result' hook (quantified outcome) drives higher saves than story hooks.",
    },
    {
        "variable": ExperimentVariable.POST_LENGTH,
        "variants": ["short_600", "medium_1000", "long_1400"],
        "hypothesis": "Medium-length posts (800-1200 chars) maximise comment rate.",
    },
    {
        "variable": ExperimentVariable.TONE,
        "variants": ["technical_direct", "conversational", "confessional"],
        "hypothesis": "Confessional tone generates more comments than technical tone.",
    },
    {
        "variable": ExperimentVariable.CTA_TYPE,
        "variants": ["question_open", "question_poll", "no_cta"],
        "hypothesis": "Open questions produce more comment volume than polls.",
    },
    {
        "variable": ExperimentVariable.STRUCTURE,
        "variants": ["list_numbered", "prose_flowing", "before_after"],
        "hypothesis": "Before/after structure drives higher save rates.",
    },
]


class ExperimentManager:
    """Manages the lifecycle of A/B experiments for post variables."""

    def __init__(self, state_path: str = "experiments.json") -> None:
        self.state_path = Path(state_path)
        self.experiments: list[Experiment] = self._load()

    def _load(self) -> list[Experiment]:
        if self.state_path.exists():
            try:
                with self.state_path.open() as f:
                    data = json.load(f)
                return [Experiment.from_dict(e) for e in data]
            except (json.JSONDecodeError, KeyError) as exc:
                logger.warning("Could not load experiments: %s", exc)
        return []

    def save(self) -> None:
        with self.state_path.open("w") as f:
            json.dump([e.to_dict() for e in self.experiments], f, indent=2)
        logger.debug("Saved %d experiments to %s", len(self.experiments), self.state_path)

    def get_active_experiment(self) -> Optional[Experiment]:
        """Return the currently running experiment, if any."""
        for exp in self.experiments:
            if exp.status == ExperimentStatus.RUNNING:
                return exp
        return None

    def start_next_experiment(self) -> Optional[Experiment]:
        """
        Start the next experiment from the plan.

        Returns the new experiment, or None if all have been run.
        """
        completed_variables = {
            ExperimentVariable(e.variable) if isinstance(e.variable, str) else e.variable
            for e in self.experiments
            if e.status != ExperimentStatus.RUNNING
        }
        for plan in EXPERIMENT_PLAN:
            if plan["variable"] not in completed_variables:
                exp = Experiment(
                    id=str(uuid.uuid4())[:8],
                    variable=plan["variable"],
                    variants=plan["variants"],
                    hypothesis=plan["hypothesis"],
                )
                self.experiments.append(exp)
                self.save()
                logger.info("Started experiment %s: %s", exp.id, exp.variable.value)
                return exp
        logger.info("All planned experiments have been run.")
        return None

    def assign_variant(self, experiment: Experiment) -> str:
        """
        Assign a variant for a new post in the experiment.

        Uses round-robin assignment to ensure even distribution.
        """
        # Count how many times each variant has been used
        variant_counts: dict = {v: 0 for v in experiment.variants}
        for post_id, result in experiment.results.items():
            v = result.get("variant")
            if v in variant_counts:
                variant_counts[v] += 1

        # Pick the least-used variant (ties broken randomly)
        min_count = min(variant_counts.values())
        candidates = [v for v, c in variant_counts.items() if c == min_count]
        return random.choice(candidates)

    def record_result(
        self,
        experiment: Experiment,
        post_id: str,
        variant: str,
        engagement_score: float,
    ) -> None:
        """Record a post's engagement score for a given variant."""
        experiment.results[post_id] = {
            "variant": variant,
            "engagement_score": engagement_score,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        self.save()
        logger.info("Recorded experiment result: post=%s, variant=%s, score=%.1f", post_id, variant, engagement_score)

        # Check if we have enough data to conclude
        self._maybe_conclude(experiment)

    def _maybe_conclude(self, experiment: Experiment) -> None:
        """Conclude the experiment if we have enough samples for each variant."""
        variant_scores: dict = {v: [] for v in experiment.variants}
        for result in experiment.results.values():
            v = result.get("variant")
            score = result.get("engagement_score", 0.0)
            if v in variant_scores:
                variant_scores[v].append(score)

        # Check if all variants have enough samples
        if not all(len(scores) >= MIN_SAMPLES_PER_VARIANT for scores in variant_scores.values()):
            return

        # Find winner by average engagement score
        averages = {
            v: sum(scores) / len(scores)
            for v, scores in variant_scores.items()
            if scores
        }
        winner = max(averages, key=averages.get)  # type: ignore[arg-type]

        experiment.winner = winner
        experiment.status = ExperimentStatus.CONCLUDED
        experiment.end_date = datetime.now(timezone.utc).isoformat()
        experiment.results["__summary__"] = {
            "averages": {v: round(avg, 2) for v, avg in averages.items()},
            "winner": winner,
            "concluded_at": experiment.end_date,
        }
        self.save()
        logger.info(
            "Experiment %s concluded. Winner: %s (avg score=%.1f)",
            experiment.id,
            winner,
            averages[winner],
        )

    def get_best_variant(self, variable: ExperimentVariable) -> Optional[str]:
        """Return the winning variant for a given variable, or None if inconclusive."""
        for exp in reversed(self.experiments):
            exp_variable = ExperimentVariable(exp.variable) if isinstance(exp.variable, str) else exp.variable
            if exp_variable == variable and exp.status == ExperimentStatus.CONCLUDED:
                return exp.winner
        return None

    def summary(self) -> str:
        """Return a human-readable summary of all experiments."""
        if not self.experiments:
            return "No experiments have been run yet."
        lines = ["## A/B Experiment Summary\n"]
        for exp in self.experiments:
            status_icon = {"running": "🔄", "concluded": "✅", "paused": "⏸️"}.get(
                exp.status.value if hasattr(exp.status, "value") else exp.status, "❓"
            )
            lines.append(f"{status_icon} **{exp.variable.value if hasattr(exp.variable, 'value') else exp.variable}**")
            lines.append(f"   Hypothesis: {exp.hypothesis}")
            lines.append(f"   Variants: {', '.join(exp.variants)}")
            if exp.winner:
                lines.append(f"   Winner: **{exp.winner}** ✓")
            lines.append("")
        return "\n".join(lines)
