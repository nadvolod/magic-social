"""Idea-driven LinkedIn draft generation.

Reads a GitHub Issue (created via the `content_idea` template), generates
5 LinkedIn draft variants with Claude Sonnet, scores them with the existing
scoring agents, and writes them to `drafts/YYYY_MM_DD_<slug>/`. Posts a
summary comment back to the Issue.

This is the v2 entry point. The v1 commit-driven `post_generator` is preserved
for manual/dispatch use but no longer runs on schedule.
"""

from __future__ import annotations

import json
import logging
import os
import re
import textwrap
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

from . import github_storage, writing_client
from .post_generator import (
    _load_external_social_lessons,
    _load_good_posts_examples,
    _load_screenshot_signal_guidance,
    score_linkedin_post_quality,
)

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPT_PATH = REPO_ROOT / "prompts" / "generate_post.md"
VOICE_PATH = REPO_ROOT / "playbook" / "voice.md"
PATTERNS_PATH = REPO_ROOT / "playbook" / "patterns.md"
DRAFTS_DIR = REPO_ROOT / "drafts"

DEFAULT_VARIANT_COUNT = 5
GITHUB_API = "https://api.github.com"


# ---------------------------------------------------------------------------
# Issue parsing
# ---------------------------------------------------------------------------


@dataclass
class IdeaIssue:
    number: int
    title: str
    raw_idea: str
    audience: str = ""
    goal: str = ""
    angle: str = ""
    references: str = ""
    supporting_notes: str = ""
    labels: list[str] = field(default_factory=list)
    url: str = ""


def fetch_issue(repo: str, token: str, issue_number: int) -> IdeaIssue:
    """Fetch and parse an Issue created from the content_idea template."""
    url = f"{GITHUB_API}/repos/{repo}/issues/{issue_number}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    return parse_issue_payload(payload)


def parse_issue_payload(payload: dict) -> IdeaIssue:
    """Convert a GitHub Issue payload into an IdeaIssue.

    Supports both the structured `content_idea.yml` template (### Section headings)
    and free-form markdown — we extract what we can and leave the rest blank.
    """
    body = payload.get("body") or ""
    labels = [l["name"] for l in payload.get("labels", []) if isinstance(l, dict)]
    return IdeaIssue(
        number=payload.get("number", 0),
        title=payload.get("title", "").strip(),
        raw_idea=_extract_section(body, "Raw idea") or body.strip(),
        audience=_extract_section(body, "Audience"),
        goal=_extract_section(body, "Primary goal") or _extract_section(body, "Goal"),
        angle=_extract_section(body, "Preferred angle") or _extract_section(body, "Angle"),
        references=_extract_section(body, "References, notes, links")
        or _extract_section(body, "References"),
        supporting_notes=_extract_section(body, "Supporting notes"),
        labels=labels,
        url=payload.get("html_url", ""),
    )


