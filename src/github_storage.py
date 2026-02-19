"""GitHub Issues storage — creates and manages social post issues."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

import requests

from .models import AnalyticsSnapshot, Post, PostStatus

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"

# Standard labels applied to every social post issue
BASE_LABELS = ["social-post"]

# Label names and their descriptions (created on first run)
LABEL_DEFINITIONS = {
    "social-post": {"color": "0075ca", "description": "AI-generated social media post"},
    "status:draft": {"color": "e4e669", "description": "Post is a draft awaiting approval"},
    "status:approved": {"color": "0e8a16", "description": "Post approved for publishing"},
    "status:published": {"color": "006b75", "description": "Post has been published"},
    "status:archived": {"color": "cfd3d7", "description": "Post archived, not published"},
    "platform:linkedin": {"color": "0a66c2", "description": "LinkedIn post"},
    "platform:x": {"color": "000000", "description": "X (Twitter) thread"},
    "platform:instagram": {"color": "e1306c", "description": "Instagram caption"},
    "analytics:pending": {"color": "fbca04", "description": "Analytics not yet collected"},
    "analytics:collected": {"color": "28a745", "description": "Analytics collected"},
    "ai": {"color": "7057ff", "description": "AI / LLM topic"},
    "distributed-systems": {"color": "e4e669", "description": "Distributed systems topic"},
    "testing": {"color": "0075ca", "description": "Testing / automation topic"},
    "performance": {"color": "d93f0b", "description": "Performance topic"},
    "reliability": {"color": "b60205", "description": "Reliability topic"},
    "career": {"color": "5319e7", "description": "Career / learning topic"},
    "engineering": {"color": "006b75", "description": "General engineering topic"},
    "experiment": {"color": "f9d0c4", "description": "Part of an A/B experiment"},
}


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def ensure_labels(repo: str, token: str) -> None:
    """Create any missing labels in the repository."""
    existing = _list_labels(repo, token)
    existing_names = {l["name"] for l in existing}
    for name, meta in LABEL_DEFINITIONS.items():
        if name not in existing_names:
            _create_label(repo, token, name, meta["color"], meta["description"])


def _list_labels(repo: str, token: str) -> list[dict]:
    url = f"{GITHUB_API}/repos/{repo}/labels"
    resp = requests.get(url, headers=_headers(token), params={"per_page": 100}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _create_label(repo: str, token: str, name: str, color: str, description: str) -> None:
    url = f"{GITHUB_API}/repos/{repo}/labels"
    payload = {"name": name, "color": color, "description": description}
    resp = requests.post(url, headers=_headers(token), json=payload, timeout=30)
    if resp.status_code == 422:
        logger.debug("Label '%s' already exists", name)
    else:
        resp.raise_for_status()
        logger.info("Created label '%s'", name)


def _build_issue_body(post: Post) -> str:
    """Build the GitHub Issue body for a social post."""
    commit_url = f"https://github.com/{post.repo}/commit/{post.source_commit_sha}"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    experiment_section = ""
    if post.experiment_id:
        experiment_section = f"""
## 🧪 Experiment
- **Experiment ID:** `{post.experiment_id}`
- **Variant:** `{post.experiment_variant or 'control'}`
"""

    return f"""## 📝 Post Metadata

| Field | Value |
|-------|-------|
| **Post ID** | `{post.id}` |
| **Source Commit** | [{post.source_commit_sha[:8]}]({commit_url}) |
| **Repository** | `{post.repo}` |
| **Hook Pattern** | `{post.hook_pattern}` |
| **Tags** | {', '.join(f'`{t}`' for t in post.tags)} |
| **Created** | {now} |
| **Status** | `{post.status.value}` |

## 💡 Lesson

{post.lesson}
{experiment_section}
---

## 🔵 LinkedIn Post

<!-- Copy-paste this into LinkedIn -->

{post.linkedin_post}

---

## 🐦 X Thread

<!-- Optional: post as a thread on X -->

{post.x_thread}

---

## 📸 Instagram Caption

<!-- Strategic only — pair with a high-quality visual. Best time: 12PM EST -->

{post.ig_caption}

---

## ✅ Publishing Checklist

- [ ] Review LinkedIn post for accuracy
- [ ] Verify no sensitive data, secrets, or proprietary code
- [ ] Approve content
- [ ] Publish to LinkedIn
- [ ] Record publish date/time
- [ ] (Optional) Post X thread
- [ ] (Optional) Post Instagram caption with visual
- [ ] Collect analytics after 48 hours
- [ ] Update analytics in this issue (see template below)

---

## 📊 Analytics Input Template

After publishing, add a comment to this issue with your metrics:

```
## Analytics Update — [DATE]

- Impressions: 
- Reactions: 
- Comments: 
- Reposts: 
- Saves: 
- Follower delta: 
- Click-through: 
- Notes: 
```

