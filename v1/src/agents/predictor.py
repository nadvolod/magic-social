"""Meta-agent that predicts whether a social post will be published and how well it will perform.

Tracks its own accuracy over time and feeds prediction misses back into the
prompt so the model can self-calibrate.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Engagement tiers ranked low → viral
ENGAGEMENT_TIERS = ("low", "medium", "high", "viral")

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a prediction engine for a LinkedIn thought-leader whose ICP is AI \
engineers building distributed systems with and without Temporal.

Given a draft post, its quality review, resonance assessment, historical \
performance data, and your own recent prediction accuracy, predict:

1. **publish_probability** (0-100): likelihood the author will publish this post.
2. **engagement_tier** ("low" | "medium" | "high" | "viral"): expected \
performance once published.
3. **reasoning**: a JSON list of 2-4 short sentences explaining the prediction. \
   Cite specific numbers from the data when possible.

Return ONLY a JSON object (no markdown fences):
{
    "publish_probability": <int 0-100>,
    "engagement_tier": "<low|medium|high|viral>",
    "reasoning": ["<reason 1>", "<reason 2>", ...]
}
"""


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_user_prompt(
    linkedin_post: str,
    tags: list[str],
    hook_pattern: str,
    quality_review: dict,
    resonance: dict,
    learning_state: dict,
    accuracy_stats: dict,
) -> str:
    """Assemble the user message that provides all context to the LLM."""
    hook_scores = learning_state.get("hook_pattern_scores", {})
    topic_scores = learning_state.get("topic_scores", {})
    raw_reasons = learning_state.get("not_published_reasons", {})
    # Normalize: not_published_reasons is a dict {reason: count} in LearningState
    if isinstance(raw_reasons, dict):
        rejection_reasons = sorted(raw_reasons.keys(), key=lambda r: raw_reasons[r], reverse=True)
    else:
        rejection_reasons = list(raw_reasons) if raw_reasons else []
    avg_rating = learning_state.get("average_rating", "N/A")

    parts = [
        "## Draft post",
        linkedin_post,
        "",
        f"Tags: {', '.join(tags) if tags else 'none'}",
        f"Hook pattern: {hook_pattern}",
        "",
        "## Quality review",
        f"Total score: {quality_review.get('total_score', 'N/A')}",
    ]

    dimensions = quality_review.get("dimensions", {})
    if dimensions:
        parts.append("Dimension scores:")
        for dim, score in dimensions.items():
            parts.append(f"  - {dim}: {score}")

    suggestions = quality_review.get("suggestions", "")
    if isinstance(suggestions, str) and suggestions:
        parts.append("Suggestions: " + suggestions)
    elif isinstance(suggestions, list) and suggestions:
        parts.append("Suggestions: " + "; ".join(suggestions))

    parts += [
        "",
        "## Resonance assessment",
        f"Resonance: {resonance.get('resonance', 'N/A')}",
        f"ICP match: {resonance.get('icp_match', 'N/A')}",
    ]
    reasons = resonance.get("reasons", [])
    if reasons:
        parts.append("Reasons: " + "; ".join(reasons))

    parts += [
        "",
        "## Historical data",
        f"Average post rating: {avg_rating}",
    ]

    if hook_scores:
        parts.append("Hook pattern success rates:")
        for hook, score in hook_scores.items():
            parts.append(f"  - {hook}: {score}")

    if topic_scores:
        parts.append("Topic scores:")
        for topic, score in topic_scores.items():
            parts.append(f"  - {topic}: {score}")

    if rejection_reasons:
        parts.append("Common rejection reasons: " + "; ".join(rejection_reasons[-5:]))

    # Self-calibration block — let the model know its own track record
    if accuracy_stats and accuracy_stats.get("total_predictions", 0) > 0:
        parts += [
            "",
            "## Your recent prediction accuracy",
            f"Total predictions evaluated: {accuracy_stats['total_predictions']}",
            f"Publish call accuracy: {accuracy_stats.get('publish_accuracy_pct', 'N/A')}%",
            f"Engagement tier accuracy: {accuracy_stats.get('tier_accuracy_pct', 'N/A')}%",
        ]
        recent_misses = accuracy_stats.get("recent_misses", [])
        if recent_misses:
            parts.append("Recent misses:")
            for miss in recent_misses[-5:]:
                parts.append(f"  - {miss}")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Main prediction function
