"""AI-powered post generator — LinkedIn-first with X thread and IG caption variants."""

from __future__ import annotations

import hashlib
import logging
import re
import textwrap
from dataclasses import dataclass, field
import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from .lesson_source import load_social_lessons
from .models import Post, PostStatus, SourceCommit

logger = logging.getLogger(__name__)

# -------------------------------------------------------------------
# Hook patterns for LinkedIn posts
# -------------------------------------------------------------------
HOOK_PATTERNS = {
    "contrarian": "Most engineers {wrong_belief}.\n\nThey're wrong.",
    "number": "{N} things I learned about {topic} the hard way:",
    "story": "Yesterday I spent {time} debugging {problem}.\n\nHere's what I found.",
    "question": "Why does {bad_thing} keep happening in {system}?",
    "result": "We cut {metric} by {amount}.\n\nHere's exactly how.",
    "confession": "I made a mistake.\n\n{honest_statement}",
    "revelation": "I was wrong about {topic}.\n\nHere's what changed my mind.",
}

# LinkedIn post hard limit; the prompt instructs the model to stay within 800-1500 chars
MAX_LINKEDIN_CHARS = 3000
QUALITY_GATE_DEFAULT_THRESHOLD = 75.0
QUALITY_GATE_DEFAULT_MAX_REWRITES = 2

# Directory containing hand-picked example posts (relative to repo root)
_GOOD_POSTS_DIR = Path(__file__).parent.parent / "good-social-posts"

# Default external lesson source. Can be overridden with SOCIAL_LESSONS_DOC_URL.
DEFAULT_SOCIAL_LESSONS_DOC_URL = (
    "https://docs.google.com/document/d/1GQD7a49V9B96wzTYt33mlJb3gae5quJzRcf4d3GiPh0/edit?usp=sharing"
)

# Keep external lesson context bounded for prompt efficiency.
MAX_EXTERNAL_LESSONS_CHARS = 3500


def _load_good_posts_examples() -> list[str]:
    """
    Load LinkedIn post examples from the good-social-posts directory.

    Each .md file is expected to contain a '## Final LinkedIn Post' section.
    Returns a list of extracted post texts to use as few-shot examples.
    """
    examples: list[str] = []
    if not _GOOD_POSTS_DIR.exists():
        return examples
    for md_file in sorted(_GOOD_POSTS_DIR.glob("*.md")):
        try:
            content = md_file.read_text(encoding="utf-8")
            post_text = _extract_linkedin_section(content)
            if post_text:
                examples.append(post_text)
        except Exception:  # noqa: BLE001
            logger.debug("Could not load good-post example from %s", md_file)
    return examples


def _extract_linkedin_section(content: str) -> str:
    """
    Extract the 'Final LinkedIn Post' section from a good-post markdown file.

    Reads until the next '## ' heading or a '---' horizontal rule.
    """
    lines = content.splitlines()
    in_section = False
    post_lines: list[str] = []

    for line in lines:
        if "## Final LinkedIn Post" in line:
            in_section = True
            continue
        if in_section:
            if (line.startswith("## ") or line.startswith("# ")) and post_lines:
                break
            if line.startswith("---") and post_lines:
                break
            post_lines.append(line)

    return "\n".join(post_lines).strip()