---

## 🤖 Raw Post Data

<details>
<summary>JSON metadata (for agent use)</summary>

```json
{post.to_json()}
```

</details>
"""


def create_post_issue(
    post: Post,
    repo: str,
    token: str,
    ensure_labels_exist: bool = True,
) -> int:
    """
    Create a GitHub Issue for the given post.

    Returns the issue number.
    """
    if ensure_labels_exist:
        ensure_labels(repo, token)

    title = f"[Social Post] {post.lesson[:80]}"
    body = _build_issue_body(post)

    labels = list(BASE_LABELS)
    labels.append(f"status:{post.status.value}")
    labels.append("platform:linkedin")
    labels.append("analytics:pending")
    labels.extend(post.tags)
    if post.experiment_id:
        labels.append("experiment")

    # Filter to only labels that exist in LABEL_DEFINITIONS
    valid_labels = [l for l in labels if l in LABEL_DEFINITIONS]

    url = f"{GITHUB_API}/repos/{repo}/issues"
    payload = {"title": title, "body": body, "labels": valid_labels}
    resp = requests.post(url, headers=_headers(token), json=payload, timeout=30)
    resp.raise_for_status()

    issue_number = resp.json()["number"]
    logger.info("Created GitHub Issue #%d for post %s", issue_number, post.id)
    return issue_number


def update_issue_status(
    repo: str,
    token: str,
    issue_number: int,
    new_status: PostStatus,
) -> None:
    """Update the status label on an existing issue."""
    # Remove old status labels
    old_labels = [f"status:{s.value}" for s in PostStatus]
    _remove_labels(repo, token, issue_number, old_labels)

    # Add new status label
    url = f"{GITHUB_API}/repos/{repo}/issues/{issue_number}/labels"
    resp = requests.post(
        url,
        headers=_headers(token),
        json={"labels": [f"status:{new_status.value}"]},
        timeout=30,
    )
    resp.raise_for_status()
    logger.info("Updated Issue #%d status to %s", issue_number, new_status.value)


def _remove_labels(repo: str, token: str, issue_number: int, labels: list[str]) -> None:
    for label in labels:
        url = f"{GITHUB_API}/repos/{repo}/issues/{issue_number}/labels/{requests.utils.quote(label)}"
        resp = requests.delete(url, headers=_headers(token), timeout=30)
        if resp.status_code not in (200, 404):
            logger.warning("Could not remove label '%s' from issue #%d: %s", label, issue_number, resp.status_code)


def add_analytics_comment(
    repo: str,
    token: str,
    issue_number: int,
    analytics: AnalyticsSnapshot,
) -> None:
    """Add an analytics update comment to a post issue."""
    body = f"""## 📊 Analytics Update — {analytics.recorded_at[:10]}

| Metric | Value |
|--------|-------|
| Impressions | {analytics.impressions:,} |
| Reactions | {analytics.reactions:,} |
| Comments | {analytics.comments:,} |
| Reposts | {analytics.reposts:,} |
| Saves | {analytics.saves:,} |
| Follower delta | {analytics.follower_delta:+,} |
| Click-through | {analytics.click_through:,} |
| **Engagement score** | **{analytics.engagement_score:.1f}** |
| **Engagement rate** | **{analytics.engagement_rate:.2f}%** |

<details>
<summary>Raw JSON</summary>

```json
{analytics.to_json()}
```

</details>
"""
    url = f"{GITHUB_API}/repos/{repo}/issues/{issue_number}/comments"
    resp = requests.post(url, headers=_headers(token), json={"body": body}, timeout=30)
    resp.raise_for_status()

    # Update analytics label
    _remove_labels(repo, token, issue_number, ["analytics:pending"])
    label_url = f"{GITHUB_API}/repos/{repo}/issues/{issue_number}/labels"
    requests.post(label_url, headers=_headers(token), json={"labels": ["analytics:collected"]}, timeout=30)

    logger.info("Added analytics comment to Issue #%d (score=%.1f)", issue_number, analytics.engagement_score)


def get_analytics_request_message(post: Post, issue_number: int, repo: str) -> str:
    """Return a message prompting the user to input analytics for a post."""
    issue_url = f"https://github.com/{repo}/issues/{issue_number}"
    return f"""
📊 **Analytics Request for Post #{issue_number}**

It's been 48+ hours since you published this post.
Please add your metrics to the GitHub Issue.

Post: {post.lesson[:80]}
Issue: {issue_url}

Add a comment with:
```
## Analytics Update — {datetime.now(timezone.utc).strftime("%Y-%m-%d")}

- Impressions: 
- Reactions: 
- Comments: 
- Reposts: 
- Saves: 
- Follower delta: 
- Click-through: 
- Notes: 
```

These metrics help the agent improve future post selection and writing quality.
    """.strip()
