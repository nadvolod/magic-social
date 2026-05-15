"""Tests for agent orchestration helpers and learning guardrails."""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta, timezone

import src.agent as agent
from src.analytics import LearningState
from src.models import Post, PostStatus, SourceCommit


def _make_source() -> SourceCommit:
    return SourceCommit(
        sha="abc123def456",
        repo="owner/repo",
        message="fix temporal workflow retries with idempotency",
        author="Nikolay",
        timestamp="2026-03-01T00:00:00Z",
        files_changed=["workflow.py"],
        diff_summary="+20 lines, -5 lines",
        score=70.0,
        score_breakdown={},
    )


def _make_post(source: SourceCommit) -> Post:
    return Post(
        id=f"post-{source.sha[:12]}",
        source_commit_sha=source.sha,
        repo=source.repo,
        lesson=source.message,
        linkedin_post="Hook\n\nBody\n\nQuestion?",
        x_thread="1/ Hook",
        ig_caption="Caption",
        hook_pattern="result",
        status=PostStatus.DRAFT,
    )


class _DummyExperiments:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def get_active_experiment(self):
        return None

    def start_next_experiment(self):
        return None


def _patch_run_scan_dependencies(monkeypatch, source: SourceCommit):
    monkeypatch.setattr(agent, "ExperimentManager", _DummyExperiments)
    monkeypatch.setattr(agent, "get_best_hook_pattern", lambda state: "result")
    monkeypatch.setattr(agent, "_get_openai_client", lambda: object())
    monkeypatch.setattr(
        agent,
        "decide_commit_with_openai",
        lambda *args, **kwargs: agent.CommitDecision(accept=True, reason="ok", confidence=1.0),
    )
    monkeypatch.setattr(agent, "generate_post_with_quality_gate", lambda **kwargs: _make_post(source))
    # Mock load_posts_from_issues for deduplication (no existing posts by default)
    monkeypatch.setattr("src.github_storage.load_posts_from_issues", lambda *args, **kwargs: [])


def test_backlog_throttle_blocks_generation(monkeypatch):
    source = _make_source()
    _patch_run_scan_dependencies(monkeypatch, source)

    def _scan_should_not_run(*args, **kwargs):
        raise AssertionError("scan_commits should not run when backlog throttle blocks")

    monkeypatch.setattr(agent, "scan_commits", _scan_should_not_run)
    monkeypatch.setattr(
        agent,
        "fetch_social_post_backlog",
        lambda *args, **kwargs: agent.BacklogStats(total_open_social=12, open_unpublished=10, stale_unpublished=2),
    )

    posts = agent.run_scan(
        repo="owner/repo",
        token="token",
        dry_run=False,
        backlog_throttle_enabled=True,
        max_open_unpublished=10,
        max_stale_unpublished=4,
    )
    assert posts == []


def test_backlog_throttle_bypassed_in_dry_run(monkeypatch):
    source = _make_source()
    _patch_run_scan_dependencies(monkeypatch, source)
    monkeypatch.setattr(agent, "scan_commits", lambda *args, **kwargs: [source])
    monkeypatch.setattr(
        agent,
        "fetch_social_post_backlog",
        lambda *args, **kwargs: agent.BacklogStats(total_open_social=20, open_unpublished=20, stale_unpublished=20),
    )

    posts = agent.run_scan(
        repo="owner/repo",
        token="token",
        dry_run=True,
        max_open_unpublished=10,
        max_stale_unpublished=4,
    )
    assert len(posts) == 1


def test_backlog_throttle_can_be_disabled(monkeypatch):
    source = _make_source()
    _patch_run_scan_dependencies(monkeypatch, source)
    monkeypatch.setattr(agent, "scan_commits", lambda *args, **kwargs: [source])
    monkeypatch.setattr(agent, "create_post_issue", lambda *args, **kwargs: 42)
    monkeypatch.setattr(
        agent,
        "fetch_social_post_backlog",
        lambda *args, **kwargs: agent.BacklogStats(total_open_social=20, open_unpublished=20, stale_unpublished=20),
    )

    posts = agent.run_scan(
        repo="owner/repo",
        token="token",
        dry_run=False,
        backlog_throttle_enabled=False,
        max_open_unpublished=10,
        max_stale_unpublished=4,
    )
    assert len(posts) == 1
    assert posts[0].github_issue_number == 42


