"""Tests for the commit scanner module."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from src.commit_scanner import (
    fetch_user_repos,
    scan_all_user_commits,
    scan_repos,
    _summarize_diff,
)


class TestFetchUserRepos:
    def _make_repo(self, name: str, owner: str = "nadvolod") -> dict:
        return {"full_name": f"{owner}/{name}", "name": name}

    def test_returns_repo_full_names(self):
        mock_response = MagicMock()
        mock_response.json.return_value = [
            self._make_repo("repo-a"),
            self._make_repo("repo-b"),
        ]
        mock_response.raise_for_status = MagicMock()
        with patch("src.commit_scanner.requests.get", return_value=mock_response):
            repos = fetch_user_repos("nadvolod", "fake-token")
        assert repos == ["nadvolod/repo-a", "nadvolod/repo-b"]

    def test_handles_empty_repo_list(self):
        mock_response = MagicMock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = MagicMock()
        with patch("src.commit_scanner.requests.get", return_value=mock_response):
            repos = fetch_user_repos("nadvolod", "fake-token")
        assert repos == []

    def test_paginates_until_empty_page(self):
        """Should stop pagination when an empty page is returned."""
        responses = [
            MagicMock(
                json=MagicMock(return_value=[self._make_repo(f"repo-{i}") for i in range(3)]),
                raise_for_status=MagicMock(),
            ),
            MagicMock(
                json=MagicMock(return_value=[]),
                raise_for_status=MagicMock(),
            ),
        ]
        with patch("src.commit_scanner.requests.get", side_effect=responses):
            repos = fetch_user_repos("nadvolod", "fake-token", per_page=3)
        assert len(repos) == 3

    def test_paginates_when_full_page_returned(self):
        """Should fetch next page when a full page of results is returned."""
        page1 = [self._make_repo(f"repo-{i}") for i in range(2)]
        page2 = [self._make_repo(f"repo-{i}") for i in range(2, 3)]
        responses = [
            MagicMock(json=MagicMock(return_value=page1), raise_for_status=MagicMock()),
            MagicMock(json=MagicMock(return_value=page2), raise_for_status=MagicMock()),
            MagicMock(json=MagicMock(return_value=[]), raise_for_status=MagicMock()),
        ]
        with patch("src.commit_scanner.requests.get", side_effect=responses):
            repos = fetch_user_repos("nadvolod", "fake-token", per_page=2)
        assert len(repos) == 3

    def test_raises_on_http_error(self):
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.HTTPError("404")
        with patch("src.commit_scanner.requests.get", return_value=mock_response):
            with pytest.raises(requests.HTTPError):
                fetch_user_repos("nadvolod", "fake-token")


class TestScanAllUserCommits:
    def _make_repo_response(self, names):
        mock = MagicMock()
        mock.json.return_value = [{"full_name": f"nadvolod/{n}"} for n in names]
        mock.raise_for_status = MagicMock()
        return mock

    def test_aggregates_commits_across_repos(self):
        """Commits from all repos should be combined and sorted by score."""
        with (
            patch("src.commit_scanner.fetch_user_repos", return_value=["nadvolod/a", "nadvolod/b"]),
            patch("src.commit_scanner.scan_commits") as mock_scan,
        ):
            from src.models import SourceCommit
            commit_a = SourceCommit(
                sha="aaa", repo="nadvolod/a", message="feat: add X", author="n", timestamp="", score=80.0
            )
            commit_b = SourceCommit(
                sha="bbb", repo="nadvolod/b", message="feat: add Y", author="n", timestamp="", score=60.0
            )
            mock_scan.side_effect = [[commit_a], [commit_b]]
            results = scan_all_user_commits("nadvolod", "fake-token")

        assert len(results) == 2
        # Should be sorted by score descending
        assert results[0].score == 80.0
        assert results[1].score == 60.0

    def test_skips_repo_on_http_error(self):
        """A failing repo should be skipped without raising."""
        with (
            patch("src.commit_scanner.fetch_user_repos", return_value=["nadvolod/ok", "nadvolod/bad"]),
            patch("src.commit_scanner.scan_commits") as mock_scan,
        ):
            from src.models import SourceCommit
            good_commit = SourceCommit(
                sha="aaa", repo="nadvolod/ok", message="feat: works", author="n", timestamp="", score=50.0
            )
            mock_scan.side_effect = [[good_commit], requests.HTTPError("403")]
            results = scan_all_user_commits("nadvolod", "fake-token")

        assert len(results) == 1
        assert results[0].sha == "aaa"

    def test_returns_empty_when_no_repos(self):
        with (
            patch("src.commit_scanner.fetch_user_repos", return_value=[]),
            patch("src.commit_scanner.scan_commits") as mock_scan,
        ):
            results = scan_all_user_commits("nadvolod", "fake-token")
        mock_scan.assert_not_called()
        assert results == []

    def test_passes_since_and_branch_to_scan_commits(self):
        with (
            patch("src.commit_scanner.fetch_user_repos", return_value=["nadvolod/repo"]),
            patch("src.commit_scanner.scan_commits", return_value=[]) as mock_scan,
        ):
            scan_all_user_commits(
                "nadvolod", "tok", since="2024-01-01T00:00:00Z", branch="develop", threshold=20.0
            )
        mock_scan.assert_called_once_with(
            "nadvolod/repo",
            "tok",
            since="2024-01-01T00:00:00Z",
            per_page=100,
            branch="develop",
            threshold=20.0,
        )


class TestScanRepos:
    def test_scan_repos_aggregates_results(self):
        """Scanning 2 repos returns commits from both, sorted by score."""
        from src.models import SourceCommit
        commit_a = SourceCommit(
            sha="aaa", repo="nadvolod/LifeNotes", message="feat: X", author="n", timestamp="", score=80.0
        )
        commit_b = SourceCommit(
            sha="bbb", repo="nadvolod/temporal-learning", message="feat: Y", author="n", timestamp="", score=60.0
        )
        with patch("src.commit_scanner.scan_commits") as mock_scan:
            mock_scan.side_effect = [[commit_a], [commit_b]]
            results = scan_repos(
                ["nadvolod/LifeNotes", "nadvolod/temporal-learning"],
                "fake-token",
            )
        assert len(results) == 2
        assert results[0].score == 80.0
        assert results[1].score == 60.0
        assert mock_scan.call_count == 2

    def test_scan_repos_skips_failing_repo(self):
        """If one repo 404s, others still scan."""
        from src.models import SourceCommit
        good = SourceCommit(
            sha="aaa", repo="nadvolod/LifeNotes", message="feat: X", author="n", timestamp="", score=50.0
        )
        with patch("src.commit_scanner.scan_commits") as mock_scan:
            mock_scan.side_effect = [[good], requests.HTTPError("404")]
            results = scan_repos(
                ["nadvolod/LifeNotes", "nadvolod/temporal-learning"],
                "fake-token",
            )
        assert len(results) == 1
        assert results[0].repo == "nadvolod/LifeNotes"

    def test_scan_repos_sorts_combined_results(self):
        """Combined list must be sorted by score descending."""
        from src.models import SourceCommit
        commits = [
            [SourceCommit(sha="c", repo="r1", message="m", author="n", timestamp="", score=30.0)],
            [SourceCommit(sha="a", repo="r2", message="m", author="n", timestamp="", score=90.0)],
        ]
        with patch("src.commit_scanner.scan_commits") as mock_scan:
            mock_scan.side_effect = commits
            results = scan_repos(["r1", "r2"], "token")
        assert results[0].score == 90.0
        assert results[1].score == 30.0


class TestSummarizeDiff:
    def test_empty_patch(self):
        assert _summarize_diff("") == ""

    def test_counts_added_removed_lines(self):
        patch = "+new line\n-old line\n context"
        summary = _summarize_diff(patch)
        assert "+1 lines" in summary
        assert "-1 lines" in summary

    def test_truncates_long_summary(self):
        patch = "+def " + "x" * 600
        summary = _summarize_diff(patch, max_chars=50)
        assert len(summary) <= 50
