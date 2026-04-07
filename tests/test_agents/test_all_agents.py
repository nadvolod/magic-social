"""Tests for all 5 AI agents — variety guardian, code curator, quality reviewer, resonance checker, predictor."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from src.agents.variety_guardian import guard_variety
from src.agents.code_curator import curate_code_snippet
from src.agents.quality_reviewer import review_quality, format_quality_comment
from src.agents.resonance_checker import check_resonance, format_resonance_comment
from src.agents.predictor import (
    predict_outcome,
    format_prediction_comment,
    compute_accuracy_stats,
    load_predictions_log,
    save_prediction,
    update_prediction_outcome,
)


def _mock_openai_response(content: str):
    """Create a mock OpenAI chat completion response."""
    mock_choice = MagicMock()
    mock_choice.message.content = content
    mock_resp = MagicMock()
    mock_resp.choices = [mock_choice]
    client = MagicMock()
    client.chat.completions.create.return_value = mock_resp
    return client


# ---------------------------------------------------------------------------
# Variety Guardian
# ---------------------------------------------------------------------------

def test_variety_guardian_returns_recommendations():
    response_json = json.dumps([
        {"sha": "abc123", "hook_pattern": "story", "skip": False, "reason": "Good fit for narrative"},
        {"sha": "def456", "hook_pattern": "result", "skip": True, "reason": "Off-ICP: generic CI/CD"},
    ])
    client = _mock_openai_response(response_json)

    candidates = [
        {"sha": "abc123", "message": "Add Temporal retry logic", "repo": "owner/repo", "tags": ["distributed-systems"]},
        {"sha": "def456", "message": "Fix CSS layout", "repo": "owner/repo", "tags": ["frontend"]},
    ]
    recent = [{"hook_pattern": "result", "tags": ["ai"], "lesson": "AI agents"}]

    recs = guard_variety(client, candidates, recent)
    assert len(recs) == 2
    assert recs[0]["sha"] == "abc123"
    assert recs[1]["skip"] is True


def test_variety_guardian_fallback_on_error():
    client = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError("API down")

    # On-ICP commit should not be skipped on fallback
    candidates = [{"sha": "abc", "message": "add Temporal workflow retry", "repo": "r", "tags": ["distributed-systems"]}]
    recs = guard_variety(client, candidates, [])
    assert len(recs) == 1
    assert recs[0]["skip"] is False

    # Off-ICP commit should be skipped even on fallback
    candidates_off = [{"sha": "def", "message": "fix CSS layout", "repo": "r", "tags": []}]
    recs_off = guard_variety(client, candidates_off, [])
    assert len(recs_off) == 1
    assert recs_off[0]["skip"] is True


# ---------------------------------------------------------------------------
# Code Curator
# ---------------------------------------------------------------------------

def test_code_curator_returns_snippet():
    response_json = json.dumps({
        "snippet": "async def run(self):\n    return await workflow.execute(task)",
        "language": "python",
        "why": "Shows the core workflow execution pattern",
    })
    client = _mock_openai_response(response_json)

    with patch("src.agents.code_curator.requests") as mock_requests:
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "files": [{"filename": "main.py", "patch": "@@ -1,3 +1,5 @@\n+async def run(self):\n+    return await workflow.execute(task)"}]
        }
        mock_requests.get.return_value = mock_resp

        result = curate_code_snippet(client, "abc123", "owner/repo", "token")

    assert result is not None
    assert "snippet" in result
    assert result["language"] == "python"


def test_code_curator_returns_none_on_error():
    client = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError("boom")

    with patch("src.agents.code_curator.requests") as mock_requests:
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"files": [{"filename": "x.py", "patch": "+x=1"}]}
        mock_requests.get.return_value = mock_resp

        result = curate_code_snippet(client, "abc", "r", "t")

    assert result is None


# ---------------------------------------------------------------------------
# Quality Reviewer
# ---------------------------------------------------------------------------

def test_quality_reviewer_returns_scores():
    response_json = json.dumps({
        "specificity": {"score": 18, "notes": "Concrete pattern"},
        "insight_depth": {"score": 14, "notes": "Known pattern"},
        "hook_strength": {"score": 16, "notes": "Good tension"},
        "code_relevance": {"score": 18, "notes": "Relevant snippet"},
        "shareability": {"score": 12, "notes": "Useful but not viral"},
        "suggestions": "Lead with the failure mode.",
    })
    client = _mock_openai_response(response_json)

    review = review_quality(client, "Post text here", "commit msg", "diff summary")
    assert review["total_score"] == 78
    assert len(review["dimensions"]) == 5


def test_quality_reviewer_format_comment():
    review = {
        "total_score": 80,
        "dimensions": {
            "specificity": {"score": 16, "max": 20, "notes": "Good"},
            "insight_depth": {"score": 16, "max": 20, "notes": "Good"},
            "hook_strength": {"score": 16, "max": 20, "notes": "Good"},
            "code_relevance": {"score": 16, "max": 20, "notes": "Good"},
            "shareability": {"score": 16, "max": 20, "notes": "Good"},
        },
        "suggestions": "Looks great.",
    }
    comment = format_quality_comment(review)
    assert "## Semantic Quality Review" in comment
    assert "80/100" in comment
    assert "Looks great." in comment


def test_quality_reviewer_fallback_on_error():
    client = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError("fail")

    review = review_quality(client, "post", "msg", "diff")
    assert review["total_score"] == 50


# ---------------------------------------------------------------------------
# Resonance Checker
# ---------------------------------------------------------------------------

def test_resonance_checker_returns_assessment():
    response_json = json.dumps({
        "resonance": "high",
        "icp_match": True,
        "reasons": ["Temporal content matches ICP"],
        "suggestion": "Should land well.",
    })
    client = _mock_openai_response(response_json)

    result = check_resonance(client, "Temporal workflow post", ["distributed-systems"], {})
    assert result["resonance"] == "high"
    assert result["icp_match"] is True


def test_resonance_checker_format_high():
    assessment = {
        "resonance": "high",
        "icp_match": True,
        "reasons": ["Good match"],
        "suggestion": "Looks good.",
    }
    comment = format_resonance_comment(assessment)
    assert "High" in comment
    assert "Yes" in comment


def test_resonance_checker_format_low():
    assessment = {
        "resonance": "low",
        "icp_match": False,
        "reasons": ["Off topic"],
        "suggestion": "Skip it.",
    }
    comment = format_resonance_comment(assessment)
    assert "Low" in comment
    assert "No" in comment


def test_resonance_checker_fallback_on_error():
    client = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError("fail")

    result = check_resonance(client, "post", [], {})
    assert result["resonance"] == "medium"


# ---------------------------------------------------------------------------
# Predictor
# ---------------------------------------------------------------------------

def test_predictor_returns_prediction():
    response_json = json.dumps({
        "publish_probability": 82,
        "engagement_tier": "high",
        "reasoning": ["Strong hook", "Good topic"],
    })
    client = _mock_openai_response(response_json)

    pred = predict_outcome(
        client, "Post text", ["temporal"], "result",
        {"total_score": 80}, {"resonance": "high"}, {}, [],
    )
    assert pred["publish_probability"] == 82
    assert pred["engagement_tier"] == "high"


def test_predictor_format_comment():
    prediction = {
        "publish_probability": 75,
        "engagement_tier": "medium",
        "reasoning": ["Decent hook", "Known topic"],
    }
    accuracy = {"total_predictions": 10, "publish_accuracy_pct": 70.0, "tier_accuracy_pct": 50.0}
    comment = format_prediction_comment(prediction, accuracy)
    assert "75%" in comment
    assert "Medium" in comment or "medium" in comment.lower()


def test_predictor_fallback_on_error():
    client = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError("fail")

    pred = predict_outcome(client, "post", [], "result", {}, {}, {}, [])
    assert pred["publish_probability"] == 50
    assert pred["engagement_tier"] == "medium"


def test_predictor_accuracy_stats_empty():
    stats = compute_accuracy_stats([])
    assert stats["total_predictions"] == 0
    assert stats["publish_accuracy_pct"] == 0.0


def test_predictor_accuracy_stats_with_data():
    predictions = [
        {"publish_probability": 80, "actual_published": True, "engagement_tier": "high", "actual_engagement_score": 50},
        {"publish_probability": 30, "actual_published": False, "engagement_tier": "low", "actual_engagement_score": 0},
        {"publish_probability": 70, "actual_published": False, "engagement_tier": "high", "actual_engagement_score": 5},
    ]
    stats = compute_accuracy_stats(predictions)
    assert stats["total_predictions"] == 3
    # 2 of 3 correct (80%→published correct, 30%→not published correct, 70%→published wrong)
    assert stats["publish_accuracy_pct"] > 60


def test_predictor_save_and_load(tmp_path):
    log_path = str(tmp_path / "predictions.json")
    pred = {"post_id": "test-1", "publish_probability": 75, "engagement_tier": "high"}
    save_prediction(pred, path=log_path)
    loaded = load_predictions_log(path=log_path)
    assert len(loaded) == 1
    assert loaded[0]["post_id"] == "test-1"


def test_predictor_update_outcome(tmp_path):
    log_path = str(tmp_path / "predictions.json")
    pred = {"post_id": "test-1", "publish_probability": 80, "engagement_tier": "high",
            "actual_published": None, "actual_engagement_score": None}
    save_prediction(pred, path=log_path)
    update_prediction_outcome("test-1", published=True, engagement_score=42.0, path=log_path)
    loaded = load_predictions_log(path=log_path)
    assert loaded[0]["actual_published"] is True
    assert loaded[0]["actual_engagement_score"] == 42.0
