"""OpenAI writing-tier client used by idea_generator and reference_posts pattern analysis.

Keeps a single (system + user → text) call shape so callers stay small. The
model defaults to a high-tier writing model; cheaper tiers are used for
evaluation/utility in their own modules.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_WRITING_MODEL = "gpt-5.4"
DEFAULT_TEMPERATURE = 0.7


def get_client():
    """Return an OpenAI client, or None if the SDK / key is unavailable.

    Callers should treat None as "no writing-tier access — abort or fall back".
    """
    if not os.environ.get("OPENAI_API_KEY"):
        return None
    try:
        from openai import OpenAI  # noqa: PLC0415
    except ImportError:
        logger.warning("openai package not installed; writing-tier calls will fail")
        return None
    return OpenAI()


def resolve_writing_model() -> str:
    return os.environ.get("WRITING_MODEL", DEFAULT_WRITING_MODEL).strip() or DEFAULT_WRITING_MODEL


def generate_text(
    client,
    system: str,
    user: str,
    *,
    model: Optional[str] = None,
    max_tokens: Optional[int] = None,
    temperature: float = DEFAULT_TEMPERATURE,
) -> str:
    """Call OpenAI chat completion and return the response text.

    By default no output cap is sent — callers that need one can pass `max_tokens`
    explicitly. Raises any underlying SDK exception — callers decide whether to
    retry or fall back.
    """
    chosen_model = model or resolve_writing_model()
    kwargs = {
        "model": chosen_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
    }
    if max_tokens is not None:
        kwargs["max_completion_tokens"] = max_tokens
    response = client.chat.completions.create(**kwargs)
    return (response.choices[0].message.content or "").strip()
