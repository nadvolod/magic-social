"""Tests for the LinkedIn API module."""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.linkedin_api import (
    LinkedInPostMetrics,
    LinkedInProfile,
    LinkedInSnapshot,
    _parse_created_at,
    _post_urn_to_url,
    fetch_follower_count,
    fetch_post_engagement,
    fetch_profile,
    fetch_recent_posts,
    load_latest_snapshot,
    save_snapshot,
)


# ---------------------------------------------------------------------------
# Data model tests
# ---------------------------------------------------------------------------

class TestLinkedInPostMetrics:
    def test_engagement_score_formula(self):
        pm = LinkedInPostMetrics(
            post_urn="urn:li:ugcPost:123",
            post_url="https://linkedin.com/feed/update/urn:li:ugcPost:123/",
            created_at="2024-01-01T00:00:00+00:00",
            likes=10,
            comments=5,
            shares=3,
            impressions=1000,
            clicks=20,
        )
        # likes×1 + comments×3 + shares×3 + impressions×0 + clicks×2
        assert pm.engagement_score == 10 + 15 + 9 + 0 + 40

    def test_to_dict(self):
        pm = LinkedInPostMetrics(
            post_urn="urn:li:ugcPost:1",
            post_url="https://linkedin.com/feed/update/urn:li:ugcPost:1/",
            created_at="2024-01-01T00:00:00+00:00",
            likes=3,
            comments=1,
            shares=0,
        )
        d = pm.to_dict()
        assert d["post_urn"] == "urn:li:ugcPost:1"
        assert d["likes"] == 3
        assert "engagement_score" in d


class TestLinkedInSnapshot:
    def test_to_dict_and_json(self):
        snap = LinkedInSnapshot(
            follower_count=500,
            connection_count=500,
        )
        d = snap.to_dict()
        assert d["follower_count"] == 500
        assert isinstance(d["post_metrics"], list)

        raw = snap.to_json()
        parsed = json.loads(raw)
        assert parsed["follower_count"] == 500


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_post_urn_to_url(self):
        urn = "urn:li:ugcPost:12345678"
        url = _post_urn_to_url(urn)
        assert "linkedin.com/feed/update/" in url
        assert urn in url

    def test_parse_created_at_with_timestamp(self):
        post = {"created": {"time": 1704067200000}}  # 2024-01-01 00:00:00 UTC
        ts = _parse_created_at(post)
        assert "2024-01-01" in ts

    def test_parse_created_at_fallback(self):
        ts = _parse_created_at({})
        # Should return a valid ISO string even with no data
        assert "T" in ts or len(ts) > 10


# ---------------------------------------------------------------------------
# API call tests (mocked)
# ---------------------------------------------------------------------------

class TestFetchProfile:
    def test_fetch_profile_success(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "id": "abcXYZ123",
            "localizedFirstName": "Nikolay",
            "localizedLastName": "Advolod",
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("src.linkedin_api.requests.get", return_value=mock_resp):
            profile = fetch_profile("fake-token")

        assert profile.person_urn == "urn:li:person:abcXYZ123"
        assert profile.first_name == "Nikolay"
        assert profile.last_name == "Advolod"


class TestFetchFollowerCount:
    def test_fetch_follower_count_success(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"paging": {"total": 1234}}
        mock_resp.raise_for_status = MagicMock()

        with patch("src.linkedin_api.requests.get", return_value=mock_resp):
            count = fetch_follower_count("urn:li:person:abc", "fake-token")

        assert count == 1234

    def test_fetch_follower_count_403_returns_zero(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 403

        with patch("src.linkedin_api.requests.get", return_value=mock_resp):
            count = fetch_follower_count("urn:li:person:abc", "fake-token")

        assert count == 0

    def test_fetch_follower_count_empty_paging(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_resp.raise_for_status = MagicMock()

        with patch("src.linkedin_api.requests.get", return_value=mock_resp):
            count = fetch_follower_count("urn:li:person:abc", "fake-token")

        assert count == 0


class TestFetchRecentPosts:
    def test_fetch_recent_posts_success(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "elements": [
                {"id": "urn:li:ugcPost:1", "created": {"time": 1704067200000}},
                {"id": "urn:li:ugcPost:2", "created": {"time": 1704153600000}},
            ]
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("src.linkedin_api.requests.get", return_value=mock_resp):
            posts = fetch_recent_posts("urn:li:person:abc", "fake-token", max_posts=5)

        assert len(posts) == 2
        assert posts[0]["id"] == "urn:li:ugcPost:1"

    def test_fetch_recent_posts_403_returns_empty(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 403

        with patch("src.linkedin_api.requests.get", return_value=mock_resp):
            posts = fetch_recent_posts("urn:li:person:abc", "fake-token")

        assert posts == []


class TestFetchPostEngagement:
    def test_fetch_engagement_success(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "likes": {"paging": {"total": 42}},
            "comments": {"paging": {"total": 7}},
            "shares": {"paging": {"total": 3}},
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("src.linkedin_api.requests.get", return_value=mock_resp):
            eng = fetch_post_engagement("urn:li:ugcPost:1", "fake-token")

        assert eng == {"likes": 42, "comments": 7, "shares": 3}

    def test_fetch_engagement_404_returns_zeros(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 404

        with patch("src.linkedin_api.requests.get", return_value=mock_resp):
            eng = fetch_post_engagement("urn:li:ugcPost:1", "fake-token")

        assert eng == {"likes": 0, "comments": 0, "shares": 0}


# ---------------------------------------------------------------------------
# Save / load snapshot
# ---------------------------------------------------------------------------

class TestSaveLoadSnapshot:
    def test_save_and_load(self, tmp_path):
        path = str(tmp_path / "metrics.json")
        snap = LinkedInSnapshot(follower_count=999, connection_count=999)
        snap.post_metrics.append(
            LinkedInPostMetrics(
                post_urn="urn:li:ugcPost:1",
                post_url="https://linkedin.com/feed/update/urn:li:ugcPost:1/",
                created_at="2024-01-01T00:00:00+00:00",
                likes=5,
            )
        )
        save_snapshot(snap, path=path)

        loaded = load_latest_snapshot(path=path)
        assert loaded is not None
        assert loaded.follower_count == 999
        assert len(loaded.post_metrics) == 1
        assert loaded.post_metrics[0].likes == 5

    def test_load_nonexistent_returns_none(self, tmp_path):
        result = load_latest_snapshot(path=str(tmp_path / "nope.json"))
        assert result is None

    def test_save_caps_at_90_entries(self, tmp_path):
        path = str(tmp_path / "metrics.json")
        for i in range(100):
            save_snapshot(LinkedInSnapshot(follower_count=i), path=path)
        with open(path) as f:
            history = json.load(f)
        assert len(history) == 90
        # Most recent entry should be the last one saved
        assert history[-1]["follower_count"] == 99
