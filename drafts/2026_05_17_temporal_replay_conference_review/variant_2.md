        # variant_2 — founder_story

        **Intended audience:** Engineers building agent workflows, especially those moving from demos to production systems with restarts, deploys, and partial failures.
        **Why it may perform:** Uses a concrete debugging story, keeps one lesson, and connects a workshop experience to a production-grade takeaway engineers can apply immediately.
        **Risks:** The 3-hour debugging detail is a plausible scenario assumption, so some readers may prefer a more explicit note that it came from workshop support.

        ---

        Yesterday I spent 3 hours debugging a workshop demo that kept "working" until it restarted.

Here's what I found.

I was helping at Replay during the Nexus workshop, and the failure mode was subtle.

The flow looked fine on the happy path.
Call service A.
Wait for a response.
Continue the workflow.

Then we'd restart a worker or lose a process.
Suddenly the system exposed the real bug: the orchestration logic assumed the process would stay alive.

The fix was not a better prompt.
It was durable state and explicit timeouts.

    result = await workflow.execute_activity(
        call_tool,
        request,
        start_to_close_timeout=timedelta(seconds=30),
        retry_policy=RetryPolicy(max_attempts=3),
    )

    await workflow.wait_condition(
        lambda: workflow_state.tool_finished
    )

That pattern is boring.
It is also what turns a workshop demo into something you can trust.

The lesson: if your AI workflow depends on process memory, it will eventually fail in production.

Replay had 2,000+ engineers in the room, and the strongest talks kept circling the same reality: durable execution matters because crashes, deploys, and partial failures are normal.

I came in expecting more discussion about model tricks.
I left thinking much more about recovery semantics.

What was the last bug you found only after a restart or deploy?
