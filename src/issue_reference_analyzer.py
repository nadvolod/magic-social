"""Per-Issue reference analyzer.

Takes the reference-post screenshots a user uploads under the "References,
notes, links" section of a content-idea Issue, runs a multimodal LLM call
that extracts each post + analyzes the cohort, and returns a Markdown
report that's injected into the draft-generation prompt.

This is the per-Issue analog of ``src/retrospective.py`` (which works from
the global ``screenshot_learning.json`` cohort). For Issues that include
their own reference uploads, the per-Issue analysis is HIGHER-fidelity
signal than the global retrospective and takes precedence.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import writing_client
from .idea_generator import _prepare_image_payload

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPT_PATH = REPO_ROOT / "prompts" / "analyze_issue_references.md"


@dataclass
class IssueReferenceReport:
    markdown: str
    reference_count: int
    target_dir: Optional[Path] = None
    entity_hints: list[str] = field(default_factory=list)


def _split_prompt(template: str) -> tuple[str, str]:
    system = re.search(r"^##\s+SYSTEM\s*$", template, re.MULTILINE)
    user = re.search(r"^##\s+USER\s*$", template, re.MULTILINE)
    if not system or not user:
        raise ValueError("prompts/analyze_issue_references.md must contain ## SYSTEM and ## USER")
    return template[system.end():user.start()].strip(), template[user.end():].strip()


def build_prompts(idea, *, reference_count: int) -> tuple[str, str]:
    if not PROMPT_PATH.exists():
        raise FileNotFoundError(f"Prompt template missing: {PROMPT_PATH}")
    template = PROMPT_PATH.read_text(encoding="utf-8")
    system_template, user_template = _split_prompt(template)

    entity_list = (
        "\n".join(f"- {e}" for e in idea.entity_candidates)
        if idea.entity_candidates
        else "(no entities extracted)"
    )

    user_prompt = user_template.format(
        issue_number=idea.number,
        issue_title=idea.title or "(no title)",
        raw_idea=idea.raw_idea or "(no raw idea provided)",
        raw_idea_entities=entity_list,
        reference_count=reference_count,
    )
    return system_template, user_prompt


def analyze(idea, *, client=None) -> Optional[IssueReferenceReport]:
    """Run the per-Issue reference analysis. Returns None when no refs are attached."""
    if not idea.reference_image_urls:
        return None

    if client is None:
        client = writing_client.get_client()
    if client is None:
        raise RuntimeError("OpenAI writing client unavailable. Set OPENAI_API_KEY.")

    image_payload = _prepare_image_payload(idea.reference_image_urls)
    if not image_payload:
        logger.warning(
            "Issue #%s has %d reference image URLs but none could be prepared as data URLs",
            idea.number,
            len(idea.reference_image_urls),
        )
        return None

    system_prompt, user_prompt = build_prompts(idea, reference_count=len(image_payload))
    markdown = writing_client.generate_text(
        client, system_prompt, user_prompt, image_urls=image_payload
    )
    return IssueReferenceReport(
        markdown=markdown.strip() + "\n",
        reference_count=len(image_payload),
    )


def write_to_drafts_dir(report: IssueReferenceReport, target_dir: Path) -> Path:
    """Save the per-Issue analysis alongside the drafts."""
    target_dir.mkdir(parents=True, exist_ok=True)
    out = target_dir / "issue_reference_analysis.md"
    out.write_text(report.markdown, encoding="utf-8")
    report.target_dir = target_dir
    return out


# ---------------------------------------------------------------------------
# Section extraction helpers (mirror retrospective.build_issue_comment)
# ---------------------------------------------------------------------------


_SECTION_RE_TEMPLATE = r"^##\s+{}\s*$.*?(?=^##\s|\Z)"


def _section(markdown: str, heading: str) -> str:
    pattern = re.compile(
        _SECTION_RE_TEMPLATE.format(re.escape(heading)),
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(markdown or "")
    return match.group(0).strip() if match else ""


def differentiation_block(report: IssueReferenceReport) -> str:
    """Pull the "How to differentiate" section — what gets injected into generation."""
    return _section(report.markdown, "How to differentiate — directives for the new post")


def cohort_summary_for_prompt(report: IssueReferenceReport) -> str:
    """Compact text block to inject into the generation prompt.

    Includes only the cohort-pattern + gap + differentiation sections — not
    the per-ref breakdowns (those are in the saved file for audit).
    """
    parts = []
    for heading in ("Cohort patterns", "Gaps in the cohort", "How to differentiate — directives for the new post"):
        section = _section(report.markdown, heading)
        if section:
            parts.append(section)
    return "\n\n".join(parts) if parts else ""


def build_issue_comment(report: IssueReferenceReport) -> str:
    """Format the analysis as an Issue comment that explains what shaped the drafts."""
    return (
        "### Per-Issue reference analysis\n\n"
        f"_Analyzed {report.reference_count} reference screenshots you uploaded to this Issue. "
        "This analysis shaped the drafts below — it's specific to YOUR references, "
        "not the global cohort. Full report saved alongside the drafts._\n\n"
        + report.markdown
    )
