"""Post-generation agent that checks whether a LinkedIn post will resonate.

Evaluates a generated post against the target ICP and historical engagement
data, returning a resonance assessment and a formatted GitHub issue comment.

ICP: AI engineers building distributed systems with and without Temporal.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

ICP_KEYWORDS = [
    "temporal",
    "workflow",
    "distributed",
    "saga",
    "orchestration",
    "durable",
    "ai agent",
    "llm",
    "inference",
    "microservice",
    "event-driven",
    "fault-tolerant",
    "retry",
    "idempotent",
    "queue",
    "worker",
    "activity",
    "signal",
]

_RESONANCE_EMOJI = {
    "high": "\U0001f7e2",   # green circle
    "medium": "\U0001f7e1", # yellow circle
    "low": "\U0001f534",    # red circle
}

_SYSTEM_PROMPT = """\
You are an audience-resonance analyst for a technical thought-leader whose \
ICP (Ideal Customer Profile) is **AI engineers building distributed systems \
with and without Temporal**.

You will be given:
1. A LinkedIn post draft.
2. The post's topic tags.
3. Historical engagement scores per tag (count and total_score).

Your job:
- Decide whether this post serves AI engineers who build distributed systems \
(with or without Temporal).
- Rate the resonance as "high", "medium", or "low".
- Provide 1-3 concise reasons explaining your rating.
- Provide a one-sentence suggestion for the author.

Return ONLY a JSON object (no markdown fences) with this shape:
{
  "resonance": "high" | "medium" | "low",
  "icp_match": true | false,
  "reasons": ["reason 1", "reason 2"],
  "suggestion": "One sentence of advice."
}

Guidelines:
- icp_match = true only when the post clearly serves AI engineers working on \
distributed systems, orchestration, durable execution, or closely related \
infrastructure topics.
- If a tag has historically high engagement (high average score), that should \
boost the resonance rating.
- If the content is generic software advice with no distributed-systems angle, \
icp_match = false and resonance should be low.
- Be honest and constructive in your suggestion."""


def _matches_icp(text: str) -> bool:
    """Return True if *text* contains at least one ICP keyword."""
    lower = text.lower()
    return any(kw in lower for kw in ICP_KEYWORDS)


def _build_user_prompt(
    linkedin_post: str,
    tags: list[str],
    topic_scores: dict,
) -> str:
    """Build the user prompt sent to the LLM."""
    score_lines: list[str] = []
    for tag in tags:
        stats = topic_scores.get(tag)
        if stats and stats.get("count", 0) > 0:
            avg = stats["total_score"] / stats["count"]
            score_lines.append(f"  - {tag}: {stats['count']} posts, avg score {avg:.1f}")
        else:
            score_lines.append(f"  - {tag}: no historical data")

    parts = [
        "LinkedIn post draft:",
        "---",
        linkedin_post,
        "---",
        "",
        f"Topic tags: {', '.join(tags)}",
        "",
        "Historical engagement per tag:",
        *(score_lines if score_lines else ["  (none)"]),
    ]
    return "\n".join(parts)


def _default_assessment() -> dict:
    """Fallback assessment when the LLM call fails."""
    return {
        "resonance": "medium",
        "icp_match": True,
        "reasons": ["Assessment unavailable — defaulting to medium resonance"],
        "suggestion": "Review manually before publishing.",
    }


def check_resonance(
    client,  # OpenAI client
    linkedin_post: str,
    tags: list[str],
    topic_scores: dict,  # from learning state: {tag: {count, total_score}}
    model: str = "gpt-5.4-mini",
) -> dict:
    """Check audience resonance for a LinkedIn post draft.

    Returns a dict with keys: resonance, icp_match, reasons, suggestion.

    Parameters
    ----------
    client:
        An already-initialised OpenAI client instance.
    linkedin_post:
        The full text of the LinkedIn post to evaluate.
    tags:
        Topic tags associated with the post.
    topic_scores:
        Historical engagement data: ``{tag: {"count": int, "total_score": float}}``.
    model:
        OpenAI model to use for analysis.
    """
    # Quick ICP pre-check — if nothing matches, we can still ask the LLM
    # but log the signal for debugging.
    combined_text = f"{linkedin_post} {' '.join(tags)}"
    if not _matches_icp(combined_text):
        logger.info("No ICP keywords detected in post or tags — likely low resonance")

    user_prompt = _build_user_prompt(linkedin_post, tags, topic_scores)

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
        raw = response.choices[0].message.content.strip()
        data = json.loads(raw)

        # Validate and normalise fields
        resonance = data.get("resonance", "medium").lower()
        if resonance not in ("high", "medium", "low"):
            logger.warning("LLM returned unknown resonance '%s', defaulting to medium", resonance)
            resonance = "medium"

        icp_match = bool(data.get("icp_match", False))

        reasons = data.get("reasons", [])
        if not isinstance(reasons, list):
            reasons = [str(reasons)]

        suggestion = data.get("suggestion", "")
        if not isinstance(suggestion, str):
            suggestion = str(suggestion)

        assessment = {
            "resonance": resonance,
            "icp_match": icp_match,
            "reasons": reasons,
            "suggestion": suggestion,
        }

        logger.info(
            "Resonance check complete: %s resonance, ICP match=%s",
            resonance,
            icp_match,
        )
        return assessment

    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.warning("Failed to parse LLM response for resonance check: %s", exc)
        return _default_assessment()
    except Exception as exc:  # noqa: BLE001
        logger.error("OpenAI API error during resonance check: %s", exc)
        return _default_assessment()


def format_resonance_comment(assessment: dict) -> str:
    """Format a resonance assessment as a GitHub issue comment in markdown.

    Parameters
    ----------
    assessment:
        The dict returned by :func:`check_resonance`.
    """
    resonance = assessment.get("resonance", "medium")
    icp_match = assessment.get("icp_match", False)
    reasons = assessment.get("reasons", [])
    suggestion = assessment.get("suggestion", "")

    # Header
    resonance_label = resonance.capitalize()
    resonance_emoji = _RESONANCE_EMOJI.get(resonance, "\U0001f7e1")
    icp_label = "Yes" if icp_match else "No"
    icp_emoji = "\u2705" if icp_match else "\u274c"

    lines = [
        "## Audience Resonance Check",
        "",
        f"**Resonance: {resonance_label}** {resonance_emoji} | **ICP Match: {icp_label}** {icp_emoji}",
        "",
    ]

    # Reason bullets
    for reason in reasons:
        lines.append(f"- {reason}")

    # Suggestion as blockquote
    if suggestion:
        lines.append("")
        lines.append(f"> {suggestion}")
    lines.append("")

    return "\n".join(lines)
