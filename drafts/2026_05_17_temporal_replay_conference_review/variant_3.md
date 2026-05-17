        # variant_3 — tactical_technical

        **Intended audience:** Production AI engineers and architects designing multi-step agent systems with approvals, tool calls, and long-running workflows.
        **Why it may perform:** Practical and teachable. The code is simple, the lesson is crisp, and the framing aligns with engineers who want implementation guidance instead of conference recap fluff.
        **Risks:** Less emotionally sticky than the story or contrarian variants. Proof is observational rather than a hard before/after metric.

        ---

        One of the most useful ideas I took from Replay was this: add durability before adding more agent features.

I attended the AI sessions and helped with workshops, and the same implementation detail kept standing out.

Many agent stacks still treat multi-step work like a single request.

That breaks the moment a tool call hangs, a worker restarts, or a human approval arrives late.

A better default is to make each step durable and independently retryable.

    @workflow.defn
    class AgentRun:
        @workflow.run
        async def run(self, task: str):
            plan = await workflow.execute_activity(create_plan, task)
            approved = await workflow.execute_activity(request_approval, plan)
            if not approved:
                return "cancelled"
            return await workflow.execute_activity(execute_plan, plan)

Why this works:
- each boundary is persisted
- retries happen per step
- human input can arrive later
- restarts do not lose progress

The lesson: durable boundaries matter more than clever chains.

Replay had 2,000+ attendees, and the strongest technical conversations were about surviving failure, not just generating output.

That's also why the Nexus material stood out to me. It forces you to think about long-running, cross-service work as a system, not a prompt.

If you're building agents today, where are you drawing the boundary between orchestration and tool execution?
