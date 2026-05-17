"""Idea-driven LinkedIn draft generation.

Reads a GitHub Issue (created via the `content_idea` template), generates
5 LinkedIn draft variants with Claude Sonnet, scores them with the existing
scoring agents, and writes them to `drafts/YYYY_MM_DD_<slug>/`. Posts one
comment per variant back to the Issue so the user can react/comment per
draft, followed by a ranked summary.

This is the v2 entry point. The v1 commit-driven `post_generator` is preserved
for manual/dispatch use but no longer runs on schedule.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests

from . import github_storage, writing_client
from .post_generator import (
    _load_good_posts_examples,
    _load_screenshot_signal_guidance,
    score_linkedin_post_quality,
)
# NOTE: _load_external_social_lessons is intentionally NOT imported — it loaded
# v1-era Google Doc lessons from the commit-driven model. Severed at the
# 2026-05-17 v2 re-baseline (Issue #422). See archive/v1/README.md.

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


MAX_IMAGES_PER_ISSUE = 20
_IMG_TAG_RE = re.compile(r"""<img\b[^>]*\bsrc=["']([^"']+)["']""", re.IGNORECASE)
_MD_IMG_RE = re.compile(r"!\[[^\]]*\]\((https?://[^)\s]+)\)")

# Words to drop from raw-idea entity extraction — common sentence starters or
# words too generic to count as "named entities" for citation purposes.
_ENTITY_STOPWORDS = {
    "the", "a", "an", "i", "and", "or", "but", "we", "you", "they", "it",
    "this", "that", "these", "those", "is", "was", "are", "were", "be", "been",
    "to", "of", "in", "on", "at", "for", "from", "with", "by", "as", "if",
    "ai", "i'm", "i've", "we're", "they're", "it's", "that's", "there", "here",
    "huge",
}


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
    image_urls: list[str] = field(default_factory=list)
    entity_candidates: list[str] = field(default_factory=list)
    reference_image_urls: list[str] = field(default_factory=list)
    supporting_image_urls: list[str] = field(default_factory=list)


_TAIL_CONNECTOR_STOPWORDS = {
    "to", "of", "for", "with", "by", "on", "in", "at", "as", "from", "into",
    "and", "or", "but", "the", "a", "an", "is", "was", "are", "were", "be",
    "been", "i", "we", "you", "they", "it", "this", "that", "thanks",
}


def _extract_entity_candidates(raw_idea: str, *, limit: int = 15) -> list[str]:
    """Pull likely named entities (proper nouns + key phrases) from the Raw Idea.

    Heuristic — meant to surface the concrete details the post should anchor in,
    even when the Raw Idea is dictation-style or typo-heavy. Captures:
      • standalone capitalized words (Nexus, Mason, Melissa, Netflix, Temporal)
      • "Capital + lowercase noun" phrases when the lowercase tail looks like a
        real noun (Tiki room, Nexus workshop) — filtered against stopwords like
        "to", "and", "thanks"
    Drops trailing function words and limits to `limit` items.
    """
    if not raw_idea:
        return []

    candidates: list[str] = []
    seen: set[str] = set()

    def _add(item: str) -> None:
        item = item.strip().rstrip(".,;:!?")
        if not item or len(item) < 2:
            return
        key = item.lower()
        if key in seen or key in _ENTITY_STOPWORDS:
            return
        seen.add(key)
        candidates.append(item)

    # Strip first-word-of-sentence to avoid catching sentence starters like "I", "We", "We".
    sentences = re.split(r"(?<=[.!?])\s+", raw_idea)
    body = " ".join(
        re.sub(r"^[A-Z][a-zA-Z0-9']*\s+", "", s) for s in sentences
    )

    # 1) Standalone capitalized words (proper nouns) — single-word entities.
    for match in re.finditer(r"\b([A-Z][a-zA-Z0-9]+)\b", body):
        _add(match.group(1))

    # 2) Capital + lowercase phrases (e.g. "Tiki room", "Nexus workshop").
    for match in re.finditer(r"\b([A-Z][a-zA-Z0-9]+)\s+([a-z][a-zA-Z0-9]+)\b", body):
        head = match.group(1)
        tail = match.group(2).lower()
        if tail in _TAIL_CONNECTOR_STOPWORDS:
            continue
        _add(f"{head} {tail}")

    return candidates[:limit]


def _extract_image_urls(body: str, limit: int = MAX_IMAGES_PER_ISSUE) -> list[str]:
    """Pull image URLs from an Issue body (both <img src=...> and ![](url) forms).

    De-duplicates while preserving order. Caps at `limit` to bound multimodal cost.
    """
    if not body:
        return []
    urls: list[str] = []
    seen: set[str] = set()
    for match in list(_IMG_TAG_RE.finditer(body)) + list(_MD_IMG_RE.finditer(body)):
        url = match.group(1).strip()
        if not url or url in seen:
            continue
        seen.add(url)
        urls.append(url)
        if len(urls) >= limit:
            break
    return urls


_H3_SPLIT_RE = re.compile(r"<h3[^>]*>(.*?)</h3>(.*?)(?=<h3|\Z)", re.DOTALL | re.IGNORECASE)


def _extract_images_by_section(body_html: str) -> dict[str, list[str]]:
    """Split body_html by <h3> and return {section_heading_lower: [image_urls]}.

    GitHub renders `### Heading` as `<h3>Heading</h3>`. We use this to attribute
    each `<img src>` to the section it appears under, so callers can distinguish
    reference-post screenshots (under "References, notes, links") from event
    photos (under "Supporting notes").
    """
    if not body_html:
        return {}
    sections: dict[str, list[str]] = {}
    for match in _H3_SPLIT_RE.finditer(body_html):
        heading = re.sub(r"<[^>]+>", "", match.group(1)).strip().lower()
        if not heading:
            continue
        content = match.group(2) or ""
        urls: list[str] = []
        seen: set[str] = set()
        for img_match in _IMG_TAG_RE.finditer(content):
            url = img_match.group(1).strip()
            if url and url not in seen:
                seen.add(url)
                urls.append(url)
        sections[heading] = urls
    return sections


def _section_images(sections: dict[str, list[str]], *heading_prefixes: str) -> list[str]:
    """Return the image list for the first section whose lowercased heading starts with any of the given prefixes."""
    for heading, urls in sections.items():
        for prefix in heading_prefixes:
            if heading.startswith(prefix.lower()):
                return urls
    return []


def fetch_issue(repo: str, token: str, issue_number: int) -> IdeaIssue:
    """Fetch and parse an Issue created from the content_idea template.

    Requests `application/vnd.github.full+json` so the payload includes BOTH
    `body` (markdown — needed for parsing template sections) AND `body_html`
    (rendered — where GitHub rewrites user-attachment image URLs into
    JWT-signed `private-user-images.githubusercontent.com` URLs that can be
    downloaded by automation).

    Requesting `html+json` alone suppresses the markdown `body` field,
    which silently empties every section (raw_idea, audience, goal, etc.).
    That bug shipped from 2026-05-17 mid-day to ~14:50 UTC and caused the
    model to hallucinate content for #422 from title + photos only.
    """
    url = f"{GITHUB_API}/repos/{repo}/issues/{issue_number}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.full+json",
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
        image_urls=_extract_image_urls(payload.get("body_html") or body),
        entity_candidates=_extract_entity_candidates(_extract_section(body, "Raw idea") or body.strip()),
        reference_image_urls=_section_images(
            _extract_images_by_section(payload.get("body_html") or ""),
            "references",  # matches "References, notes, links (optional)"
        ),
        supporting_image_urls=_section_images(
            _extract_images_by_section(payload.get("body_html") or ""),
            "supporting notes",
        ),
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
    """Signals the model should treat as anti-patterns.

    v2 uses screenshot-learning signal only. The v1 external-lessons path
    (Google Doc) is intentionally severed — see archive/v1/README.md.
    """
    screenshot = _load_screenshot_signal_guidance()
    if not screenshot:
        return ""
    return "SCREENSHOT-LEARNED SIGNALS:\n\n" + screenshot


RETROSPECTIVE_PATH = REPO_ROOT / "playbook" / "retrospective.md"


def _load_retrospective_block() -> str:
    """Load the data-driven retrospective if it exists.

    Produced by `src/retrospective.py` from the user's own published-post
    analytics + uploaded reference-post signals. Refreshed on each
    analytics-update cycle. Falls back to empty string when the file
    isn't there yet (fresh repos / before the first refresh).
    """
    text = _load_text(RETROSPECTIVE_PATH).strip()
    if not text:
        return ""
    return (
        "COMPETITIVE LANDSCAPE — these are the reference posts you must outperform. "
        "The Raw Idea is the subject; the patterns below are the bar to clear, "
        "not a template to imitate. If a reference pattern doesn't serve the Raw Idea, "
        "drop it.\n\n" + text
    )


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


def build_prompts(
    idea: IdeaIssue,
    *,
    variant_count: int = DEFAULT_VARIANT_COUNT,
    per_issue_reference_block: str = "",
) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) for an idea, fully substituted.

    `per_issue_reference_block` (optional) is the Markdown produced by
    `issue_reference_analyzer` for the Issue's uploaded reference screenshots.
    When present, it takes precedence over the global retrospective.
    """
    template = _load_text(PROMPT_PATH)
    if not template:
        raise FileNotFoundError(f"Prompt template missing: {PROMPT_PATH}")

    system_template, user_template = _split_prompt_template(template)

    voice = _load_text(VOICE_PATH).strip()
    patterns = _load_text(PATTERNS_PATH).strip()
    retrospective = _load_retrospective_block()
    examples = _good_examples_block()
    rejection = _rejection_block()

    per_issue_block_text = (
        "PER-ISSUE REFERENCE ANALYSIS — distilled from the screenshots the user "
        "uploaded to THIS Issue. These directives are higher-priority than the "
        "global retrospective below; they reflect what the user's specific "
        "reference cohort did and where this post should differentiate.\n\n"
        + per_issue_reference_block
        if per_issue_reference_block.strip()
        else "(no per-Issue references uploaded — falling back to global retrospective only)"
    )

    system_prompt = system_template.format(
        voice_block=voice or "(no voice playbook loaded)",
        patterns_block=patterns or "(no patterns harvested yet)",
        per_issue_reference_block=per_issue_block_text,
        retrospective_block=retrospective or "(no retrospective yet — publish posts or upload screenshots so analytics-update can populate playbook/retrospective.md)",
        good_examples_block=examples or "(no verified examples loaded)",
        rejection_avoidance_block=rejection or "(no external lessons loaded)",
    )

    entity_list = (
        "\n".join(f"- {e}" for e in idea.entity_candidates)
        if idea.entity_candidates
        else "(no obvious named entities found — work from whatever specifics are in the Raw idea)"
    )

    user_prompt = user_template.format(
        variant_count=variant_count,
        issue_title=idea.title or "(no title)",
        raw_idea=idea.raw_idea or "(no raw idea provided)",
        audience=idea.audience or "Default ICP — AI engineers, distributed systems, Temporal users",
        goal=idea.goal or "Authority / credibility",
        angle=idea.angle or "No preference — generate all five",
        references=idea.references or "(none provided)",
        raw_idea_entities=entity_list,
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
    per_issue_reference_block: str = "",
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

    system_prompt, user_prompt = build_prompts(
        idea,
        variant_count=variant_count,
        per_issue_reference_block=per_issue_reference_block,
    )
    image_payload = _prepare_image_payload(idea.image_urls)
    raw = writing_client.generate_text(
        client,
        system_prompt,
        user_prompt,
        image_urls=image_payload,
    )
    return _extract_json(raw)


# ---------------------------------------------------------------------------
# Image payload prep (GitHub user-attachments need auth + resizing)
# ---------------------------------------------------------------------------


_IMAGE_MAX_EDGE = 768  # detail="low" only uses 512px tiles, 768 gives slight margin
_IMAGE_DOWNLOAD_TIMEOUT = 20


def _prepare_image_payload(urls: list[str]) -> list[str]:
    """Convert raw image URLs into a list of base64 data URLs.

    GitHub `user-attachments` URLs reject anonymous fetches from third-party
    services like OpenAI's image downloader (HTTP 400). We pull each image
    on the runner (with GITHUB_TOKEN if needed), resize, and inline it as
    `data:image/...;base64,...`. Failures are logged and skipped so the
    overall generation still runs.
    """
    if not urls:
        return []
    try:
        from PIL import Image  # noqa: PLC0415
    except ImportError:
        logger.warning("Pillow not available — skipping image attachments")
        return []

    gh_token = os.environ.get("GITHUB_TOKEN", "")
    data_urls: list[str] = []
    for url in urls:
        try:
            headers = {"User-Agent": "magic-social-bot/1.0"}
            host = urlparse(url).hostname or ""
            if gh_token and ("github.com" in host or "githubusercontent.com" in host):
                headers["Authorization"] = f"Bearer {gh_token}"
            resp = requests.get(url, headers=headers, timeout=_IMAGE_DOWNLOAD_TIMEOUT)
            resp.raise_for_status()
            img = Image.open(io.BytesIO(resp.content))
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img.thumbnail((_IMAGE_MAX_EDGE, _IMAGE_MAX_EDGE))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=80)
            b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            data_urls.append(f"data:image/jpeg;base64,{b64}")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Skipping image %s: %s", url, exc)
            continue
    logger.info("Prepared %d/%d images for multimodal call", len(data_urls), len(urls))
    return data_urls


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

    # Clean stale variant files so previous runs (which may have produced more
    # variants under different settings) don't pollute the current cohort.
    for stale in target_dir.glob("variant_*.md"):
        stale.unlink()

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
        "emotional_core": variants.get("emotional_core", ""),
        "topic_classification": variants.get("topic_classification", ""),
    }
    (target_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    source_snapshot = (
        f"# Source Issue snapshot — #{idea.number}\n\n"
        f"**Title:** {idea.title}\n"
        f"**URL:** {idea.url}\n\n"
        f"## Raw idea\n{idea.raw_idea}\n\n"
        f"## Audience\n{idea.audience}\n\n"
        f"## Goal\n{idea.goal}\n\n"
        f"## Angle\n{idea.angle}\n\n"
        f"## References\n{idea.references}\n\n"
        f"## Supporting notes\n{idea.supporting_notes}\n"
    )
    (target_dir / "source_issue.md").write_text(source_snapshot, encoding="utf-8")

    return paths


def _format_variant_md(key: str, variant: dict) -> str:
    from .linkedin_format import to_linkedin_format  # noqa: PLC0415

    post = (variant.get("post") or variant.get("body") or "").strip()
    return (
        f"# {key} — {variant.get('angle', 'unspecified angle')}\n\n"
        f"**Intended audience:** {variant.get('intended_audience', '')}\n"
        f"**Why it may perform:** {variant.get('why_it_may_perform', '')}\n"
        f"**Risks:** {variant.get('risks', '')}\n\n"
        f"## LinkedIn-ready post (copy below)\n\n"
        f"```\n{to_linkedin_format(post)}\n```\n"
    )


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


def build_variant_comment(key: str, variant: dict, score: dict) -> str:
    """Render one draft as a self-contained Issue comment for per-draft voting.

    The post body is run through `linkedin_format.to_linkedin_format` so any
    markdown the model emits is converted to LinkedIn-native equivalents
    (Unicode bold/italic, `•` bullets, no backticks). The body is wrapped in
    a fenced code block so the reader can copy it verbatim — what they see
    is what LinkedIn will see.
    """
    from .linkedin_format import to_linkedin_format  # noqa: PLC0415  (avoid cycle)

    angle = variant.get("angle") or "unspecified angle"
    post_text_raw = (variant.get("post") or variant.get("body") or "").strip()
    post_text = to_linkedin_format(post_text_raw)
    audience = variant.get("intended_audience", "")
    why = variant.get("why_it_may_perform", "")
    risks = variant.get("risks", "")
    brings = variant.get("what_this_brings_vs_references", "")
    rubric_total = score.get("rubric_total", 0)
    label = key.replace("_", " ").title()

    parts = [
        f"## {label} — {angle}",
        "",
        f"**Rubric:** {rubric_total:.1f}/100",
        "",
        "**📋 Copy below — already formatted for LinkedIn (paste straight into the composer):**",
        "",
        "```",
        post_text,
        "```",
        "",
        f"- **Audience:** {audience}",
        f"- **Why it may perform:** {why}",
        f"- **Risks:** {risks}",
    ]
    if brings:
        parts.append(f"- **vs reference cohort:** {brings}")
    parts.extend([
        "",
        "_React 👍 / 👎 to vote, or reply with edits. Highest-voted draft is the one to ship._",
        "",
    ])
    return "\n".join(parts)


def build_summary_comment(idea: IdeaIssue, target_dir: Path, scores: dict, paths: list[Path]) -> str:
    rel_dir = _rel_to_repo(target_dir)
    top = pick_top_variant(scores)
    top_line = (
        f"**Top by rubric:** `{top}` "
        f"({scores.get(top, {}).get('angle', '')}, {scores.get(top, {}).get('rubric_total', 0):.1f}/100)"
        if top
        else "(no variants generated)"
    )
    ranked = sorted(scores.items(), key=lambda kv: kv[1].get("rubric_total", 0), reverse=True)
    score_lines = "\n".join(
        f"- `{k}`: {v.get('rubric_total', 0):.1f}/100 — {v.get('angle', '')}"
        for k, v in ranked
    )

    # Surface the model's own classification of the Raw Idea (if metadata.json is present).
    emotional_line = ""
    topic_line = ""
    meta_path = target_dir / "metadata.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("emotional_core"):
                emotional_line = f"**Emotional core:** {meta['emotional_core']}\n\n"
            if meta.get("topic_classification"):
                topic_line = f"**Topic class:** {meta['topic_classification']}\n\n"
        except (OSError, json.JSONDecodeError):
            pass

    return (
        f"Generated {len(paths)} LinkedIn drafts — each posted as its own comment above so you can 👍 / 👎 per draft.\n\n"
        f"{emotional_line}"
        f"{topic_line}"
        f"{top_line}\n\n"
        f"**Ranked rubric:**\n"
        f"{score_lines}\n\n"
        f"Markdown copies of each draft also saved under `{rel_dir}/` for reference.\n"
    )


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
    """End-to-end: fetch Issue → analyze references → generate → write → comment."""
    from . import issue_reference_analyzer  # noqa: PLC0415  (avoid cycle)
    from . import retrospective as retrospective_mod  # noqa: PLC0415

    idea = fetch_issue(repo, token, issue_number)

    # Per-Issue reference analysis — if the user uploaded reference screenshots
    # under "References, notes, links", analyze them BEFORE generating so the
    # directives shape the draft prompt. Returns None when no refs are attached.
    per_issue_report = None
    per_issue_block = ""
    if idea.reference_image_urls:
        try:
            per_issue_report = issue_reference_analyzer.analyze(idea, client=client)
            if per_issue_report:
                per_issue_block = issue_reference_analyzer.cohort_summary_for_prompt(
                    per_issue_report
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Per-Issue reference analysis failed: %s", exc)

    variants = generate_variants(
        idea,
        client=client,
        variant_count=variant_count,
        per_issue_reference_block=per_issue_block,
    )
    target_dir = draft_dir_for(idea)
    paths = write_drafts(idea, variants, target_dir)
    scores = json.loads((target_dir / "scores.json").read_text(encoding="utf-8"))
    summary = build_summary_comment(idea, target_dir, scores, paths)

    # Persist the per-Issue analysis alongside the drafts.
    if per_issue_report:
        issue_reference_analyzer.write_to_drafts_dir(per_issue_report, target_dir)

    # Freeze the global retrospective that also informed these drafts.
    retrospective_md = ""
    if RETROSPECTIVE_PATH.exists():
        retrospective_mod.snapshot_for_issue(target_dir, retrospective_path=RETROSPECTIVE_PATH)
        retrospective_md = RETROSPECTIVE_PATH.read_text(encoding="utf-8")

    if post_comment:
        # Per-Issue analysis comment goes FIRST — it's the primary signal for this Issue.
        if per_issue_report:
            github_storage.add_comment(
                repo,
                token,
                issue_number,
                issue_reference_analyzer.build_issue_comment(per_issue_report),
            )
        if retrospective_md:
            github_storage.add_comment(
                repo,
                token,
                issue_number,
                retrospective_mod.build_issue_comment(retrospective_md),
            )
        for key in sorted(variants.keys()):
            if not key.startswith("variant_"):
                continue
            body = build_variant_comment(key, variants[key], scores.get(key, {}))
            github_storage.add_comment(repo, token, issue_number, body)
        github_storage.add_comment(repo, token, issue_number, summary)
        github_storage.add_label_to_issue(repo, token, issue_number, "drafts_generated")

    return GenerationResult(target_dir=target_dir, variant_paths=paths, scores=scores, summary=summary)
