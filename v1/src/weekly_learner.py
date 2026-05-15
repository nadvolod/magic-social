"""
Weekly synthesis engine — turns accumulated feedback into prompt improvements.

Runs once per week (typically via cron/GitHub Actions) to:
  1. Analyze all feedback received in the past 7 days
  2. Detect recurring rejection patterns and generate prompt patches
  3. Compute KPIs (publish rate, time-to-publish, engagement growth, etc.)
  4. Auto-save published posts to good-social-posts/
  5. Write LESSONS_LEARNED.md entries and a WEEKLY_REPORT.md dashboard
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from .analytics import LearningState
from .github_storage import load_posts_from_issues
from .linkedin_api import load_latest_snapshot
from .models import Post, PostFeedback, PostStatus
from .regeneration import LESSONS_LEARNED_PATH, _write_lesson

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MODEL = "gpt-5.4-mini"
PATCH_TTL_DAYS = 30
MIN_OCCURRENCES_FOR_PATCH = 2
LOOKBACK_DAYS = 7

# Patch types
PATCH_TYPE_AVOID_TOPIC = "avoid_topic"
PATCH_TYPE_STYLE_RULE = "style_rule"
PATCH_TYPE_NICHE_FOCUS = "niche_focus"


# ---------------------------------------------------------------------------
# Prompt patches — load / save / generate
# ---------------------------------------------------------------------------

def load_prompt_patches(path: str) -> list[dict]:
    """Load existing prompt patches from prompt_patches.json.

    Returns an empty list if the file does not exist or is malformed.
    """
    try:
        with open(path) as f:
            data = json.load(f)
        return data.get("patches", [])
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        logger.debug("No existing prompt patches at %s — starting fresh.", path)
        return []


def save_prompt_patches(patches: list[dict], path: str) -> None:
    """Save prompt patches to disk, archiving any older than 30 days.

    Patches whose ``added`` timestamp is older than ``PATCH_TTL_DAYS`` are
    removed to prevent unbounded growth and keep the prompt clean.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=PATCH_TTL_DAYS)

    active: list[dict] = []
    archived = 0
    for patch in patches:
        added_str = patch.get("added", "")
        try:
            added_dt = datetime.fromisoformat(added_str.replace("Z", "+00:00"))
            if added_dt.tzinfo is None:
                added_dt = added_dt.replace(tzinfo=timezone.utc)
        except (ValueError, AttributeError):
            # Keep patches with unparseable dates (better safe than sorry).
            active.append(patch)
            continue

        if added_dt >= cutoff:
            active.append(patch)
        else:
            archived += 1

    payload = {
        "updated_at": now.isoformat(),
        "patches": active,
    }

    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w") as f:
        json.dump(payload, f, indent=2)

    if archived:
        logger.info(
            "Saved %d active prompt patches to %s (archived %d expired).",
            len(active), path, archived,
        )
    else:
        logger.info("Saved %d prompt patches to %s.", len(active), path)


