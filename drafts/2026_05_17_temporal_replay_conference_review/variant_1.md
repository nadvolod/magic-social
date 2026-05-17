        # variant_1 — contrarian

        **Intended audience:** Senior engineers and staff engineers building AI agents in production, especially those evaluating orchestration and durable execution patterns.
        **Why it may perform:** Strong contrarian hook, clear single lesson, concrete code, and a conference-derived insight tied directly to production pain the ICP recognizes.
        **Risks:** Could feel slightly broad without a personal production metric. Relies on conference observation rather than a deep incident story.

        ---

        Most engineers think AI agents fail because of prompts. They're wrong.

I went to Replay and spent most of my time in the AI and Nexus workshops.

The pattern that kept coming up was not model quality.

It was orchestration quality.

Teams can usually get a demo working.
What breaks in production is everything around the model:
retries, timeouts, resumability, and handoffs between systems.

A simple pattern I kept seeing was this:

    @workflow.defn
    class ResearchRun:
        @workflow.run
        async def run(self, query: str):
            plan = await workflow.execute_activity(make_plan, query)
            for step in plan.steps:
                await workflow.execute_activity(
                    execute_step,
                    step,
                    retry_policy=RetryPolicy(max_attempts=3),
                )
            return await workflow.execute_activity(finalize_report, query)

That code is not flashy.

That's the point.

The durable insight: production AI is mostly a distributed systems problem wearing an LLM badge.

Replay made that feel obvious. More than 2,000 engineers showed up to talk about durable execution, not just prompts. That tells you where the real pain is.

My biggest takeaway from the conference was that the "boring" parts are becoming the differentiator.

If your agent cannot survive a crash at step 4 of 9, you do not have an agent system yet. You have a demo.

What part of your AI stack is causing more pain today: model behavior or orchestration?
