        # variant_3 — tactical

        **Intended audience:** Engineers and technical leaders responsible for deciding whether AI systems are ready for production deployment.
        **Why it may perform:** Highly saveable because it provides a reusable checklist. Keeps the conference framing but turns it into practical value.
        **Risks:** Bullets are less distinctive than code for some technical audiences. Still credible because this is an EXPERIENCE topic.

        ---

        Replay gave me a simple filter for evaluating AI systems in production.

I came away from the conference with one practical checklist.

I was at Replay with 2,000+ engineers focused on durable execution and AI, and I helped as a teaching assistant in the Nexus workshop with Mason and the AI workshop with Melissa.

Across sessions, hallway conversations, and talks from teams like Netflix and OpenAI, the same production questions kept showing up.

So this is the filter I'm taking back to every AI design review:

- Can this workflow resume after a crash?
- Can it retry without duplicating side effects?
- Can it survive long waits and partial progress?
- Can we inspect what step failed and why?
- Can we change the system without breaking in-flight work?

If the answer is no to most of these, it's not production-ready.
Even if the demo looks great.

One scene from the event captured the contrast for me.
During the day, engineers were deep in workshop problems about orchestration and recovery.
At night, the secret Tiki room, live music, and glow-in-the-dark cotton candy made it feel almost surreal.

But the lesson was very grounded.

AI in production should be reviewed like distributed systems infrastructure.
Not like a prompt experiment.

What checks are on your AI production-readiness list right now?