def generate_prompt_patches(
    learning_state: LearningState,
    recent_feedback_reasons: Counter,
) -> list[dict]:
    """Generate prompt patches for rejection reasons appearing 2+ times.

    Each patch is a lightweight rule that the post generator should follow:
      - ``avoid_topic`` — stop writing about a topic that keeps getting rejected.
      - ``style_rule`` — adjust tone / length / structure.
      - ``niche_focus`` — sharpen the content niche.

    Returns:
        A list of patch dicts ready for serialization.
    """
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    patches: list[dict] = []

    # Map known reasons to patch types and human-readable rules.
    reason_to_patch: dict[str, tuple[str, str]] = {
        "useless_topic": (PATCH_TYPE_AVOID_TOPIC, "Avoid this topic — users consistently find it irrelevant."),
        "not_relevant": (PATCH_TYPE_NICHE_FOCUS, "Content is drifting off-niche. Refocus on core topics."),
        "too_long": (PATCH_TYPE_STYLE_RULE, "Keep posts shorter — aim for concise, scannable content."),
        "weak_hook": (PATCH_TYPE_STYLE_RULE, "Strengthen opening hooks — first line must earn the scroll-stop."),
        "needs_rewrite": (PATCH_TYPE_STYLE_RULE, "Posts need higher polish — tighten language, cut filler."),
        "quality": (PATCH_TYPE_STYLE_RULE, "Raise overall quality bar — check clarity, specificity, value."),
        "skip": (PATCH_TYPE_AVOID_TOPIC, "Posts are being skipped — re-examine topic selection."),
        "no_feedback_72h": (PATCH_TYPE_STYLE_RULE, "Posts are being ignored — make them more compelling."),
        "stale_unpublished_7d": (PATCH_TYPE_AVOID_TOPIC, "Posts go stale before publishing — pick more timely topics."),
    }

    for reason, count in recent_feedback_reasons.items():
        if count < MIN_OCCURRENCES_FOR_PATCH:
            continue

        reason_key = reason.lower().strip()
        if reason_key in reason_to_patch:
            patch_type, rule_template = reason_to_patch[reason_key]
        else:
            # Unknown reason — generate a generic style rule.
            patch_type = PATCH_TYPE_STYLE_RULE
            rule_template = f"Address recurring feedback: '{reason_key}'."

        patch = {
            "type": patch_type,
            "rule": rule_template,
            "reason": f"Rejection reason '{reason_key}' appeared {count} times in the last week.",
            "added": now_iso,
            "source_issues": [],  # Populated by caller if issue numbers are tracked.
        }
        patches.append(patch)

    logger.info("Generated %d prompt patches from %d rejection reasons.", len(patches), len(recent_feedback_reasons))
    return patches


# ---------------------------------------------------------------------------
# KPI computation
# ---------------------------------------------------------------------------

def compute_kpis(
    posts: list[Post],
    learning_state: LearningState,
    linkedin_metrics_path: str = "linkedin_metrics.json",
) -> dict:
    """Compute weekly KPIs from posts and learning state.

    Returns a dict with:
      - publish_rate: percentage of posts generated this week that were published
      - feedback_convergence: count of rejection reasons appearing both this and last week
      - time_to_publish_days: average days from created_at to published_at
      - engagement_growth_pct: week-over-week engagement score change
      - follower_delta: net follower change from LinkedIn metrics
    """
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=LOOKBACK_DAYS)

    # --- Publish Rate ---
    week_posts = _posts_in_window(posts, week_ago, now)
    published_this_week = [p for p in week_posts if p.status == PostStatus.PUBLISHED]
    publish_rate = (
        (len(published_this_week) / len(week_posts) * 100)
        if week_posts
        else 0.0
    )

    # --- Feedback Convergence ---
    # Compare this week's rejection reasons against last week's.
    this_week_reasons = _rejection_reasons_in_window(learning_state, week_ago, now)
    last_week_start = week_ago - timedelta(days=LOOKBACK_DAYS)
    last_week_reasons = _rejection_reasons_in_window(learning_state, last_week_start, week_ago)
    feedback_convergence = len(set(this_week_reasons.keys()) & set(last_week_reasons.keys()))

    # --- Time-to-Publish ---
    ttp_values: list[float] = []
    for post in published_this_week:
        days = _days_between(post.created_at, post.published_at)
        if days is not None and days >= 0:
            ttp_values.append(days)
    time_to_publish_days = (
        sum(ttp_values) / len(ttp_values) if ttp_values else 0.0
    )

    # --- Engagement Growth ---
    engagement_growth_pct = _compute_engagement_growth(learning_state)

    # --- Follower Delta ---
    follower_delta = _compute_follower_delta(linkedin_metrics_path)

    kpis = {
        "publish_rate": round(publish_rate, 1),
        "feedback_convergence": feedback_convergence,
        "time_to_publish_days": round(time_to_publish_days, 2),
        "engagement_growth_pct": round(engagement_growth_pct, 1),
        "follower_delta": follower_delta,
        "posts_generated": len(week_posts),
        "posts_published": len(published_this_week),
        "period_start": week_ago.strftime("%Y-%m-%d"),
        "period_end": now.strftime("%Y-%m-%d"),
    }

    logger.info(
        "KPIs computed: publish_rate=%.1f%%, convergence=%d, ttp=%.2fd, engagement_growth=%.1f%%, follower_delta=%+d",
        kpis["publish_rate"],
        kpis["feedback_convergence"],
        kpis["time_to_publish_days"],
        kpis["engagement_growth_pct"],
        kpis["follower_delta"],
    )
    return kpis


