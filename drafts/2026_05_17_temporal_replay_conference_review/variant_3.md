# variant_3 — tactical

**Intended audience:** Staff/principal engineers choosing workflow, agent, or durable execution infrastructure
**Why it may perform:** Highly saveable format, practical checklist, and directly relevant to framework evaluation decisions.
**Risks:** Less emotionally engaging than a more scene-based conference recap. Also depends on the audience caring about tool selection.

---

My biggest takeaway from Temporal Replay: evaluate orchestration tools with 5 failure questions.

Assuming this was a conference review built around practical takeaways.

Replay reinforced something I keep seeing in production.

Teams compare workflow and agent tooling on developer experience first.

I think that's backwards.

The better filter is failure handling.

The 5 questions I'd now ask after this event:

1. What happens if a worker crashes mid-step?
2. What happens if the process restarts during a deploy?
3. Can the system resume without redoing completed work?
4. Where is retry behavior defined and audited?
5. What prevents non-deterministic orchestration logic?

If a tool answers those clearly, I'm interested.

If it mostly shows happy-path demos, I'm skeptical.

That's what made Replay useful for me.

It kept bringing the conversation back to operational mechanics instead of abstractions.

Especially for AI agents, that matters.

A 20-minute task is not impressive if a timeout forces you to restart from zero.

A multi-step workflow is not reliable if retries duplicate side effects.

The lesson: evaluate orchestration systems by recovery behavior, not demo quality.

What failure question do you ask first when you're evaluating workflow or agent infrastructure?