@lru_cache(maxsize=1)
def _load_external_social_lessons() -> str:
    """
    Load maintained social-post lessons from env-configured sources.

    Priority:
      1) SOCIAL_LESSONS_FILE (local file path)
      2) SOCIAL_LESSONS_DOC_URL (Google Doc URL)
      3) DEFAULT_SOCIAL_LESSONS_DOC_URL
    """
    lessons_file = os.environ.get("SOCIAL_LESSONS_FILE", "").strip()
    doc_url = os.environ.get("SOCIAL_LESSONS_DOC_URL", "").strip()
    if not doc_url:
        doc_url = DEFAULT_SOCIAL_LESSONS_DOC_URL
    if doc_url.lower() in {"off", "none", "false", "0"}:
        doc_url = ""
    try:
        return load_social_lessons(
            doc_url=doc_url,
            file_path=lessons_file or None,
            max_chars=MAX_EXTERNAL_LESSONS_CHARS,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not load external social lessons: %s", exc)
        return ""


@lru_cache(maxsize=1)
def _load_screenshot_signal_guidance() -> str:
    """
    Load compact guidance distilled from screenshot-learning state.

    This lets generation inherit observed external winners/losers without
    requiring manual curation every time.
    """
    try:
        from .screenshot_learning import ScreenshotLearningState, build_prompt_guidance  # noqa: PLC0415

        state = ScreenshotLearningState.load("screenshot_learning.json")
        return build_prompt_guidance(state, top_n=5)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not load screenshot signal guidance: %s", exc)
        return ""


@lru_cache(maxsize=1)
def _load_linkedin_data_guidance() -> str:
    """
    Load compact guidance from ingested LinkedIn engagement data.

    When linkedin_insights.json exists, distill the key findings
    into a short prompt section for the generator.
    """
    try:
        from .linkedin_data import LinkedInDataInsights  # noqa: PLC0415

        insights = LinkedInDataInsights.load("linkedin_insights.json")
        if insights.total_posts == 0:
            return ""

        parts = [f"Data from {insights.total_posts} real LinkedIn posts:"]

        if insights.optimal_length_range != (800, 1500):
            lo, hi = insights.optimal_length_range
            parts.append(f"- Optimal post length: {lo}-{hi} characters")

        if insights.engagement_by_day_of_week:
            best_day = max(insights.engagement_by_day_of_week, key=insights.engagement_by_day_of_week.get)  # type: ignore[arg-type]
            parts.append(f"- Best posting day: {best_day}")

        if insights.high_engagement_patterns:
            hooks = insights.high_engagement_patterns[:3]
            parts.append("- Top-performing hook patterns:")
            for hook in hooks:
                parts.append(f'  "{hook}"')

        return "\n".join(parts)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not load LinkedIn data guidance: %s", exc)
        return ""


def _load_prompt_patches_block() -> str:
    """Load learned rules from prompt_patches.json into a prompt section."""
    patches_path = Path(__file__).parent.parent / "prompt_patches.json"
    if not patches_path.exists():
        return ""
    try:
        import json as _json
        with patches_path.open() as f:
            data = _json.load(f)
        patches = data.get("patches", [])
        if not patches:
            return ""
        rules = [f"- {p['rule']}" for p in patches if "rule" in p]
        if not rules:
            return ""
        return (
            "\n\nLearned rules from feedback (MUST follow these):\n\n"
            + "\n".join(rules[:15])
        )
    except Exception:  # noqa: BLE001
        return ""


def _load_lessons_learned_block() -> str:
    """Load recent lessons from LESSONS_LEARNED.md into a prompt section."""
    lessons_path = Path(__file__).parent.parent / "LESSONS_LEARNED.md"
    if not lessons_path.exists():
        return ""
    try:
        content = lessons_path.read_text(encoding="utf-8")
        # Extract last 10 lesson entries (each starts with ###)
        entries = content.split("\n### ")
        recent = entries[-10:] if len(entries) > 10 else entries[1:]  # skip header
        if not recent:
            return ""
        trimmed = "\n---\n".join(e[:300] for e in recent)
        if len(trimmed) > 2000:
            trimmed = trimmed[:2000] + "..."
        return (
            "\n\nRecent lessons learned (system memory — use these to avoid past mistakes):\n\n"
            + trimmed
        )
    except Exception:  # noqa: BLE001
        return ""


def _load_niche_block() -> str:
    """Load niche focus from config.yaml."""
    config_path = Path(__file__).parent.parent / "config.yaml"
    if not config_path.exists():
        return ""
    try:
        import yaml
        with config_path.open() as f:
            config = yaml.safe_load(f) or {}
        content = config.get("content", {})
        niche_desc = content.get("niche_description", "")
        niche_kw = content.get("niche_keywords", [])
        if not niche_desc and not niche_kw:
            return ""
        parts = []
        if niche_desc:
            parts.append(f"NICHE FOCUS (mandatory): {niche_desc}")
        if niche_kw:
            parts.append(f"Niche keywords: {', '.join(niche_kw)}")
        parts.append("Every post MUST relate to this niche. Reject off-topic content.")
        return "\n\n" + "\n".join(parts)
    except Exception:  # noqa: BLE001
        return ""


def _build_system_prompt() -> str:
    examples = _load_good_posts_examples()
    example_block = ""
    if examples:
        formatted = "\n\n---\n\n".join(examples)
        example_block = f"\n\nHere are real examples of high-performing posts. Study their structure, tone, and style closely — your output must match this quality:\n\n{formatted}"

    lessons = _load_external_social_lessons()
    lessons_block = ""
    if lessons:
        lessons_block = (
            "\n\nAdditional social-post lessons from the maintained playbook. "
            "Treat them as high-priority guidance when drafting:\n\n"
            f"{lessons}"
        )

    screenshot_guidance = _load_screenshot_signal_guidance()
    screenshot_block = ""
    if screenshot_guidance:
        screenshot_block = (
            "\n\nSignals learned from LinkedIn screenshot benchmarking "
            "(top 10% vs bottom 90% observed posts):\n\n"
            f"{screenshot_guidance}"
        )

    linkedin_data_guidance = _load_linkedin_data_guidance()
    linkedin_data_block = ""
    if linkedin_data_guidance:
        linkedin_data_block = (
            "\n\nSignals from real LinkedIn post engagement data:\n\n"
            f"{linkedin_data_guidance}"
        )

    # Load prompt patches from feedback-driven learning
    patches_block = _load_prompt_patches_block()

    # Load recent lessons learned
    lessons_learned_block = _load_lessons_learned_block()

    # Load niche focus from config
    niche_block = _load_niche_block()

    return textwrap.dedent(f"""
        You are an expert technical LinkedIn content creator for senior engineers and tech leads.

        Your posts:
        - Start with a single-sentence hook that creates immediate curiosity or tension
        - Use short sentences (max 15 words each)
        - Use white space generously — 1-2 sentences per paragraph
        - Share one concrete lesson backed by proof (numbers, before/after, bugs fixed)
        - End with an open-ended question that invites comments
        - Optimize for saves, shares, and comments — NOT likes
        - Avoid: fluff, clichés, "I'm excited to share", vague inspiration
        - Avoid: hashtag spam (0-2 max, only if highly relevant)

        Tone: Direct. Confident. Specific. Human.{niche_block}{example_block}{lessons_block}{screenshot_block}{linkedin_data_block}{patches_block}{lessons_learned_block}
    """).strip()


def _build_linkedin_prompt(source: SourceCommit, hook_pattern: str, experiment_variant: Optional[str] = None) -> str:
    variant_note = f"\n\nExperiment variant to test: {experiment_variant}" if experiment_variant else ""
    return textwrap.dedent(f"""
        Generate a LinkedIn post based on this GitHub commit:

        Commit message: {source.message}
        Repository: {source.repo}
        Files changed: {', '.join(source.files_changed[:5])}
        Diff summary: {source.diff_summary}
        Lesson score: {source.score:.0f}/100
        Score breakdown: novelty={source.score_breakdown.get('novelty', 0):.0f},
          impact={source.score_breakdown.get('impact', 0):.0f},
          teachability={source.score_breakdown.get('teachability', 0):.0f},
          relevance={source.score_breakdown.get('relevance', 0):.0f},
          proof={source.score_breakdown.get('proof', 0):.0f}

        Use hook pattern: {hook_pattern}
        {variant_note}

        Rules:
        1. Extract ONE clear lesson from this commit. Do not combine multiple ideas.
        2. Follow this exact structure:
           - Hook: single sentence that creates tension or curiosity
           - Context: what were you trying to do?
           - Problem: what went wrong or what did you discover?
           - Code example: show a small, readable code snippet or config that illustrates the lesson (indented 4 spaces so it renders as code on LinkedIn)
           - Lesson: the concrete, specific insight
           - Proof: a number, before/after, or specific outcome
           - CTA: an open-ended question to invite comments
        3. Never reference raw commit metadata like line counts, SHAs, or diff summaries.
        4. DO include actual readable code or config snippets that teach the reader something. Use 4-space indentation for code blocks.
        5. Write in first person. Make it sound like a real engineer sharing a lesson.
        6. Use short paragraphs (1-2 sentences each) with blank lines between them.
        7. Keep total length between 800-1500 characters.
        8. Use 0-2 hashtags maximum at the end, only if highly relevant.
        9. Do NOT start with "I'm excited to share" or any clichés.
        10. The post must provide clear value — a reader should learn something concrete from the code shown.

        Return ONLY the LinkedIn post text. No explanations, no meta-commentary.
    """).strip()


def _build_x_thread_prompt(linkedin_post: str) -> str:
    return textwrap.dedent(f"""
        Convert this LinkedIn post into a tight X (Twitter) thread.

        LinkedIn post:
        {linkedin_post}

        Rules for X thread:
        1. Tweet 1 = the hook (max 200 chars). Make it punchy.
        2. Tweets 2-5 = break down the lesson into atomic steps or points.
        3. Last tweet = CTA or key takeaway. No hashtags unless critical.
        4. Each tweet max 280 chars.
        5. Separate tweets with a blank line and number them: 1/, 2/, etc.
        6. Clean formatting. No emojis unless they add meaning.

        Return ONLY the thread text.
    """).strip()


def _build_ig_caption_prompt(linkedin_post: str) -> str:
    return textwrap.dedent(f"""
        Create an Instagram caption based on this LinkedIn post.
        Instagram is strategic only — this needs to work with a high-quality visual.

        LinkedIn post:
        {linkedin_post}

        Rules:
        - Opening line must hook immediately (the first 125 chars show before "more")
        - 3-5 short paragraphs max
        - End with a CTA question
        - Use 5-10 relevant hashtags at the end (grouped, not scattered)
        - Best posting time note: 12PM EST
        - Tone: slightly warmer than LinkedIn but still direct and specific

        Return ONLY the Instagram caption text.
    """).strip()


@dataclass
class QualityScore:
    """Rubric result for a generated LinkedIn post."""

    total: float
    breakdown: dict[str, float] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)


