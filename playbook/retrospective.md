# LinkedIn Retrospective — last 60 days

## Snapshot

There are **no analytics from your own published posts** in this 60-day window, so this retrospective relies entirely on a **small external reference set**: **3 top posts** and **5 usable bottom posts** (1 bottom entry, ref #93, has no text/signals and is not usable for pattern extraction). The clearest headline finding is that the top references won with **clear utility and simple packaging** — announcement, build story, or tutorial framed in a **list or structured explainer** — while many bottom references underperformed when they led with a **generic problem statement, contrarian line without strong proof, or overt promotion**. Confidence is **moderate at best** because the sample is small and there is no first-party performance data to validate fit with your voice or audience.

## Top performers

- **Source:** Reference — issue #95  
  **Key metrics:** engagement_score **436.0**; **379 reactions**, **12 comments**, **7 reposts**  
  **Why it worked:** It used an **announcement hook** plus an **introduction → features → comparison → CTA** structure with concrete product-change framing, which is the clearest packaging in the top set. [ref #95]

- **Source:** Reference — issue #94  
  **Key metrics:** engagement_score **111.0**; **60 reactions**, **10 comments**, **7 reposts**  
  **Why it worked:** It paired a **personal-story hook** with a **list structure** around something the author built, making the post feel both credible and easy to scan. [ref #94]

- **Source:** Reference — issue #92  
  **Key metrics:** engagement_score **36.0**; **5,883 impressions**, **27 reactions**, **2 comments**, **1 repost**  
  **Why it worked:** It framed the post as a **tutorial** with an **informative hook**, **educational tone**, and **list structure**, signaling immediate practical value. [ref #92]

## Bottom performers

- **Source:** Reference — issue #90  
  **Key metrics:** engagement_score **0.0**; **515 impressions**, **0 reactions**, **0 comments**, **0 reposts**  
  **Why it likely underperformed:** It opened with a **problem statement** and used a **narrative + bullet** format with **code** and **numbers**, but the hook was broad and the CTA leaned on curiosity rather than a clearly packaged payoff. [ref #90]

- **Source:** Reference — issue #204  
  **Key metrics:** engagement_score **2.0**; **2 reactions**, **0 comments**, **0 reposts**  
  **Why it likely underperformed:** Despite a sharp **contrarian/problem-solution hook**, it stayed in a **short anecdote → solution → takeaway** format without the stronger list/tutorial packaging seen in the top posts. [ref #204]

- **Source:** Reference — issue #413  
  **Key metrics:** engagement_score **21.0**; **890 impressions**, **9 reactions**, **4 comments**, **0 reposts**  
  **Why it likely underperformed:** It mixed **technical explanation** with a **promo/webinar CTA**, and that promotional intent appears weaker than the utility-first CTAs in the top set. [ref #413]

- **Source:** Reference — issue #100  
  **Key metrics:** engagement_score **49.0**; **3,480 impressions**, **31 reactions**, **5 comments**, **1 repost**  
  **Why it likely underperformed:** It was **informative** and **step-by-step**, but the hook centered on a niche config optimization rather than a broader build, launch, or tutorial frame that top posts used. [ref #100]

## Do this

- **Open with one of three proven hook types only:** an **announcement**, a **personal build story**, or a **tutorial/informative label** in the first line; these are the only hook styles represented in the top set. [ref #95, ref #94, ref #92]

- **Use a visibly structured body — preferably a list — for technical posts.** Two of the three top posts used a **list** structure, and the third used a tightly ordered **intro → features → comparison → CTA** sequence. [ref #94, ref #92, ref #95]

- **Make the payoff explicit in the first two lines.** Top posts immediately signaled what the reader would get: a new release, something built with Temporal, or a tutorial; bottom posts more often opened on a problem or opinion before clarifying the value. [ref #95, ref #94, ref #92 vs. ref #90, ref #204]

- **Anchor the post in a concrete artifact: launch, build, or tutorial.** Every top reference is tied to a tangible object the reader can understand quickly, while weaker posts often centered on a lesson, workflow gripe, or tooling preference. [ref #95, ref #94, ref #92 vs. ref #90, ref #204, ref #100]

- **Keep the CTA utility-first and low-friction:** “details,” “link,” or light contact invitation — not a webinar or overt promo ask. The strongest top post used a simple more-details CTA, and the tutorial post used a link; the promo-heavy webinar CTA appears in a bottom post. [ref #95, ref #92 vs. ref #413]

- **Include concrete specifics when the post is about product or capability changes.** The strongest post in the entire set included **numbers** and a **comparison** section; by contrast, bottom posts sometimes had numbers but not in a high-salience comparison frame. [ref #95 vs. ref #90, ref #204, ref #413]

## Avoid this

- **Avoid opening on a generic problem statement without naming the concrete deliverable.** The zero-engagement ref #90 starts with a familiar engineering pain, but top posts lead with what changed, what was built, or what will be taught. [ref #90 vs. ref #95, ref #94, ref #92]

- **Avoid contrarian one-liners unless the proof lands immediately after.** Ref #204 had a sharp contrarian hook but still posted near the bottom, suggesting the line alone is not enough without stronger packaging or evidence. [ref #204]

- **Avoid mixing education with overt promotion in the same post.** Ref #413 combined technical content with a webinar/promo CTA and underperformed relative to the utility-first top references. [ref #413 vs. ref #95, ref #92]

- **Avoid niche tooling tweaks as the main frame unless you broaden the relevance.** Ref #100 was step-by-step and useful, but it still sat in the bottom cohort because the topic framing was narrower than the tutorial/build/launch posts. [ref #100 vs. ref #94, ref #92, ref #95]

## How to exceed this cohort

The bar to clear is set by **ref #95’s scale**, **ref #94’s credible build-story framing**, and **ref #92’s tutorial clarity**. The next post should be better on at least three dimensions: **more specific to senior engineers building distributed systems/agents**, **more grounded in lived implementation detail**, and **more credible through sharper evidence or comparison points** than the strongest reference provides. Since you have no first-party analytics in-window, treat these references as directional only, then push beyond them with stronger practitioner proof and tighter relevance to Temporal, AI agents, or distributed systems. The Raw Idea is non-negotiable subject matter — references inform tone and shape, not topic. If a reference pattern doesn't strengthen the Raw Idea, drop it.