def _extract_section(body: str, heading: str) -> str:
    """Extract the text under a GitHub-form-rendered heading.

    GitHub issue forms render `id: x` fields as `### Label\n\nvalue\n\n### Next`.
    We match on heading text (case-insensitive, substring) and stop at the next `###`.
    """
    if not body:
        return ""
    pattern = re.compile(
        rf"^###\s+{re.escape(heading)}.*?\n(?P<value>.*?)(?=^###\s|\Z)",
        re.IGNORECASE | re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(body)
    if not match:
        return ""
    value = match.group("value").strip()
    # Strip the "_No response_" placeholder GitHub inserts for empty fields.
    if value.lower() == "_no response_":
        return ""
    return value


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------


def _load_text(path: Path) -> str:
    if not path.exists():
        logger.warning("Missing prompt asset: %s", path)
        return ""
    return path.read_text(encoding="utf-8")


def _good_examples_block() -> str:
    examples = _load_good_posts_examples()
    if not examples:
        return ""
    return (
        "VERIFIED HIGH-PERFORMING EXAMPLES — match this quality bar:\n\n"
        + "\n\n---\n\n".join(examples)
    )


def _rejection_block() -> str:
    lessons = _load_external_social_lessons()
    screenshot = _load_screenshot_signal_guidance()
    parts = []
    if lessons:
        parts.append("EXTERNAL LESSONS:\n\n" + lessons)
    if screenshot:
        parts.append("SCREENSHOT-LEARNED SIGNALS:\n\n" + screenshot)
    return "\n\n".join(parts)


def _split_prompt_template(template: str) -> tuple[str, str]:
    """Split prompts/generate_post.md into (system, user) sections.

    The file uses `## SYSTEM` and `## USER` markers. Everything before `## SYSTEM`
    is treated as documentation and discarded.
    """
    system_marker = re.search(r"^##\s+SYSTEM\s*$", template, re.MULTILINE)
    user_marker = re.search(r"^##\s+USER\s*$", template, re.MULTILINE)
    if not system_marker or not user_marker:
        raise ValueError("prompts/generate_post.md must contain ## SYSTEM and ## USER sections")
    system_text = template[system_marker.end():user_marker.start()].strip()
    user_text = template[user_marker.end():].strip()
    return system_text, user_text


def build_prompts(idea: IdeaIssue, *, variant_count: int = DEFAULT_VARIANT_COUNT) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) for an idea, fully substituted."""
    template = _load_text(PROMPT_PATH)
    if not template:
        raise FileNotFoundError(f"Prompt template missing: {PROMPT_PATH}")

    system_template, user_template = _split_prompt_template(template)

    voice = _load_text(VOICE_PATH).strip()
    patterns = _load_text(PATTERNS_PATH).strip()
    examples = _good_examples_block()
    rejection = _rejection_block()

    system_prompt = system_template.format(
        voice_block=voice or "(no voice playbook loaded)",
        patterns_block=patterns or "(no patterns harvested yet)",
        good_examples_block=examples or "(no verified examples loaded)",
        rejection_avoidance_block=rejection or "(no external lessons loaded)",
    )

    user_prompt = user_template.format(
        variant_count=variant_count,
        issue_title=idea.title or "(no title)",
        raw_idea=idea.raw_idea or "(no raw idea provided)",
        audience=idea.audience or "Default ICP — AI engineers, distributed systems, Temporal users",
        goal=idea.goal or "Authority / credibility",
        angle=idea.angle or "No preference — generate all five",
        references=idea.references or "(none provided)",
    )
    return system_prompt, user_prompt


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def _extract_json(text: str) -> dict:
    """Pull a JSON object out of a model response that may contain extra text."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def generate_variants(
    idea: IdeaIssue,
    *,
    client=None,
    variant_count: int = DEFAULT_VARIANT_COUNT,
) -> dict:
    """Return a dict of variant_N → variant_payload.

    If `client` is None, attempts to construct one. If unavailable, raises RuntimeError
    so callers know nothing was generated.
    """
    if client is None:
        client = writing_client.get_client()
    if client is None:
        raise RuntimeError(
            "OpenAI writing client unavailable. Set OPENAI_API_KEY and install openai."
        )

    system_prompt, user_prompt = build_prompts(idea, variant_count=variant_count)
    raw = writing_client.generate_text(client, system_prompt, user_prompt)
    return _extract_json(raw)


# ---------------------------------------------------------------------------
# Output / file writing
# ---------------------------------------------------------------------------


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str, max_len: int = 40) -> str:
    text = text.lower().strip().lstrip("[idea]").strip()
    text = text.replace("[idea]", "")
    slug = _SLUG_RE.sub("_", text).strip("_")
    return slug[:max_len] or "idea"


def draft_dir_for(idea: IdeaIssue, *, now: Optional[datetime] = None) -> Path:
    now = now or datetime.now(timezone.utc)
    return DRAFTS_DIR / f"{now:%Y_%m_%d}_{_slugify(idea.title)}"


