"""
LinkedIn API polling — fetches post engagement metrics and follower count.

Authentication:
    Requires a LinkedIn OAuth 2.0 access token with these scopes:
        - r_liteprofile        → read your own profile URN
        - r_member_social      → read your own posts and their engagement
        - r_1st_connections_size → read your connection/follower count

    Set the token in the environment:
        export LINKEDIN_ACCESS_TOKEN="AQV..."

    To obtain a token, create a LinkedIn App at https://www.linkedin.com/developers/
    and complete the Authorization Code Flow.  Store the long-lived token as the
    repository secret LINKEDIN_ACCESS_TOKEN.

Usage (CLI):
    python -m src.agent linkedin-poll

    This command:
      1. Fetches your current follower/connection count
      2. Lists your most recent posts (up to --max-posts, default 10)
      3. Fetches engagement stats (likes, comments, shares) for each post
      4. Writes a linkedin_metrics.json snapshot for the learning state
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import requests

logger = logging.getLogger(__name__)

LINKEDIN_API = "https://api.linkedin.com/v2"
LINKEDIN_REST_API = "https://api.linkedin.com/rest"

# LinkedIn API version header required for newer REST endpoints
_LINKEDIN_VERSION = "202401"


def _headers(access_token: str) -> dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "X-Restli-Protocol-Version": "2.0.0",
        "LinkedIn-Version": _LINKEDIN_VERSION,
    }


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class LinkedInProfile:
    """Basic LinkedIn profile data."""
    person_urn: str                      # e.g. "urn:li:person:abcXYZ"
    first_name: str
    last_name: str


@dataclass
class LinkedInPostMetrics:
    """Engagement metrics for a single LinkedIn post."""
    post_urn: str                        # e.g. "urn:li:ugcPost:12345"
    post_url: str                        # https://www.linkedin.com/feed/update/...
    created_at: str                      # ISO 8601
    likes: int = 0
    comments: int = 0
    shares: int = 0
    impressions: int = 0
    clicks: int = 0

    @property
    def engagement_score(self) -> float:
        """Mirrors the engagement score formula used in AnalyticsSnapshot."""
        return (
            self.likes * 1
            + self.comments * 3
            + self.shares * 3
            + self.impressions * 0
            + self.clicks * 2
        )

    def to_dict(self) -> dict:
        return {
            "post_urn": self.post_urn,
            "post_url": self.post_url,
            "created_at": self.created_at,
            "likes": self.likes,
            "comments": self.comments,
            "shares": self.shares,
            "impressions": self.impressions,
            "clicks": self.clicks,
            "engagement_score": self.engagement_score,
        }


@dataclass
class LinkedInSnapshot:
    """Full snapshot of LinkedIn account metrics at a point in time."""
    recorded_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    follower_count: int = 0
    connection_count: int = 0
    post_metrics: list[LinkedInPostMetrics] = field(default_factory=list)
    auth_error: bool = False

    def to_dict(self) -> dict:
        return {
            "recorded_at": self.recorded_at,
            "follower_count": self.follower_count,
            "connection_count": self.connection_count,
            "post_metrics": [p.to_dict() for p in self.post_metrics],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

def fetch_profile(access_token: str) -> LinkedInProfile:
    """Fetch the authenticated user's LinkedIn profile URN and name."""
    url = f"{LINKEDIN_API}/me"
    params = {"projection": "(id,localizedFirstName,localizedLastName)"}
    resp = requests.get(url, headers=_headers(access_token), params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return LinkedInProfile(
        person_urn=f"urn:li:person:{data['id']}",
        first_name=data.get("localizedFirstName", ""),
        last_name=data.get("localizedLastName", ""),
    )


# ---------------------------------------------------------------------------
# Follower / connection count
# ---------------------------------------------------------------------------

def fetch_follower_count(person_urn: str, access_token: str) -> int:
    """
    Fetch the number of first-degree connections for the authenticated user.

    LinkedIn does not expose personal follower counts via a public API endpoint
    for non-creator-mode profiles.  The most reliable proxy is the connection
    count returned by:
        GET /rest/connections?q=viewer&start=0&count=0

    If the `r_1st_connections_size` scope is granted the `paging.total` field
    returns the exact count.
    """
    url = f"{LINKEDIN_REST_API}/connections"
    params = {"q": "viewer", "start": 0, "count": 0}
    resp = requests.get(url, headers=_headers(access_token), params=params, timeout=30)
    if resp.status_code == 403:
        logger.warning(
            "LinkedIn follower count unavailable: r_1st_connections_size scope not granted. "
            "Grant this scope in your LinkedIn app permissions."
        )
        return 0
    resp.raise_for_status()
    data = resp.json()
    return data.get("paging", {}).get("total", 0)


# ---------------------------------------------------------------------------
# Posts
# ---------------------------------------------------------------------------

def fetch_recent_posts(person_urn: str, access_token: str, max_posts: int = 10) -> list[dict]:
    """
    List the authenticated user's most recent UGC posts (text + article posts).

    Returns a list of raw UGC post dicts from the LinkedIn API.
    """
    url = f"{LINKEDIN_API}/ugcPosts"
    params = {
        "q": "authors",
        "authors": f"List({person_urn})",
        "count": max_posts,
        "start": 0,
    }
    resp = requests.get(url, headers=_headers(access_token), params=params, timeout=30)
    if resp.status_code == 403:
        logger.warning(
            "LinkedIn posts unavailable: r_member_social scope not granted. "
            "Grant r_member_social in your LinkedIn app permissions."
        )
        return []
    resp.raise_for_status()
    data = resp.json()
    return data.get("elements", [])


def _post_urn_to_url(post_urn: str) -> str:
    """Convert a UGC post URN to a public LinkedIn URL."""
    # urn:li:ugcPost:12345  →  https://www.linkedin.com/feed/update/urn:li:ugcPost:12345/
    return f"https://www.linkedin.com/feed/update/{post_urn}/"


def _parse_created_at(post: dict) -> str:
    """Extract ISO-8601 creation timestamp from a UGC post dict."""
    ts_ms = post.get("created", {}).get("time", 0)
    if ts_ms:
        return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat()
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Post engagement (likes, comments, shares)
# ---------------------------------------------------------------------------

def fetch_post_engagement(post_urn: str, access_token: str) -> dict:
    """
    Fetch likes, comments, and shares for a single post via the socialActions API.

    Returns a dict with keys: likes, comments, shares.
    """
    encoded_urn = requests.utils.quote(post_urn, safe="")
    url = f"{LINKEDIN_API}/socialActions/{encoded_urn}"
    params = {"projection": "(likes,comments,shares)"}
    resp = requests.get(url, headers=_headers(access_token), params=params, timeout=30)
    if resp.status_code in (403, 404):
        logger.debug("Could not fetch engagement for %s (status=%s)", post_urn, resp.status_code)
        return {"likes": 0, "comments": 0, "shares": 0}
    resp.raise_for_status()
    data = resp.json()
    return {
        "likes": data.get("likes", {}).get("paging", {}).get("total", 0),
        "comments": data.get("comments", {}).get("paging", {}).get("total", 0),
        "shares": data.get("shares", {}).get("paging", {}).get("total", 0),
    }


def fetch_post_impressions(post_urn: str, access_token: str) -> int:
    """
    Fetch impression count for a post via the organizationalEntityShareStatistics or
    shareStatistics API.

    Returns 0 if the endpoint is unavailable (impressions are only accessible for
    posts made via the Marketing API or Organization pages).
    """
    url = f"{LINKEDIN_API}/shareStatistics"
    params = {"q": "organizationalEntity", "share": post_urn}
    resp = requests.get(url, headers=_headers(access_token), params=params, timeout=30)
    if resp.status_code in (400, 403, 404):
        return 0
    try:
        resp.raise_for_status()
        data = resp.json()
        elements = data.get("elements", [])
        if elements:
            total_stats = elements[0].get("totalShareStatistics", {})
            return total_stats.get("impressionCount", 0)
    except Exception:
        pass
    return 0


# ---------------------------------------------------------------------------
# Main poll function
# ---------------------------------------------------------------------------

def poll_linkedin(access_token: str, max_posts: int = 10) -> LinkedInSnapshot:
    """
    Full LinkedIn poll: profile → follower count → recent posts → engagement.

    Returns a LinkedInSnapshot with all collected metrics.
    """
    logger.info("Starting LinkedIn poll (max_posts=%d)…", max_posts)

    snapshot = LinkedInSnapshot()

    # Step 1: Profile (need the URN for subsequent calls)
    try:
        profile = fetch_profile(access_token)
        logger.info("LinkedIn profile: %s %s (%s)", profile.first_name, profile.last_name, profile.person_urn)
    except requests.HTTPError as exc:
        status_code = getattr(exc.response, "status_code", None)
        if status_code in (401, 403):
            logger.error(
                "LinkedIn authentication failed (HTTP %s). "
                "Your LINKEDIN_ACCESS_TOKEN is likely expired or invalid. "
                "Refresh it and update the GitHub secret.",
                status_code,
            )
            print(
                f"\n❌ LinkedIn API authentication failed (HTTP {status_code}).\n"
                "Your access token is expired or invalid.\n"
                "Refresh it via the OAuth flow and update LINKEDIN_ACCESS_TOKEN in GitHub Secrets.",
                file=sys.stderr,
            )
        else:
            logger.error("Failed to fetch LinkedIn profile: %s", exc)
        snapshot.auth_error = True
        return snapshot

    # Step 2: Follower / connection count
    try:
        snapshot.connection_count = fetch_follower_count(profile.person_urn, access_token)
        # LinkedIn exposes follower count for creator-mode profiles via the same endpoint
        snapshot.follower_count = snapshot.connection_count
        logger.info("LinkedIn connections/followers: %d", snapshot.follower_count)
    except requests.HTTPError as exc:
        logger.warning("Could not fetch follower count: %s", exc)

    # Step 3: Recent posts
    posts = []
    try:
        posts = fetch_recent_posts(profile.person_urn, access_token, max_posts=max_posts)
        logger.info("Fetched %d LinkedIn posts", len(posts))
    except requests.HTTPError as exc:
        logger.warning("Could not fetch LinkedIn posts: %s", exc)

    # Step 4: Engagement per post
    for post in posts:
        post_urn = post.get("id", "")
        if not post_urn:
            continue

        try:
            engagement = fetch_post_engagement(post_urn, access_token)
        except Exception as exc:
            logger.warning("Engagement fetch failed for %s: %s", post_urn, exc)
            engagement = {"likes": 0, "comments": 0, "shares": 0}

        impressions = 0
        try:
            impressions = fetch_post_impressions(post_urn, access_token)
        except Exception:
            pass

        metrics = LinkedInPostMetrics(
            post_urn=post_urn,
            post_url=_post_urn_to_url(post_urn),
            created_at=_parse_created_at(post),
            likes=engagement["likes"],
            comments=engagement["comments"],
            shares=engagement["shares"],
            impressions=impressions,
        )
        snapshot.post_metrics.append(metrics)
        logger.info(
            "  Post %s: likes=%d, comments=%d, shares=%d, impressions=%d",
            post_urn,
            metrics.likes,
            metrics.comments,
            metrics.shares,
            metrics.impressions,
        )

    return snapshot


def save_snapshot(snapshot: LinkedInSnapshot, path: str = "linkedin_metrics.json") -> None:
    """Append the snapshot to a JSON file, keeping the last 90 days of history."""
    import json as _json
    from pathlib import Path

    file_path = Path(path)
    history: list[dict] = []

    if file_path.exists():
        try:
            with file_path.open() as f:
                history = _json.load(f)
        except (_json.JSONDecodeError, ValueError):
            history = []

    history.append(snapshot.to_dict())

    # Keep only the most recent 90 entries (≈ 3 months of daily runs)
    history = history[-90:]

    with file_path.open("w") as f:
        _json.dump(history, f, indent=2)

    logger.info("LinkedIn snapshot saved to %s (%d entries)", path, len(history))


def load_latest_snapshot(path: str = "linkedin_metrics.json") -> Optional[LinkedInSnapshot]:
    """Load the most recent LinkedIn snapshot from the history file."""
    import json as _json
    from pathlib import Path

    file_path = Path(path)
    if not file_path.exists():
        return None

    try:
        with file_path.open() as f:
            history = _json.load(f)
        if not history:
            return None
        latest = history[-1]
        snap = LinkedInSnapshot(
            recorded_at=latest.get("recorded_at", ""),
            follower_count=latest.get("follower_count", 0),
            connection_count=latest.get("connection_count", 0),
        )
        for pm in latest.get("post_metrics", []):
            snap.post_metrics.append(LinkedInPostMetrics(
                post_urn=pm.get("post_urn", ""),
                post_url=pm.get("post_url", ""),
                created_at=pm.get("created_at", ""),
                likes=pm.get("likes", 0),
                comments=pm.get("comments", 0),
                shares=pm.get("shares", 0),
                impressions=pm.get("impressions", 0),
                clicks=pm.get("clicks", 0),
            ))
        return snap
    except Exception as exc:
        logger.warning("Could not load LinkedIn snapshot: %s", exc)
        return None
