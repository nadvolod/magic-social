"""Tests for screenshot-learning pipeline helpers."""

from src.screenshot_learning import (
    ScreenshotExample,
    ScreenshotLearningState,
    build_signal_balance,
    deterministic_top_decile_label,
    extract_image_urls,
    process_screenshot_issue,
)


def test_extract_image_urls_from_markdown_and_html():
    body = """
![img](https://example.com/a.png)
<img src="https://example.com/b.jpg" />
https://example.com/c.webp
"""
    urls = extract_image_urls(body)
    assert "https://example.com/a.png" in urls
    assert "https://example.com/b.jpg" in urls
    assert "https://example.com/c.webp" in urls


def test_deterministic_top_decile_label_uses_percentile():
    scores = [10, 20, 30, 40, 50, 60, 70, 80, 90]
    label, percentile = deterministic_top_decile_label(scores, 95)
    assert label == "top_10_percent"
    assert percentile >= 0.9

    label2, percentile2 = deterministic_top_decile_label(scores, 15)
    assert label2 == "bottom_90_percent"
    assert percentile2 < 0.9


def test_build_signal_balance_separates_positive_and_negative():
    # Need at least 2 examples per signal to meet minimum support threshold
    state = ScreenshotLearningState(
        examples=[
            ScreenshotExample(
                issue_number=1,
                issue_url="u1",
                image_url="i1",
                recorded_at="2026-03-01T00:00:00Z",
                classification="top_10_percent",
                signals={"hook_style": "result", "cta_type": "question_open"},
            ),
            ScreenshotExample(
                issue_number=3,
                issue_url="u3",
                image_url="i3",
                recorded_at="2026-03-01T00:00:00Z",
                classification="top_10_percent",
                signals={"hook_style": "result", "cta_type": "question_open"},
            ),
            ScreenshotExample(
                issue_number=2,
                issue_url="u2",
                image_url="i2",
                recorded_at="2026-03-01T00:00:00Z",
                classification="bottom_90_percent",
                signals={"hook_style": "story", "cta_type": "no_cta"},
            ),
            ScreenshotExample(
                issue_number=4,
                issue_url="u4",
                image_url="i4",
                recorded_at="2026-03-01T00:00:00Z",
                classification="bottom_90_percent",
                signals={"hook_style": "story", "cta_type": "no_cta"},
            ),
        ]
    )
    positives, negatives = build_signal_balance(state, top_n=5)
    assert any("hook_style=result" in s for s in positives)
    assert any("hook_style=story" in s for s in negatives)


def test_process_screenshot_issue_adds_example_and_labels(monkeypatch):
    issue = {
        "number": 42,
        "html_url": "https://github.com/owner/repo/issues/42",
        "body": "![shot](https://example.com/shot.png)",
        "labels": [{"name": "social-screenshot"}],
    }
    state = ScreenshotLearningState()

    posted = {"comments": 0, "labels": 0}

    monkeypatch.setattr("src.screenshot_learning.fetch_issue_comments", lambda *args, **kwargs: [])
    monkeypatch.setattr("src.screenshot_learning.download_image_as_data_url", lambda *args, **kwargs: "data:image/png;base64,abc")
    monkeypatch.setattr(
        "src.screenshot_learning.extract_metrics_and_signals_with_openai",
        lambda *args, **kwargs: {
            "metrics": {"impressions": 1000, "reactions": 100, "comments": 20, "reposts": 10, "saves": 25},
            "signals": {"hook_style": "result"},
            "summary": "Strong proof-based post.",
            "hook_excerpt": "We cut latency by 80%.",
        },
    )
    monkeypatch.setattr(
        "src.screenshot_learning.decide_top10_with_openai",
        lambda *args, **kwargs: ("top_10_percent", "High relative score.", 0.9),
    )
    monkeypatch.setattr(
        "src.screenshot_learning._add_labels",
        lambda *args, **kwargs: posted.__setitem__("labels", posted["labels"] + 1),
    )
    monkeypatch.setattr("src.screenshot_learning._remove_label", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "src.screenshot_learning._post_comment",
        lambda *args, **kwargs: posted.__setitem__("comments", posted["comments"] + 1),
    )

    ex = process_screenshot_issue(
        repo="owner/repo",
        token="token",
        issue=issue,
        state=state,
        openai_client=object(),
        dry_run=False,
    )
    assert ex is not None
    assert ex.issue_number == 42
    assert ex.classification == "top_10_percent"
    assert len(state.examples) == 1
    assert posted["labels"] == 1
    assert posted["comments"] == 1
