"""Tier D acceptance — LLM-as-judge for v2 variants.

Loads the 5 generated variants for an Issue, the Raw Idea, and the top 3
reference posts, then asks an evaluation LLM to score each variant on:

  1. Raw Idea fidelity        (1-5)
  2. Specificity              (1-5)
  3. Reference exceedance     (1-5)
  4. Voice authenticity       (1-5)

The canonical PASS condition (v2 worked) is:
  • ≥ 3 of 5 variants score >= 4 on Raw Idea fidelity AND >= 3 on Reference exceedance
  • Median across all 5 variants is >= 3.5 on every dimension

Output is a human-readable judge_report.md in the variant's drafts folder,
ending with `PASS` or `FAIL`.
"""

from __future__ import annotations

import json
import logging
import os
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import requests

from . import writing_client
from .screenshot_learning import (
    DEFAULT_SCREENSHOT_STATE_PATH,
    ScreenshotExample,
    ScreenshotLearningState,
)

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
DRAFTS_ROOT = REPO_ROOT / "drafts"
PROMPT_PATH = REPO_ROOT / "prompts" / "judge_variants.md"

JUDGE_MODEL_DEFAULT = "gpt-5.4-mini"

DIMENSIONS = (
    "raw_idea_fidelity",
    "specificity",
    "reference_exceedance",
    "voice_authenticity",
)


# ---------------------------------------------------------------------------
# Data gathering
# ---------------------------------------------------------------------------


@dataclass
class VariantInput:
    variant_id: str
    angle: str
    post_text: str

    def to_dict(self) -> dict:
        return {"variant_id": self.variant_id, "angle": self.angle, "post_text": self.post_text}


@dataclass
class JudgeContext:
    issue_number: int
    raw_idea: str
    drafts_dir: Path
    variants: list[VariantInput]
    references: list[ScreenshotExample]


def find_drafts_dir(issue_number: int, *, repo: Optional[str] = None) -> Optional[Path]:
    """Find the most recent drafts/<date>_<slug>/ folder for an Issue.

    Reads each candidate's metadata.json for the source_issue link.
    """
    if not DRAFTS_ROOT.exists():
        return None

    issue_marker = f"#{issue_number}"
    candidates: list[Path] = []
    for d in DRAFTS_ROOT.iterdir():
        if not d.is_dir():
            continue
        meta = d / "metadata.json"
        if not meta.exists():
            continue
        try:
            payload = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("issue_number") == issue_number:
            candidates.append(d)
            continue
        src = payload.get("source_issue") or ""
        if issue_marker in src or (repo and f"{repo}/issues/{issue_number}" in src):
            candidates.append(d)
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.name)


def _strip_variant_md(text: str) -> tuple[str, str]:
    """Variant files are '# variant_N — angle\\n\\n**...metadata...**\\n\\n---\\n\\n<post>'.

    Return (angle, post_text).
    """
    header = re.match(r"^#\s+variant_\d+\s+—\s+(?P<angle>.+)$", text, re.MULTILINE)
    angle = header.group("angle").strip() if header else "unknown"
    parts = text.split("\n---\n", 1)
    body = parts[1] if len(parts) == 2 else text
    return angle, body.strip()


def load_variants(drafts_dir: Path) -> list[VariantInput]:
    variants: list[VariantInput] = []
    for path in sorted(drafts_dir.glob("variant_*.md")):
        text = path.read_text(encoding="utf-8")
        angle, body = _strip_variant_md(text)
        variants.append(VariantInput(variant_id=path.stem, angle=angle, post_text=body))
    return variants


def fetch_raw_idea(repo: str, token: str, issue_number: int) -> str:
    """Pull the Raw Idea section from the live GitHub Issue."""
    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    body = resp.json().get("body") or ""
    return _extract_raw_idea(body)


def _extract_raw_idea(body: str) -> str:
    """Pull the '### Raw idea' section from a content-idea Issue body."""
    match = re.search(
        r"^###\s+Raw idea\s*$(?P<value>.*?)(?=^###\s|\Z)",
        body or "",
        re.IGNORECASE | re.DOTALL | re.MULTILINE,
    )
    return match.group("value").strip() if match else (body or "").strip()


def top_references(*, top_n: int = 3) -> list[ScreenshotExample]:
    state = ScreenshotLearningState.load(DEFAULT_SCREENSHOT_STATE_PATH)
    tops = sorted(
        (e for e in state.examples if e.classification == "top_10_percent"),
        key=lambda e: e.engagement_score,
        reverse=True,
    )[:top_n]
    return tops


def build_judge_context(
    issue_number: int,
    *,
    repo: str,
    token: str,
    drafts_dir: Optional[Path] = None,
    top_reference_n: int = 3,
) -> JudgeContext:
    target = drafts_dir or find_drafts_dir(issue_number, repo=repo)
    if target is None:
        raise RuntimeError(
            f"No drafts directory found for Issue #{issue_number}. "
            "Re-trigger generation, then run judge-variants again."
        )
    return JudgeContext(
        issue_number=issue_number,
        raw_idea=fetch_raw_idea(repo, token, issue_number),
        drafts_dir=target,
        variants=load_variants(target),
        references=top_references(top_n=top_reference_n),
    )


# ---------------------------------------------------------------------------
# Prompt + LLM call
# ---------------------------------------------------------------------------


def _split_prompt(template: str) -> tuple[str, str]:
    system = re.search(r"^##\s+SYSTEM\s*$", template, re.MULTILINE)
    user = re.search(r"^##\s+USER\s*$", template, re.MULTILINE)
    if not system or not user:
        raise ValueError("prompts/judge_variants.md must contain ## SYSTEM and ## USER")
    return template[system.end():user.start()].strip(), template[user.end():].strip()


