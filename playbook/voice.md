# Voice Guide — synthesized 2026-06-03

## Audience & ICP

This author writes for software engineers building production systems, especially around AI agents, workflows, distributed systems, and reliability. The curated posts consistently target readers who care about failure modes, architecture tradeoffs, debugging lessons, and practical implementation details rather than high-level AI hype.

## Tone

- **Direct and technical, but conversational** — posts use plain first-person framing ("I spent 3 days debugging...", "I'm building...") while discussing architecture, retries, determinism, and verification in concrete terms. [own examples 1–5]
- **Confident, grounded in evidence** — claims are usually backed by a bug, code snippet, metric, or before/after result such as "23% to 1.8%" or "2% to 0%." [own examples 2–4]
- **Slightly contrarian without sounding performative** — several posts pivot from a common assumption to a sharper lesson ("They're solving the wrong problem," "the fix wasn't prompt engineering. It was architecture"). [own examples 2, 3, 5]
- **Practical over promotional** — even when mentioning tools like Temporal or OpenAI, the emphasis is on what broke, how it was fixed, and what pattern generalizes. [own examples 2–5, ref #94, ref #92]
- **Invites peer discussion through specific questions** — endings ask for concrete war stories or implementation approaches, not generic engagement bait. [own examples 1–5]

## Hook style

- **False simplicity → real systems complexity** — opens with something that sounds easy, then reveals the hidden engineering problem underneath. [own example 1]
- **Debugging war story** — starts with time spent, a failure, or a production incident, then unpacks the root cause. [own examples 2, 4]
- **Strong result + "here's how"** — leads with a measurable improvement and promises the exact mechanism behind it. [own example 3]
- **Contrarian question** — opens by challenging a common practice or asking why standard approaches fail in production. [own examples 2, 5]
- **Personal build/update announcement** — benchmark posts sometimes open with a product launch or "I built something" framing, but the curated voice uses this less often and usually ties it quickly to an engineering lesson. [ref #95, ref #94, own example 1]

## Sentence and paragraph rhythm

- **Short sentences dominate the openings** — hooks often arrive as 1 short sentence per line, usually around 4–10 words, to create momentum ("Sounds trivial. It isn't."). [own examples 1, 2, 4, 5]
- **Paragraphs are brief, usually 1–3 sentences** — the author rarely stacks dense blocks; most ideas get their own paragraph for readability. [own examples 1–5]
- **Frequent white space for emphasis** — important turns are isolated on their own lines, especially lessons or reframes ("But the fix wasn't prompt engineering. It was architecture."). [own examples 1, 3]
- **Uses question lists to surface edge cases** — multiple posts include 3–4 parallel questions in bullets or hyphen lists to show operational complexity. [own examples 1, 5]
- **Code snippet followed by interpretation** — technical examples are shown in a compact code block, then immediately translated into a plain-English lesson. [own examples 2–5]
- **Ends with a single discussion prompt** — the final line is usually one question, separated as its own paragraph. [own examples 1–5]

## Vocabulary cues

- **Prefers concrete systems language** — words like "workflow," "activity," "retry," "idempotency," "non-deterministic," "audit trail," "timeouts," and "crash recovery" appear repeatedly. [own examples 2–5]
- **Uses "root cause," "fix," and "lesson" as structural markers** — many posts explicitly label the problem, the correction, and the takeaway. [own examples 2, 4]
- **Frames bad assumptions with sharp contrast words** — "Sounds trivial. It isn't." / "The lesson isn't X. It's Y." / "wasn't prompt engineering. It was architecture." [own examples 1–3]
- **Prefers exact numbers over vague improvement claims** — percentages, hours, days, counts, and durations are common and specific. [own examples 2–5, ref #95]
- **Uses production-oriented qualifiers** — phrases like "in production," "happy path," "edge cases," "silently," and "durably" signal real-world reliability concerns. [own examples 1, 3, 4, 5]
- **Names tools directly when relevant** — Temporal, OpenAI, Stripe, `datetime.now()`, `uuid4()`, and `AGENTS.md` are used plainly rather than abstracted away. [own examples 1–5]
- **Avoids inflated marketing language** — no visible use of buzzwords like "revolutionary," "game-changing," or "leverage"; the style stays concrete and technical. [own examples 1–5]

## Anti-patterns (what NOT to do)

- **Don't write generic inspirational advice without an engineering artifact** — the strongest posts always include a bug, metric, code snippet, edge-case list, or implementation detail, which is what makes the lesson credible.
- **Don't lead with product hype and stop there** — benchmark announcement posts exist, but the curated voice is strongest when a tool mention leads into a systems lesson rather than a feature parade.
- **Don't use long, dense paragraphs** — the author consistently relies on short paragraphs and white space, so wall-of-text formatting would break the reading rhythm.
- **Don't make abstract claims without numbers or consequences** — when something improved or failed, the posts usually quantify it or describe the operational impact; vague "better performance" language would feel off-voice.
- **Don't end with a generic CTA like "DM me" or "link in comments"** — the established pattern is a specific peer question that invites technical discussion.
- **Don't stay on the happy path** — the voice repeatedly focuses on retries, crashes, restarts, deadlocks, hallucinations, and duplicate charges; omitting failure modes would miss the core perspective.

## Quality bar — what a great post must do

- Open with a concrete problem, surprising result, or contrarian observation in very short lines.
- Ground the post in a real build/debugging scenario with specific systems detail.
- Show at least one of: code, metrics, edge cases, before/after numbers, or a precise root cause.
- Pivot to a clear lesson that generalizes beyond the single incident.
- Keep paragraphs short and use white space to isolate key insights.
- End with one specific question that invites practitioners to share real experience.

---

_Synthesized from 3 top reference posts, 5 curated examples on 2026-06-03._
