        # variant_3 — tactical_technical

        **Intended audience:** Production engineers who want concrete patterns for AI workflow reliability
        **Why it may perform:** Highly practical, easy to save, and delivers a concrete code pattern with a crisp operational lesson.
        **Risks:** Less emotional than the story variant and lighter on measurable outcome data.

        ---

        The most useful AI lesson I took from Replay was 6 lines of timeout and retry config.

I went to Replay expecting model discussions.

The more valuable takeaway was operational.

If you're building AI in production, every external call needs explicit failure boundaries.
Otherwise one slow dependency turns your agent into a stuck process.

This is the baseline pattern I keep coming back to:

    result = await workflow.execute_activity(
        call_model,
        prompt,
        start_to_close_timeout=timedelta(seconds=45),
        retry_policy=RetryPolicy(max_attempts=3),
    )

That snippet teaches two things.

First, timeouts are part of the contract.
Second, retries belong at the activity boundary, not hidden inside random helper code.

The lesson: reliable AI systems come from explicit orchestration semantics, not smarter prompts.

My proof is qualitative but specific.

Across sessions, workshops, and hallway conversations with 2,000+ attendees, the strongest production patterns kept coming back to the same boring primitives: retries, replay, and resumability.

That's also why the conference felt useful.
It was one of the few AI-heavy events where infrastructure got equal billing.

If you're shipping agents today, what's your default timeout and retry policy for model calls?
