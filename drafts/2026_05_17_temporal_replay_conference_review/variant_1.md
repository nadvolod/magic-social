        # variant_1 — contrarian

        **Intended audience:** Senior engineers building AI agents and distributed systems in production
        **Why it may perform:** Strong contrarian hook, one clear lesson, credible conference-based authority signal, and concrete workflow code aligned with Temporal users.
        **Risks:** Leans on conference synthesis rather than a personal production metric, so it may feel less hard-won than an incident post.

        ---

        Most engineers treat AI orchestration as a prompt problem. They're wrong.

At Replay, I was listening for one thing: what actually breaks when AI systems leave the demo stage.

The pattern was consistent.

The hard part isn't getting an LLM to answer.

It's surviving timeouts, partial progress, retries, deploys, and human approvals without losing state.

That's why the most useful takeaway for me wasn't a model trick.

It was durable execution.

A simple pattern looks like this:

    @workflow.defn
    class ResearchWorkflow:
        @workflow.run
        async def run(self, query: str) -> Report:
            plan = await workflow.execute_activity(create_plan, query)
            for step in plan.steps:
                await workflow.execute_activity(execute_step, step)
            return await workflow.execute_activity(summarize_results, query)

Each step is isolated.
Each step can retry.
Each step can resume after a crash.

The lesson: AI agents fail in production for distributed systems reasons, not prompt reasons.

My proof was the conference itself.

In a room of 2,000+ engineers, the most credible conversations were about replay, recovery, and orchestration boundaries.
Not prompt templates.

That matched what I've seen building production systems too.

The "AI" part gets attention.
The durable part keeps it alive.

What failure mode forced you to stop treating agent orchestration like a prompt engineering problem?
