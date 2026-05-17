        # variant_5 — short_engagement

        **Intended audience:** Engineers running AI systems in production who care more about reliability than hype.
        **Why it may perform:** Short, sharp, and comment-friendly. Strong claim, concrete snippet, and a specific CTA aimed at practitioners.
        **Risks:** Less room for nuance or proof. Some readers may want more detail before engaging.

        ---

        Most AI agent conversations still focus too much on prompts.

Replay pushed me the other way.

After spending time in the AI sessions and helping with workshops, my biggest takeaway was simple:

    await workflow.execute_activity(
        run_step,
        step,
        retry_policy=RetryPolicy(max_attempts=3),
    )

The real production problem is orchestration.
Retries. Timeouts. Resume after crash. Human handoff.

More than 2,000 engineers showed up to talk about durable execution.
That says a lot.

What failure mode is hurting your agent system most right now?
