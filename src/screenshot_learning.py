"""LinkedIn screenshot learning loop (issue-driven, AI-classified)."""

from __future__ import annotations

import base64
import json
import logging
import math
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

from .github_storage import ensure_labels

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
SCREENSHOT_LABEL = "social-screenshot"
SCREENSHOT_PROCESSED_LABEL = "screenshot:processed"
SCREENSHOT_TOP_LABEL = "screenshot:top10"
SCREENSHOT_BOTTOM_LABEL = "screenshot:bottom90"
DEFAULT_SCREENSHOT_STATE_PATH = "screenshot_learning.json"


@dataclass
class ScreenshotExample:
    """A single learned example from a LinkedIn screenshot issue."""

    issue_number: int
    issue_url: str
    image_url: str
    recorded_at: str
    metrics: dict = field(default_factory=dict)
    engagement_score: float = 0.0
    percentile: float = 0.0
    classification: str = "bottom_90_percent"
    reason: str = ""
    confidence: float = 0.0
    signals: dict = field(default_factory=dict)
    summary: str = ""
    hook_excerpt: str = ""

    def to_dict(self) -> dict:
        return {
            "issue_number": self.issue_number,
            "issue_url": self.issue_url,
            "image_url": self.image_url,
            "recorded_at": self.recorded_at,
            "metrics": self.metrics,
            "engagement_score": self.engagement_score,
            "percentile": self.percentile,
            "classification": self.classification,
            "reason": self.reason,
            "confidence": self.confidence,
            "signals": self.signals,
            "summary": self.summary,
            "hook_excerpt": self.hook_excerpt,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ScreenshotExample":
        return cls(
            issue_number=int(data.get("issue_number", 0)),
            issue_url=str(data.get("issue_url", "")),
            image_url=str(data.get("image_url", "")),
            recorded_at=str(data.get("recorded_at", "")),
            metrics=data.get("metrics", {}) or {},
            engagement_score=float(data.get("engagement_score", 0.0) or 0.0),
            percentile=float(data.get("percentile", 0.0) or 0.0),
            classification=str(data.get("classification", "bottom_90_percent")),
            reason=str(data.get("reason", "")),
            confidence=float(data.get("confidence", 0.0) or 0.0),
            signals=data.get("signals", {}) or {},
            summary=str(data.get("summary", "")),
            hook_excerpt=str(data.get("hook_excerpt", "")),
        )


@dataclass
class ScreenshotLearningState:
    """Persisted screenshot-learning dataset and derived signal memory."""

    examples: list[ScreenshotExample] = field(default_factory=list)
    version: int = 1

    def to_dict(self) -> dict:
        return {
            "examples": [e.to_dict() for e in self.examples],
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ScreenshotLearningState":
        examples = [ScreenshotExample.from_dict(x) for x in (data.get("examples", []) or [])]
        return cls(examples=examples, version=int(data.get("version", 1)))

    def save(self, path: str = DEFAULT_SCREENSHOT_STATE_PATH) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str = DEFAULT_SCREENSHOT_STATE_PATH) -> "ScreenshotLearningState":
        p = Path(path)
        if not p.exists():
            return cls()
        try:
            return cls.from_dict(json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError, TypeError):
            return cls()

    @property
    def top_10_count(self) -> int:
        return sum(1 for e in self.examples if e.classification == "top_10_percent")

    @property
    def bottom_90_count(self) -> int:
        return sum(1 for e in self.examples if e.classification != "top_10_percent")

    def has_issue(self, issue_number: int) -> bool:
        return any(e.issue_number == issue_number for e in self.examples)


def _github_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _list_issues(repo: str, token: str, state: str = "open", labels: Optional[str] = None) -> list[dict]:
    """Fetch issues with optional label filter (excluding pull requests)."""
    issues: list[dict] = []
    page = 1
    while True:
        params = {"state": state, "per_page": 100, "page": page}
        if labels:
            params["labels"] = labels
        resp = requests.get(
            f"{GITHUB_API}/repos/{repo}/issues",
            headers=_github_headers(token),
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        for issue in batch:
            if "pull_request" not in issue:
                issues.append(issue)
        if len(batch) < 100:
            break
        page += 1
    return issues


def list_screenshot_issues(repo: str, token: str, state: str = "open") -> list[dict]:
    """
    Fetch screenshot-learning issues (excluding pull requests).

    Primary source: issues with label `social-screenshot`.
    Fallback source: issues whose title starts with `[Social Screenshot]`.
    """
    by_label = _list_issues(repo, token, state=state, labels=SCREENSHOT_LABEL)
    all_open = _list_issues(repo, token, state=state, labels=None)

    merged: dict[int, dict] = {int(i["number"]): i for i in by_label}
    for issue in all_open:
        num = int(issue["number"])
        title = str(issue.get("title", "")).strip().lower()
        if title.startswith("[social screenshot]"):
            merged[num] = issue
    return sorted(merged.values(), key=lambda x: x.get("created_at", ""))


def issue_has_label(issue: dict, label: str) -> bool:
    return any(l.get("name") == label for l in issue.get("labels", []))


def extract_image_urls(markdown: str) -> list[str]:
    """Extract image URLs from markdown/image HTML snippets."""
    if not markdown:
        return []

    # Strip HTML comments so template examples (<!-- ![img](https://...) -->)
    # don't get picked up as real image URLs.
    cleaned = re.sub(r"<!--.*?-->", "", markdown, flags=re.DOTALL)

    urls: list[str] = []
    md_matches = re.findall(r"!\[[^\]]*]\((https?://[^)\s]+)\)", cleaned, flags=re.IGNORECASE)
    html_matches = re.findall(r'<img[^>]+src=["\'](https?://[^"\']+)["\']', cleaned, flags=re.IGNORECASE)
    bare_matches = re.findall(r"(https?://\S+\.(?:png|jpe?g|webp|gif)(?:\?\S*)?)", cleaned, flags=re.IGNORECASE)

    for url in md_matches + html_matches + bare_matches:
        clean = url.strip()
        if clean not in urls:
            urls.append(clean)
    return urls


def fetch_issue_comments(repo: str, token: str, issue_number: int) -> list[dict]:
    url = f"{GITHUB_API}/repos/{repo}/issues/{issue_number}/comments"
    resp = requests.get(url, headers=_github_headers(token), params={"per_page": 100}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def find_first_image_url(issue: dict, comments: list[dict]) -> Optional[str]:
    for url in extract_image_urls(issue.get("body", "")):
        return url
    for comment in comments:
        for url in extract_image_urls(comment.get("body", "")):
            return url
    return None


def download_image_as_data_url(image_url: str, token: str, web_token: Optional[str] = None) -> str:
    """Download image bytes and return a data URL for OpenAI vision.

    ``web_token``, when provided, is used for the initial request to
    ``github.com/user-attachments/`` URLs.  The default ``GITHUB_TOKEN``
    issued to GitHub-Actions is a *repository installation* token and
    **cannot** access private user-attachment URLs.  A classic PAT with
    ``repo`` scope (or a fine-grained token with Issues-read) works.
    """
    download_token = web_token or token
    is_user_attachment = "user-attachments/assets" in image_url

    # For user-attachment URLs, use curl to avoid Python idna/urllib3
    # validation errors that occur in some CI environments.
    if is_user_attachment:
        result = subprocess.run(
            ["curl", "-sL", "-H", f"Authorization: token {download_token}", image_url],
            capture_output=True,
            timeout=60,
        )
        if result.returncode != 0 or not result.stdout:
            raise RuntimeError(f"curl failed for {image_url}: {result.stderr.decode()}")
        content = result.stdout
    else:
        headers = {"Authorization": f"Bearer {token}", "Accept": "image/*,*/*"}
        resp = requests.get(image_url, headers=headers, timeout=30)
        resp.raise_for_status()
        content = resp.content

    # Infer content type from magic bytes
    if content[:8].startswith(b"\x89PNG"):
        content_type = "image/png"
    elif content[:3] in (b"\xff\xd8\xff",):
        content_type = "image/jpeg"
    elif content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        content_type = "image/webp"
    else:
        content_type = "image/png"

    encoded = base64.b64encode(content).decode("ascii")
    return f"data:{content_type};base64,{encoded}"


def _normalize_metrics(raw: dict) -> dict:
    def _val(key: str) -> int:
        value = raw.get(key)
        if value is None:
            return 0
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0

    return {
        "impressions": _val("impressions"),
        "reactions": _val("reactions"),
        "comments": _val("comments"),
        "reposts": _val("reposts"),
        "saves": _val("saves"),
    }


def engagement_score(metrics: dict) -> float:
    return (
        float(metrics.get("saves", 0)) * 4.0
        + float(metrics.get("reposts", 0)) * 3.0
        + float(metrics.get("comments", 0)) * 3.0
        + float(metrics.get("reactions", 0)) * 1.0
    )


def percentile_rank(scores: list[float], value: float) -> float:
    if not scores:
        return 1.0
    less_or_equal = sum(1 for s in scores if s <= value)
    return less_or_equal / len(scores)


def deterministic_top_decile_label(scores: list[float], value: float) -> tuple[str, float]:
    merged = list(scores) + [value]
    p = percentile_rank(merged, value)
    label = "top_10_percent" if p >= 0.9 else "bottom_90_percent"
    return label, p


def summarize_score_distribution(scores: list[float]) -> dict:
    if not scores:
        return {"count": 0, "p50": 0.0, "p75": 0.0, "p90": 0.0, "min": 0.0, "max": 0.0}
    sorted_scores = sorted(scores)

    def _q(q: float) -> float:
        if not sorted_scores:
            return 0.0
        idx = int(math.ceil(q * len(sorted_scores))) - 1
        idx = max(0, min(idx, len(sorted_scores) - 1))
        return float(sorted_scores[idx])

    return {
        "count": len(sorted_scores),
        "p50": _q(0.50),
        "p75": _q(0.75),
        "p90": _q(0.90),
        "min": float(sorted_scores[0]),
        "max": float(sorted_scores[-1]),
    }


def _parse_json_from_text(text: str) -> dict:
    text = (text or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return {}
    return {}


def extract_metrics_and_signals_with_openai(
    openai_client,
    image_data_url: str,
    model: str = "gpt-5.4-mini",
) -> dict:
    """Use OpenAI vision to read screenshot metrics + content signals."""
    if openai_client is None:
        raise RuntimeError("OpenAI client is required for screenshot extraction.")

    system_prompt = (
        "You extract LinkedIn post analytics from screenshots and identify post signals. "
        "Return only valid JSON."
    )
    user_prompt = (
        "Read this LinkedIn post screenshot. Extract visible analytics and post-quality signals.\n\n"
        "Return JSON with this schema:\n"
        "{"
        "\"metrics\": {\"impressions\": int|null, \"reactions\": int|null, \"comments\": int|null, \"reposts\": int|null, \"saves\": int|null},"
        "\"signals\": {\"hook_style\": str, \"tone\": str, \"structure\": str, \"cta_type\": str, \"has_code\": bool, \"has_numbers\": bool, \"topic\": str},"
        "\"summary\": \"short summary\","
        "\"hook_excerpt\": \"first line or hook if visible\""
        "}\n"
        "Use null when a metric is not visible."
    )

    response = openai_client.chat.completions.create(
        model=model,
        temperature=0.0,
        max_tokens=500,
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                ],
            },
        ],
    )
    content = response.choices[0].message.content or ""
    payload = _parse_json_from_text(content)
    return {
        "metrics": _normalize_metrics(payload.get("metrics", {}) or {}),
        "signals": payload.get("signals", {}) or {},
        "summary": str(payload.get("summary", "")).strip(),
        "hook_excerpt": str(payload.get("hook_excerpt", "")).strip(),
    }


def decide_top10_with_openai(
    openai_client,
    metrics: dict,
    score: float,
    percentile: float,
    distribution: dict,
    model: str = "gpt-5.4-mini",
) -> tuple[str, str, float]:
    """Ask OpenAI to classify top 10% vs bottom 90% from score context."""
    if openai_client is None:
        label = "top_10_percent" if percentile >= 0.9 else "bottom_90_percent"
        return label, "OpenAI unavailable; fallback to percentile rule.", 0.0

    system_prompt = (
        "You classify LinkedIn post performance into exactly one bucket: top_10_percent or bottom_90_percent. "
        "Use score distribution context and percentile. Return JSON only."
    )
    user_prompt = (
        "Classify this screenshot-derived post performance.\n\n"
        f"Candidate metrics: {json.dumps(metrics, ensure_ascii=True)}\n"
        f"Candidate engagement_score: {score:.1f}\n"
        f"Candidate percentile (computed): {percentile:.4f}\n"
        f"Historical distribution: {json.dumps(distribution, ensure_ascii=True)}\n\n"
        "Return JSON: {\"classification\":\"top_10_percent|bottom_90_percent\",\"reason\":\"short reason\",\"confidence\":0.0}"
    )
    try:
        response = openai_client.chat.completions.create(
            model=model,
            temperature=0.0,
            max_tokens=180,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        payload = _parse_json_from_text(response.choices[0].message.content or "")
        label = str(payload.get("classification", "")).strip()
        if label not in ("top_10_percent", "bottom_90_percent"):
            label = "top_10_percent" if percentile >= 0.9 else "bottom_90_percent"
        reason = str(payload.get("reason", "")).strip() or "Classification based on relative score percentile."
        confidence = float(payload.get("confidence", 0.0) or 0.0)
        return label, reason, confidence
    except Exception as exc:  # noqa: BLE001
        logger.warning("OpenAI screenshot classification failed: %s", exc)
        label = "top_10_percent" if percentile >= 0.9 else "bottom_90_percent"
        return label, "OpenAI classification failed; fallback to percentile rule.", 0.0


def _signal_bucket(example: ScreenshotExample) -> str:
    return "top" if example.classification == "top_10_percent" else "bottom"


def build_signal_balance(state: ScreenshotLearningState, top_n: int = 6) -> tuple[list[str], list[str]]:
    """
    Build positive/negative signal strings from learned screenshot examples.

    Returns:
      (positive_signals, negative_signals)
    """
    counts: dict[str, dict[str, int]] = {}
    for e in state.examples:
        bucket = _signal_bucket(e)
        signals = e.signals or {}
        for key, value in signals.items():
            if value in (None, "", []):
                continue
            values: list[str]
            if isinstance(value, list):
                values = [str(v).strip().lower() for v in value if str(v).strip()]
            else:
                values = [str(value).strip().lower()]
            for item in values:
                signal_key = f"{key}={item}"
                slot = counts.setdefault(signal_key, {"top": 0, "bottom": 0})
                slot[bucket] += 1

    positive_ranked: list[tuple[str, int]] = []
    negative_ranked: list[tuple[str, int]] = []
    for signal_key, c in counts.items():
        delta = c["top"] - c["bottom"]
        if delta > 0:
            positive_ranked.append((signal_key, delta))
        elif delta < 0:
            negative_ranked.append((signal_key, -delta))

    positive_ranked.sort(key=lambda x: (-x[1], x[0]))
    negative_ranked.sort(key=lambda x: (-x[1], x[0]))
    positives = [s for s, _ in positive_ranked[:top_n]]
    negatives = [s for s, _ in negative_ranked[:top_n]]
    return positives, negatives


def build_prompt_guidance(state: ScreenshotLearningState, top_n: int = 5) -> str:
    """Return compact text guidance for generation prompts."""
    positives, negatives = build_signal_balance(state, top_n=top_n)
    if not positives and not negatives:
        return ""
    lines = ["Screenshot-derived LinkedIn signals from observed posts:"]
    if positives:
        lines.append("Prefer patterns:")
        lines.extend(f"- {s}" for s in positives)
    if negatives:
        lines.append("Avoid patterns:")
        lines.extend(f"- {s}" for s in negatives)
    return "\n".join(lines)


def _post_comment(repo: str, token: str, issue_number: int, body: str) -> None:
    url = f"{GITHUB_API}/repos/{repo}/issues/{issue_number}/comments"
    resp = requests.post(url, headers=_github_headers(token), json={"body": body}, timeout=30)
    resp.raise_for_status()


def _add_labels(repo: str, token: str, issue_number: int, labels: list[str]) -> None:
    url = f"{GITHUB_API}/repos/{repo}/issues/{issue_number}/labels"
    resp = requests.post(url, headers=_github_headers(token), json={"labels": labels}, timeout=30)
    resp.raise_for_status()


def _remove_label(repo: str, token: str, issue_number: int, label: str) -> None:
    url = f"{GITHUB_API}/repos/{repo}/issues/{issue_number}/labels/{requests.utils.quote(label)}"
    resp = requests.delete(url, headers=_github_headers(token), timeout=30)
    if resp.status_code not in (200, 404):
        resp.raise_for_status()


def process_screenshot_issue(
    repo: str,
    token: str,
    issue: dict,
    state: ScreenshotLearningState,
    openai_client,
    dry_run: bool = False,
    web_token: Optional[str] = None,
) -> Optional[ScreenshotExample]:
    """Process one screenshot issue into a learned example."""
    issue_number = int(issue["number"])
    if state.has_issue(issue_number):
        return None

    comments = fetch_issue_comments(repo, token, issue_number)
    image_url = find_first_image_url(issue, comments)
    if not image_url:
        if not dry_run:
            _post_comment(
                repo,
                token,
                issue_number,
                "I could not find an image in this issue yet. Please attach a LinkedIn screenshot and retry.",
            )
        return None

    image_data_url = download_image_as_data_url(image_url, token, web_token=web_token)
    extracted = extract_metrics_and_signals_with_openai(openai_client, image_data_url)
    metrics = _normalize_metrics(extracted.get("metrics", {}) or {})
    score = engagement_score(metrics)

    history_scores = [e.engagement_score for e in state.examples]
    deterministic_label, percentile = deterministic_top_decile_label(history_scores, score)
    distribution = summarize_score_distribution(history_scores)

    ai_label, reason, confidence = decide_top10_with_openai(
        openai_client=openai_client,
        metrics=metrics,
        score=score,
        percentile=percentile,
        distribution=distribution,
    )
    classification = ai_label if ai_label in ("top_10_percent", "bottom_90_percent") else deterministic_label

    example = ScreenshotExample(
        issue_number=issue_number,
        issue_url=str(issue.get("html_url", "")),
        image_url=image_url,
        recorded_at=datetime.now(timezone.utc).isoformat(),
        metrics=metrics,
        engagement_score=score,
        percentile=percentile,
        classification=classification,
        reason=reason,
        confidence=confidence,
        signals=extracted.get("signals", {}) or {},
        summary=str(extracted.get("summary", "")),
        hook_excerpt=str(extracted.get("hook_excerpt", "")),
    )

    state.examples.append(example)

    if not dry_run:
        _remove_label(repo, token, issue_number, SCREENSHOT_TOP_LABEL)
        _remove_label(repo, token, issue_number, SCREENSHOT_BOTTOM_LABEL)
        _add_labels(
            repo,
            token,
            issue_number,
            [
                SCREENSHOT_LABEL,
                SCREENSHOT_PROCESSED_LABEL,
                SCREENSHOT_TOP_LABEL if classification == "top_10_percent" else SCREENSHOT_BOTTOM_LABEL,
            ],
        )
        _post_comment(
            repo,
            token,
            issue_number,
            "\n".join(
                [
                    "## Screenshot Classification",
                    "",
                    f"- Classification: **{classification}**",
                    f"- Engagement score: **{score:.1f}**",
                    f"- Percentile: **{percentile * 100:.1f}%**",
                    f"- Reason: {reason}",
                    "",
                    "### Extracted Metrics",
                    f"- Impressions: {metrics.get('impressions', 0)}",
                    f"- Reactions: {metrics.get('reactions', 0)}",
                    f"- Comments: {metrics.get('comments', 0)}",
                    f"- Reposts: {metrics.get('reposts', 0)}",
                    f"- Saves: {metrics.get('saves', 0)}",
                    "",
                    f"Summary: {example.summary or '_n/a_'}",
                ]
            ),
        )

    return example


def run_screenshot_learning_cycle(
    repo: str,
    token: str,
    state_path: str = DEFAULT_SCREENSHOT_STATE_PATH,
    max_issues: int = 25,
    dry_run: bool = False,
    openai_client=None,
    web_token: Optional[str] = None,
) -> list[ScreenshotExample]:
    """
    Process open screenshot issues and update learning state.

    The issue-only UX is:
      1) create issue from screenshot template
      2) paste/upload screenshot
      3) this job extracts metrics/signals and classifies top 10% vs bottom 90%
    """
    if openai_client is None:
        raise RuntimeError("OPENAI_API_KEY is required for screenshot learning.")

    ensure_labels(repo, token)
    state = ScreenshotLearningState.load(state_path)
    issues = list_screenshot_issues(repo, token, state="open")
    candidates = [
        i for i in issues
        if not issue_has_label(i, SCREENSHOT_PROCESSED_LABEL) and not state.has_issue(int(i["number"]))
    ]
    candidates.sort(key=lambda x: x.get("created_at", ""), reverse=False)
    candidates = candidates[:max_issues]

    learned: list[ScreenshotExample] = []
    for issue in candidates:
        try:
            example = process_screenshot_issue(
                repo=repo,
                token=token,
                issue=issue,
                state=state,
                openai_client=openai_client,
                dry_run=dry_run,
                web_token=web_token,
            )
            if example is not None:
                learned.append(example)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Screenshot issue #%s failed: %s", issue.get("number"), exc)

    if learned and not dry_run:
        state.save(state_path)
    return learned
