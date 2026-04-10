# Good Post Example — Question Hook (LLM/AI Engineering)

## Final LinkedIn Post

Why do most AI agent frameworks fail in production?

I've deployed 3 different agent frameworks this year. Two failed within a week.

The pattern was always the same: the framework handles the happy path beautifully, but has no answer for:

- What happens when the LLM times out mid-chain?
- What happens when your agent crashes after step 3 of 7?
- How do you resume a 20-minute research task after a deploy?

The surviving framework wasn't a framework at all. It was Temporal + raw OpenAI calls:

    @workflow.defn
    class ResearchAgent:
        @workflow.run
        async def run(self, query: str) -> Report:
            plan = await workflow.execute_activity(
                create_plan, args=[query], start_to_close_timeout=timedelta(seconds=30)
            )
            results = []
            for step in plan.steps:
                result = await workflow.execute_activity(
                    execute_step, args=[step], retry_policy=RetryPolicy(max_attempts=3)
                )
                results.append(result)
            return await workflow.execute_activity(
                synthesize, args=[results], start_to_close_timeout=timedelta(seconds=60)
            )

Each step is an activity. If the agent crashes at step 4, it resumes at step 4 on restart. No lost work. No re-running expensive LLM calls.

The "boring" infrastructure — retries, timeouts, crash recovery — is what separates a demo from a product.

What's your experience running AI agents in production? Framework or custom?