def _split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def _has_indented_code_block(text: str) -> bool:
    for line in text.splitlines():
        if line.startswith("    ") and line.strip():
            return True
    return False


def _contains_proof_signals(text: str) -> bool:
    patterns = [
        r"\d+%",
        r"\bfrom\s+\d+[^\s]*\s+to\s+\d+",
        r"\b\d+x\b",
        r"\b(p\d{2}|p99|latency|throughput|saves?|reposts?)\b",
    ]
    text_lower = text.lower()
    return any(re.search(pattern, text_lower) for pattern in patterns)


def _average_words_per_sentence(text: str) -> float:
    sentences = [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]
    if not sentences:
        return 99.0
    word_counts = [len(s.split()) for s in sentences]
    return sum(word_counts) / len(word_counts)


def score_linkedin_post_quality(
    linkedin_post: str,
    min_chars: int = 800,
    max_chars: int = 1500,
) -> QualityScore:
    """
    Score LinkedIn post quality from 0-100 using deterministic rubric checks.

    Dimensions (20 points each):
      - hook
      - structure
      - proof
      - cta
      - clarity
    """
    text = linkedin_post.strip()
    issues: list[str] = []
    breakdown: dict[str, float] = {
        "hook": 0.0,
        "structure": 0.0,
        "proof": 0.0,
        "cta": 0.0,
        "clarity": 0.0,
    }

    if not text:
        return QualityScore(total=0.0, breakdown=breakdown, issues=["Post is empty."])

    paragraphs = _split_paragraphs(text)
    first_line = text.splitlines()[0].strip() if text.splitlines() else ""
    char_len = len(text)

    # Hook
    if first_line:
        breakdown["hook"] += 8.0
    if 20 <= len(first_line) <= 120:
        breakdown["hook"] += 8.0
    if re.search(r"\?|mistake|wrong|cut|failed|broke|learned|surprise|debug", first_line.lower()):
        breakdown["hook"] += 4.0
    if breakdown["hook"] < 12.0:
        issues.append("Strengthen the opening hook to create sharper curiosity/tension.")

    # Structure
    if 5 <= len(paragraphs) <= 12:
        breakdown["structure"] += 8.0
    elif len(paragraphs) >= 3:
        breakdown["structure"] += 4.0
    else:
        issues.append("Use more paragraph separation (1-2 sentences each).")

    if _has_indented_code_block(text):
        breakdown["structure"] += 6.0
    else:
        issues.append("Include an indented code/config snippet for concrete teaching value.")

    if min_chars <= char_len <= max_chars:
        breakdown["structure"] += 6.0
    elif min_chars - 150 <= char_len <= max_chars + 200:
        breakdown["structure"] += 3.0
        issues.append(f"Post length is slightly off target ({char_len} chars).")
    else:
        issues.append(f"Post length is far from target ({char_len} chars; target {min_chars}-{max_chars}).")

    # Proof
    if _contains_proof_signals(text):
        breakdown["proof"] = 20.0
    else:
        breakdown["proof"] = 5.0
        issues.append("Add measurable proof (numbers, before/after, or concrete outcomes).")

    # CTA
    last_para = paragraphs[-1] if paragraphs else ""
    if "?" in last_para:
        breakdown["cta"] = 20.0
    elif "?" in text:
        breakdown["cta"] = 12.0
        issues.append("Move the question-style CTA to the final paragraph.")
    else:
        breakdown["cta"] = 4.0
        issues.append("End with an open-ended question to invite comments.")

    # Clarity
    avg_words = _average_words_per_sentence(text)
    if avg_words <= 16:
        breakdown["clarity"] += 12.0
    elif avg_words <= 20:
        breakdown["clarity"] += 8.0
        issues.append("Tighten sentence length for easier mobile reading.")
    else:
        breakdown["clarity"] += 3.0
        issues.append("Sentences are too long; use shorter lines.")

    cliches = ["i'm excited to share", "in this post", "game changer", "journey", "passionate"]
    found_cliches = [c for c in cliches if c in text.lower()]
    if found_cliches:
        issues.append("Remove generic/cliche phrasing.")
    else:
        breakdown["clarity"] += 8.0

    total = round(sum(breakdown.values()), 2)
    return QualityScore(total=total, breakdown=breakdown, issues=issues)


