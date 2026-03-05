"""Tests for weekly self-improvement tuning."""

from datetime import datetime, timedelta, timezone

import yaml

from src.analytics import LearningState
from src.self_improvement import (
    ImprovementContext,
    apply_config_tunings,
    build_improvement_context,
    render_self_improvement_report,
)


def _issue(
    state: str = "open",
    status_label: str = "status:draft",
    created_at: str = "2026-03-01T00:00:00Z",
    updated_at: str = "2026-03-01T00:00:00Z",
    comments: int = 0,
) -> dict:
    return {
        "state": state,
        "labels": [{"name": status_label}],
        "created_at": created_at,
        "updated_at": updated_at,
        "comments": comments,
    }


def test_build_improvement_context_counts_backlog_signals():
    now = datetime.now(timezone.utc)
    old = (now - timedelta(days=8)).isoformat()
    recent = (now - timedelta(days=1)).isoformat()
    issues = [
        _issue(state="open", status_label="status:draft", created_at=old, comments=0),
        _issue(state="open", status_label="status:approved", created_at=old, comments=0),
        _issue(state="open", status_label="status:published", created_at=recent, comments=2),
    ]
    ctx = build_improvement_context(issues, now=now)
    assert ctx.total_social_issues == 3
    assert ctx.open_unpublished == 2
    assert ctx.stale_unpublished_7d == 2
    assert ctx.old_unreviewed_72h == 2


def test_apply_config_tunings_updates_threshold_and_limits(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "agent": {"score_threshold": 15.0, "max_posts_per_run": 10},
                "post_generation": {"linkedin_max_chars": 1500},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    state = LearningState(
        not_published_reasons={
            "too_long": 4,
            "stale_unpublished_7d": 4,
            "not_relevant": 0,
        }
    )
    ctx = ImprovementContext(
        total_social_issues=20,
        open_social_issues=14,
        open_unpublished=13,
        stale_unpublished_7d=6,
        old_unreviewed_72h=7,
    )
    changes = apply_config_tunings(str(config_path), state, ctx)
    updated = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    assert changes
    assert updated["agent"]["score_threshold"] >= 20.0
    assert updated["agent"]["max_posts_per_run"] <= 8
    assert updated["post_generation"]["linkedin_max_chars"] <= 1350


def test_render_self_improvement_report_contains_sections():
    state = LearningState(not_published_reasons={"quality": 3})
    ctx = ImprovementContext(total_social_issues=5, open_social_issues=3, open_unpublished=2)
    report = render_self_improvement_report(state, ctx, ["Raised threshold"], "config.yaml")
    assert "Weekly Self-Improvement Report" in report
    assert "Backlog Signals" in report
    assert "Raised threshold" in report
