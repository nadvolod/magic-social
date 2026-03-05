"""Tests for GitHub issue storage helpers."""

from src.github_storage import load_posts_from_issues
from src.models import PostStatus


def test_load_posts_from_issues_parses_embedded_post_json(monkeypatch):
    issue = {
        "number": 42,
        "title": "[Social Post] lesson",
        "body": (
            "<details>\n<summary>🤖 Raw Post Data (JSON metadata for agent use)</summary>\n\n"
            "```json\n"
            '{"id":"post-abc","source_commit_sha":"abc","repo":"owner/repo","lesson":"L","linkedin_post":"P",'
            '"x_thread":"X","ig_caption":"I","hook_pattern":"result","status":"draft","tags":["ai"]}\n'
            "```\n</details>"
        ),
        "labels": [{"name": "status:published"}],
        "created_at": "2026-03-01T00:00:00Z",
        "updated_at": "2026-03-02T00:00:00Z",
    }

    monkeypatch.setattr(
        "src.github_storage.list_social_post_issues",
        lambda repo, token, state="all": [issue],
    )

    posts = load_posts_from_issues("owner/repo", "token", state="all")
    assert len(posts) == 1
    assert posts[0].id == "post-abc"
    assert posts[0].github_issue_number == 42
    assert posts[0].status == PostStatus.PUBLISHED


def test_load_posts_from_issues_falls_back_when_json_missing(monkeypatch):
    issue = {
        "number": 5,
        "title": "[Social Post] fallback title",
        "body": "No raw JSON here.",
        "labels": [{"name": "status:draft"}],
        "created_at": "2026-03-01T00:00:00Z",
        "updated_at": "2026-03-01T00:00:00Z",
    }

    monkeypatch.setattr(
        "src.github_storage.list_social_post_issues",
        lambda repo, token, state="all": [issue],
    )

    posts = load_posts_from_issues("owner/repo", "token", state="all")
    assert len(posts) == 1
    assert posts[0].id == "issue-5"
    assert posts[0].status == PostStatus.DRAFT