def test_cleanup_backlog_archives_old_keeps_recent(monkeypatch, tmp_path):
    """cleanup-backlog should archive old drafts and keep the most recent ones."""
    now = datetime.now(timezone.utc)
    old_date = (now - timedelta(days=5)).isoformat()
    recent_date = (now - timedelta(days=1)).isoformat()

    old_post = _make_post(_make_source())
    old_post.id = "post-old"
    old_post.github_issue_number = 100
    old_post.created_at = old_date

    recent_post = _make_post(_make_source())
    recent_post.id = "post-recent"
    recent_post.source_commit_sha = "different_sha"
    recent_post.github_issue_number = 200
    recent_post.created_at = recent_date

    # Mock load_posts_from_issues to return both posts (recent first)
    monkeypatch.setattr(
        "src.github_storage.load_posts_from_issues",
        lambda *args, **kwargs: [recent_post, old_post],
    )
    # Mock feedback fetching (no explicit feedback)
    monkeypatch.setattr(
        "src.analytics.fetch_issue_feedback",
        lambda *args, **kwargs: None,
    )
    # Mock GitHub operations
    comments_added = []
    monkeypatch.setattr(
        "src.github_storage.add_comment",
        lambda repo, token, num, body: comments_added.append((num, body)),
    )
    monkeypatch.setattr(
        "src.github_storage.update_issue_status",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "src.github_storage.close_issue",
        lambda *args, **kwargs: None,
    )

    # Write a minimal learning state file
    state_path = str(tmp_path / "learning_state.json")
    from src.analytics import LearningState
    LearningState().save(state_path)

    snapshot_path = str(tmp_path / "snapshot.json")
    archived = agent.run_cleanup_backlog(
        repo="owner/repo",
        token="token",
        keep_recent=1,
        older_than_days=3,
        learning_state_path=state_path,
        snapshot_output=snapshot_path,
    )

    assert archived == 1, "Should archive 1 old draft"
    assert len(comments_added) == 1, "Should add archive comment to old issue"
    assert comments_added[0][0] == 100, "Comment should be on the old issue"
    assert "backlog_cleanup_unreviewed" in comments_added[0][1]

    import json
    with open(snapshot_path) as f:
        snapshot = json.load(f)
    assert snapshot["archived_count"] == 1
    assert snapshot["retained_count"] == 1
    assert any(e["retained"] for e in snapshot["entries"])
    assert any(not e["retained"] for e in snapshot["entries"])


def test_cleanup_backlog_dry_run_makes_no_changes(monkeypatch, tmp_path):
    """--dry-run should not archive anything."""
    now = datetime.now(timezone.utc)
    old_date = (now - timedelta(days=5)).isoformat()

    old_post = _make_post(_make_source())
    old_post.github_issue_number = 100
    old_post.created_at = old_date

    monkeypatch.setattr(
        "src.github_storage.load_posts_from_issues",
        lambda *args, **kwargs: [old_post],
    )
    monkeypatch.setattr(
        "src.analytics.fetch_issue_feedback",
        lambda *args, **kwargs: None,
    )

    state_path = str(tmp_path / "learning_state.json")
    from src.analytics import LearningState
    LearningState().save(state_path)

    archived = agent.run_cleanup_backlog(
        repo="owner/repo",
        token="token",
        keep_recent=0,
        older_than_days=3,
        learning_state_path=state_path,
        dry_run=True,
    )
    assert archived == 0, "Dry run should not actually archive"


def test_fetch_social_post_backlog_counts_open_and_stale(monkeypatch):
    now = datetime.now(timezone.utc)
    old = (now - timedelta(days=10)).isoformat()
    recent = (now - timedelta(days=1)).isoformat()
    pages = [
        [
            {
                "number": 1,
                "state": "open",
                "labels": [{"name": "status:draft"}],
                "created_at": old,
            },
            {
                "number": 2,
                "state": "open",
                "labels": [{"name": "status:approved"}],
                "created_at": recent,
            },
            {
                "number": 3,
                "state": "open",
                "labels": [{"name": "status:published"}],
                "created_at": old,
            },
        ],
        [],
    ]

    class _Resp:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    def _fake_get(*args, **kwargs):
        return _Resp(pages.pop(0))

    monkeypatch.setattr("requests.get", _fake_get)
    stats = agent.fetch_social_post_backlog("owner/repo", "token", stale_days=7)
    assert stats.total_open_social == 3
    assert stats.open_unpublished == 2
    assert stats.stale_unpublished == 1


def test_apply_learning_guardrails_no_bad_batch_keeps_inputs():
    state = LearningState()
    threshold, max_posts = agent.apply_learning_guardrails(state, threshold=20.0, max_posts=10)
    assert threshold == 20.0
    assert max_posts == 10


def test_apply_learning_guardrails_tightens_with_bad_batch_signal():
    state = LearningState(
        not_published_reasons={
            "historical_batch_bad_practice_pre_2026-03-03_2359_est": 37
        }
    )
    threshold, max_posts = agent.apply_learning_guardrails(state, threshold=15.0, max_posts=10)
    assert threshold == 40.0
    assert max_posts == 3


def test_apply_learning_guardrails_preserves_stricter_existing_values():
    state = LearningState(
        not_published_reasons={
            "historical_batch_bad_practice_pre_2026-03-03_2359_est": 50
        }
    )
    threshold, max_posts = agent.apply_learning_guardrails(state, threshold=55.0, max_posts=2)
    assert threshold == 55.0
    assert max_posts == 2