# ---------------------------------------------------------------------------

def predict_outcome(
    client,  # OpenAI client
    linkedin_post: str,
    tags: list[str],
    hook_pattern: str,
    quality_review: dict,
    resonance: dict,
    learning_state: dict,
    prediction_history: list[dict],
    model: str = "gpt-5.4-mini",
) -> dict:
    """Predict publish probability and engagement tier.

    Parameters
    ----------
    client:
        An already-initialised OpenAI client instance.
    linkedin_post:
        The full text of the draft LinkedIn post.
    tags:
        Topic tags associated with the post.
    hook_pattern:
        The hook style used (e.g. "result", "contrarian").
    quality_review:
        Output from the quality reviewer agent.
    resonance:
        Output from the resonance checker agent.
    learning_state:
        Accumulated learning data — hook scores, topic scores, etc.
    prediction_history:
        Recent predictions with outcomes, used for self-calibration.
    model:
        OpenAI model to use.

    Returns
    -------
    dict with keys: post_id, publish_probability, engagement_tier, reasoning,
    predicted_at, actual_published, actual_engagement_score.
    """
    post_id = f"post-{uuid.uuid4().hex[:6]}"
    accuracy_stats = compute_accuracy_stats(prediction_history)

    user_prompt = _build_user_prompt(
        linkedin_post=linkedin_post,
        tags=tags,
        hook_pattern=hook_pattern,
        quality_review=quality_review,
        resonance=resonance,
        learning_state=learning_state,
        accuracy_stats=accuracy_stats,
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_completion_tokens=512,
            temperature=0.3,
        )

        raw = (response.choices[0].message.content or "").strip()
        data = json.loads(raw)

        publish_probability = int(data.get("publish_probability", 50))
        publish_probability = max(0, min(100, publish_probability))

        engagement_tier = data.get("engagement_tier", "medium").lower()
        if engagement_tier not in ENGAGEMENT_TIERS:
            logger.warning(
                "LLM returned unknown engagement tier '%s', falling back to 'medium'",
                engagement_tier,
            )
            engagement_tier = "medium"

        reasoning = data.get("reasoning", [])
        if not isinstance(reasoning, list):
            reasoning = [str(reasoning)]

    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.warning("Failed to parse LLM prediction response: %s", exc)
        publish_probability = 50
        engagement_tier = "medium"
        reasoning = ["Prediction unavailable — LLM response could not be parsed."]
    except Exception as exc:  # noqa: BLE001
        logger.error("OpenAI API error during prediction: %s", exc)
        publish_probability = 50
        engagement_tier = "medium"
        reasoning = ["Prediction unavailable — API error."]

    return {
        "post_id": post_id,
        "publish_probability": publish_probability,
        "engagement_tier": engagement_tier,
        "reasoning": reasoning,
        "predicted_at": datetime.now(timezone.utc).isoformat(),
        "actual_published": None,
        "actual_engagement_score": None,
    }


# ---------------------------------------------------------------------------
# Comment formatting
# ---------------------------------------------------------------------------

