"""Pre-generation agent that prevents repetitive social posts.

Analyzes recent posts and candidate commits to recommend hook patterns
and skip decisions, enforcing variety and ICP relevance.

ICP: AI engineers building distributed systems with and without Temporal.
"""

from __future__ import annotations

import json
import logging
from collections import Counter

logger = logging.getLogger(__name__)

HOOK_PATTERNS = [
    "contrarian",
    "number",
    "story",
    "question",
    "result",
    "confession",
    "revelation",
]

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
]

# Variety thresholds applied to the last 10 posts
_MAX_SAME_HOOK = 2
_MAX_SAME_TAG = 3
_RECENT_WINDOW = 10

_SYSTEM_PROMPT = """\
You are a social-media variety guardian for a technical thought-leader whose \
ICP is AI engineers building distributed systems with and without Temporal.

Given a commit (message + tags) and recent post history, return JSON:
{
  "hook_pattern": "<one of: contrarian, number, story, question, result, confession, revelation>",
  "skip": <true|false>,
  "reason": "<short explanation>"
}

Rules:
- skip = true when the commit has nothing to do with AI engineering, \
distributed systems, or Temporal.
- Choose a hook_pattern that differs from the most recently overused patterns.
- Be concise in your reason (one sentence).
Return ONLY the JSON object, no markdown fences."""


def _matches_icp(text: str) -> bool:
    """Return True if *text* contains at least one ICP keyword."""
    lower = text.lower()
    return any(kw in lower for kw in ICP_KEYWORDS)


def _overused_hooks(recent_posts: list[dict]) -> set[str]:
    """Return hook patterns that appear >= _MAX_SAME_HOOK in the window."""
    window = recent_posts[-_RECENT_WINDOW:]
    counts = Counter(
        hook_pattern
        for p in window
        for hook_pattern in [p.get("hook_pattern")]
        if hook_pattern
    )
    return {h for h, c in counts.items() if c >= _MAX_SAME_HOOK}


def _overused_tags(recent_posts: list[dict]) -> set[str]:
    """Return topic tags that appear >= _MAX_SAME_TAG in the window."""
    window = recent_posts[-_RECENT_WINDOW:]
    tag_counts: Counter[str] = Counter()
    for p in window:
        for t in p.get("tags", []):
            tag_counts[t] += 1
    return {t for t, c in tag_counts.items() if c >= _MAX_SAME_TAG}


def _pick_fallback_hook(overused: set[str]) -> str:
    """Pick the first non-overused hook, defaulting to 'result'."""
    for h in HOOK_PATTERNS:
        if h not in overused:
            return h
    return "result"


def _build_user_prompt(
    commit: dict,
    overused_hooks: set[str],
    overused_tags: set[str],
) -> str:
    """Build the per-commit user prompt for the LLM."""
    parts = [
        f"Commit SHA: {commit['sha']}",
        f"Commit message: {commit['message']}",
        f"Repo: {commit.get('repo', 'unknown')}",
        f"Tags: {', '.join(commit.get('tags', []))}",
        "",
        f"Overused hook patterns (avoid these): {', '.join(sorted(overused_hooks)) or 'none'}",
        f"Overused topic tags (avoid these): {', '.join(sorted(overused_tags)) or 'none'}",
    ]
    return "\n".join(parts)


def _default_recommendation(commit: dict, overused: set[str]) -> dict:
    """Fallback recommendation when the LLM call fails."""
    text = f"{commit.get('message', '')} {' '.join(commit.get('tags', []))}"
    skip = not _matches_icp(text)
    return {
        "sha": commit["sha"],
        "hook_pattern": _pick_fallback_hook(overused),
        "skip": skip,
        "reason": "default — LLM unavailable" if not skip else "topic outside ICP scope",
    }


def guard_variety(
    client,  # OpenAI client
    candidate_commits: list[dict],
    recent_posts: list[dict],
    model: str = "gpt-5.4-mini",
) -> list[dict]:
    """Analyse *candidate_commits* against *recent_posts* and return per-commit recommendations.

    Each recommendation contains:
        sha          – commit SHA
        hook_pattern – one of HOOK_PATTERNS
        skip         – True if the commit should be skipped
        reason       – short human-readable explanation

    Parameters
    ----------
    client:
        An already-initialised OpenAI client instance.
    candidate_commits:
        ``[{"sha": str, "message": str, "repo": str, "tags": list[str]}, ...]``
    recent_posts:
        ``[{"hook_pattern": str, "tags": list[str], "lesson": str}, ...]``
    model:
        OpenAI model to use for analysis.
    """
    overused_hooks = _overused_hooks(recent_posts)
    overused_tags = _overused_tags(recent_posts)

    if overused_hooks:
        logger.info("Overused hook patterns: %s", overused_hooks)
    if overused_tags:
        logger.info("Overused topic tags: %s", overused_tags)

    recommendations: list[dict] = []

    for commit in candidate_commits:
        # Fast-path: skip commits obviously outside ICP without burning tokens
        text = f"{commit.get('message', '')} {' '.join(commit.get('tags', []))}"
        if not _matches_icp(text):
            rec = {
                "sha": commit["sha"],
                "hook_pattern": _pick_fallback_hook(overused_hooks),
                "skip": True,
                "reason": "commit topic does not match ICP — no AI engineering, distributed systems, or Temporal relevance",
            }
            logger.debug("Skipping commit %s — outside ICP", commit["sha"])
            recommendations.append(rec)
            continue

        # Build prompt and call the LLM
        user_prompt = _build_user_prompt(commit, overused_hooks, overused_tags)

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                max_completion_tokens=256,
                temperature=0.4,
            )
            raw = response.choices[0].message.content.strip()
            data = json.loads(raw)

            hook = data.get("hook_pattern", "result")
            if hook not in HOOK_PATTERNS:
                logger.warning("LLM returned unknown hook '%s', falling back to 'result'", hook)
                hook = "result"

            rec = {
                "sha": commit["sha"],
                "hook_pattern": hook,
                "skip": bool(data.get("skip", False)),
                "reason": data.get("reason", ""),
            }
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning("Failed to parse LLM response for %s: %s", commit["sha"], exc)
            rec = _default_recommendation(commit, overused_hooks)
        except Exception as exc:  # noqa: BLE001
            logger.error("OpenAI API error for commit %s: %s", commit["sha"], exc)
            rec = _default_recommendation(commit, overused_hooks)

        recommendations.append(rec)

    logger.info(
        "Variety guardian processed %d commits: %d to post, %d to skip",
        len(recommendations),
        sum(1 for r in recommendations if not r["skip"]),
        sum(1 for r in recommendations if r["skip"]),
    )

    return recommendations
