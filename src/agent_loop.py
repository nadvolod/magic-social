"""Pre-creation agent quality loop.

Runs the 4 post-generation agents (Quality Reviewer, Resonance Checker,
Predictor, Bar Raiser) on a post BEFORE it becomes a GitHub Issue.

If the Bar Raiser rejects, the loop rewrites the post using specific
agent feedback, then re-evaluates. Up to max_iterations rewrites.

Returns the best version of the post along with all agent results,
so they can be posted as comments without re-running the agents.
"""

from __future__ import annotations

import logging
import textwrap
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class AgentLoopResult:
    """Result from the pre-creation agent quality loop."""

    post_text: str
    quality_review: dict = field(default_factory=dict)
    resonance: dict = field(default_factory=dict)
    prediction: dict = field(default_factory=dict)
    bar_raiser_verdict: dict = field(default_factory=dict)
    iterations: int = 0
    improved: bool = False


def _run_agents(
    openai_client,
    post_text: str,
    commit_message: str,
    commit_diff: str,
    tags: list[str],
    hook_pattern: str,
    learning_state,
) -> tuple[dict, dict, dict, dict]:
    """Run all 4 agents and return their results."""
    quality_review: dict = {}
    resonance: dict = {}
    prediction: dict = {}
    verdict: dict = {}

    try:
        from .agents.quality_reviewer import review_quality  # noqa: PLC0415
        quality_review = review_quality(openai_client, post_text, commit_message, commit_diff)
    except Exception:  # noqa: BLE001
        logger.warning("Quality reviewer failed in agent loop (non-fatal)", exc_info=True)

    try:
        from .agents.resonance_checker import check_resonance  # noqa: PLC0415
        topic_scores = learning_state.topic_scores if learning_state else {}
        resonance = check_resonance(openai_client, post_text, tags, topic_scores)
    except Exception:  # noqa: BLE001
        logger.warning("Resonance checker failed in agent loop (non-fatal)", exc_info=True)

    try:
        from .agents.predictor import predict_outcome, load_predictions_log  # noqa: PLC0415
        ls_dict = learning_state.to_dict() if learning_state else {}
        predictions = load_predictions_log()
        prediction = predict_outcome(
            openai_client, post_text, tags, hook_pattern,
            quality_review, resonance, ls_dict, predictions[-30:],
        )
    except Exception:  # noqa: BLE001
        logger.warning("Predictor failed in agent loop (non-fatal)", exc_info=True)

    try:
        from .agents.bar_raiser import BarRaiserState, raise_the_bar  # noqa: PLC0415
        bar_state = BarRaiserState.load()
        verdict = raise_the_bar(quality_review, resonance, prediction, bar_state)
        # Don't save bar_state here — save it only when the final post is committed to an issue
    except Exception:  # noqa: BLE001
        logger.warning("Bar Raiser failed in agent loop (non-fatal)", exc_info=True)

    return quality_review, resonance, prediction, verdict


def _build_agent_rewrite_prompt(
    post_text: str,
    quality_review: dict,
    resonance: dict,
    prediction: dict,
    verdict: dict,
) -> str:
    """Build a rewrite prompt from specific agent failures."""
    issues: list[str] = []

    # Extract low-scoring dimensions from quality review
    if quality_review:
        for dim, score in quality_review.items():
            if isinstance(score, (int, float)) and score < 14:
                issues.append(f"- {dim.replace('_', ' ').title()} scored {score}/20 — needs improvement")

    # Extract resonance issues
    if resonance:
        icp_match = resonance.get("icp_match")
        if icp_match and isinstance(icp_match, str) and "weak" in icp_match.lower():
            issues.append("- ICP match is weak — needs direct connection to AI agents, Temporal, or distributed systems")
        icp_match_num = resonance.get("icp_match_score")
        if isinstance(icp_match_num, (int, float)) and icp_match_num < 14:
            issues.append("- Audience resonance is low — make the lesson more relevant to AI engineers building distributed systems")

    # Extract prediction concerns
    if prediction:
        prob = prediction.get("publish_probability")
        if isinstance(prob, (int, float)) and prob < 40:
            issues.append(f"- Predicted publish probability is only {prob}% — post needs to be more compelling")

    # Extract bar raiser failures
    if verdict:
        failures = verdict.get("failures", [])
        for failure in failures[:3]:
            if isinstance(failure, str):
                issues.append(f"- Bar Raiser: {failure}")
            elif isinstance(failure, dict):
                issues.append(f"- Bar Raiser: {failure.get('reason', str(failure))}")

    if not issues:
        issues.append("- Overall quality is below the bar — make the hook sharper, the lesson more specific, and add concrete proof")

    issues_text = "\n".join(issues)
    return textwrap.dedent(f"""
        Rewrite this LinkedIn post to address these specific quality issues:

        {issues_text}

        Current post:
        {post_text}

        Rewrite requirements:
        1. Keep one clear lesson only.
        2. Add specific proof (numbers or before/after).
        3. Include an indented code/config snippet (4 spaces).
        4. Keep 800-1500 characters.
        5. End with an open-ended question.
        6. The lesson must be relevant to AI engineers building distributed systems.

        Return ONLY the rewritten LinkedIn post text.
    """).strip()


def agent_quality_loop(
    post_text: str,
    commit_message: str,
    commit_diff: str,
    tags: list[str],
    hook_pattern: str,
    openai_client,
    learning_state,
    model: str = "gpt-5.4-mini",
    max_iterations: int = 2,
) -> AgentLoopResult:
    """
    Run agents on the post and rewrite if rejected.

    Returns the best version of the post along with agent results.
    """
    from .post_generator import _build_system_prompt, _generate_with_openai  # noqa: PLC0415

    best_text = post_text
    best_result = AgentLoopResult(post_text=post_text)

    for iteration in range(max_iterations + 1):
        quality_review, resonance, prediction, verdict = _run_agents(
            openai_client, best_text, commit_message, commit_diff,
            tags, hook_pattern, learning_state,
        )

        result = AgentLoopResult(
            post_text=best_text,
            quality_review=quality_review,
            resonance=resonance,
            prediction=prediction,
            bar_raiser_verdict=verdict,
            iterations=iteration,
            improved=iteration > 0,
        )

        verdict_str = verdict.get("verdict", "")
        if verdict_str in ("pass", "conditional") or not verdict_str:
            logger.info(
                "Agent loop: post passed on iteration %d (verdict=%s)",
                iteration, verdict_str or "no-verdict",
            )
            return result

        if iteration >= max_iterations:
            logger.info(
                "Agent loop: post still rejected after %d iterations, returning best version",
                max_iterations,
            )
            return result

        # Rewrite using agent feedback
        logger.info("Agent loop: post rejected (iteration %d), rewriting with agent feedback", iteration)
        rewrite_prompt = _build_agent_rewrite_prompt(
            best_text, quality_review, resonance, prediction, verdict,
        )
        best_text = _generate_with_openai(
            openai_client, model, _build_system_prompt(), rewrite_prompt,
        )
        best_result = result

    return best_result
