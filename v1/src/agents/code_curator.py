"""Pre-generation agent that selects the most teachable code snippet from a commit diff."""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# Patterns that indicate sensitive content — strip these before sending to LLM.
_SENSITIVE_PATTERNS = re.compile(
    r"""
    (?:                             # API keys / secrets / tokens
        (?:api[_-]?key|secret|password|passwd|token|auth|credential|private[_-]?key)
        \s*[:=]\s*
        ["']?[A-Za-z0-9+/=_\-]{8,}["']?
    )
    |(?:                            # AWS-style keys
        (?:AKIA|ASIA)[A-Z0-9]{16}
    )
    |(?:                            # Bearer tokens
        Bearer\s+[A-Za-z0-9\-._~+/]+=*
    )
    |(?:                            # GitHub tokens
        gh[ps]_[A-Za-z0-9]{36,}
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)

MAX_DIFF_CHARS = 3000


# ------------------------------------------------------------------
# GitHub helper
# ------------------------------------------------------------------

def fetch_commit_diff(repo: str, sha: str, token: str) -> Optional[str]:
    """Fetch the raw diff for a commit via the GitHub JSON endpoint."""
    url = f"https://api.github.com/repos/{repo}/commits/{sha}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        if not resp.ok:
            logger.warning(
                "GitHub API returned %s for %s/%s: %s",
                resp.status_code, repo, sha[:8], resp.text[:200],
            )
            return None
        data = resp.json()
        patches: list[str] = []
        for f in data.get("files", []):
            patch = f.get("patch", "")
            if patch:
                patches.append(f"--- {f['filename']} ---\n{patch}")
        return "\n\n".join(patches) if patches else None
    except requests.RequestException as exc:
        logger.warning("Failed to fetch commit diff for %s/%s: %s", repo, sha[:8], exc)
        return None


# ------------------------------------------------------------------
# Sanitisation
# ------------------------------------------------------------------

def _sanitize_diff(diff: str) -> str:
    """Remove sensitive patterns and truncate to MAX_DIFF_CHARS."""
    cleaned = _SENSITIVE_PATTERNS.sub("<REDACTED>", diff)
    if len(cleaned) > MAX_DIFF_CHARS:
        cleaned = cleaned[:MAX_DIFF_CHARS] + "\n... (truncated)"
    return cleaned


# ------------------------------------------------------------------
# LLM selection
# ------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a developer-educator who picks the single most teachable code snippet \
from a commit diff for use in a LinkedIn post.

Rules:
- Pick ONE snippet of 5-15 lines of *added* or *modified* code (green lines in the diff).
- The snippet should illustrate a clear pattern, technique, or insight.
- Strip diff markers (+/-) from the snippet — return clean, runnable code.
- Identify the programming language.
- Write a short "why" sentence (max 30 words) explaining what makes the snippet interesting.

Respond with ONLY a JSON object (no markdown fences):
{
    "snippet": "<the code>",
    "language": "<language>",
    "why": "<one-sentence explanation>"
}

If no snippet is interesting enough, respond with exactly: null
"""


def curate_code_snippet(
    client,  # OpenAI client
    sha: str,
    repo: str,
    token: str,
    model: str = "gpt-5.4-mini",
) -> Optional[dict]:
    """Select the most teachable code snippet from a GitHub commit.

    Returns a dict with keys ``snippet``, ``language``, and ``why``,
    or ``None`` if no suitable snippet is found or on any failure.
    """
    # 1. Fetch the commit diff ------------------------------------------------
    raw_diff = fetch_commit_diff(repo, sha, token)
    if not raw_diff:
        logger.info("No diff content for %s/%s — skipping snippet curation.", repo, sha[:8])
        return None

    # 2. Sanitize & truncate ---------------------------------------------------
    safe_diff = _sanitize_diff(raw_diff)

    # 3. Ask the LLM to pick the best snippet ---------------------------------
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Here is the diff for commit {sha[:8]} in {repo}:\n\n"
                        f"{safe_diff}\n\n"
                        "Pick the most teachable snippet."
                    ),
                },
            ],
            max_completion_tokens=512,
            temperature=0.3,
        )
    except Exception as exc:
        logger.warning("OpenAI call failed during snippet curation: %s", exc)
        return None

    # 4. Parse the structured output ------------------------------------------
    content = (response.choices[0].message.content or "").strip()

    if content.lower() == "null" or not content:
        logger.info("LLM found no interesting snippet for %s/%s.", repo, sha[:8])
        return None

    # Strip possible markdown code fences the model might add anyway
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)

    try:
        result = json.loads(content)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse LLM snippet response as JSON: %s — raw: %s", exc, content[:300])
        return None

    # 5. Validate the result ---------------------------------------------------
    if not isinstance(result, dict):
        logger.warning("LLM returned non-dict for snippet curation: %s", type(result))
        return None

    snippet = result.get("snippet", "")
    language = result.get("language", "")
    why = result.get("why", "")

    if not snippet or not language:
        logger.warning("LLM snippet response missing required fields.")
        return None

    # Enforce 5-15 line range (soft: log but still return)
    line_count = len(snippet.strip().splitlines())
    if line_count < 5 or line_count > 15:
        logger.info(
            "Snippet has %d lines (outside 5-15 ideal range) — returning anyway.", line_count,
        )

    return {
        "snippet": snippet.strip(),
        "language": language.strip().lower(),
        "why": why.strip(),
    }
