# Good Post Example — Result Hook (AI Agents)

## Final LinkedIn Post

We cut our AI agent's hallucination rate from 23% to under 2%.

Here's exactly how.

Our research agent was summarizing documents and confidently inventing facts. Classic LLM problem.

But the fix wasn't prompt engineering. It was architecture.

We wrapped every LLM call in a Temporal activity with a verification step:

    @activity.defn
    async def verified_summarize(doc: str) -> Summary:
        raw = await llm.summarize(doc)
        claims = await llm.extract_claims(raw)
        verified = []
        for claim in claims:
            if await search_document(doc, claim.text):
                verified.append(claim)
        return Summary(claims=verified, dropped=len(claims)-len(verified))

The key insight: treat every LLM output as untrusted input. Verify claims against source material before passing them downstream.

The Temporal wrapper gives us automatic retries, timeouts, and a full audit trail of what was verified vs. dropped.

23% hallucination rate → 1.8% in production.

The cost: ~40% more LLM calls per request. Worth it when your agent is making decisions humans act on.

How are you handling hallucination detection in your AI pipelines?
