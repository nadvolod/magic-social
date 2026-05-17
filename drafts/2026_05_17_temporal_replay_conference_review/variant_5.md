        # variant_5 — short_engagement

        **Intended audience:** Engineers shipping AI systems who care about operational reliability
        **Why it may perform:** Compact, opinionated, and easy to comment on. Strong claim plus a specific question should drive engagement.
        **Risks:** Short format sacrifices nuance and may feel less differentiated without a stronger personal anecdote.

        ---

        Most AI conference takeaways focus on models.

My biggest takeaway from Replay was the opposite.

The teams building credible AI systems were obsessed with boring infrastructure: retries, timeouts, replay, resumability.

    await workflow.execute_activity(
        call_model,
        prompt,
        retry_policy=RetryPolicy(max_attempts=3),
    )

In a 2,000+ engineer room, durability kept coming up more than prompts.

What's the most important "boring" reliability feature in your AI stack right now?
