"""Tests for agent orchestration helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import src.agent as agent
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
    monkeypatch.setattr(agent, "_get_openai_client", lambda: None)
    monkeypatch.setattr(agent, "generate_post", lambda **kwargs: _make_post(source))


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
