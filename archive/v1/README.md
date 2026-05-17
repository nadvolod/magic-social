# v1 archive — cutover at Issue #422 on 2026-05-17

This folder holds artifacts from the v1 commit-driven model of LinkedIn draft generation. v1 auto-generated posts from git commits, scored them with a rubric tuned for code recaps, and tracked rejection reasons in a long-running learning state.

v2 (idea-driven) replaces that model. Drafts are now generated from the **Raw Idea** field of a content-idea Issue, reference posts (external LinkedIn screenshots in `screenshot_learning.json`) are the bar to clear, and the Raw Idea is the subject. Lessons distilled under v1 do not transfer — they encoded assumptions about commit-style content that no longer hold.

**Baseline:** [Issue #422](https://github.com/nadvolod/magic-social/issues/422) — first content-idea Issue under the v2 model after the re-baseline.

## What's here

| File | What it was | Why it's archived |
|---|---|---|
| `LESSONS_LEARNED.md` | Dated lessons from v1 feedback cycles ("9 posts rejected", "16 posts no feedback in 72h") | Tied to the commit-driven rejection loop. v2 has no such loop yet — and the lessons themselves ("posts go stale") don't apply when Issues are inherently timely. |
| `prompt_patches.json` | Auto-applied prompt rules from v1 feedback | The single entry was an `avoid_topic` rule mitigating stale commit-generated content. Not applicable to Issue-driven generation. |
| `linkedin_metrics.json` | 69 daily account-poll snapshots | All empty (`post_metrics: []`, `follower_count: 0`). The polling pipeline was never wired up. v2 relies on `screenshot_learning.json` for engagement signal instead. |
| `learning_state.json` | 58 v1 rejection fingerprints + v1 schema fields (`applied_feedback_fingerprints`, `not_published_reasons`, etc.) | Contaminated with v1 rejection reasons. Replaced at the root with a clean v2-schema file. |
| `voice.md` | Hand-written voice guide calibrated under v1 | Replaced by a data-derived voice synthesized from top reference posts + `good-social-posts/` exemplars. See `playbook/voice.md` going forward. |

## Recovering this state

`git log archive/v1/` and `git log -- LESSONS_LEARNED.md prompt_patches.json linkedin_metrics.json learning_state.json playbook/voice.md` show the full pre-cutover history. The files are intact — nothing was rewritten. To restore any of them, `git mv archive/v1/<file> <original-path>`.

## What does NOT need archiving (still valid for v2)

- `screenshot_learning.json` — external LinkedIn reference posts (top-10% / bottom-90%). Model-agnostic.
- `playbook/patterns.md` — patterns harvested from external reference analyses. Reference-derived, not commit-derived.
- `good-social-posts/*.md` — real LinkedIn posts in the user's voice. Quality bar, not v1 artifact.
- `reference_posts/` (if/when present) — external event-cohort analyses.

The v1 generator code (`src/post_generator.py` and its loaders `_load_external_social_lessons`, `_load_linkedin_data_guidance`, `_load_prompt_patches_block`, `_load_lessons_learned_block`) still exists for legacy/manual use, but is no longer invoked by the v2 entry point (`src/idea_generator.py`).
