"""Tests for GitHub issue storage helpers."""

from unittest.mock import MagicMock, patch

from src.github_storage import (
    _build_issue_body,
    _extract_post_json,
    create_post_issue,
    load_posts_from_issues,
)
from src.models import Post, PostStatus


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


def test_build_issue_body_embeds_raw_post_json():
    """_build_issue_body must embed the Raw Post Data JSON so load_posts_from_issues
    can extract source_commit_sha for deduplication — the root cause of the duplicate
    post bug (same post created on every workflow run because SHA was always 'unknown')."""
    post = Post(
        id="post-dedup-test",
        source_commit_sha="deadbeef1234abcd",
        repo="owner/repo",
        lesson="Test lesson",
        linkedin_post="Hook\n\nBody\n\nQuestion?",
        x_thread="1/ Hook",
        ig_caption="Caption",
        hook_pattern="result",
    )
    body = _build_issue_body(post)

    # The body must contain the JSON block matching RAW_POST_JSON_RE
    payload = _extract_post_json(body)
    assert payload is not None, (
        "_extract_post_json returned None — Raw Post Data JSON not found in issue body. "
        "This means deduplication will never work and the same post will be re-created every run."
    )
    assert payload["source_commit_sha"] == "deadbeef1234abcd"
    assert payload["id"] == "post-dedup-test"


def test_load_posts_from_issues_extracts_sha_from_body(monkeypatch):
    """load_posts_from_issues must return the real source_commit_sha (not 'unknown')
    so that run_scan deduplication can exclude already-processed commits."""
    post = Post(
        id="post-sha-test",
        source_commit_sha="cafebabe5678",
        repo="owner/repo",
        lesson="SHA extraction test",
        linkedin_post="Some post content",
        x_thread="",
        ig_caption="",
        hook_pattern="result",
    )
    issue = {
        "number": 77,
        "title": "[Social Post] SHA extraction test",
        "body": _build_issue_body(post),
        "labels": [{"name": "status:draft"}],
        "created_at": "2026-03-01T00:00:00Z",
        "updated_at": "2026-03-01T00:00:00Z",
    }

    monkeypatch.setattr(
        "src.github_storage.list_social_post_issues",
        lambda repo, token, state="all": [issue],
    )

    loaded = load_posts_from_issues("owner/repo", "token", state="all")
    assert len(loaded) == 1
    assert loaded[0].source_commit_sha == "cafebabe5678", (
        "source_commit_sha must not be 'unknown' — deduplication relies on this value"
    )
    assert loaded[0].id == "post-sha-test"


def _make_post(**kwargs) -> Post:
    defaults = dict(
        id="post-123",
        source_commit_sha="abc123",
        repo="owner/repo",
        lesson="test lesson",
        linkedin_post="Tip:\n\n    def hello():\n        print('hi')\n\nTry it!",
        x_thread="thread",
        ig_caption="caption",
        hook_pattern="result",
    )
    defaults.update(kwargs)
    return Post(**defaults)


@patch("src.github_storage.requests")
@patch("src.github_storage.generate_code_snippet_image", create=True)
def test_create_post_issue_uploads_code_image(mock_gen, mock_requests):
    """Code image is generated, uploaded, and commented on the issue."""
    mock_gen.return_value = b"\x89PNG_fake_image_bytes"

    # Mock issue creation response
    create_resp = MagicMock()
    create_resp.ok = True
    create_resp.json.return_value = {"number": 42}
    create_resp.raise_for_status = MagicMock()

    # Mock GET for existing file check (404 = file doesn't exist)
    check_resp = MagicMock()
    check_resp.ok = False

    # Mock PUT upload response
    upload_resp = MagicMock()
    upload_resp.ok = True
    upload_resp.json.return_value = {
        "content": {"download_url": "https://raw.example.com/image.png"}
    }

    # Mock comment responses
    comment_resp = MagicMock()
    comment_resp.ok = True

    # Mock label listing
    labels_resp = MagicMock()
    labels_resp.ok = True
    labels_resp.json.return_value = [
        {"name": "social-post"},
        {"name": "status:draft"},
        {"name": "platform:linkedin"},
        {"name": "analytics:pending"},
    ]
    labels_resp.raise_for_status = MagicMock()

    def route_request(url, **kwargs):
        if "/labels" in url:
            return labels_resp
        if "/contents/" in url:
            return check_resp
        return comment_resp

    mock_requests.get.side_effect = route_request
    mock_requests.post.side_effect = lambda url, **kw: create_resp if "/issues" in url and "/comments" not in url else comment_resp
    mock_requests.put.return_value = upload_resp

    post = _make_post()

    with patch("src.github_storage.generate_code_snippet_image", mock_gen):
        issue_num = create_post_issue(post, "owner/repo", "fake-token")

    assert issue_num == 42
    assert post.code_image_url == "https://raw.example.com/image.png"
    # Should have called PUT to upload the image
    mock_requests.put.assert_called_once()


@patch("src.github_storage.requests")
def test_create_post_issue_image_failure_nonfatal(mock_requests):
    """Image generation failure doesn't break issue creation."""
    create_resp = MagicMock()
    create_resp.ok = True
    create_resp.json.return_value = {"number": 99}
    create_resp.raise_for_status = MagicMock()

    comment_resp = MagicMock()
    comment_resp.ok = True

    labels_resp = MagicMock()
    labels_resp.ok = True
    labels_resp.json.return_value = [
        {"name": "social-post"},
        {"name": "status:draft"},
        {"name": "platform:linkedin"},
        {"name": "analytics:pending"},
    ]
    labels_resp.raise_for_status = MagicMock()

    mock_requests.get.return_value = labels_resp
    mock_requests.post.side_effect = lambda url, **kw: create_resp if "/issues" in url and "/comments" not in url else comment_resp

    post = _make_post()

    with patch("src.code_image.generate_code_snippet_image", side_effect=RuntimeError("boom")):
        issue_num = create_post_issue(post, "owner/repo", "fake-token")

    # Issue was still created despite image failure
    assert issue_num == 99
    assert post.code_image_url is None
