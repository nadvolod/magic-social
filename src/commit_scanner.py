"""GitHub commit scanner — fetches and scores recent commits."""

from __future__ import annotations

import logging
import os
from typing import Optional

import requests

from .models import SourceCommit
from .scoring import score_commit, SCORE_THRESHOLD, is_sensitive

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


def _github_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _summarize_diff(patch: str, max_chars: int = 500) -> str:
    """
    Return a safe, truncated summary of a diff patch.

    Never returns raw code — only describes changed file patterns
    and added/removed line counts.
    """
    if not patch:
        return ""
    lines = patch.splitlines()
    added = sum(1 for l in lines if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in lines if l.startswith("-") and not l.startswith("---"))
    summary = f"+{added} lines, -{removed} lines"
    # Add structural keywords from diff without pasting actual code
    keywords = []
    for line in lines:
        stripped = line.lstrip("+-").strip().lower()
        for kw in ["def ", "class ", "async ", "await ", "import ", "raise ", "return "]:
            if stripped.startswith(kw):
                keywords.append(stripped.split("(")[0].split(":")[0].strip())
                break
    if keywords:
        summary += f"; touches: {', '.join(dict.fromkeys(keywords))[:max_chars]}"
    return summary[:max_chars]


def fetch_commits(
    repo: str,
    token: str,
    since: Optional[str] = None,
    per_page: int = 100,
    branch: str = "main",
) -> list[dict]:
    """Fetch recent commits from a GitHub repository."""
    headers = _github_headers(token)
    params: dict = {"sha": branch, "per_page": per_page}
    if since:
        params["since"] = since
    url = f"{GITHUB_API}/repos/{repo}/commits"
    response = requests.get(url, headers=headers, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def fetch_commit_detail(repo: str, sha: str, token: str) -> dict:
    """Fetch detailed information about a single commit including diff."""
    headers = _github_headers(token)
    url = f"{GITHUB_API}/repos/{repo}/commits/{sha}"
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.json()


def scan_commits(
    repo: str,
    token: str,
    since: Optional[str] = None,
    per_page: int = 100,
    branch: str = "main",
    threshold: float = SCORE_THRESHOLD,
) -> list[SourceCommit]:
    """
    Scan recent commits in a repo, score each one, and return those
    that meet the lesson-worthiness threshold.

    Args:
        repo:      Full repo name, e.g. "owner/repo".
        token:     GitHub personal access token.
        since:     ISO 8601 timestamp; only commits after this date.
        per_page:  Number of commits to fetch (max 100).
        branch:    Branch to scan.
        threshold: Minimum score to include a commit.

    Returns:
        List of SourceCommit objects sorted by score descending.
    """
    logger.info("Scanning commits for %s (branch=%s, since=%s)", repo, branch, since)
    raw_commits = fetch_commits(repo, token, since=since, per_page=per_page, branch=branch)
    results: list[SourceCommit] = []

    for raw in raw_commits:
        sha = raw["sha"]
        commit_data = raw.get("commit", {})
        message = commit_data.get("message", "").strip()
        author = commit_data.get("author", {}).get("name", "unknown")
        timestamp = commit_data.get("author", {}).get("date", "")

        # Quick pre-filter on message only (avoids extra API call)
        quick_score, _ = score_commit(message)
        if quick_score == 0.0:
            logger.debug("Skipping commit %s (pre-filter)", sha[:8])
            continue

        # Fetch full diff for detailed scoring
        try:
            detail = fetch_commit_detail(repo, sha, token)
        except requests.HTTPError as exc:
            logger.warning("Could not fetch diff for %s: %s", sha[:8], exc)
            detail = raw

        files = detail.get("files", [])
        files_changed = [f["filename"] for f in files]
        diff_summary_parts = []
        for f in files:
            patch = f.get("patch", "")
            if is_sensitive(patch):
                logger.warning("Skipping diff for %s — sensitive content detected", f["filename"])
                continue
            diff_summary_parts.append(_summarize_diff(patch))

        diff_summary = "; ".join(filter(None, diff_summary_parts))

        total_score, breakdown = score_commit(message, diff_summary, files_changed)
        if total_score < threshold:
            logger.debug("Commit %s scored %.1f — below threshold %.1f", sha[:8], total_score, threshold)
            continue

        source = SourceCommit(
            sha=sha,
            repo=repo,
            message=message,
            author=author,
            timestamp=timestamp,
            files_changed=files_changed,
            diff_summary=diff_summary,
            score=total_score,
            score_breakdown=breakdown.to_dict(),
        )
        results.append(source)
        logger.info("Commit %s scored %.1f ✓", sha[:8], total_score)

    results.sort(key=lambda c: c.score, reverse=True)
    logger.info("Found %d lesson-worthy commits out of %d scanned", len(results), len(raw_commits))
    return results