def format_prediction_comment(prediction: dict, accuracy_stats: dict) -> str:
    """Format a prediction as a GitHub issue comment in Markdown."""
    prob = prediction.get("publish_probability", "?")
    tier = prediction.get("engagement_tier", "?").capitalize()
    reasoning = prediction.get("reasoning", [])

    lines = [
        "## Prediction",
        "",
        f"**Publish probability: {prob}%** | **Engagement forecast: {tier}**",
        "",
        "Reasoning:",
    ]
    for reason in reasoning:
        lines.append(f"- {reason}")

    total = accuracy_stats.get("total_predictions", 0)
    if total > 0:
        pub_acc = accuracy_stats.get("publish_accuracy_pct", 0)
        tier_acc = accuracy_stats.get("tier_accuracy_pct", 0)
        lines += [
            "",
            f"_Predictor accuracy (last {total} posts): "
            f"{pub_acc}% publish calls correct, "
            f"{tier_acc}% engagement tier correct_",
        ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def load_predictions_log(path: str = "predictions_log.json") -> list[dict]:
    """Load prediction history from file.

    Returns an empty list if the file does not exist or is malformed.
    """
    filepath = Path(path)
    if not filepath.exists():
        logger.debug("Predictions log not found at %s — returning empty list.", path)
        return []
    try:
        data = json.loads(filepath.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            logger.warning("Predictions log is not a list — returning empty list.")
            return []
        return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load predictions log from %s: %s", path, exc)
        return []


def save_prediction(prediction: dict, path: str = "predictions_log.json") -> None:
    """Append a prediction to the log file."""
    predictions = load_predictions_log(path)
    predictions.append(prediction)
    try:
        Path(path).write_text(
            json.dumps(predictions, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        logger.info("Saved prediction %s to %s.", prediction.get("post_id"), path)
    except OSError as exc:
        logger.error("Failed to save prediction to %s: %s", path, exc)


def update_prediction_outcome(
    post_id: str,
    published: bool,
    engagement_score: float = 0.0,
    path: str = "predictions_log.json",
) -> None:
    """Update a prediction with actual outcome after feedback is collected."""
    predictions = load_predictions_log(path)
    updated = False

    for pred in predictions:
        if pred.get("post_id") == post_id:
            pred["actual_published"] = published
            pred["actual_engagement_score"] = engagement_score
            updated = True
            break

    if not updated:
        logger.warning("Prediction %s not found in %s — cannot update.", post_id, path)
        return

    try:
        Path(path).write_text(
            json.dumps(predictions, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        logger.info("Updated prediction %s with outcome: published=%s, engagement=%.1f",
                     post_id, published, engagement_score)
    except OSError as exc:
        logger.error("Failed to write updated predictions to %s: %s", path, exc)


# ---------------------------------------------------------------------------
# Accuracy computation
# ---------------------------------------------------------------------------

def _engagement_tier_from_score(score: float) -> str:
    """Map a numeric engagement score to a tier label."""
    if score >= 100:
        return "viral"
    if score >= 40:
        return "high"
    if score >= 15:
        return "medium"
    return "low"


def compute_accuracy_stats(predictions: list[dict]) -> dict:
    """Compute predictor accuracy from historical predictions.

    Only considers predictions that have ``actual_published`` set (i.e. those
    with known outcomes).

    Returns
    -------
    dict with keys: total_predictions, publish_accuracy_pct,
    tier_accuracy_pct, recent_misses.
    """
    evaluated = [
        p for p in predictions
        if p.get("actual_published") is not None
    ]

    if not evaluated:
        return {
            "total_predictions": 0,
            "publish_accuracy_pct": 0.0,
            "tier_accuracy_pct": 0.0,
            "recent_misses": [],
        }

    publish_correct = 0
    tier_correct = 0
    recent_misses: list[str] = []

    for pred in evaluated:
        predicted_publish = pred.get("publish_probability", 50) >= 50
        actual_publish = pred["actual_published"]

        # Publish accuracy
        if predicted_publish == actual_publish:
            publish_correct += 1
        else:
            action = "publish" if predicted_publish else "skip"
            actual_action = "published" if actual_publish else "skipped"
            recent_misses.append(
                f"{pred.get('post_id', '?')}: predicted {action}, actual {actual_action}"
            )

        # Tier accuracy (only meaningful for published posts with engagement data)
        actual_score = pred.get("actual_engagement_score")
        if actual_publish and actual_score is not None:
            actual_tier = _engagement_tier_from_score(actual_score)
            predicted_tier = pred.get("engagement_tier", "medium")
            if predicted_tier == actual_tier:
                tier_correct += 1
            else:
                recent_misses.append(
                    f"{pred.get('post_id', '?')}: predicted {predicted_tier}, "
                    f"actual {actual_tier}"
                )

    total = len(evaluated)
    published_with_scores = [
        p for p in evaluated
        if p.get("actual_published") and p.get("actual_engagement_score") is not None
    ]
    tier_total = len(published_with_scores) if published_with_scores else 1

    return {
        "total_predictions": total,
        "publish_accuracy_pct": round(publish_correct / total * 100, 1),
        "tier_accuracy_pct": round(tier_correct / tier_total * 100, 1),
        "recent_misses": recent_misses[-10:],  # keep last 10 misses
    }
