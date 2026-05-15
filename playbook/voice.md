# Voice & Style Playbook

This is the durable voice guide for LinkedIn drafts. It is loaded into every generation prompt by `src/idea_generator.py`. Update sparingly — only when a pattern is proven across multiple posts.

## ICP (Ideal Customer Profile)

The reader is one of:
- A senior software engineer building distributed systems
- An engineer deploying AI agents in production
- A Temporal user (or someone debating whether to adopt durable execution)
- A staff/principal engineer who decides what frameworks teams adopt

Posts are NOT for:
- Junior developers learning to code
- Marketing or business audiences
- Generic "tech inspiration" readers

If a draft does not speak directly to the ICP above, it is off-topic and must be rejected.

## What the audience values

- Hard-won lessons from real production incidents
- Specific code/config snippets that teach a concrete technique
- Honest numbers (latency, error rates, cost, time saved)
- Contrarian takes backed by experience
- "Boring infrastructure" framing: retries, timeouts, crash recovery, idempotency

## What the audience scrolls past

- Generic AI hype ("AI is changing everything")
- Marketing-speak ("excited to announce", "thrilled to share")
- Posts without a concrete example or code
- Multi-topic posts (more than one lesson)
- Tutorials that don't end with a real takeaway

## Voice characteristics (extracted from the 5 verified high-performers in `good-social-posts/`)

1. **Hook is one line.** No throat-clearing.
   - "Most engineers retry failed API calls with exponential backoff."
   - "Yesterday I spent 4 hours debugging a workflow that silently stopped processing events."
   - "Why do most AI agent frameworks fail in production?"

2. **Second line resolves or amplifies the hook.** Often a contradiction or a "here's what I found."
   - "They're solving the wrong problem."
   - "Here's what I found."

3. **Code appears mid-post, indented 4 spaces, ~5–10 lines.** Real, runnable-looking. Not pseudocode.

4. **Lesson is one sentence.** Crisp. Quotable. Often contrarian.
   - "Retries without idempotency are a liability, not a safety net."
   - "Pure functions in workflows, side effects in activities."
   - "The 'boring' infrastructure is what separates a demo from a product."

5. **Proof is a real number.** "23% hallucination rate → 1.8%." "Duplicate charges dropped from ~2% to 0%." "4 hours of debugging." If you can't supply a real number, don't invent one — use a concrete observation instead ("Zero recurrence since.").

6. **CTA is one question.** Open-ended. Specific to the lesson.
   - "What's the most expensive retry bug you've shipped?"
   - "How are you handling hallucination detection in your AI pipelines?"

7. **Paragraph rhythm: short. Single-sentence paragraphs are common.** Long paragraphs are rare and reserved for code context.

## Recurring framings that work

- "Most engineers X. They're wrong." → contrarian authority
- "I spent N hours debugging Y. Here's what I found." → story / discovery
- "I've deployed N of X. Two failed. Here's the pattern." → authority through pattern
- "The fix was N lines." + code → tactical credibility
- "It looked like everything worked — until you check the [data source]." → silent-failure narrative

## Recurring topics where the user has authority

- Temporal (workflows, activities, retries, idempotency, replay determinism)
- AI agents in production (hallucination, durability, multi-step orchestration)
- Distributed systems debugging
- Testing & coverage discipline
- AGENTS.md / AI coding constraints
- Durable execution as a pattern (not just a Temporal product)

## Anti-patterns — never do these

- Open with "I'm excited to share" or any variant
- More than 2 hashtags
- Emoji decoration (a single emoji inline is acceptable; emoji-as-bullet is not)
- Combine multiple lessons in one post
- Reference raw GitHub Issue IDs, labels, or commit SHAs in the post body
- Invent benchmarks, customer outcomes, or specific company names
- Mimic another creator's personal story or proprietary numbers
- Generic CTAs like "thoughts?" or "what do you think?"

## Length targets

- LinkedIn primary variants: 800–1500 characters
- Short engagement variant: 300–700 characters
- Hook: ≤ 120 characters
- Average sentence length: ≤ 16 words

## How this file is used

The runtime injects this file's contents into the system prompt of `src/idea_generator.py`. Sections marked as anti-patterns become hard constraints. The "Voice characteristics" section is shown to the model as the style spec.
