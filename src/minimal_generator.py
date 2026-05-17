"""Minimal-prompt generator (experiment).

Companion to ``idea_generator`` that strips the v2 "Do this / Avoid this"
distilled rules and instead injects:
  • the user's data-derived voice (playbook/voice.md)
  • curated own-voice examples (good-social-posts/*.md)
  • raw text of the top + bottom reference posts (no rule distillation)
  • explicit per-variant image-handling output

Outputs to ``drafts/<date>_<slug>/minimal/`` to enable side-by-side
comparison with the production pipeline. Does NOT post comments to
the Issue — it's a quiet experiment.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import writing_client
from .idea_generator import (
    DRAFTS_DIR,
    IdeaIssue,
    _extract_json,
    _prepare_image_payload,
    _slugify,
    draft_dir_for,
    fetch_issue,
)
from .post_generator import _load_good_posts_examples, score_linkedin_post_quality
from .screenshot_learning import (
    DEFAULT_SCREENSHOT_STATE_PATH,
    ScreenshotExample,
    ScreenshotLearningState,
)

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPT_PATH = REPO_ROOT / "prompts" / "generate_post_minimal.md"
VOICE_PATH = REPO_ROOT / "playbook" / "voice.md"

DEFAULT_VARIANT_CAP = 5
DEFAULT_TOP_REFERENCE_N = 5
DEFAULT_BOTTOM_REFERENCE_N = 5


# ---------------------------------------------------------------------------
# Reference-cohort assembly (raw text — not distilled rules)
# ---------------------------------------------------------------------------


def _reference_payload(example: ScreenshotExample) -> dict:
    return {
        "identifier": f"ref #{example.issue_number}",
        "engagement_score": round(float(example.engagement_score), 2),
        "metrics": example.metrics,
        "hook_excerpt": example.hook_excerpt,
        "summary": example.summary,
        "signals": example.signals,
    }


def gather_raw_references(
    *,
    state_path: str = DEFAULT_SCREENSHOT_STATE_PATH,
    top_n: int = DEFAULT_TOP_REFERENCE_N,
    bottom_n: int = DEFAULT_BOTTOM_REFERENCE_N,
) -> tuple[str, str]:
    """Return (top_block, bottom_block) as JSON strings of raw reference data."""
    state = ScreenshotLearningState.load(state_path)
    if not state.examples:
        return "(no reference cohort yet)", "(no reference cohort yet)"

    sorted_examples = sorted(state.examples, key=lambda e: e.engagement_score, reverse=True)
    top = [e for e in sorted_examples if e.classification == "top_10_percent"][:top_n]
    bottom = [e for e in reversed(sorted_examples) if e.classification != "top_10_percent"][:bottom_n]

    top_block = json.dumps([_reference_payload(e) for e in top], indent=2) if top else "(no top performers yet)"
    bottom_block = json.dumps([_reference_payload(e) for e in bottom], indent=2) if bottom else "(no bottom performers yet)"
    return top_block, bottom_block


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------


def _split_prompt(template: str) -> tuple[str, str]:
    system = re.search(r"^##\s+SYSTEM\s*$", template, re.MULTILINE)
    user = re.search(r"^##\s+USER\s*$", template, re.MULTILINE)
    if not system or not user:
        raise ValueError("prompts/generate_post_minimal.md must contain ## SYSTEM and ## USER")
    return template[system.end():user.start()].strip(), template[user.end():].strip()


def _good_examples_block_text() -> str:
    examples = _load_good_posts_examples()
    if not examples:
        return "(no curated examples loaded)"
    return "\n\n---\n\n".join(examples)


def build_prompts(
    idea: IdeaIssue,
    *,
    variant_count: int = DEFAULT_VARIANT_CAP,
    per_issue_reference_block: str = "",
) -> tuple[str, str]:
    if not PROMPT_PATH.exists():
        raise FileNotFoundError(f"Prompt template missing: {PROMPT_PATH}")
    template = PROMPT_PATH.read_text(encoding="utf-8")
    system_template, user_template = _split_prompt(template)

    voice = VOICE_PATH.read_text(encoding="utf-8").strip() if VOICE_PATH.exists() else "(no voice guide loaded)"
    examples = _good_examples_block_text()
    top_block, bottom_block = gather_raw_references()

    per_issue_text = per_issue_reference_block.strip() if per_issue_reference_block else (
        "(no reference screenshots uploaded to this Issue — use the raw reference cohort below)"
    )

    system_prompt = system_template.format(
        voice_block=voice,
        good_examples_block=examples,
        per_issue_reference_block=per_issue_text,
    )

    entity_list = (
        "\n".join(f"- {e}" for e in idea.entity_candidates)
        if idea.entity_candidates
        else "(no obvious named entities found — work from whatever specifics are in the Raw idea)"
    )

    user_prompt = user_template.format(
        issue_title=idea.title or "(no title)",
        raw_idea=idea.raw_idea or "(no raw idea provided)",
        raw_idea_entities=entity_list,
        audience=idea.audience or "Default ICP — AI engineers, distributed systems, Temporal users",
        goal=idea.goal or "Authority / credibility",
        angle=idea.angle or "No preference",
        references=idea.references or "(none provided)",
        image_count=len(idea.image_urls),
        variant_count=variant_count,
        reference_top_block=top_block,
        reference_bottom_block=bottom_block,
    )
    return system_prompt, user_prompt


# ---------------------------------------------------------------------------
# Generation + output
# ---------------------------------------------------------------------------


@dataclass
class MinimalResult:
    target_dir: Path
    variant_paths: list[Path]
    raw_response: dict


def generate(
    idea: IdeaIssue,
    *,
    client=None,
    variant_count: int = DEFAULT_VARIANT_CAP,
    per_issue_reference_block: str = "",
) -> dict:
    if client is None:
        client = writing_client.get_client()
    if client is None:
        raise RuntimeError("OpenAI writing client unavailable. Set OPENAI_API_KEY.")

    system_prompt, user_prompt = build_prompts(
        idea,
        variant_count=variant_count,
        per_issue_reference_block=per_issue_reference_block,
    )
    image_payload = _prepare_image_payload(idea.image_urls)
    raw = writing_client.generate_text(
        client, system_prompt, user_prompt, image_urls=image_payload
    )
    return _extract_json(raw)


def _format_variant_md(key: str, variant: dict) -> str:
    images = variant.get("images") or []
    image_lines = []
    for i, img in enumerate(images, 1):
        image_lines.append(
            f"- **Image {i}** "
            f"(placement: {img.get('placement', 'none')})\n"
            f"  - desc: {img.get('description', '')}\n"
            f"  - caption: {img.get('caption', '')}\n"
            f"  - alt: {img.get('alt_text', '')}"
        )
    images_section = "\n".join(image_lines) if image_lines else "_no images recommended for this variant_"

    return (
        f"# {key} — {variant.get('angle', 'unspecified angle')}\n\n"
        f"**Intended audience:** {variant.get('intended_audience', '')}\n"
        f"**Why it may perform:** {variant.get('why_it_may_perform', '')}\n"
        f"**Risks:** {variant.get('risks', '')}\n"
        f"**vs reference cohort:** {variant.get('what_this_brings_vs_references', '')}\n\n"
        f"## Recommended images\n\n{images_section}\n\n"
        f"---\n\n"
        f"{(variant.get('post') or '').strip()}\n"
    )


def write_outputs(idea: IdeaIssue, response: dict, parent_dir: Path) -> MinimalResult:
    target_dir = parent_dir / "minimal"
    target_dir.mkdir(parents=True, exist_ok=True)
    for stale in target_dir.glob("variant_*.md"):
        stale.unlink()

    paths: list[Path] = []
    scores: dict[str, dict] = {}
    for key in sorted(response.keys()):
        if not key.startswith("variant_"):
            continue
        variant = response[key]
        path = target_dir / f"{key}.md"
        path.write_text(_format_variant_md(key, variant), encoding="utf-8")
        paths.append(path)

        post_text = variant.get("post") or ""
        quality = score_linkedin_post_quality(post_text)
        scores[key] = {
            "angle": variant.get("angle", ""),
            "rubric_total": quality.total,
            "rubric_breakdown": quality.breakdown,
            "rubric_issues": quality.issues,
        }

    (target_dir / "scores.json").write_text(json.dumps(scores, indent=2), encoding="utf-8")
    (target_dir / "response.json").write_text(json.dumps(response, indent=2), encoding="utf-8")
    meta = {
        "issue_number": idea.number,
        "title": idea.title,
        "emotional_core": response.get("emotional_core", ""),
        "topic_classification": response.get("topic_classification", ""),
        "reference_observations": response.get("reference_observations", ""),
        "variant_count": len(paths),
    }
    (target_dir / "metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return MinimalResult(target_dir=target_dir, variant_paths=paths, raw_response=response)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run(
    repo: str,
    token: str,
    issue_number: int,
    *,
    client=None,
    variant_count: int = DEFAULT_VARIANT_CAP,
) -> MinimalResult:
    """End-to-end: fetch → analyze references → generate → write. No Issue comments."""
    from . import issue_reference_analyzer  # noqa: PLC0415

    idea = fetch_issue(repo, token, issue_number)

    per_issue_block = ""
    per_issue_report = None
    if idea.reference_image_urls:
        try:
            per_issue_report = issue_reference_analyzer.analyze(idea, client=client)
            if per_issue_report:
                per_issue_block = issue_reference_analyzer.cohort_summary_for_prompt(
                    per_issue_report
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Per-Issue reference analysis failed: %s", exc)

    response = generate(
        idea,
        client=client,
        variant_count=variant_count,
        per_issue_reference_block=per_issue_block,
    )
    parent_dir = draft_dir_for(idea)
    result = write_outputs(idea, response, parent_dir)
    if per_issue_report:
        issue_reference_analyzer.write_to_drafts_dir(per_issue_report, result.target_dir)
    return result