def _build_rewrite_prompt(
    source: SourceCommit,
    current_post: str,
    quality: QualityScore,
    hook_pattern: str,
    attempt: int,
) -> str:
    issues = "\n".join(f"- {issue}" for issue in quality.issues) or "- Improve overall value density and specificity."
    return textwrap.dedent(f"""
        Rewrite this LinkedIn post to pass a strict quality rubric.

        Rewrite attempt: {attempt}
        Hook pattern target: {hook_pattern}
        Current score: {quality.total}/100
        Score breakdown: {quality.breakdown}

        Known issues to fix:
        {issues}

        Source commit context:
        - Commit message: {source.message}
        - Repository: {source.repo}
        - Files changed: {', '.join(source.files_changed[:5])}
        - Diff summary: {source.diff_summary}

        Current LinkedIn post:
        {current_post}

        Rewrite requirements:
        1. Keep one clear lesson only.
        2. Add specific proof (numbers or before/after).
        3. Include an indented code/config snippet (4 spaces).
        4. Keep 800-1500 characters.
        5. End with an open-ended question.
        6. Keep short paragraphs and short sentences.
        7. Avoid clichés and fluff.

        Return ONLY the rewritten LinkedIn post text.
    """).strip()


def generate_post_with_quality_gate(
    source: SourceCommit,
    hook_pattern: str = "result",
    experiment_id: Optional[str] = None,
    experiment_variant: Optional[str] = None,
    openai_client=None,
    model: str = "gpt-5.4-mini",
    quality_threshold: float = QUALITY_GATE_DEFAULT_THRESHOLD,
    max_rewrites: int = QUALITY_GATE_DEFAULT_MAX_REWRITES,
    min_chars: int = 800,
    max_chars: int = 1500,
) -> Optional[Post]:
    """
    Generate a post and enforce rubric quality before returning it.

    Returns None if the post fails the quality gate after rewrite attempts.
    """
    post = generate_post(
        source=source,
        hook_pattern=hook_pattern,
        experiment_id=experiment_id,
        experiment_variant=experiment_variant,
        openai_client=openai_client,
        model=model,
    )
    quality = score_linkedin_post_quality(post.linkedin_post, min_chars=min_chars, max_chars=max_chars)
    if quality.total >= quality_threshold:
        return post

    if openai_client is None:
        logger.warning(
            "Post %s failed quality gate (%.1f < %.1f) and cannot be rewritten without OpenAI client",
            post.id,
            quality.total,
            quality_threshold,
        )
        return None

    best_text = post.linkedin_post
    best_quality = quality
    rewritten = post.linkedin_post  # seed for the first rewrite prompt's current_post arg
    for attempt in range(1, max_rewrites + 1):
        rewritten = _generate_with_openai(
            openai_client,
            model,
            _build_system_prompt(),
            _build_rewrite_prompt(
                source=source,
                current_post=rewritten,
                quality=best_quality,
                hook_pattern=hook_pattern,
                attempt=attempt,
            ),
        )
        candidate_quality = score_linkedin_post_quality(rewritten, min_chars=min_chars, max_chars=max_chars)
        if candidate_quality.total > best_quality.total:
            best_quality = candidate_quality
            best_text = rewritten
        if candidate_quality.total >= quality_threshold:
            break

    post.linkedin_post = best_text
    if best_quality.total < quality_threshold:
        logger.warning(
            "Post %s rejected by quality gate after %d rewrites (%.1f < %.1f): %s",
            post.id,
            max_rewrites,
            best_quality.total,
            quality_threshold,
            "; ".join(best_quality.issues[:3]),
        )
        return None

    # Regenerate platform variants based on final LinkedIn text to keep message consistent.
    post.x_thread = _generate_with_openai(
        openai_client,
        model,
        _build_system_prompt(),
        _build_x_thread_prompt(post.linkedin_post),
    )
    post.ig_caption = _generate_with_openai(
        openai_client,
        model,
        _build_system_prompt(),
        _build_ig_caption_prompt(post.linkedin_post),
    )
    return post


