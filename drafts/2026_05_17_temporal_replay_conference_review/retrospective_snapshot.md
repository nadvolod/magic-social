# LinkedIn Retrospective — last 60 days

## Snapshot

There are **no published-post analytics from your own account in this 60-day window**, so this retrospective relies entirely on **external reference posts**: **3 top performers** and **5 usable bottom performers** (one bottom entry, **ref #93**, has no content/signals and cannot support conclusions). The clearest pattern is that top posts were **straightforward, informative, and structurally easy to scan**—announcement, personal build story, or tutorial/list—while several bottom posts were **more technical, code-heavy, or promotional** without a comparably strong payoff signal. Confidence is **moderate at best** because the sample is small and only reference-based.

## Top performers

- **Source:** Reference — issue #95  
  **Key metrics:** engagement_score **436.0**; **379 reactions**, **12 comments**, **7 reposts**  
  **Why it worked:** It used an **announcement hook** with an **informative tone** and a clear **introduction → features → comparison → CTA** structure around a timely technology update.  

- **Source:** Reference — issue #94  
  **Key metrics:** engagement_score **111.0**; **60 reactions**, **10 comments**, **7 reposts**  
  **Why it worked:** It framed the content as a **personal story** tied to a real build and delivered it in a **list structure**, which made the Temporal use case concrete and easy to follow.  

- **Source:** Reference — issue #92  
  **Key metrics:** engagement_score **36.0**; **5,883 impressions**, **27 reactions**, **2 comments**, **1 repost**  
  **Why it worked:** It positioned itself as an **educational tutorial** with an **informative hook** and **list structure**, creating a clear expectation of practical value.  

## Bottom performers

- **Source:** Reference — issue #90  
  **Key metrics:** engagement_score **0.0**; **515 impressions**, **0 reactions**, **0 comments**, **0 reposts**  
  **Why it likely underperformed:** It opened with a **problem statement** and used a **narrative + bullets** format, but the post was also **code-including** and technically specific, which did not convert even modest reach into engagement.  

- **Source:** Reference — issue #204  
  **Key metrics:** engagement_score **2.0**; **2 reactions**, **0 comments**, **0 reposts**  
  **Why it likely underperformed:** Despite a sharp **contrarian/problem-solution hook**, it stayed in a **personal anecdote → problem → solution → takeaway** frame that appears less effective here than the top cohort’s simpler announcement/list/tutorial formats.  

- **Source:** Reference — issue #413  
  **Key metrics:** engagement_score **21.0**; **890 impressions**, **9 reactions**, **4 comments**, **0 reposts**  
  **Why it likely underperformed:** It mixed a **problem-solution hook** with a **promotional CTA** and **webinar link**, making it feel more like marketing than a standalone lesson.  

- **Source:** Reference — issue #100  
  **Key metrics:** engagement_score **49.0**; **3,480 impressions**, **31 reactions**, **5 comments**, **1 repost**  
  **Why it likely underperformed:** It was **step-by-step** and useful, but the topic was a narrow tooling tweak and included **code**, which drew some interest but far less than broader tutorial/build-story posts.  

- **Source:** Reference — issue #93  
  **Key metrics:** engagement_score **0.0**; no usable metrics/signals  
  **Why it likely underperformed:** No content was captured, so this entry should be excluded from pattern-setting.  

## Do this

- Open with a **plain-English value signal in the first line**: either a product/news announcement, a personal build statement, or a tutorial label; avoid making the reader infer the topic. [ref #95, ref #94, ref #92]  
- Use a **scan-friendly structure**: either a **list** for builds/tutorials or a **4-part sequence** of intro, features/details, comparison/context, and CTA for announcements. [ref #95, ref #94, ref #92]  
- Make the post about **one concrete artifact**—a launch, a thing you built, or a tutorial—not a broad reflection on a problem. [ref #95, ref #94, ref #92 vs. ref #90, ref #204]  
- Keep the tone **informative or educational**, not sales-led; the strongest reference posts all emphasized explanation over promotion. [ref #95, ref #94, ref #92 vs. ref #413]  
- If you include a CTA, make it **low-friction and content-adjacent**—“details,” “link,” or “contact”—rather than a webinar or overt promo ask. [ref #95, ref #92, ref #94 vs. ref #413]  
- For technical topics, **lead with the outcome/use case before implementation details**; the better-performing references foregrounded what was built or learned, while lower performers led more directly from technical setup/problem framing. [ref #94, ref #92 vs. ref #90, ref #100]  

## Avoid this

- Avoid opening on a **generic pain point or engineering annoyance** without immediately anchoring it to a tangible deliverable; that pattern showed up in low performers, not top ones. [ref #90, ref #204]  
- Avoid making the post **code-forward** in the main narrative; every usable bottom post with `has_code: true` stayed in the bottom cohort, while all top posts had `has_code: false`. [ref #90, ref #413, ref #100 vs. ref #95, ref #94, ref #92]  
- Avoid **promotional CTAs** such as webinar pushes or product-marketing framing; the clearest example underperformed despite decent formatting. [ref #413]  
- Avoid overly **niche tooling/setup posts** unless you broaden them into a larger engineering lesson or workflow outcome. [ref #100 vs. ref #92, ref #94]  

## Shaping the next draft

Write the next post as a **clear, useful artifact post**: first line says exactly what it is, then use a **list-based structure** to explain what was built, what it does, and why it matters to engineers working on distributed systems, AI agents, or Temporal. Keep the body **educational and concrete**, minimize code in the post itself, and end with a **light CTA** to learn more rather than a promotional ask.
