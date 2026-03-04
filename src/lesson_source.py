"""External lesson sources for post-generation guidance."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import requests

GOOGLE_DOC_ID_RE = re.compile(r"/document/d/([a-zA-Z0-9_-]+)")


def extract_google_doc_id(url: str) -> Optional[str]:
    """Extract the Google Doc ID from a standard docs URL."""
    if not url:
        return None
    match = GOOGLE_DOC_ID_RE.search(url)
    if match is None:
        return None
    return match.group(1)


def google_doc_export_url(url_or_id: str) -> Optional[str]:
    """
    Convert a Google Doc URL or ID to a plain-text export endpoint.

    Returns None for non-Google-Docs inputs.
    """
    if not url_or_id:
        return None

    doc_id = extract_google_doc_id(url_or_id)
    if doc_id is None and re.fullmatch(r"[a-zA-Z0-9_-]{8,}", url_or_id):
        doc_id = url_or_id
    if doc_id is None:
        return None
    return f"https://docs.google.com/document/d/{doc_id}/export?format=txt"


def normalize_lessons_text(text: str, max_chars: int = 3500, max_lines: int = 60) -> str:
    """
    Normalize lesson text so it is prompt-friendly and bounded in size.

    Keeps short, non-empty lines and trims hard length.
    """
    if not text:
        return ""

    clean_lines = [line.strip() for line in text.splitlines() if line.strip()]
    clean_lines = clean_lines[:max_lines]
    normalized = "\n".join(clean_lines).strip()
    if len(normalized) > max_chars:
        normalized = normalized[: max_chars - 16].rstrip() + "\n...[truncated]"
    return normalized


def fetch_google_doc_lessons(url_or_id: str, timeout: int = 20, max_chars: int = 3500) -> str:
    """Fetch lesson text from a Google Doc shared with view access."""
    export_url = google_doc_export_url(url_or_id)
    if export_url is None:
        return ""

    resp = requests.get(export_url, timeout=timeout)
    resp.raise_for_status()
    return normalize_lessons_text(resp.text, max_chars=max_chars)


def load_social_lessons(
    doc_url: Optional[str] = None,
    file_path: Optional[str] = None,
    max_chars: int = 3500,
) -> str:
    """
    Load social-post lessons from either:
      1) a local text/markdown file, or
      2) a Google Doc URL/ID.

    File input has priority because it is deterministic and offline-friendly.
    """
    if file_path:
        path = Path(file_path)
        if path.exists():
            return normalize_lessons_text(path.read_text(encoding="utf-8"), max_chars=max_chars)

    if doc_url:
        return fetch_google_doc_lessons(doc_url, max_chars=max_chars)

    return ""