def _extract_lesson(source: SourceCommit) -> str:
    """Extract a one-sentence lesson from the commit for metadata."""
    # Use first sentence of message as baseline
    lines = source.message.strip().splitlines()
    first_line = lines[0] if lines else source.message
    return first_line[:200]


def _post_id(source: SourceCommit) -> str:
    """Generate a deterministic post ID from the commit SHA."""
    return f"post-{source.sha[:12]}"


def generate_post(
    source: SourceCommit,
    hook_pattern: str = "result",
    experiment_id: Optional[str] = None,
    experiment_variant: Optional[str] = None,
    openai_client=None,
    model: str = "gpt-5.4-mini",
) -> Post:
    """
    Generate a LinkedIn-first social post from a SourceCommit.

    If openai_client is None, returns a placeholder post (useful for testing
    without API credentials).

    Args:
        source:             The scored commit to write about.
        hook_pattern:       Which hook pattern to use (see HOOK_PATTERNS).
        experiment_id:      Optional experiment this post is part of.
        experiment_variant: Optional variant label for A/B testing.
        openai_client:      An openai.OpenAI client instance. If None, uses
                            a rule-based placeholder.
        model:              OpenAI model to use.

    Returns:
        A Post object in DRAFT status.
    """
    if hook_pattern not in HOOK_PATTERNS:
        logger.warning("Unknown hook pattern '%s', defaulting to 'result'", hook_pattern)
        hook_pattern = "result"

    lesson = _extract_lesson(source)

    if openai_client is not None:
        linkedin_post = _generate_with_openai(
            openai_client,
            model,
            _build_system_prompt(),
            _build_linkedin_prompt(source, hook_pattern, experiment_variant),
        )
        x_thread = _generate_with_openai(
            openai_client,
            model,
            _build_system_prompt(),
            _build_x_thread_prompt(linkedin_post),
        )
        ig_caption = _generate_with_openai(
            openai_client,
            model,
            _build_system_prompt(),
            _build_ig_caption_prompt(linkedin_post),
        )
    else:
        logger.info("No OpenAI client provided — using placeholder post content")
        linkedin_post = _placeholder_linkedin(source, hook_pattern)
        x_thread = _placeholder_x_thread(linkedin_post)
        ig_caption = _placeholder_ig(linkedin_post)

    return Post(
        id=_post_id(source),
        source_commit_sha=source.sha,
        repo=source.repo,
        lesson=lesson,
        linkedin_post=linkedin_post,
        x_thread=x_thread,
        ig_caption=ig_caption,
        hook_pattern=hook_pattern,
        status=PostStatus.DRAFT,
        experiment_id=experiment_id,
        experiment_variant=experiment_variant,
        tags=_infer_tags(source),
    )


