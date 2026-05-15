# LinkedIn Post + Image Placement Guidance

## Final LinkedIn Post

I thought email reminders would be easy.

They turned into a distributed systems problem.

I'm building a small app called **Life Notes**.

The idea is simple: Help people **avoid making the same mistake twice.**

But one feature did break the system, many times:

**Email reminders.**

Sounds trivial. It isn't.

Once you try to build it properly, the edge cases explode.

A few problems that show up immediately:

• What happens to scheduled reminders when the server restarts?\
• What happens when a user changes the number of reminders per day?\
• How do you spread notifications across the day instead of sending them
all at once?\
• How do you guarantee reminders aren't duplicated or lost?

That's when I realized:

**Email reminders aren't a feature.\
They're a scheduling system.**

This turned a "simple feature" into a **distributed systems problem.**

One unexpected discovery while building this:

Adding these instructions to my `AGENTS.md` dramatically improved the
quality of AI-generated code.

    Act as an architect and review the PR for areas of weakness.

    Act as a tester and identify all edge cases. Write tests.
    Prefer integration tests that make DB and API calls.

    Code coverage must be measured and maintained.

    Must have thorough monitoring.

    Must include thorough logging.

These few lines changed the behavior of the AI completely.

Instead of generating quick demos, it started producing:

• stronger architectures\
• real edge-case handling\
• better tests\
• production-grade thinking

Examples from the AI PR review below.

The biggest lesson so far:

**The quality of AI code depends heavily on the constraints you give
it.**

Most developers prompt AI like a junior dev.

If you prompt it like a **staff engineer reviewing production systems**,
the output changes dramatically.

Curious how others are structuring their `AGENTS.md` or AI coding
guidelines.

------------------------------------------------------------------------

# How to Attach Screenshots in LinkedIn

## Image Order (Important)

Use **two images** in this order:

1.  **Architecture Weaknesses Identified**
2.  **Code Coverage Table**

### Why this order works

The narrative becomes:

Problem → Engineering analysis → Proof of rigor.

Readers first see the **system critique**, then the **testing results**.

This increases credibility.

------------------------------------------------------------------------

# Where the Images Appear

LinkedIn images appear **after the text**, so reference them in the
post.

Insert this line before the lesson section:

> Examples from the AI PR review below.

Then attach the screenshots when posting.

------------------------------------------------------------------------

# Screenshot Optimization

For best engagement:

## Image 1 (Architecture Weaknesses)

Crop so the list is clearly visible:

-   No retry mechanism
-   Single-instance assumption
-   No circuit breaker
-   No pagination
-   Idempotency key granularity

This reads like a **system design interview critique**, which engineers
love.

## Image 2 (Code Coverage)

Show the **90% enforcement** headline clearly.

This signals: - strong testing culture - production discipline - real
engineering rigor

------------------------------------------------------------------------

# Why Screenshots Increase Engagement

Engineering posts perform better when they include:

-   GitHub screenshots
-   architecture diagrams
-   logs or terminal output
-   test coverage results

They prove the work is **real**, not theoretical.

------------------------------------------------------------------------

# Optional Future Content (High-Leverage)

This single topic can become **three posts**:

1.  *Why email reminders become distributed systems problems*
2.  *The AGENTS.md trick that makes AI code better*
3.  *AI reviewing architecture weaknesses in my PR*

This multiplies reach and builds authority.
