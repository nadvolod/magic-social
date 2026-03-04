"""Tests for external lesson sources."""

from pathlib import Path
from unittest.mock import MagicMock

from src.lesson_source import (
    extract_google_doc_id,
    fetch_google_doc_lessons,
    google_doc_export_url,
    load_social_lessons,
    normalize_lessons_text,
)


def test_extract_google_doc_id_from_url():
    url = "https://docs.google.com/document/d/1GQD7a49V9B96wzTYt33mlJb3gae5quJzRcf4d3GiPh0/edit?usp=sharing"
    assert extract_google_doc_id(url) == "1GQD7a49V9B96wzTYt33mlJb3gae5quJzRcf4d3GiPh0"


def test_google_doc_export_url_from_id():
    doc_id = "abc123_DEF-xyz"
    assert google_doc_export_url(doc_id) == f"https://docs.google.com/document/d/{doc_id}/export?format=txt"


def test_normalize_lessons_text_truncates():
    raw = "\n".join(f"Line {i}" for i in range(100))
    normalized = normalize_lessons_text(raw, max_chars=100, max_lines=10)
    assert "Line 0" in normalized
    assert len(normalized) <= 100


def test_load_social_lessons_prefers_file(tmp_path: Path):
    lesson_file = tmp_path / "lessons.md"
    lesson_file.write_text("Lesson A\nLesson B\n", encoding="utf-8")
    loaded = load_social_lessons(doc_url="https://docs.google.com/document/d/abc/edit", file_path=str(lesson_file))
    assert "Lesson A" in loaded
    assert "Lesson B" in loaded


def test_fetch_google_doc_lessons(monkeypatch):
    mock_resp = MagicMock()
    mock_resp.text = "Rule 1\nRule 2\n"
    mock_resp.raise_for_status = MagicMock()

    monkeypatch.setattr("src.lesson_source.requests.get", lambda *args, **kwargs: mock_resp)
    lessons = fetch_google_doc_lessons("https://docs.google.com/document/d/abc123/edit")
    assert "Rule 1" in lessons
    assert "Rule 2" in lessons