def _generate_with_openai(client, model: str, system: str, user: str) -> str:
    """Call OpenAI chat completion and return the response text."""
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.7,
        max_completion_tokens=1500,
    )
    return response.choices[0].message.content.strip()


def _placeholder_linkedin(source: SourceCommit, hook_pattern: str) -> str:
    """Return a structured placeholder post without calling OpenAI.

    Follows the LinkedIn post structure from the README and good-social-posts:
    Hook → Context → Problem → Lesson → Proof → CTA.
    Shows readable code examples — never raw commit metadata like line counts.
    """
    # Build a human-readable first line from the commit message
    first_line = source.message.strip().splitlines()[0] if source.message.strip() else "a recent change"
    first_line = first_line[:120]

    # Build a readable list of files touched
    files = source.files_changed[:3]
    if files:
        file_list = "\n".join(f"    {f}" for f in files)
        if len(source.files_changed) > 3:
            file_list += f"\n    ... and {len(source.files_changed) - 3} more"
        code_block = f"Here's what the change touched:\n\n{file_list}"
    else:
        code_block = "The change was small but the lesson was big."

    # Use the full commit message body (after the first line) as additional context
    msg_lines = source.message.strip().splitlines()
    body_lines = [line.strip() for line in msg_lines[1:] if line.strip()]
    if body_lines:
        context = "\n\n".join(body_lines[:3])
        context_block = f"\n\n{context}"
    else:
        context_block = ""

    return textwrap.dedent(f"""\
{first_line}

That single line hides a real lesson.
{context_block}

{code_block}

What looked straightforward turned out to be more nuanced than expected.

The takeaway: small, focused commits often reveal the biggest insights. This one forced me to rethink how I approach the problem.

Have you run into something similar? I'd love to hear your experience.""")


