        # variant_2 — founder_story

        **Intended audience:** Engineers evaluating how to move AI workflows from demos to production
        **Why it may perform:** Uses a concrete story, a debugging frame, and a relatable workshop moment that exposes a real production concern.
        **Risks:** The debugging scenario is inferred from the workshop context, so some readers may want a more explicit personal production incident.

        ---

        Yesterday I spent 2 hours debugging a workshop example that looked fine. Here's what I found.

I was helping at Replay as a teaching assistant for two workshops.

The code worked on the happy path.

Then someone asked the production question:
"What happens if the process dies after step 2?"

That was the real bug.

The first version was doing orchestration inline inside an activity-shaped blob.
It could finish.
But it couldn't recover cleanly.

We refactored it into workflow state plus retryable activities:

    @workflow.defn
    class NexusFlow:
        @workflow.run
        async def run(self, req: Input) -> Output:
            a = await workflow.execute_activity(step_a, req)
            b = await workflow.execute_activity(step_b, a)
            return await workflow.execute_activity(step_c, b)

One small structural change.
Completely different failure behavior.

Now if the worker restarts after step_b, the workflow resumes from recorded history instead of replaying side effects blindly.

The lesson: if your AI or integration flow can't resume mid-flight, you haven't built orchestration yet.

The proof was immediate.

In the workshop, people stopped asking about the happy path and started asking the right questions: retries, recovery, and determinism.
That shift was the most valuable part of the session for me.

Replay had 2,000+ engineers in the room, but the best moments were still the small ones where a "working demo" became a production design discussion.

What's the question that usually reveals whether a workflow is real or just a demo?
