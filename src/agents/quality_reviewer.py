"""Post-generation agent that performs semantic quality review of LinkedIn posts.

Scores generated posts on five dimensions that the existing regex-based
quality gate cannot evaluate: specificity, insight depth, hook strength,
code relevance, and shareability.  Returns a structured score breakdown
and can format the result as a GitHub issue comment in markdown.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

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

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_GOOD_POSTS_DIR = _REPO_ROOT / "good-social-posts"


@lru_cache(maxsize=1)
def _calibration_anchors() -> str:
    """Build a calibration block with ground-truth examples.

    Anchors the LLM scorer so it doesn't drift toward the middle of the range.
    Uses 2 of the 5 verified high-performers as 18-20 anchors. Rejected/weak
    examples are described abstractly to avoid leaking real bad drafts.
    """
    anchors: list[str] = []
    if _GOOD_POSTS_DIR.exists():
        for md in sorted(_GOOD_POSTS_DIR.glob("*.md"))[:2]:
            try:
                content = md.read_text(encoding="utf-8")
            except OSError:
                continue
            # Extract the body under '## Final LinkedIn Post'.
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
            body = "\n".join(lines).strip()
            if body:
                anchors.append(body[:1200])

    if not anchors:
        return ""

    examples = "\n\n---\n\n".join(anchors)
    return (
        "\n\nCALIBRATION — these are verified 5/5 posts the user has published successfully. "
        "Any new post that matches their bar of specificity, code quality, and lesson clarity "
        "should score 18-20 on the corresponding dimension. Anything weaker scores lower.\n\n"
        f"{examples}\n\n"
        "A post that scores ≤5 on any dimension would: (a) open with a cliché like 'I'm excited to share', "
        "(b) include no code or only pseudocode, (c) state a generic lesson without a number or before/after, "
        "or (d) target an audience other than senior engineers / distributed systems / AI agents / Temporal."
    )


_SYSTEM_PROMPT_BASE = """\
You are a senior LinkedIn content strategist who reviews technical posts \
written for AI engineers building distributed systems.

Score the post on these five dimensions (0-20 each):

1. **Specificity** — Does it teach a concrete, actionable lesson vs. generic advice?
2. **Insight Depth** — Would an experienced engineer learn something new?
3. **Hook Strength** — Does the opening genuinely create curiosity (not just pattern-matching)?
4. **Code Relevance** — Does the code snippet illustrate the core lesson (not boilerplate)?
5. **Shareability** — Would someone repost this to look smart/helpful?

Use the FULL 0-20 range. Do NOT default to 10-15 when uncertain. Posts that match the
calibration anchors below should score 18-20. Posts that lack code, specific numbers,
or an ICP-aligned audience should score ≤5 on the relevant dimensions.

Return ONLY a JSON object with this exact schema (no markdown fences):
{
  "specificity": {"score": <int 0-20>, "notes": "<one sentence>"},
  "insight_depth": {"score": <int 0-20>, "notes": "<one sentence>"},
  "hook_strength": {"score": <int 0-20>, "notes": "<one sentence>"},
  "code_relevance": {"score": <int 0-20>, "notes": "<one sentence>"},
  "shareability": {"score": <int 0-20>, "notes": "<one sentence>"},
  "suggestions": "<one sentence of actionable improvement advice>"
}"""


def _system_prompt() -> str:
    return _SYSTEM_PROMPT_BASE + _calibration_anchors()


# Backwards-compat alias (keep existing imports working)
_SYSTEM_PROMPT = _SYSTEM_PROMPT_BASE

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
                {"role": "system", "content": _system_prompt()},
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