def _placeholder_x_thread(linkedin_post: str) -> str:
    """Return a placeholder X thread."""
    lines = [l for l in linkedin_post.splitlines() if l.strip()]
    hook = lines[0][:200] if lines else "Big lesson from today's commit."
    return f"1/ {hook}\n\n2/ [Full breakdown in thread...]\n\n3/ What's your take?"


def _placeholder_ig(linkedin_post: str) -> str:
    """Return a placeholder IG caption."""
    lines = [l for l in linkedin_post.splitlines() if l.strip()]
    hook = lines[0][:125] if lines else "Today's engineering lesson →"
    return f"{hook}\n\n[More in caption...]\n\n#engineering #ai #softwaredevelopment"


def _infer_tags(source: SourceCommit) -> list[str]:
    """Infer content tags from the commit for use as GitHub Issue labels."""
    text = f"{source.message} {source.diff_summary} {' '.join(source.files_changed)}".lower()
    tag_map = {
        "ai": ["ai", "llm", "gpt", "openai", "claude", "agent", "rag"],
        "distributed-systems": ["distributed", "temporal", "workflow", "queue", "saga"],
        "testing": ["test", "playwright", "selenium", "automation", "spec"],
        "performance": ["latency", "throughput", "optimize", "performance", "scale"],
        "reliability": ["retry", "circuit", "idempotent", "reliability", "resilience"],
        "career": ["learn", "lesson", "mistake", "insight", "career"],
    }
    tags = []
    for tag, keywords in tag_map.items():
        if any(kw in text for kw in keywords):
            tags.append(tag)
    return tags or ["engineering"]