def _references_block(refs: list[ScreenshotExample]) -> str:
    payload = [
        {
            "identifier": f"ref #{r.issue_number}",
            "hook_excerpt": r.hook_excerpt,
            "summary": r.summary,
            "engagement_score": round(float(r.engagement_score), 2),
            "metrics": r.metrics,
        }
        for r in refs
    ]
    return json.dumps(payload, indent=2)


def _variants_block(variants: list[VariantInput]) -> str:
    return json.dumps([v.to_dict() for v in variants], indent=2)


def build_judge_prompts(ctx: JudgeContext) -> tuple[str, str]:
    if not PROMPT_PATH.exists():
        raise FileNotFoundError(f"Prompt template missing: {PROMPT_PATH}")
    template = PROMPT_PATH.read_text(encoding="utf-8")
    system_template, user_template = _split_prompt(template)
    user_prompt = user_template.format(
        issue_number=ctx.issue_number,
        raw_idea=ctx.raw_idea or "(missing)",
        variants_block=_variants_block(ctx.variants),
        references_block=_references_block(ctx.references),
    )
    return system_template, user_prompt


def _extract_json(text: str) -> dict:
    text = (text or "").strip()
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


def call_judge(ctx: JudgeContext, *, client=None, model: Optional[str] = None) -> dict:
    if client is None:
        client = writing_client.get_client()
    if client is None:
        raise RuntimeError(
            "OpenAI client unavailable. Set OPENAI_API_KEY and install openai."
        )
    system_prompt, user_prompt = build_judge_prompts(ctx)
    chosen_model = model or os.environ.get("JUDGE_MODEL") or JUDGE_MODEL_DEFAULT
    raw = writing_client.generate_text(
        client, system_prompt, user_prompt, model=chosen_model, temperature=0.0
    )
    return _extract_json(raw)


# ---------------------------------------------------------------------------
# Verdict + report
# ---------------------------------------------------------------------------


@dataclass
class Verdict:
    passed: bool
    reasons: list[str] = field(default_factory=list)


def evaluate_verdict(judge_payload: dict) -> Verdict:
    """Apply the canonical PASS condition from the plan.

    PASS when:
      * >= 3 of 5 variants have raw_idea_fidelity >= 4 AND reference_exceedance >= 3
      * median across all variants is >= 3.5 on every dimension
    """
    variants = judge_payload.get("variants") or []
    if not variants:
        return Verdict(passed=False, reasons=["No variants scored by judge."])

    hits = 0
    for v in variants:
        if (v.get("raw_idea_fidelity", 0) or 0) >= 4 and (v.get("reference_exceedance", 0) or 0) >= 3:
            hits += 1
    threshold = 3
    reasons: list[str] = []
    if hits < threshold:
        reasons.append(
            f"Only {hits} of {len(variants)} variants met the (raw_idea_fidelity >= 4 AND "
            f"reference_exceedance >= 3) bar; need {threshold}."
        )

    dim_medians: dict[str, float] = {}
    for dim in DIMENSIONS:
        values = [float(v.get(dim, 0) or 0) for v in variants]
        if not values:
            continue
        dim_medians[dim] = statistics.median(values)
        if dim_medians[dim] < 3.5:
            reasons.append(f"Median {dim} = {dim_medians[dim]:.1f} (< 3.5)")

    return Verdict(passed=not reasons, reasons=reasons)


def render_report(judge_payload: dict, verdict: Verdict, *, ctx: JudgeContext) -> str:
    lines = [
        f"# Variant judge report — Issue #{ctx.issue_number}",
        "",
        f"_Drafts: `{ctx.drafts_dir.relative_to(REPO_ROOT)}`._",
        f"_References: {len(ctx.references)} top-performing posts from `screenshot_learning.json`._",
        "",
        "## Per-variant scores",
        "",
        "| Variant | RawIdea | Specificity | RefExceed | Voice | Diagnosis |",
        "|---|---|---|---|---|---|",
    ]
    for v in judge_payload.get("variants", []):
        diag = (v.get("diagnosis") or "").replace("|", "\\|")
        lines.append(
            f"| {v.get('variant_id','?')} "
            f"| {v.get('raw_idea_fidelity','?')} "
            f"| {v.get('specificity','?')} "
            f"| {v.get('reference_exceedance','?')} "
            f"| {v.get('voice_authenticity','?')} "
            f"| {diag} |"
        )

    lines.append("")
    lines.append("## Reasons per variant")
    for v in judge_payload.get("variants", []):
        lines.append("")
        lines.append(f"### {v.get('variant_id','?')}")
        for dim in DIMENSIONS:
            score = v.get(dim, "?")
            reason = v.get(f"{dim}_reason", "")
            lines.append(f"- **{dim}** ({score}/5): {reason}")

    lines.append("")
    lines.append("## Verdict")
    lines.append("")
    if verdict.passed:
        lines.append("PASS — v2 model meets the acceptance bar.")
    else:
        lines.append("FAIL — v2 model did NOT meet the acceptance bar.")
        for reason in verdict.reasons:
            lines.append(f"- {reason}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_judge(
    issue_number: int,
    *,
    repo: str,
    token: str,
    drafts_dir: Optional[Path] = None,
    client=None,
    model: Optional[str] = None,
) -> tuple[Path, Verdict]:
    ctx = build_judge_context(
        issue_number, repo=repo, token=token, drafts_dir=drafts_dir
    )
    payload = call_judge(ctx, client=client, model=model)
    verdict = evaluate_verdict(payload)
    report = render_report(payload, verdict, ctx=ctx)
    report_path = ctx.drafts_dir / "judge_report.md"
    report_path.write_text(report, encoding="utf-8")
    logger.info("Wrote judge report: %s (PASS=%s)", report_path, verdict.passed)
    return report_path, verdict