class _FakeMessage:
    def __init__(self, content: str):
        self.content = content


class _FakeChoice:
    def __init__(self, content: str):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content: str):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, content: str):
        self._content = content

    def create(self, **kwargs):
        return _FakeResponse(self._content)


class _FakeChat:
    def __init__(self, content: str):
        self.completions = _FakeCompletions(content)


class _FakeOpenAI:
    def __init__(self, content: str):
        self.chat = _FakeChat(content)


class TestCLIArgValidation:
    def test_quality_threshold_rejects_out_of_range(self):
        """--quality-threshold outside [0, 100] must fail with a clear error."""
        result = subprocess.run(
            [sys.executable, "-m", "src.agent", "scan", "--repo", "o/r", "--quality-threshold", "150"],
            capture_output=True, text=True, env={**__import__("os").environ, "GITHUB_TOKEN": "fake"},
        )
        assert result.returncode != 0
        assert "quality-threshold" in result.stderr.lower()

    def test_max_rewrites_rejects_negative(self):
        """--max-rewrites must be >= 0."""
        result = subprocess.run(
            [sys.executable, "-m", "src.agent", "scan", "--repo", "o/r", "--max-rewrites", "-1"],
            capture_output=True, text=True, env={**__import__("os").environ, "GITHUB_TOKEN": "fake"},
        )
        assert result.returncode != 0
        assert "max-rewrites" in result.stderr.lower()


def test_deduplication_skips_existing_commit_shas(monkeypatch):
    """Commits that already have social-post issues should be skipped."""
    source = _make_source()
    _patch_run_scan_dependencies(monkeypatch, source)
    monkeypatch.setattr(agent, "scan_commits", lambda *args, **kwargs: [source])

    # Simulate an existing post with the same commit SHA
    existing_post = _make_post(source)
    monkeypatch.setattr(
        "src.github_storage.load_posts_from_issues",
        lambda *args, **kwargs: [existing_post],
    )

    posts = agent.run_scan(
        repo="owner/repo",
        token="token",
        dry_run=True,
    )
    assert posts == [], "Should skip commit that already has a social-post issue"


def test_deduplication_allows_new_commits(monkeypatch):
    """Commits that have no existing social-post issue should proceed."""
    source = _make_source()
    _patch_run_scan_dependencies(monkeypatch, source)
    monkeypatch.setattr(agent, "scan_commits", lambda *args, **kwargs: [source])

    # Existing posts have different SHAs
    other_post = _make_post(source)
    other_post.source_commit_sha = "different_sha_999"
    monkeypatch.setattr(
        "src.github_storage.load_posts_from_issues",
        lambda *args, **kwargs: [other_post],
    )

    posts = agent.run_scan(
        repo="owner/repo",
        token="token",
        dry_run=True,
    )
    assert len(posts) == 1, "New commit should not be filtered out"


def test_allow_duplicate_commits_bypasses_dedup(monkeypatch):
    """--allow-duplicate-commits should skip deduplication entirely."""
    source = _make_source()
    _patch_run_scan_dependencies(monkeypatch, source)
    monkeypatch.setattr(agent, "scan_commits", lambda *args, **kwargs: [source])

    # Even with an existing post with the same SHA, it should proceed
    existing_post = _make_post(source)
    monkeypatch.setattr(
        "src.github_storage.load_posts_from_issues",
        lambda *args, **kwargs: [existing_post],
    )

    posts = agent.run_scan(
        repo="owner/repo",
        token="token",
        dry_run=True,
        allow_duplicate_commits=True,
    )
    assert len(posts) == 1, "Deduplication should be bypassed"


def test_decide_commit_with_openai_accepts_valid_json():
    source = _make_source()
    state = LearningState()
    client = _FakeOpenAI('{"decision":"accept","reason":"strong external lesson","confidence":0.88}')
    decision = agent.decide_commit_with_openai(client, source, state)
    assert decision.accept is True
    assert "external lesson" in decision.reason
    assert decision.confidence == 0.88


def test_decide_commit_with_openai_rejects_valid_json():
    source = _make_source()
    state = LearningState()
    client = _FakeOpenAI('{"decision":"reject","reason":"internal maintenance only","confidence":0.91}')
    decision = agent.decide_commit_with_openai(client, source, state)
    assert decision.accept is False
    assert "internal maintenance" in decision.reason


def test_decide_commit_with_openai_handles_wrapped_json():
    source = _make_source()
    state = LearningState()
    client = _FakeOpenAI(
        "Here is the result:\n"
        '{"decision":"reject","reason":"not audience-relevant","confidence":0.7}\n'
    )
    decision = agent.decide_commit_with_openai(client, source, state)
    assert decision.accept is False
    assert "audience-relevant" in decision.reason
