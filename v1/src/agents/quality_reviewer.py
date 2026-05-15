"""Post-generation agent that performs semantic quality review of LinkedIn posts.

Scores generated posts on five dimensions that the existing regex-based
quality gate cannot evaluate: specificity, insight depth, hook strength,
code relevance, and shareability.  Returns a structured score breakdown
and can format the result as a GitHub issue comment in markdown.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scoring dimensions (each 0-20, total 0-100)
# ---------------------------------------------------------------------------
DIMENSIONS = [
    "specificity",
    "insight_depth",
    "hook_strength",
    "code_relevance",
    "shareability",
]

_DIMENSION_MAX = 20

_SYSTEM_PROMPT = """\
You are a senior LinkedIn content strategist who reviews technical posts \
written for AI engineers building distributed systems.

Score the post on these five dimensions (0-20 each):

1. **Specificity** — Does it teach a concrete, actionable lesson vs. generic advice?
2. **Insight Depth** — Would an experienced engineer learn something new?
3. **Hook Strength** — Does the opening genuinely create curiosity (not just pattern-matching)?
4. **Code Relevance** — Does the code snippet illustrate the core lesson (not boilerplate)?
5. **Shareability** — Would someone repost this to look smart/helpful?

Return ONLY a JSON object with this exact schema (no markdown fences):
{
  "specificity": {"score": <int 0-20>, "notes": "<one sentence>"},
  "insight_depth": {"score": <int 0-20>, "notes": "<one sentence>"},
  "hook_strength": {"score": <int 0-20>, "notes": "<one sentence>"},
  "code_relevance": {"score": <int 0-20>, "notes": "<one sentence>"},
  "shareability": {"score": <int 0-20>, "notes": "<one sentence>"},
  "suggestions": "<one sentence of actionable improvement advice>"
}"""

# Display labels for the markdown table
_DIMENSION_LABELS = {
    "specificity": "Specificity",
    "insight_depth": "Insight Depth",
    "hook_strength": "Hook Strength",
    "code_relevance": "Code Relevance",
    "shareability": "Shareability",
}


def _build_user_prompt(
    linkedin_post: str,
    commit_message: str,
    commit_diff_summary: str,
) -> str:
    """Assemble the user prompt with the post and its source context."""
    parts = [
        "## LinkedIn Post\n",
        linkedin_post,
        "\n## Source Commit",
        f"Message: {commit_message}",
        f"Diff summary: {commit_diff_summary}",
    ]
    return "\n".join(parts)


def _default_review() -> dict:
    """Fallback review returned when the LLM call fails."""
    dimensions = {}
    for dim in DIMENSIONS:
        dimensions[dim] = {
            "score": 10,
            "max": _DIMENSION_MAX,
            "notes": "Review unavailable",
        }
    return {
        "total_score": 50,
        "dimensions": dimensions,
        "suggestions": "Review unavailable — could not reach the language model.",
    }


def _clamp_score(value: int | float) -> int:
    """Clamp a score to the 0-20 range and return an int."""
    return max(0, min(_DIMENSION_MAX, int(value)))


def review_quality(
    client,  # OpenAI client
    linkedin_post: str,
    commit_message: str,
    commit_diff_summary: str,
    model: str = "gpt-5.4-mini",
) -> dict:
    """Semantic quality review. Returns score breakdown + suggestions.

    Parameters
    ----------
    client:
        An already-initialised OpenAI client instance.
    linkedin_post:
        The full generated LinkedIn post text.
    commit_message:
        The source commit message that the post was generated from.
    commit_diff_summary:
        A short summary of the commit diff for context.
    model:
        OpenAI model to use for the review.

    Returns
    -------
    dict with keys ``total_score``, ``dimensions``, and ``suggestions``.
    Each dimension entry has ``score``, ``max``, and ``notes``.
    Falls back gracefully on any failure.
    """
    user_prompt = _build_user_prompt(linkedin_post, commit_message, commit_diff_summary)

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_completion_tokens=512,
            temperature=0.3,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content.strip()
        data = json.loads(raw)
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.warning("Failed to parse quality review response: %s", exc)
        return _default_review()
    except Exception as exc:  # noqa: BLE001
        logger.error("OpenAI API error during quality review: %s", exc)
        return _default_review()

    # Build the normalised result
    dimensions: dict[str, dict] = {}
    total = 0

    for dim in DIMENSIONS:
        entry = data.get(dim, {})
        if isinstance(entry, dict):
            score = _clamp_score(entry.get("score", 10))
            notes = str(entry.get("notes", "No notes provided"))
        else:
            # Handle unexpected shape gracefully
            score = _clamp_score(entry) if isinstance(entry, (int, float)) else 10
            notes = "No notes provided"

        dimensions[dim] = {
            "score": score,
            "max": _DIMENSION_MAX,
            "notes": notes,
        }
        total += score

    suggestions = str(data.get("suggestions", "No suggestions provided."))

    review = {
        "total_score": total,
        "dimensions": dimensions,
        "suggestions": suggestions,
    }

    logger.info("Quality review complete — total score: %d/100", total)
    return review


def format_quality_comment(review: dict) -> str:
    """Format the review as a GitHub issue comment in markdown.

    Parameters
    ----------
    review:
        The dict returned by :func:`review_quality`.

    Returns
    -------
    A markdown-formatted string suitable for posting as a GitHub comment.
    """
    total = review.get("total_score", 0)
    dimensions = review.get("dimensions", {})
    suggestions = review.get("suggestions", "")

    lines = [
        "## Semantic Quality Review",
        "",
        f"**Score: {total}/100**",
        "",
        "| Dimension | Score | Notes |",
        "|-----------|-------|-------|",
    ]

    for dim in DIMENSIONS:
        entry = dimensions.get(dim, {})
        label = _DIMENSION_LABELS.get(dim, dim)
        score = entry.get("score", 0)
        max_score = entry.get("max", _DIMENSION_MAX)
        notes = entry.get("notes", "")
        lines.append(f"| {label} | {score}/{max_score} | {notes} |")

    lines.append("")
    lines.append(f"**Suggestions:** {suggestions}")

    return "\n".join(lines)
