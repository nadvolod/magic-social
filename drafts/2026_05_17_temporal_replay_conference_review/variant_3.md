# variant_3 — tactical

**Intended audience:** Staff and principal engineers evaluating agent architectures and orchestration frameworks
**Why it may perform:** List structure is easy to scan, highly actionable, and tied directly to production concerns the ICP values
**Risks:** Because this is an EXPERIENCE topic, it avoids code; readers expecting a deeper Temporal implementation detail may want a follow-up post

---

Replay reinforced a simple checklist I now use for every AI agent architecture.

If a system cannot survive interruption, I do not consider it production-ready.

That was the recurring theme I heard across sessions and hallway conversations.

Not model quality.

Not prompt tricks.

Recovery.

Watching packed rooms dig into workflow diagrams and long-running execution made the pattern hard to miss.

So here is the practical filter I would apply before shipping any agent:

1. Can each step be retried safely?
2. Can the process resume after a worker crash?
3. Can you inspect state mid-run?
4. Can you change code without corrupting in-flight work?
5. Can you explain what happened after the fact?

If I get a "no" on any of those, I know where the incident will come from.

A lot of agent stacks still look great in a demo and weak under interruption.

That is exactly why durable execution keeps coming up.

The strongest signal at Replay was not branding.

It was seeing rooms full of engineers spend their time on the boring questions that decide whether a system survives contact with production.

The lesson:

For AI agents, the architecture review should start with recovery semantics, not model choice.

What is the first question on your production-readiness checklist for agent systems?