def write_drafts(idea: IdeaIssue, variants: dict, target_dir: Path) -> list[Path]:
    """Write variant_N.md files, scores.json, metadata.json. Returns list of variant file paths."""
    target_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    scores: dict[str, dict] = {}

    for key in sorted(variants.keys()):
        if not key.startswith("variant_"):
            continue
        variant = variants[key]
        post_text = variant.get("post") or variant.get("body") or ""
        path = target_dir / f"{key}.md"
        path.write_text(_format_variant_md(key, variant), encoding="utf-8")
        paths.append(path)

        quality = score_linkedin_post_quality(post_text)
        scores[key] = {
            "angle": variant.get("angle", ""),
            "rubric_total": quality.total,
            "rubric_breakdown": quality.breakdown,
            "rubric_issues": quality.issues,
        }

    (target_dir / "scores.json").write_text(json.dumps(scores, indent=2), encoding="utf-8")

    metadata = {
        "source_issue": idea.url or f"#{idea.number}",
        "issue_number": idea.number,
        "title": idea.title,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "audience": idea.audience,
        "goal": idea.goal,
        "angle": idea.angle,
        "variant_count": len(paths),
    }
    (target_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    source_snapshot = textwrap.dedent(f"""\
        # Source Issue snapshot — #{idea.number}

        **Title:** {idea.title}
        **URL:** {idea.url}

        ## Raw idea
        {idea.raw_idea}

        ## Audience
        {idea.audience}

        ## Goal
        {idea.goal}

        ## Angle
        {idea.angle}

        ## References
        {idea.references}

        ## Supporting notes
        {idea.supporting_notes}
    """)
    (target_dir / "source_issue.md").write_text(source_snapshot, encoding="utf-8")

    return paths


def _format_variant_md(key: str, variant: dict) -> str:
    return textwrap.dedent(f"""\
        # {key} — {variant.get('angle', 'unspecified angle')}

        **Intended audience:** {variant.get('intended_audience', '')}
        **Why it may perform:** {variant.get('why_it_may_perform', '')}
        **Risks:** {variant.get('risks', '')}

        ---

        {variant.get('post') or variant.get('body') or ''}
    """)


def pick_top_variant(scores: dict) -> Optional[str]:
    """Return the variant key with the highest rubric score."""
    if not scores:
        return None
    ranked = sorted(scores.items(), key=lambda kv: kv[1].get("rubric_total", 0), reverse=True)
    return ranked[0][0]


def _rel_to_repo(path: Path) -> Path:
    """Path relative to repo root if possible, else the path itself."""
    try:
        return path.relative_to(REPO_ROOT)
    except ValueError:
        return path


def build_summary_comment(idea: IdeaIssue, target_dir: Path, scores: dict, paths: list[Path]) -> str:
    rel_dir = _rel_to_repo(target_dir)
    top = pick_top_variant(scores)
    top_line = (
        f"**Top recommendation:** `{top}` "
        f"(angle: {scores.get(top, {}).get('angle', '')}, rubric: {scores.get(top, {}).get('rubric_total', 0):.1f}/100)"
        if top
        else "(no variants generated)"
    )
    file_lines = "\n".join(f"- `{_rel_to_repo(p)}`" for p in paths)
    score_lines = "\n".join(
        f"- `{k}`: {v.get('rubric_total', 0):.1f}/100 — {v.get('angle', '')}"
        for k, v in scores.items()
    )
    return textwrap.dedent(f"""\
        Generated {len(paths)} LinkedIn draft variants from this idea.

        {top_line}

        **Files:**
        {file_lines}

        **Rubric scores:**
        {score_lines}

        **Recommended next step:**
        Review the top variant in `{rel_dir}/`. If you want to publish, paste the final text into LinkedIn and add an `## Analytics Update` comment here after 48h.
    """)


# ---------------------------------------------------------------------------
# Top-level run
# ---------------------------------------------------------------------------


@dataclass
class GenerationResult:
    target_dir: Path
    variant_paths: list[Path]
    scores: dict
    summary: str


def run(
    repo: str,
    token: str,
    issue_number: int,
    *,
    client=None,
    variant_count: int = DEFAULT_VARIANT_COUNT,
    post_comment: bool = True,
) -> GenerationResult:
    """End-to-end: fetch Issue → generate → write → comment."""
    idea = fetch_issue(repo, token, issue_number)
    variants = generate_variants(idea, client=client, variant_count=variant_count)
    target_dir = draft_dir_for(idea)
    paths = write_drafts(idea, variants, target_dir)
    scores = json.loads((target_dir / "scores.json").read_text(encoding="utf-8"))
    summary = build_summary_comment(idea, target_dir, scores, paths)

    if post_comment:
        github_storage.add_comment(repo, token, issue_number, summary)
        github_storage.add_label_to_issue(repo, token, issue_number, "drafts_generated")

    return GenerationResult(target_dir=target_dir, variant_paths=paths, scores=scores, summary=summary)
