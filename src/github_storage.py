"""GitHub Issues storage — creates and manages social post issues."""

from __future__ import annotations

import json
import logging
import re
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
    "social-screenshot": {"color": "1d76db", "description": "LinkedIn screenshot for learning/classification"},
    "screenshot:processed": {"color": "0e8a16", "description": "Screenshot has been analyzed and learned"},
    "screenshot:top10": {"color": "5319e7", "description": "Screenshot classified as top 10% performance"},
    "screenshot:bottom90": {"color": "d93f0b", "description": "Screenshot classified as bottom 90% performance"},
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

RAW_POST_JSON_RE = re.compile(
    r"Raw Post Data.*?```json\s*(\{.*?\})\s*```",
    re.IGNORECASE | re.DOTALL,
)


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
    """Build the GitHub Issue body for a social post.

    The issue is structured so the LinkedIn post is front-and-centre and
    easy to copy-paste.  X Thread and Instagram sections are omitted —
    LinkedIn is the only platform we're optimising for right now.
    """
    commit_url = f"https://github.com/{post.repo}/commit/{post.source_commit_sha}"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    experiment_section = ""
    if post.experiment_id:
        experiment_section = f"""
## 🧪 Experiment
- **Experiment ID:** `{post.experiment_id}`
- **Variant:** `{post.experiment_variant or 'control'}`
"""

    return f"""## 🔵 LinkedIn Post

<!-- Copy-paste the text below into LinkedIn -->

{post.linkedin_post}

---

## ⚡ Quick Mobile Feedback

If you're on mobile, use any one of these:

- [ ] Publish
- [ ] Rewrite
- [ ] Skip
- [ ] Too long
- [ ] Not relevant
- [ ] Weak hook

Or just react to this issue:
- 👍 good draft
- 👎 bad draft
- 🚀 published

---

## ✅ Publishing Checklist

- [ ] Review LinkedIn post for accuracy
- [ ] Verify no sensitive data, secrets, or proprietary code
- [ ] Approve content
- [ ] Publish to LinkedIn
- [ ] Record publish date/time
- [ ] Collect analytics after 48 hours

---

## 💬 Post Feedback

Whether or not you publish this post, please add a comment with your honest feedback.
This helps the agent learn your preferences and improve future posts.

Quick mobile options (copy one or two lines):
```
## Post Feedback
- Verdict: ✅ published
- Verdict: ❌ skipped
- Reason: quality
- Rating: 4
- Improve: add one concrete metric and stronger takeaway
```

Detailed option:
```
## Post Feedback — [DATE]

- Published: yes / no
- If not published, why: quality / style / not relevant / too long / too technical / other
- What would make it better: 
- Rating (1-5): 
```

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

## 📝 Post Metadata

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

<details>
<summary>🤖 Raw Post Data (JSON metadata for agent use)</summary>

```json
{post.to_json()}
```

</details>
"""


def _extract_post_json(issue_body: str) -> Optional[dict]:
    """Extract the raw Post JSON payload from the issue body."""
    if not issue_body:
        return None
    match = RAW_POST_JSON_RE.search(issue_body)
    if match is None:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def _status_from_labels(labels: list[dict]) -> Optional[PostStatus]:
    """Return status parsed from status:* labels."""
    for label in labels:
        name = label.get("name", "")
        if name.startswith("status:"):
            status_raw = name.split(":", 1)[1]
            try:
                return PostStatus(status_raw)
            except ValueError:
                return None
    return None


def list_social_post_issues(repo: str, token: str, state: str = "all") -> list[dict]:
    """Fetch social-post issues from GitHub (excluding pull requests)."""
    issues: list[dict] = []
    page = 1
    while True:
        url = f"{GITHUB_API}/repos/{repo}/issues"
        resp = requests.get(
            url,
            headers=_headers(token),
            params={"state": state, "labels": "social-post", "per_page": 100, "page": page},
            timeout=30,
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        for issue in batch:
            if "pull_request" not in issue:
                issues.append(issue)
        if len(batch) < 100:
            break
        page += 1
    return issues


def load_posts_from_issues(repo: str, token: str, state: str = "all") -> list[Post]:
    """
    Load Post objects from existing social-post issues.

    Uses embedded Raw Post Data JSON when available; falls back to minimal
    inferred fields if the JSON block is missing.
    """
    issues = list_social_post_issues(repo, token, state=state)
    posts: list[Post] = []

    for issue in issues:
        issue_number = issue["number"]
        labels = issue.get("labels", [])
        status = _status_from_labels(labels) or PostStatus.DRAFT
        issue_created = issue.get("created_at", datetime.now(timezone.utc).isoformat())
        issue_updated = issue.get("updated_at", issue_created)

        payload = _extract_post_json(issue.get("body", ""))
        if payload:
            try:
                post = Post.from_dict(payload)
            except Exception:  # noqa: BLE001
                post = Post(
                    id=f"issue-{issue_number}",
                    source_commit_sha="unknown",
                    repo=repo,
                    lesson=issue.get("title", f"Issue #{issue_number}"),
                    linkedin_post="",
                    x_thread="",
                    ig_caption="",
                    hook_pattern="result",
                )
        else:
            post = Post(
                id=f"issue-{issue_number}",
                source_commit_sha="unknown",
                repo=repo,
                lesson=issue.get("title", f"Issue #{issue_number}"),
                linkedin_post="",
                x_thread="",
                ig_caption="",
                hook_pattern="result",
            )

        post.github_issue_number = issue_number
        post.status = status
        post.created_at = post.created_at or issue_created
        if post.created_at == "":
            post.created_at = issue_created
        if post.status == PostStatus.PUBLISHED and not post.published_at:
            post.published_at = issue_updated
        posts.append(post)

    posts.sort(key=lambda p: p.created_at, reverse=True)
    return posts


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