# ---------------------------------------------------------------------------
# Auto-save published posts
# ---------------------------------------------------------------------------

def auto_save_published_post(post: Post, good_posts_dir: str = "good-social-posts") -> bool:
    """Save a published post's LinkedIn text to good-social-posts/ for future reference.

    File name: ``post-{issue_number}.md``

    Returns True if the post was saved, False if it was skipped (not published,
    already exists, or missing content).
    """
    if post.status != PostStatus.PUBLISHED:
        return False

    if not post.linkedin_post or not post.linkedin_post.strip():
        logger.debug("Skipping auto-save for post %s — no LinkedIn content.", post.id)
        return False

    issue_num = post.github_issue_number or post.id
    dir_path = Path(good_posts_dir)
    dir_path.mkdir(parents=True, exist_ok=True)

    file_name = f"post-{issue_num}.md"
    file_path = dir_path / file_name

    if file_path.exists():
        logger.debug("Post %s already saved at %s — skipping.", post.id, file_path)
        return False

    content_lines = [
        f"# Post #{issue_num}",
        "",
        f"**Published:** {post.published_at or 'unknown'}",
        f"**Hook pattern:** {post.hook_pattern}",
        f"**Tags:** {', '.join(post.tags) if post.tags else 'none'}",
        "",
        "---",
        "",
        post.linkedin_post.strip(),
        "",
    ]

    file_path.write_text("\n".join(content_lines), encoding="utf-8")
    logger.info("Auto-saved published post to %s", file_path)
    return True


# ---------------------------------------------------------------------------
# Weekly report rendering
# ---------------------------------------------------------------------------

