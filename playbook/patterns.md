# Reusable Patterns

Living document of reusable hook, structure, and CTA patterns harvested from reference-post analysis. Updated by `src/reference_posts.py` when new pattern reports are generated, and curated manually.

## Hook patterns (verified)

| Pattern | Example | When to use |
|---|---|---|
| Contrarian | "Most engineers retry failed API calls with exponential backoff. They're wrong." | When the lesson contradicts common practice |
| Story / discovery | "Yesterday I spent 4 hours debugging a workflow that silently stopped processing events." | Real incident with a clear root cause |
| Question | "Why do most AI agent frameworks fail in production?" | Pattern across multiple cases the user has seen |
| Result | "We cut our AI agent's hallucination rate from 23% to under 2%." | When you have a real, defensible number |
| Confession | "I made a mistake. Here's what it cost." | Honest post-mortem; only when truthful |

## Body structure patterns

- **Two-line opener:** Hook line + amplifying line. Then blank line. Then body.
- **Code-mid-post:** Body sets up the problem, code appears around 50% of the post, lesson follows immediately after code.
- **Before/after framing:** Show broken code, then fixed code. Lesson is the one-line diff in mindset.

## CTA patterns

- Direct experience: "What's your most painful 'it was one line' debugging story?"
- Comparison: "How are you handling X in production?"
- Decision: "Framework or custom?"

## Anti-patterns observed in reference posts that did NOT perform

(Populated as reference-post analysis runs.)

## Pattern reports

(Links to detailed reports in `reference_posts/<event>/analysis/pattern_report.md` will be added by the analyzer.)
