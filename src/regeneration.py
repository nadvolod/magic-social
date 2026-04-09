"""
Feedback-driven regeneration — close rejected posts and generate replacements.

Three behaviors, one principle: never just close, always replace.

1. Post-specific rejection → find better source material, generate replacement
2. Generic/niche feedback → close ALL non-matching drafts, generate replacements
3. Similar-topic rejection → close drafts with same problem, generate replacements

Also detects patterns (stuck loops) and writes lessons to LESSONS_LEARNED.md.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Optional

from .analytics import LearningState
from .commit_scanner import scan_repos
from .github_storage import (
    add_comment,
    close_issue,
    close_issue_with_replacement,
    create_post_issue,
    update_issue_status,
)
from .models import Post, PostFeedback, PostStatus, SourceCommit
from .post_generator import HOOK_PATTERNS, generate_post_with_quality_gate
from .scoring import RELEVANT_TOPICS

logger = logging.getLogger(__name__)

MAX_REGENERATION_ATTEMPTS = 3
LESSONS_LEARNED_PATH = "LESSONS_LEARNED.md"

# Words that signal generic/directive feedback (not post-specific)
_DIRECTIVE_PHRASES = [
    "all posts should",
    "every post",
    "focus on",
    "only write about",
    "niche",
    "from now on",
    "going forward",
    "always",
    "never write about",
    "stop writing about",
    "our focus",
    "my niche",
    "topic should be",
]

# Reasons that indicate topic-level rejection (may apply to siblings)
_TOPIC_REJECTION_REASONS = {"useless_topic", "not_relevant"}

# Stop words to exclude from keyword extraction
_STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "must", "to", "of",
    "in", "for", "on", "with", "at", "by", "from", "as", "into", "about",
    "that", "this", "it", "its", "and", "or", "but", "not", "no", "so",
    "if", "then", "than", "too", "very", "just", "also", "more", "most",
    "all", "each", "every", "any", "some", "such", "only", "own", "same",
    "post", "posts", "should", "write", "writing", "make", "like",
}


# ---------------------------------------------------------------------------
# Feedback classification
# ---------------------------------------------------------------------------

def classify_feedback(
    feedback: PostFeedback,
    post: Post,
) -> Literal["post_specific", "generic", "abandon", "none"]:
    """Classify feedback as post-specific, generic directive, abandon signal, or no-op."""
    if feedback.not_published_reason == "abandon":
        return "abandon"

    notes = (feedback.improvement_notes or "").lower().strip()
    if notes:
        # Check for abandon keywords in free-text (word boundaries to avoid false positives like "skill")
        if any(re.search(rf"\b{re.escape(word)}\b", notes) for word in ("abandon", "kill", "stop trying", "give up")):
            return "abandon"

        # Check for directive/generic language
        if len(notes) > 40 and any(phrase in notes for phrase in _DIRECTIVE_PHRASES):
            return "generic"

    # Post-specific rejection
    if feedback.published is False and (
        feedback.not_published_reason
        or (feedback.rating is not None and feedback.rating <= 2)
    ):
        return "post_specific"

    return "none"


def extract_feedback_keywords(feedback: PostFeedback) -> list[str]:
    """Extract actionable topic/quality keywords from feedback text."""
    text = " ".join(filter(None, [
        feedback.improvement_notes,
        feedback.not_published_reason,
    ])).lower()

    words = re.findall(r"[a-z][a-z0-9.]+", text)
    keywords = [w for w in words if w not in _STOP_WORDS and len(w) > 2]

    # Also match against known relevant topics. These are regex patterns, so
    # use them directly and normalize the matched text into a keyword label.
    for topic in RELEVANT_TOPICS:
        match = re.search(topic, text)
        if match:
            normalized = re.sub(r"[^a-z0-9]+", "-", match.group(0).lower()).strip("-")
            if normalized:
                keywords.append(normalized)

    return list(dict.fromkeys(keywords))  # deduplicate preserving order


def matches_niche_directive(post: Post, directive_keywords: list[str]) -> bool:
    """Return True if the post's content/tags align with the directive keywords."""
    if not directive_keywords:
        return True  # no directive = everything matches

    post_text = f"{post.lesson} {post.linkedin_post} {' '.join(post.tags)}".lower()
    matches = sum(1 for kw in directive_keywords if kw in post_text)
    # Require at least 1/3 of directive keywords to match
    return matches >= max(1, len(directive_keywords) // 3)


# ---------------------------------------------------------------------------
# Commit ranking for feedback-aware regeneration
# ---------------------------------------------------------------------------

def rank_commits_for_feedback(
    commits: list[SourceCommit],
    feedback: PostFeedback,
    rejected_post: Post,
    excluded_shas: set[str] | None = None,
    priority_topics: list[str] | None = None,
) -> list[SourceCommit]:
    """Re-rank scanned commits based on feedback signals. Best candidates first."""
    excluded = excluded_shas or set()
    excluded.add(rejected_post.source_commit_sha)
    keywords = extract_feedback_keywords(feedback)

    scored: list[tuple[float, SourceCommit]] = []
    for commit in commits:
        if commit.sha in excluded:
            continue

        bonus = 0.0
        text = f"{commit.message} {commit.diff_summary}".lower()

        # Boost for matching feedback keywords
        kw_matches = sum(1 for kw in keywords if kw in text)
        bonus += kw_matches * 10.0

        # Boost for priority topics
        if priority_topics:
            topic_matches = sum(1 for t in priority_topics if t in text)
            bonus += topic_matches * 8.0

        # Diversity bonus — different repo than the rejected post
        if commit.repo != rejected_post.repo:
            bonus += 5.0

        scored.append((commit.score + bonus, commit))

    scored.sort(key=lambda x: -x[0])
    return [c for _, c in scored]


# ---------------------------------------------------------------------------
# Regeneration
# ---------------------------------------------------------------------------

def should_regenerate(post: Post) -> bool:
    """Return True if the post is eligible for regeneration (under attempt limit)."""
    return (
        post.regeneration_attempt < MAX_REGENERATION_ATTEMPTS
        and post.status not in (PostStatus.PUBLISHED, PostStatus.ABANDONED)
    )


def regenerate_from_feedback(
    rejected_post: Post,
    feedback: PostFeedback,
    source_repos: list[str],
    issue_repo: str,
    token: str,
    openai_client,
    learning_state: LearningState,
    model: str = "gpt-5.4-mini",
    scan_days: int = 14,
    score_threshold: float = 20.0,
    quality_threshold: float = 75.0,
    max_rewrites: int = 2,
) -> Optional[Post]:
    """Generate a replacement post from better source material based on feedback."""
    old_issue = rejected_post.github_issue_number
    attempt = rejected_post.regeneration_attempt + 1

    if attempt > MAX_REGENERATION_ATTEMPTS:
        if old_issue:
            add_comment(
                issue_repo, token, old_issue,
                f"Maximum regeneration attempts ({MAX_REGENERATION_ATTEMPTS}) reached. "
                "Closing chain — the system needs different source material or a different approach.",
            )
            close_issue(issue_repo, token, old_issue)
        _detect_pattern_and_learn(rejected_post, feedback, learning_state)
        return None

    # Scan all repos with wider window for better candidates
    cutoff = (datetime.now(timezone.utc) - timedelta(days=scan_days)).isoformat()
    try:
        candidates = scan_repos(
            repos=source_repos,
            token=token,
            since=cutoff,
            threshold=score_threshold,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to scan repos for regeneration: %s", exc)
        return None

    ranked = rank_commits_for_feedback(candidates, feedback, rejected_post)
    if not ranked:
        if old_issue:
            add_comment(
                issue_repo, token, old_issue,
                "Could not find better source material for this feedback. "
                "Consider providing different direction or waiting for new commits.",
            )
        return None

    # Try top candidates until one passes quality gate
    feedback_summary = _feedback_summary(feedback)
    import random  # noqa: PLC0415
    hooks = list(HOOK_PATTERNS.keys())
    new_post = None

    for source in ranked[:5]:
        random.shuffle(hooks)
        for hook in hooks[:3]:
            new_post = generate_post_with_quality_gate(
                source=source,
                hook_pattern=hook,
                openai_client=openai_client,
                model=model,
                quality_threshold=quality_threshold,
                max_rewrites=max_rewrites,
            )
            if new_post:
                break
        if new_post:
            break

    if new_post is None:
        if old_issue:
            add_comment(
                issue_repo, token, old_issue,
                "Regeneration failed — all candidate posts fell below quality threshold. "
                f"Attempted {min(5, len(ranked))} commits with 3 hook patterns each.",
            )
        return None

    # Set lineage
    new_post.parent_issue_number = old_issue
    new_post.regeneration_attempt = attempt
    new_post.regeneration_feedback = feedback_summary
    new_post.id = f"{new_post.id}-regen{attempt}"

    # Create the new issue
    new_issue = create_post_issue(
        new_post, issue_repo, token,
        openai_client=openai_client,
        source_commit=source,
        learning_state=learning_state,
    )
    new_post.github_issue_number = new_issue

    # Link the issues
    add_comment(
        issue_repo, token, new_issue,
        f"Regenerated from #{old_issue} (attempt {attempt}/{MAX_REGENERATION_ATTEMPTS}).\n\n"
        f"**Feedback:** {feedback_summary}\n\n"
        f"**Source:** `{new_post.repo}` / `{new_post.source_commit_sha[:8]}`\n\n"
        f"**Hook:** `{new_post.hook_pattern}`",
    )

    if old_issue:
        close_issue_with_replacement(
            issue_repo, token, old_issue,
            f"Regenerated based on feedback: _{feedback_summary}_",
            new_issue,
        )

    # Record in learning state
    learning_state.regeneration_history.append({
        "parent_issue": old_issue,
        "child_issue": new_issue,
        "feedback": feedback_summary,
        "attempt": attempt,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    logger.info(
        "Regenerated post: #%s → #%d (attempt %d, feedback: %s)",
        old_issue, new_issue, attempt, feedback_summary,
    )
    return new_post


def handle_abandon(post: Post, repo: str, token: str) -> None:
    """Mark a regeneration chain as abandoned."""
    if post.github_issue_number:
        add_comment(
            repo, token, post.github_issue_number,
            "Regeneration chain abandoned by user. No further attempts will be made.",
        )
        update_issue_status(repo, token, post.github_issue_number, PostStatus.ABANDONED)
    logger.info("Abandoned regeneration chain for post %s (issue #%s)", post.id, post.github_issue_number)


# ---------------------------------------------------------------------------
# Generic feedback — bulk close + replace
# ---------------------------------------------------------------------------

def apply_generic_feedback(
    feedback: PostFeedback,
    feedback_source_issue: int,
    open_posts: list[Post],
    source_repos: list[str],
    issue_repo: str,
    token: str,
    openai_client,
    learning_state: LearningState,
    model: str = "gpt-5.4-mini",
    max_replacements: int = 10,
) -> list[Post]:
    """Close non-matching open drafts and generate replacements aligned with the directive."""
    keywords = extract_feedback_keywords(feedback)
    if not keywords:
        logger.info("No actionable keywords from generic feedback, skipping bulk close.")
        return []

    directive_summary = _feedback_summary(feedback)

    # Find posts that don't match the directive
    non_matching: list[Post] = []
    for post in open_posts:
        if post.status not in (PostStatus.DRAFT, PostStatus.APPROVED):
            continue
        if post.github_issue_number == feedback_source_issue:
            continue  # Don't close the post that received the feedback
        if not matches_niche_directive(post, keywords):
            non_matching.append(post)

    if not non_matching:
        logger.info("All open drafts match the directive. No bulk action needed.")
        return []

    logger.info(
        "Generic feedback from #%d: closing %d non-matching drafts, generating replacements.",
        feedback_source_issue, len(non_matching),
    )

    # Scan for replacement material
    cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    try:
        candidates = scan_repos(repos=source_repos, token=token, since=cutoff, threshold=20.0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to scan repos for generic feedback replacements: %s", exc)
        return []

    # Filter candidates to only niche-matching ones
    niche_candidates = [
        c for c in candidates
        if any(kw in f"{c.message} {c.diff_summary}".lower() for kw in keywords)
    ]

    replacements: list[Post] = []
    import random  # noqa: PLC0415
    hooks = list(HOOK_PATTERNS.keys())

    for post in non_matching[:max_replacements]:
        # Generate replacement from niche-matching commits
        new_post = None
        random.shuffle(niche_candidates)
        for source in niche_candidates[:5]:
            random.shuffle(hooks)
            new_post = generate_post_with_quality_gate(
                source=source,
                hook_pattern=hooks[0],
                openai_client=openai_client,
                model=model,
            )
            if new_post:
                break

        if new_post:
            new_post.parent_issue_number = post.github_issue_number
            new_post.regeneration_attempt = post.regeneration_attempt + 1
            new_post.regeneration_feedback = directive_summary
            new_post.id = f"{new_post.id}-regen-generic"

            new_issue = create_post_issue(
                new_post, issue_repo, token,
                openai_client=openai_client,
                source_commit=source,
                learning_state=learning_state,
            )
            new_post.github_issue_number = new_issue

            add_comment(
                issue_repo, token, new_issue,
                f"Replaced #{post.github_issue_number} per generic feedback on "
                f"#{feedback_source_issue}.\n\n**Directive:** {directive_summary}",
            )
            replacements.append(new_post)

            close_issue_with_replacement(
                issue_repo, token, post.github_issue_number,
                f"Closed — doesn't match niche focus per feedback on #{feedback_source_issue}: "
                f"_{directive_summary}_",
                new_issue,
            )
        else:
            # Don't close without a replacement — core principle.
            # Leave the post open with a comment explaining the situation.
            add_comment(
                issue_repo, token, post.github_issue_number,
                f"Doesn't match niche focus per feedback on #{feedback_source_issue}: "
                f"_{directive_summary}_\n\n"
                "No replacement material found yet. Will retry on next scan.",
            )

    # Write lesson about the directive
    _write_lesson(
        f"Generic feedback applied from #{feedback_source_issue}",
        f"Directive: {directive_summary}. "
        f"Closed {len(non_matching)} non-matching drafts, generated {len(replacements)} replacements.",
        "directive",
    )

    return replacements


def apply_similar_feedback(
    feedback: PostFeedback,
    source_post: Post,
    open_posts: list[Post],
    source_repos: list[str],
    issue_repo: str,
    token: str,
    openai_client,
    learning_state: LearningState,
    model: str = "gpt-5.4-mini",
    max_replacements: int = 10,
) -> list[Post]:
    """Find other open drafts with the same topic problem and close + replace them."""
    if feedback.not_published_reason not in _TOPIC_REJECTION_REASONS:
        return []

    # Find drafts with overlapping tags or similar content
    source_tags = set(source_post.tags)
    source_words = set(re.findall(r"[a-z]{4,}", source_post.lesson.lower()))

    similar: list[Post] = []
    for post in open_posts:
        if post.status not in (PostStatus.DRAFT, PostStatus.APPROVED):
            continue
        if post.github_issue_number == source_post.github_issue_number:
            continue
        # Check tag overlap
        if source_tags & set(post.tags):
            similar.append(post)
            continue
        # Check content overlap
        post_words = set(re.findall(r"[a-z]{4,}", post.lesson.lower()))
        if len(source_words & post_words) >= 2:
            similar.append(post)

    if not similar:
        return []

    logger.info(
        "Similar-topic feedback from #%s: found %d drafts with same problem.",
        source_post.github_issue_number, len(similar),
    )

    feedback_summary = _feedback_summary(feedback)
    replacements: list[Post] = []

    for post in similar[:max_replacements]:
        new_post = regenerate_from_feedback(
            rejected_post=post,
            feedback=feedback,
            source_repos=source_repos,
            issue_repo=issue_repo,
            token=token,
            openai_client=openai_client,
            learning_state=learning_state,
            model=model,
        )
        if new_post:
            replacements.append(new_post)

    if similar:
        _write_lesson(
            f"Similar-topic rejection from #{source_post.github_issue_number}",
            f"Reason: {feedback_summary}. Found {len(similar)} similar drafts, "
            f"generated {len(replacements)} replacements.",
            "pattern",
        )

    return replacements


# ---------------------------------------------------------------------------
# Pattern detection & lessons learned
# ---------------------------------------------------------------------------

def _detect_pattern_and_learn(
    post: Post,
    feedback: PostFeedback,
    learning_state: LearningState,
) -> None:
    """Detect if regeneration keeps failing for the same reason and write a lesson."""
    history = learning_state.regeneration_history
    if not history:
        return

    # Look at recent feedback reasons in regeneration history
    recent_reasons = [
        h.get("feedback", "")
        for h in history[-10:]
    ]
    reason_counts = Counter(recent_reasons)

    for reason, count in reason_counts.most_common(3):
        if count >= 2 and reason:
            _write_lesson(
                f"Regeneration loop detected: '{reason}' appeared {count} times",
                f"The same feedback keeps coming back. This suggests a deeper problem — "
                f"not just the individual post, but the content strategy or source material. "
                f"Last post in chain: #{post.github_issue_number}, attempt {post.regeneration_attempt}.",
                "pattern",
            )
            break


def _write_lesson(title: str, body: str, category: str) -> None:
    """Append a dated entry to LESSONS_LEARNED.md."""
    path = Path(LESSONS_LEARNED_PATH)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    entry = f"\n### {now} — {title}\n\n**Category:** {category}\n\n{body}\n\n---\n"

    if not path.exists():
        path.write_text(
            "# Lessons Learned\n\n"
            "Auto-generated journal of what the system learns from feedback, "
            "patterns, and failures. Each entry is dated and categorized.\n\n"
            "---\n"
            + entry,
            encoding="utf-8",
        )
    else:
        with path.open("a", encoding="utf-8") as f:
            f.write(entry)

    logger.info("Lesson written: %s", title)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _feedback_summary(feedback: PostFeedback) -> str:
    """Build a short summary string from feedback."""
    parts: list[str] = []
    if feedback.not_published_reason:
        parts.append(feedback.not_published_reason.replace("_", " "))
    if feedback.improvement_notes:
        notes = feedback.improvement_notes.strip()
        if len(notes) > 100:
            notes = notes[:97] + "..."
        parts.append(notes)
    return "; ".join(parts) if parts else "rejected"
