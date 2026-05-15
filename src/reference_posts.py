"""Reference post intelligence pipeline.

Workflow:
  1. User drops LinkedIn screenshots into `reference_posts/<event_slug>/raw/`
  2. This module extracts structured JSON from each screenshot via a multimodal
     model (default: gpt-4o-mini) → writes to `reference_posts/<event>/extracted/`
  3. Aggregates extracted JSON into a pattern report via Claude Sonnet
     → writes `reference_posts/<event>/analysis/pattern_report.md`
  4. Pattern report's `## Durable lessons for the playbook` section is appended
     to `playbook/patterns.md` for future generation context.

This is the v2 reference-post intelligence module (PRD v6 §9).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import writing_client

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
REFERENCE_POSTS_DIR = REPO_ROOT / "reference_posts"
PROMPT_EXTRACT_PATH = REPO_ROOT / "prompts" / "extract_screenshot.md"
PROMPT_ANALYZE_PATH = REPO_ROOT / "prompts" / "analyze_reference_posts.md"
PLAYBOOK_PATTERNS_PATH = REPO_ROOT / "playbook" / "patterns.md"

SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}

DEFAULT_MULTIMODAL_MODEL = "gpt-4o-mini"


# ---------------------------------------------------------------------------
# Event folder helpers
# ---------------------------------------------------------------------------


@dataclass
class EventPaths:
    slug: str
    root: Path
    raw: Path
    extracted: Path
    analysis: Path

    @classmethod
    def for_slug(cls, slug: str) -> "EventPaths":
        root = REFERENCE_POSTS_DIR / slug
        return cls(
            slug=slug,
            root=root,
            raw=root / "raw",
            extracted=root / "extracted",
            analysis=root / "analysis",
        )

    def ensure(self) -> None:
        for d in (self.raw, self.extracted, self.analysis):
            d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Screenshot extraction
# ---------------------------------------------------------------------------


def _load_prompt(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Prompt file missing: {path}")
    return path.read_text(encoding="utf-8")


def _extraction_user_prompt() -> str:
    """The user-facing portion of the extraction prompt — everything after the leading marker.

    The file has a leading description and a `---` separator; we send only the part after
    the separator to keep prompts terse.
    """
    text = _load_prompt(PROMPT_EXTRACT_PATH)
    parts = text.split("---", maxsplit=1)
    return parts[1].strip() if len(parts) == 2 else text.strip()


def _encode_image(path: Path) -> tuple[str, str]:
    """Return (mime_type, base64_data) for a local image file."""
    suffix = path.suffix.lower()
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(suffix, "image/png")
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return mime, data


def _strip_json_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text


def _parse_extraction(raw: str) -> dict:
    raw = _strip_json_fence(raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def extract_one_screenshot(
    image_path: Path,
    *,
    openai_client=None,
    model: str = DEFAULT_MULTIMODAL_MODEL,
) -> dict:
    """Call the multimodal model on a single screenshot and return parsed JSON."""
    if openai_client is None:
        try:
            from openai import OpenAI  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError("openai package not installed") from exc
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY not set — cannot extract screenshots")
        openai_client = OpenAI()

    mime, data = _encode_image(image_path)
    user_text = _extraction_user_prompt()

    response = openai_client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{data}"},
                    },
                ],
            }
        ],
        temperature=0.1,
        max_completion_tokens=1500,
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content or "{}"
    parsed = _parse_extraction(raw)
    parsed.setdefault("source_file", image_path.name)
    parsed.setdefault("extracted_at", datetime.now(timezone.utc).isoformat())
    return parsed


def extract_event(
    slug: str,
    *,
    openai_client=None,
    model: str = DEFAULT_MULTIMODAL_MODEL,
    overwrite: bool = False,
) -> list[Path]:
    """Extract JSON for every screenshot in `reference_posts/<slug>/raw/`.

    Skips images that already have an extracted JSON unless `overwrite=True`.
    Returns the list of written JSON paths.
    """
    paths = EventPaths.for_slug(slug)
    paths.ensure()

    written: list[Path] = []
    for image in sorted(paths.raw.iterdir()):
        if image.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
            continue
        out_path = paths.extracted / f"{image.stem}.json"
        if out_path.exists() and not overwrite:
            logger.info("Skipping %s — extraction already exists", image.name)
            continue
        try:
            extracted = extract_one_screenshot(image, openai_client=openai_client, model=model)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to extract %s: %s", image.name, exc)
            continue
        out_path.write_text(json.dumps(extracted, indent=2), encoding="utf-8")
        written.append(out_path)
    return written


# ---------------------------------------------------------------------------
# Pattern analysis
# ---------------------------------------------------------------------------


def load_extracted(slug: str) -> list[dict]:
    """Return all extracted JSON objects for an event slug."""
    paths = EventPaths.for_slug(slug)
    if not paths.extracted.exists():
        return []
    result: list[dict] = []
    for json_path in sorted(paths.extracted.glob("*.json")):
        try:
            result.append(json.loads(json_path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not load %s: %s", json_path, exc)
    return result


def _split_analysis_prompt() -> tuple[str, str]:
    """Split the analyze prompt file into (system, user)."""
    text = _load_prompt(PROMPT_ANALYZE_PATH)
    system_match = re.search(r"^##\s+SYSTEM\s*$", text, re.MULTILINE)
    user_match = re.search(r"^##\s+USER\s*$", text, re.MULTILINE)
    if not system_match or not user_match:
        raise ValueError("analyze_reference_posts.md must have ## SYSTEM and ## USER")
    system = text[system_match.end():user_match.start()].strip()
    user = text[user_match.end():].strip()
    return system, user


def analyze_event(
    slug: str,
    *,
    writing_cli=None,
) -> Path:
    """Aggregate extracted posts into a pattern report. Returns the report path."""
    extracted = load_extracted(slug)
    if not extracted:
        raise RuntimeError(
            f"No extracted posts in reference_posts/{slug}/extracted/ — run extraction first."
        )

    posts_json = json.dumps(extracted, indent=2)
    system_prompt, user_template = _split_analysis_prompt()
    user_prompt = user_template.format(posts_json=posts_json)

    if writing_cli is None:
        writing_cli = writing_client.get_client()
    if writing_cli is None:
        raise RuntimeError("OpenAI writing client unavailable. Set OPENAI_API_KEY.")

    report = writing_client.generate_text(
        writing_cli, system_prompt, user_prompt, max_tokens=2500
    )

    paths = EventPaths.for_slug(slug)
    paths.ensure()
    report_path = paths.analysis / "pattern_report.md"
    report_path.write_text(report, encoding="utf-8")

    _append_durable_lessons_to_playbook(slug, report)

    return report_path


def _append_durable_lessons_to_playbook(slug: str, report: str) -> None:
    """Append the 'Durable lessons' section of a report to playbook/patterns.md.

    No-op if the section is missing or the playbook file isn't present.
    """
    if not PLAYBOOK_PATTERNS_PATH.exists():
        return
    match = re.search(
        r"##\s+Durable lessons for the playbook\s*\n(?P<body>.*?)(?=^##\s|\Z)",
        report,
        re.MULTILINE | re.DOTALL,
    )
    if not match:
        return
    lessons = match.group("body").strip()
    if not lessons:
        return

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    addition = textwrap_dedent(f"""

        ### Harvested from `{slug}` ({today})

        {lessons}
        """)
    with PLAYBOOK_PATTERNS_PATH.open("a", encoding="utf-8") as f:
        f.write(addition)


def textwrap_dedent(text: str) -> str:
    """Local dedent to avoid importing textwrap just for one call."""
    lines = text.splitlines()
    # Compute the common leading-whitespace ignoring empty lines.
    stripped = [l for l in lines if l.strip()]
    if not stripped:
        return text
    indent = min(len(l) - len(l.lstrip()) for l in stripped)
    return "\n".join(l[indent:] if len(l) >= indent else l for l in lines)


# ---------------------------------------------------------------------------
# Top-level entry points (for CLI / workflow)
# ---------------------------------------------------------------------------


def run_full_pipeline(
    slug: str,
    *,
    openai_client=None,
    writing_cli=None,
    multimodal_model: str = DEFAULT_MULTIMODAL_MODEL,
) -> dict:
    """Extract → analyze for an event slug. Returns a summary dict.

    `openai_client` is used for the multimodal extraction tier.
    `writing_cli` is used for the writing tier (currently also OpenAI, gpt-5.4).
    """
    extracted_paths = extract_event(slug, openai_client=openai_client, model=multimodal_model)
    report_path = analyze_event(slug, writing_cli=writing_cli)
    return {
        "slug": slug,
        "extracted_count": len(extracted_paths),
        "report_path": str(report_path),
    }
