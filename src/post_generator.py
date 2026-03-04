"""AI-powered post generator — LinkedIn-first with X thread and IG caption variants."""

from __future__ import annotations

import hashlib
import logging
import textwrap
from pathlib import Path
from typing import Optional

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

# Directory containing hand-picked example posts (relative to repo root)
_GOOD_POSTS_DIR = Path(__file__).parent.parent / "good-social-posts"


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


def _build_system_prompt() -> str:
    examples = _load_good_posts_examples()
    example_block = ""
    if examples:
        formatted = "\n\n---\n\n".join(examples)
        example_block = f"\n\nHere are real examples of high-performing posts. Study their structure, tone, and style closely — your output must match this quality:\n\n{formatted}"

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
        - Topics that work: AI/LLMs, distributed systems, Temporal.io, testing, engineering career

        Tone: Direct. Confident. Specific. Human.{example_block}
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
           - Lesson: the concrete, specific insight
           - Proof: a number, before/after, or specific outcome
           - CTA: an open-ended question to invite comments
        3. Never paste code, diffs, secrets, tokens, or customer data.
        4. Write in first person. Make it sound like a real engineer sharing a lesson.
        5. Use short paragraphs (1-2 sentences each) with blank lines between them.
        6. Keep total length between 800-1500 characters.
        7. Use 0-2 hashtags maximum at the end, only if highly relevant.
        8. Do NOT start with "I'm excited to share" or any clichés.
        9. The post must provide clear value — a reader should learn something concrete.

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
    model: str = "gpt-4o",
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
        max_tokens=1500,
    )
    return response.choices[0].message.content.strip()


def _placeholder_linkedin(source: SourceCommit, hook_pattern: str) -> str:
    """Return a structured placeholder post without calling OpenAI.

    Follows the LinkedIn post structure from the README and good-social-posts:
    Hook → Context → Problem → Lesson → Proof → CTA.
    The output should read like a real LinkedIn post, not a raw data dump.
    """
    # Build a human-readable first line from the commit message
    first_line = source.message.strip().splitlines()[0] if source.message.strip() else "a recent change"
    first_line = first_line[:120]

    # Summarise the change scope
    file_count = len(source.files_changed)
    files_note = (
        f"across {file_count} files" if file_count > 1
        else f"in {source.files_changed[0]}" if file_count == 1
        else "in the codebase"
    )

    diff_note = source.diff_summary if source.diff_summary else "a targeted code change"

    return textwrap.dedent(f"""\
{first_line}

That single line hides a real lesson.

Here's the context:

I was working on a change {files_note} — {diff_note}.

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
