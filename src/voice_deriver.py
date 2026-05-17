"""Data-derived voice guide for the v2 model.

Replaces the previously hand-written ``playbook/voice.md`` with a synthesis
from real proof sources:

* top-performing external LinkedIn posts from ``screenshot_learning.json``
* curated own-voice exemplars from ``good-social-posts/*.md``

A single LLM call (``prompts/derive_voice.md``) produces a fresh
``playbook/voice.md``. Git history is the voice history.

Designed to mirror the patterns of ``src/retrospective.py`` and reuse
shared utilities — see ``run_refresh`` for the orchestration shape that
matches ``retrospective.run_refresh``.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import writing_client
from .post_generator import _load_good_posts_examples
from .screenshot_learning import (
    DEFAULT_SCREENSHOT_STATE_PATH,
    ScreenshotExample,
    ScreenshotLearningState,
)

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPT_PATH = REPO_ROOT / "prompts" / "derive_voice.md"
PLAYBOOK_VOICE_PATH = REPO_ROOT / "playbook" / "voice.md"

DEFAULT_TOP_REFERENCE_N = 5


# ---------------------------------------------------------------------------
# Source gathering
# ---------------------------------------------------------------------------


@dataclass
class VoiceSources:
    top_reference_examples: list[ScreenshotExample] = field(default_factory=list)
    good_examples: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.top_reference_examples and not self.good_examples

    def source_counts(self) -> str:
        return (
            f"{len(self.top_reference_examples)} top reference posts, "
            f"{len(self.good_examples)} curated examples"
        )


def gather_voice_sources(
    *,
    screenshot_state_path: str = DEFAULT_SCREENSHOT_STATE_PATH,
    top_n: int = DEFAULT_TOP_REFERENCE_N,
) -> VoiceSources:
    """Pull top-performing reference posts + curated own-voice examples."""
    state = ScreenshotLearningState.load(screenshot_state_path)
    tops = sorted(
        (e for e in state.examples if e.classification == "top_10_percent"),
        key=lambda e: e.engagement_score,
        reverse=True,
    )[:top_n]
    good = _load_good_posts_examples()
    return VoiceSources(top_reference_examples=tops, good_examples=good)


def _top_reference_block(examples: list[ScreenshotExample]) -> str:
    if not examples:
        return "(none)"
    payload = [
        {
            "identifier": f"ref #{e.issue_number}",
            "hook_excerpt": e.hook_excerpt,
            "summary": e.summary,
            "engagement_score": round(float(e.engagement_score), 2),
            "metrics": e.metrics,
            "signals": e.signals,
        }
        for e in examples
    ]
    return json.dumps(payload, indent=2)


def _good_examples_block(examples: list[str]) -> str:
    if not examples:
        return "(none)"
    # Separate examples with a visible divider for the model.
    return "\n\n---\n\n".join(examples)


# ---------------------------------------------------------------------------
# Prompt assembly + LLM call
# ---------------------------------------------------------------------------


def _split_prompt(template: str) -> tuple[str, str]:
    system = re.search(r"^##\s+SYSTEM\s*$", template, re.MULTILINE)
    user = re.search(r"^##\s+USER\s*$", template, re.MULTILINE)
    if not system or not user:
        raise ValueError("prompts/derive_voice.md must contain ## SYSTEM and ## USER")
    return template[system.end():user.start()].strip(), template[user.end():].strip()


def build_voice_prompts(sources: VoiceSources, *, now: Optional[datetime] = None) -> tuple[str, str]:
    if not PROMPT_PATH.exists():
        raise FileNotFoundError(f"Prompt template missing: {PROMPT_PATH}")
    template = PROMPT_PATH.read_text(encoding="utf-8")
    system_template, user_template = _split_prompt(template)

    now = now or datetime.now(timezone.utc)
    generated_at = now.strftime("%Y-%m-%d")
    user_prompt = user_template.format(
        generated_at=generated_at,
        source_counts=sources.source_counts(),
        top_reference_block=_top_reference_block(sources.top_reference_examples),
        good_examples_block=_good_examples_block(sources.good_examples),
    )
    return system_template, user_prompt


def derive_voice(
    sources: VoiceSources,
    *,
    client=None,
    now: Optional[datetime] = None,
) -> str:
    """Return synthesized voice Markdown. Skips the LLM call if sources are empty."""
    if sources.is_empty():
        return _empty_voice_markdown(now)

    if client is None:
        client = writing_client.get_client()
    if client is None:
        raise RuntimeError(
            "OpenAI writing client unavailable. Set OPENAI_API_KEY and install openai."
        )

    system_prompt, user_prompt = build_voice_prompts(sources, now=now)
    markdown = writing_client.generate_text(client, system_prompt, user_prompt)
    return markdown.strip() + "\n"


def _empty_voice_markdown(now: Optional[datetime]) -> str:
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    return (
        f"# Voice Guide — synthesized {stamp}\n\n"
        "_No source data available yet — populate `good-social-posts/` and/or "
        "upload reference screenshots via the social-screenshot Issue template, "
        "then re-run `python -m src.agent derive-voice`._\n\n"
        f"_Synthesized from 0 top reference posts, 0 curated examples on {stamp}._\n"
    )


# ---------------------------------------------------------------------------
# Writing artifact
# ---------------------------------------------------------------------------


def write_voice(markdown: str, *, target_path: Path = PLAYBOOK_VOICE_PATH) -> Path:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(markdown, encoding="utf-8")
    logger.info("Wrote voice guide: %s", target_path)
    return target_path


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_refresh(
    *,
    client=None,
    dry_run: bool = False,
    target_path: Path = PLAYBOOK_VOICE_PATH,
) -> str:
    """Gather → derive → write. Returns the markdown string."""
    sources = gather_voice_sources()
    markdown = derive_voice(sources, client=client)
    if not dry_run:
        write_voice(markdown, target_path=target_path)
    return markdown
