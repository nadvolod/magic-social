"""Analytics collection, parsing, and learning loop."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

import requests

from .models import AnalyticsSnapshot, Post, PostFeedback

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"

# Default scoring weights (adjusted by the learning loop)
DEFAULT_WEIGHTS = {
    "novelty": 1.0,
    "impact": 1.0,
    "teachability": 1.0,
    "relevance": 1.0,
    "proof": 1.0,
}

# Metric keys expected in analytics comments
METRIC_KEYS = [
    "impressions",
    "reactions",
    "comments",
    "reposts",
    "saves",
    "follower_delta",
    "click_through",
]


def _github_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


# -------------------------------------------------------------------
# Parsing analytics from issue comments
# -------------------------------------------------------------------

def parse_analytics_from_comment(comment_body: str, post_id: str, issue_number: int) -> Optional[AnalyticsSnapshot]:
    """
    Parse an analytics update comment and return an AnalyticsSnapshot.

    Expected format (case-insensitive):
        Impressions: 1234
        Reactions: 56
        ...
    """
    if "Analytics Update" not in comment_body:
        return None

    metrics: dict = {}
    for key in METRIC_KEYS:
        # Match "key: value" (with optional spaces and commas in number)
        # Support both underscore and hyphen separators (e.g. click_through / click-through)
        key_pattern = key.replace('_', '[_\\- ]')
        pattern = rf"{key_pattern}[:\s]+([+-]?[\d,]+)"
        match = re.search(pattern, comment_body, re.IGNORECASE)
        if match:
            try:
                value = int(match.group(1).replace(",", ""))
                metrics[key] = value
            except ValueError:
                metrics[key] = 0
        else:
            metrics[key] = 0

    return AnalyticsSnapshot(
        post_id=post_id,
        github_issue_number=issue_number,
        **metrics,
    )


def fetch_issue_analytics(
    repo: str,
    token: str,
    issue_number: int,
    post_id: str,
) -> Optional[AnalyticsSnapshot]:
    """
    Fetch analytics from a GitHub Issue by reading its comments.

    Returns the most recent analytics comment parsed as an AnalyticsSnapshot.
    """
    url = f"{GITHUB_API}/repos/{repo}/issues/{issue_number}/comments"
    resp = requests.get(url, headers=_github_headers(token), timeout=30)
    resp.raise_for_status()
    comments = resp.json()

    snapshots = []
    for comment in comments:
        body = comment.get("body", "")
        snap = parse_analytics_from_comment(body, post_id, issue_number)
        if snap:
            snapshots.append(snap)

    if not snapshots:
        return None

    # Return the most recently recorded snapshot
    return sorted(snapshots, key=lambda s: s.recorded_at, reverse=True)[0]


# -------------------------------------------------------------------
# Parsing qualitative post feedback from issue comments
# -------------------------------------------------------------------

def parse_feedback_from_comment(comment_body: str, post_id: str) -> Optional[PostFeedback]:
    """
    Parse a post feedback comment and return a PostFeedback object.

    Expected format (case-insensitive):
        ## Post Feedback — [DATE]
        - Published: yes / no
        - If not published, why: quality / style / not relevant / other
        - What would make it better: <free text>
        - Rating (1-5): 4
    """
    if "Post Feedback" not in comment_body:
        return None

    def _first_match(pattern: str) -> Optional[str]:
        m = re.search(pattern, comment_body, re.IGNORECASE)
        return m.group(1).strip() if m else None

    published_raw = _first_match(r"published[:\s]+([^\n]+)")
    published: Optional[bool] = None
    if published_raw:
        if re.search(r"\byes\b", published_raw, re.IGNORECASE):
            published = True
        elif re.search(r"\bno\b", published_raw, re.IGNORECASE):
            published = False

    not_published_reason = _first_match(r"(?:if not published,? why|why not)[:\s]+([^\n]+)")
    improvement_notes = _first_match(r"(?:what would make it better|improvement)[:\s]+([^\n]+)")

    rating: Optional[int] = None
    rating_raw = _first_match(r"rating[^:]*:[:\s]+([1-5])")
    if rating_raw:
        try:
            rating = int(rating_raw)
        except ValueError:
            pass

    return PostFeedback(
        post_id=post_id,
        published=published,
        not_published_reason=not_published_reason,
        improvement_notes=improvement_notes,
        rating=rating,
    )


def fetch_issue_feedback(
    repo: str,
    token: str,
    issue_number: int,
    post_id: str,
) -> Optional[PostFeedback]:
    """
    Fetch qualitative feedback from a GitHub Issue by reading its comments.

    Returns the most recent feedback comment parsed as a PostFeedback object.
    """
    url = f"{GITHUB_API}/repos/{repo}/issues/{issue_number}/comments"
    resp = requests.get(url, headers=_github_headers(token), timeout=30)
    resp.raise_for_status()
    comments = resp.json()

    latest_feedback: Optional[PostFeedback] = None
    for comment in comments:
        body = comment.get("body", "")
        fb = parse_feedback_from_comment(body, post_id)
        if fb:
            # Keep the last matching feedback based on the API's comment ordering
            latest_feedback = fb

    if latest_feedback is None:
        return None

    return latest_feedback
# -------------------------------------------------------------------
# Learning loop — adjusts scoring weights based on analytics
# -------------------------------------------------------------------

@dataclass
class LearningState:
    """
    Persisted state of the learning loop.

    Stored as a JSON file (or in a GitHub Gist in production).
    """

    scoring_weights: dict = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    hook_pattern_scores: dict = field(default_factory=dict)
    topic_scores: dict = field(default_factory=dict)
    best_performing_posts: list[str] = field(default_factory=list)
    total_posts_analyzed: int = 0
    # Qualitative feedback tracking
    not_published_reasons: dict = field(default_factory=dict)   # reason → count
    total_feedback_received: int = 0
    total_ratings_received: int = 0
    average_rating: float = 0.0
    version: int = 1

    def to_dict(self) -> dict:
        return {
            "scoring_weights": self.scoring_weights,
            "hook_pattern_scores": self.hook_pattern_scores,
            "topic_scores": self.topic_scores,
            "best_performing_posts": self.best_performing_posts,
            "total_posts_analyzed": self.total_posts_analyzed,
            "not_published_reasons": self.not_published_reasons,
            "total_feedback_received": self.total_feedback_received,
            "total_ratings_received": self.total_ratings_received,
            "average_rating": self.average_rating,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LearningState":
        return cls(
            scoring_weights=data.get("scoring_weights", dict(DEFAULT_WEIGHTS)),
            hook_pattern_scores=data.get("hook_pattern_scores", {}),
            topic_scores=data.get("topic_scores", {}),
            best_performing_posts=data.get("best_performing_posts", []),
            total_posts_analyzed=data.get("total_posts_analyzed", 0),
            not_published_reasons=data.get("not_published_reasons", {}),
            total_feedback_received=data.get("total_feedback_received", 0),
            total_ratings_received=data.get("total_ratings_received", 0),
            average_rating=data.get("average_rating", 0.0),
            version=data.get("version", 1),
        )

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: str) -> "LearningState":
        try:
            with open(path) as f:
                return cls.from_dict(json.load(f))
        except (FileNotFoundError, json.JSONDecodeError):
            return cls()


# Guardrail: maximum multiplier for any single weight to prevent overfitting
MAX_WEIGHT_MULTIPLIER = 3.0
MIN_WEIGHT_MULTIPLIER = 0.2
# Minimum posts required before adjusting weights
MIN_POSTS_FOR_LEARNING = 3


def update_learning_state(
    state: LearningState,
    post: Post,
    analytics: AnalyticsSnapshot,
    feedback: Optional[PostFeedback] = None,
) -> LearningState:
    """
    Update scoring weights and pattern scores based on post performance.

    The learning loop adjusts:
    1. Scoring dimension weights (proof, novelty, etc.) — dimensions that
       correlate with high engagement get a modest boost.
    2. Hook pattern scores — patterns that produce high-engagement posts
       are preferred for future generation.
    3. Topic scores — topics with high engagement are prioritized.
    4. Qualitative feedback — not-published reasons and ratings inform
       post generation quality over time.

    Guardrails:
    - Weight adjustments are capped to avoid overfitting.
    - Adjustments are gradual (smooth step size).
    - Requires MIN_POSTS_FOR_LEARNING posts before making adjustments.
    """
    state.total_posts_analyzed += 1

    # Record hook pattern performance
    hook = post.hook_pattern
    if hook not in state.hook_pattern_scores:
        state.hook_pattern_scores[hook] = {"count": 0, "total_score": 0.0}
    state.hook_pattern_scores[hook]["count"] += 1
    state.hook_pattern_scores[hook]["total_score"] += analytics.engagement_score

    # Record topic performance
    for tag in post.tags:
        if tag not in state.topic_scores:
            state.topic_scores[tag] = {"count": 0, "total_score": 0.0}
        state.topic_scores[tag]["count"] += 1
        state.topic_scores[tag]["total_score"] += analytics.engagement_score

    # Track best performing posts
    if analytics.engagement_score > 0:
        state.best_performing_posts.append(post.id)
        state.best_performing_posts = state.best_performing_posts[-20:]

    # Incorporate qualitative feedback
    if feedback is not None:
        _apply_qualitative_feedback(state, feedback)

    # Adjust scoring weights only after enough data
    if state.total_posts_analyzed >= MIN_POSTS_FOR_LEARNING:
        _adjust_weights(state, post, analytics)

    logger.info(
        "Learning state updated: %d posts analyzed, hook=%s, engagement=%.1f",
        state.total_posts_analyzed,
        hook,
        analytics.engagement_score,
    )
    return state


def _apply_qualitative_feedback(state: LearningState, feedback: PostFeedback) -> None:
    """
    Incorporate qualitative user feedback into the learning state.

    Tracks:
    - How often posts are not published (and why)
    - Average user rating across all rated posts
    """
    state.total_feedback_received += 1

    # Track not-published reasons
    if feedback.published is False and feedback.not_published_reason:
        reason = feedback.not_published_reason.lower().strip()
        state.not_published_reasons[reason] = state.not_published_reasons.get(reason, 0) + 1

    # Update rolling average rating — only count feedback that includes a rating
    if feedback.rating is not None:
        prev_count = state.total_ratings_received
        state.total_ratings_received += 1
        state.average_rating = (
            (state.average_rating * prev_count + feedback.rating) / state.total_ratings_received
        )

    logger.info(
        "Qualitative feedback applied: published=%s, rating=%s, reasons=%s",
        feedback.published,
        feedback.rating,
        state.not_published_reasons,
    )


def _adjust_weights(
    state: LearningState,
    post: Post,
    analytics: AnalyticsSnapshot,
) -> None:
    """
    Gradually adjust scoring dimension weights based on engagement.

    If engagement_score is above average → nudge weights of the dimensions
    that scored high in this post upward.
    If below average → nudge them down.
    """
    avg_score = _average_engagement_score(state)
    relative_performance = analytics.engagement_score / max(avg_score, 1.0)

    # Step size is small to avoid overfitting
    step = 0.05
    adjustment = step if relative_performance > 1.2 else (-step if relative_performance < 0.8 else 0.0)

    if adjustment == 0.0:
        return

    # Identify which scoring dimensions were strongest for this post
    # (use post's source_commit scoring — available in a real system via DB lookup)
    # Here we use a simplified heuristic: adjust 'proof' dimension since it
    # correlates most with measurable claims, which typically drive engagement.
    dimension_to_adjust = _infer_strong_dimension(post)

    current = state.scoring_weights.get(dimension_to_adjust, 1.0)
    new_value = current + adjustment
    # Apply guardrails
    new_value = max(MIN_WEIGHT_MULTIPLIER, min(MAX_WEIGHT_MULTIPLIER, new_value))
    state.scoring_weights[dimension_to_adjust] = round(new_value, 3)

    logger.debug(
        "Adjusted weight '%s': %.3f → %.3f (engagement=%.1f, avg=%.1f)",
        dimension_to_adjust,
        current,
        new_value,
        analytics.engagement_score,
        avg_score,
    )


def _average_engagement_score(state: LearningState) -> float:
    """Compute average engagement score across all recorded posts."""
    scores = []
    for data in state.hook_pattern_scores.values():
        if data["count"] > 0:
            scores.append(data["total_score"] / data["count"])
    return sum(scores) / len(scores) if scores else 1.0


def _infer_strong_dimension(post: Post) -> str:
    """
    Infer which scoring dimension to adjust based on the post's characteristics.

    This is a heuristic; a full implementation would look up the source commit's
    score_breakdown from a database.
    """
    if "proof" in post.tags or post.hook_pattern == "result":
        return "proof"
    if "ai" in post.tags or "distributed-systems" in post.tags:
        return "relevance"
    if post.hook_pattern in ("story", "confession"):
        return "novelty"
    return "teachability"


def get_best_hook_pattern(state: LearningState) -> str:
    """Return the hook pattern with the highest average engagement score."""
    if not state.hook_pattern_scores:
        return "result"  # Default
    best = max(
        state.hook_pattern_scores.items(),
        key=lambda kv: kv[1]["total_score"] / max(kv[1]["count"], 1),
    )
    return best[0]


def get_analytics_prompt(post: Post, issue_number: int) -> str:
    """Return a human-readable prompt asking the user to enter analytics."""
    return f"""
📊 Analytics Collection — Post #{issue_number}

Please provide the performance metrics for your post:
  "{post.lesson[:80]}"

Go to your LinkedIn analytics and enter:
  1. Impressions (total views)
  2. Reactions (likes, celebrates, etc.)
  3. Comments
  4. Reposts
  5. Saves (if available)
  6. Follower change since posting
  7. Click-through count (if available)

Add these as a comment on GitHub Issue #{issue_number}.
The agent will read them automatically on the next run.
    """.strip()