def render_weekly_report(
    kpis: dict,
    patches: list[dict],
    lessons: list[str],
    activity_stats: dict,
) -> str:
    """Generate the WEEKLY_REPORT.md content with a KPI dashboard at top.

    Args:
        kpis: Dict from ``compute_kpis``.
        patches: Active prompt patches.
        lessons: List of lesson strings written this cycle.
        activity_stats: Additional stats (total_posts, total_feedback, etc.).

    Returns:
        Markdown string ready to write to disk.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    period = f"{kpis.get('period_start', '?')} to {kpis.get('period_end', '?')}"

    # --- KPI Dashboard ---
    report_parts = [
        f"# Weekly Learning Report",
        "",
        f"**Generated:** {now}",
        f"**Period:** {period}",
        "",
        "## KPI Dashboard",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Publish Rate | {kpis.get('publish_rate', 0):.1f}% ({kpis.get('posts_published', 0)}/{kpis.get('posts_generated', 0)}) |",
        f"| Time-to-Publish | {kpis.get('time_to_publish_days', 0):.1f} days |",
        f"| Engagement Growth | {kpis.get('engagement_growth_pct', 0):+.1f}% |",
        f"| Feedback Convergence | {kpis.get('feedback_convergence', 0)} recurring reasons |",
        f"| Follower Delta | {kpis.get('follower_delta', 0):+d} |",
        "",
    ]

    # --- Activity Summary ---
    report_parts.extend([
        "## Activity Summary",
        "",
        f"- **Total posts tracked:** {activity_stats.get('total_posts', 0)}",
        f"- **Total feedback received (all time):** {activity_stats.get('total_feedback', 0)}",
        f"- **Average rating (explicit):** {activity_stats.get('avg_rating', 0):.1f}/5",
        f"- **Regeneration chains this week:** {activity_stats.get('regenerations_this_week', 0)}",
        "",
    ])

    # --- Prompt Patches ---
    report_parts.extend([
        "## Active Prompt Patches",
        "",
    ])
    if patches:
        for i, patch in enumerate(patches, 1):
            report_parts.append(
                f"{i}. **[{patch.get('type', '?')}]** {patch.get('rule', '—')}"
            )
            report_parts.append(f"   _Reason:_ {patch.get('reason', '—')}")
            report_parts.append(f"   _Added:_ {patch.get('added', '—')}")
            report_parts.append("")
    else:
        report_parts.append("_No active prompt patches._")
        report_parts.append("")

    # --- Lessons Learned ---
    report_parts.extend([
        "## Lessons Learned This Week",
        "",
    ])
    if lessons:
        for lesson in lessons:
            report_parts.append(f"- {lesson}")
        report_parts.append("")
    else:
        report_parts.append("_No new lessons this week._")
        report_parts.append("")

    # --- Footer ---
    report_parts.extend([
        "---",
        "",
        "_This report is auto-generated by the weekly learning cycle._",
        "",
    ])

    return "\n".join(report_parts)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_weekly_learning_cycle(
    repo: str,
    token: str,
    learning_state_path: str = "learning_state.json",
    patches_path: str = "prompt_patches.json",
    report_output: str = "WEEKLY_REPORT.md",
    lessons_path: str = LESSONS_LEARNED_PATH,
) -> dict:
    """Execute the full weekly learning cycle.

    Steps:
      1. Load learning_state.json
      2. Load all posts from GitHub issues
      3. Analyze feedback from the past 7 days
      4. Group rejections by not_published_reason, count occurrences
      5. For reasons appearing 2+ times, create prompt patches
      6. Extract common themes from improvement_notes
      7. Compute KPIs
      8. Auto-save any newly published posts to good-social-posts/
      9. Write prompt_patches.json
     10. Append to LESSONS_LEARNED.md
     11. Generate WEEKLY_REPORT.md

    Returns:
        A summary dict with KPIs, patch count, and lesson count.
    """
    logger.info("Starting weekly learning cycle for repo=%s", repo)

    # 1. Load learning state
    learning_state = LearningState.load(learning_state_path)
    logger.info(
        "Loaded learning state: %d posts analyzed, %d feedback received.",
        learning_state.total_posts_analyzed,
        learning_state.total_feedback_received,
    )

    # 2. Load all posts from GitHub issues
    try:
        all_posts = load_posts_from_issues(repo, token, state="all")
        logger.info("Loaded %d posts from GitHub issues.", len(all_posts))
    except Exception:
        logger.exception("Failed to load posts from GitHub issues.")
        all_posts = []

    # 3. Analyze feedback from the past 7 days
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=LOOKBACK_DAYS)
    recent_fingerprints = _get_recent_fingerprints(learning_state, week_ago)
    logger.info("Found %d feedback entries from the past 7 days.", len(recent_fingerprints))

    # 4. Group rejections by not_published_reason
    recent_feedback_reasons = _extract_rejection_reasons(recent_fingerprints)
    if recent_feedback_reasons:
        logger.info(
            "Rejection reasons this week: %s",
            dict(recent_feedback_reasons.most_common()),
        )

    # 5. Generate prompt patches for recurring reasons
    existing_patches = load_prompt_patches(patches_path)
    new_patches = generate_prompt_patches(learning_state, recent_feedback_reasons)

    # Merge: keep existing patches that are still active, add new ones (deduplicate by rule).
    merged_patches = _merge_patches(existing_patches, new_patches)

    # 6. Extract common themes from improvement_notes
    themes = _extract_improvement_themes(recent_fingerprints)
    lessons_written: list[str] = []

    if themes:
        for theme, count in themes.most_common(5):
            lesson_text = f"Improvement theme '{theme}' mentioned {count} time(s) this week."
            _write_lesson(
                f"Weekly theme: {theme}",
                lesson_text,
                "weekly_synthesis",
            )
            lessons_written.append(lesson_text)

    # Write lessons for new patches too.
    for patch in new_patches:
        lesson_text = f"Prompt patch added: [{patch['type']}] {patch['rule']}"
        _write_lesson(
            f"Prompt patch: {patch['type']}",
            f"{patch['rule']} — {patch['reason']}",
            "prompt_patch",
        )
        lessons_written.append(lesson_text)

    # 7. Compute KPIs
    kpis = compute_kpis(all_posts, learning_state)

    # 8. Auto-save published posts from this week
    saved_count = 0
    published_this_week = [
        p for p in all_posts
        if p.status == PostStatus.PUBLISHED and _is_in_window(p.published_at, week_ago, now)
    ]
    for post in published_this_week:
        if auto_save_published_post(post):
            saved_count += 1

    if saved_count:
        logger.info("Auto-saved %d published posts to good-social-posts/.", saved_count)

    # 9. Write prompt_patches.json
    save_prompt_patches(merged_patches, patches_path)

    # 10. (Lessons already appended in step 6 via _write_lesson)

    # 11. Generate WEEKLY_REPORT.md
    regenerations_this_week = sum(
        1 for h in learning_state.regeneration_history
        if _is_in_window(h.get("timestamp"), week_ago, now)
    )

    activity_stats = {
        "total_posts": len(all_posts),
        "total_feedback": learning_state.total_feedback_received,
        "avg_rating": learning_state.explicit_average_rating,
        "regenerations_this_week": regenerations_this_week,
    }

    report_content = render_weekly_report(kpis, merged_patches, lessons_written, activity_stats)

    report_path = Path(report_output)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_content, encoding="utf-8")
    logger.info("Weekly report written to %s", report_output)

    # Save learning state (no structural changes, but records the cycle ran).
    learning_state.save(learning_state_path)

    summary = {
        "kpis": kpis,
        "patches_active": len(merged_patches),
        "patches_new": len(new_patches),
        "lessons_written": len(lessons_written),
        "posts_saved": saved_count,
        "report_path": report_output,
    }

    logger.info(
        "Weekly learning cycle complete: %d KPIs, %d patches (%d new), %d lessons, %d posts saved.",
        len(kpis),
        len(merged_patches),
        len(new_patches),
        len(lessons_written),
        saved_count,
    )
    return summary


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _posts_in_window(posts: list[Post], start: datetime, end: datetime) -> list[Post]:
    """Return posts whose created_at falls within [start, end]."""
    result: list[Post] = []
    for post in posts:
        created = _parse_datetime(post.created_at)
        if created is not None and start <= created <= end:
            result.append(post)
    return result


def _is_in_window(
    timestamp_str: Optional[str],
    start: datetime,
    end: datetime,
) -> bool:
    """Return True if the ISO timestamp falls within [start, end]."""
    if not timestamp_str:
        return False
    dt = _parse_datetime(timestamp_str)
    return dt is not None and start <= dt <= end


def _parse_datetime(iso_str: Optional[str]) -> Optional[datetime]:
    """Safely parse an ISO-8601 string to a timezone-aware datetime."""
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, AttributeError):
        return None


def _days_between(start_iso: Optional[str], end_iso: Optional[str]) -> Optional[float]:
    """Compute days between two ISO timestamps. Returns None on parse failure."""
    start = _parse_datetime(start_iso)
    end = _parse_datetime(end_iso)
    if start is None or end is None:
        return None
    delta = end - start
    return delta.total_seconds() / 86400


def _get_recent_fingerprints(
    learning_state: LearningState,
    since: datetime,
) -> dict[str, str]:
    """Return feedback fingerprints recorded since ``since``.

    The fingerprint format is: ``published|reason|notes|rating|timestamp``
    We filter by the timestamp component (last pipe-separated field).
    """
    recent: dict[str, str] = {}
    for post_id, fp in learning_state.applied_feedback_fingerprints.items():
        parts = fp.split("|")
        if len(parts) >= 5:
            ts_str = parts[4].strip()
        else:
            # Fallback: cannot determine timestamp, skip.
            continue

        ts = _parse_datetime(ts_str)
        if ts is not None and ts >= since:
            recent[post_id] = fp

    return recent


def _extract_rejection_reasons(fingerprints: dict[str, str]) -> Counter:
    """Count not_published_reason from fingerprint strings.

    Fingerprint format: ``published|reason|notes|rating|timestamp``
    We only count entries where published == 'False' and reason is non-empty.
    """
    reasons: Counter = Counter()
    for fp in fingerprints.values():
        parts = fp.split("|")
        if len(parts) < 2:
            continue
        published = parts[0].strip()
        reason = parts[1].strip()
        if published.lower() == "false" and reason:
            reasons[reason] += 1
    return reasons


def _rejection_reasons_in_window(
    learning_state: LearningState,
    start: datetime,
    end: datetime,
) -> Counter:
    """Count rejection reasons from fingerprints within [start, end]."""
    reasons: Counter = Counter()
    for fp in learning_state.applied_feedback_fingerprints.values():
        parts = fp.split("|")
        if len(parts) < 5:
            continue
        ts = _parse_datetime(parts[4].strip())
        if ts is None or not (start <= ts <= end):
            continue
        published = parts[0].strip()
        reason = parts[1].strip()
        if published.lower() == "false" and reason:
            reasons[reason] += 1
    return reasons


def _extract_improvement_themes(fingerprints: dict[str, str]) -> Counter:
    """Extract recurring keywords from improvement_notes in fingerprints.

    Fingerprint format: ``published|reason|notes|rating|timestamp``
    The notes field (index 2) contains free-text improvement suggestions.
    """
    word_counts: Counter = Counter()
    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "have", "has", "had", "do", "does", "did", "will", "would",
        "could", "should", "may", "might", "to", "of", "in", "for",
        "on", "with", "at", "by", "from", "as", "it", "its", "and",
        "or", "but", "not", "no", "so", "if", "this", "that", "more",
        "make", "post", "posts", "like", "just", "also", "very",
    }

    for fp in fingerprints.values():
        parts = fp.split("|")
        if len(parts) < 3:
            continue
        notes = parts[2].strip().lower()
        if not notes:
            continue
        words = re.findall(r"[a-z][a-z0-9-]+", notes)
        meaningful = [w for w in words if w not in stop_words and len(w) > 2]
        word_counts.update(meaningful)

    # Filter to words appearing at least twice to surface real themes.
    return Counter({w: c for w, c in word_counts.items() if c >= 2})


def _compute_engagement_growth(learning_state: LearningState) -> float:
    """Compute week-over-week engagement growth from hook_pattern_scores.

    Uses a simple heuristic: average engagement across all patterns now vs.
    the stored average_rating as a proxy for previous performance.

    Returns percentage change (positive = improvement).
    """
    if not learning_state.hook_pattern_scores:
        return 0.0

    total_score = 0.0
    total_count = 0
    for data in learning_state.hook_pattern_scores.values():
        total_score += data.get("total_score", 0.0)
        total_count += data.get("count", 0)

    if total_count == 0:
        return 0.0

    current_avg = total_score / total_count

    # Use explicit average rating scaled to engagement as a baseline.
    # If no baseline exists, we cannot compute growth.
    baseline = learning_state.explicit_average_rating
    if baseline <= 0:
        return 0.0

    # Normalize: the baseline rating is on a 1-5 scale, engagement scores
    # are on a different scale. Use relative change from a stored baseline.
    # For a first approximation, report the raw average engagement as growth
    # relative to the first half of data vs second half.
    if total_count < 4:
        return 0.0

    # Split hook pattern performance into older vs newer entries.
    scores_list: list[float] = []
    for data in learning_state.hook_pattern_scores.values():
        if data.get("count", 0) > 0:
            scores_list.append(data["total_score"] / data["count"])

    if len(scores_list) < 2:
        return 0.0

    mid = len(scores_list) // 2
    older_avg = sum(scores_list[:mid]) / mid
    newer_avg = sum(scores_list[mid:]) / (len(scores_list) - mid)

    if older_avg <= 0:
        return 0.0

    return ((newer_avg - older_avg) / older_avg) * 100


def _compute_follower_delta(linkedin_metrics_path: str) -> int:
    """Compute net follower change from the last two LinkedIn snapshots.

    Returns 0 if insufficient data is available.
    """
    try:
        file_path = Path(linkedin_metrics_path)
        if not file_path.exists():
            return 0

        with open(file_path) as f:
            history = json.load(f)

        if not isinstance(history, list) or len(history) < 2:
            return 0

        latest = history[-1].get("follower_count", 0)
        previous = history[-2].get("follower_count", 0)
        return latest - previous
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        logger.debug("Could not compute follower delta from %s.", linkedin_metrics_path)
        return 0


def _merge_patches(existing: list[dict], new: list[dict]) -> list[dict]:
    """Merge existing and new patches, deduplicating by rule text.

    New patches take precedence (refresh the ``added`` date) over existing
    patches with the same rule.
    """
    by_rule: dict[str, dict] = {}
    for patch in existing:
        rule = patch.get("rule", "")
        by_rule[rule] = patch

    for patch in new:
        rule = patch.get("rule", "")
        by_rule[rule] = patch  # overwrite existing with refreshed date

    return list(by_rule.values())
