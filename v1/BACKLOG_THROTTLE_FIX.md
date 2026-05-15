# Fix Plan: Backlog Growth, Duplicate Drafts, and Safe Recovery

**Date:** 2026-04-14
**Status:** Implemented (pending merge + cleanup run)
**Branch:** feat/feedback-loop-and-auto-regen

## Context

Post generation is currently blocked by the backlog throttle, but the throttle is not the primary bug. The deeper problem is that the scan workflow keeps revisiting the same rolling commit window and can create new social-post issues for commits that already produced drafts.

Current evidence:

```text
Backlog throttle activated for None: open_unpublished=121 (limit=10)
Backlog throttle activated -- skipping new draft generation.
Open unpublished: 121 (limit 10)
Stale unpublished (>7d): 0 (limit 4)
```

This explains why generation is stopped today, but not why the backlog grew so quickly. The backlog grew because the system is not idempotent.

## Root Cause

### Primary root cause: no deduplication before issue creation

- `scan` defaults to a rolling 7-day window when `--since` is not provided.
- The workflow runs on both `push` to `main` and the daily cron.
- The generator creates GitHub issues directly without checking whether that source commit already produced a social-post issue.
- Result: the same qualifying commit can be turned into a new draft issue on multiple runs.

### Secondary contributors

- The live workflow generates `--variations 3`, which multiplies draft volume.
- The backlog throttle limit of 10 is much lower than the workflow's possible output.
- The auto-archive path only targets old drafts and currently archives by age, not by confirmed lack of feedback.
- `health-check` exists but is not wired into the workflow, so the system can "succeed" while doing no useful work.

## Why Raising the Throttle Alone Is Not Enough

Increasing `DEFAULT_MAX_OPEN_UNPUBLISHED` from 10 to 30 would reduce immediate pressure, but it would not stop duplicate drafts from accumulating on later runs. It treats the symptom, not the growth mechanism.

The durable fix is:

1. Make scan idempotent.
2. Clean up the existing backlog without losing learning data.
3. Reduce generation pressure and overlapping workflow risk.
4. Improve visibility when generation is blocked again.

## Updated Fix Plan

### Step 1: Add idempotency before issue creation

Before creating a new social-post issue:

- Load existing social-post issues from GitHub with `state=all`.
- Build a processed set keyed by `source_commit_sha`.
- Skip generation for any commit SHA that already exists in a prior social-post issue.
- Log which commit was skipped and why.

Recommended behavior:

- Deduplication should be permanent by default: once a commit has produced a social-post issue, future scans should skip it.
- Add a manual override such as `--allow-duplicate-commits` for exceptional recovery/debug use.

This is the most important fix in the plan.

### Step 2: Preserve learning data before archiving backlog

We cannot guarantee retroactive human-quality feedback for drafts that nobody reviewed. We can guarantee that we preserve all available signal before cleanup.

For every issue selected for cleanup:

- Re-run analytics/feedback collection first.
- Parse any existing explicit signals:
  - comments
  - checkbox feedback
  - reactions
- Infer any implicit signals already supported by the system:
  - `no_feedback_72h`
  - `stale_unpublished_7d`
- Apply those signals to `learning_state.json` before closing anything.

For issues with no explicit human feedback, add a standardized archive feedback comment before closure so the reason remains visible in GitHub history and can be reprocessed later.

Recommended reason key:

- `backlog_cleanup_unreviewed`

Recommended note:

- archived during backlog reset to unblock generation before individual review

This keeps the cleanup signal distinct from explicit human rejection reasons.

### Step 3: Add a dedicated cleanup command instead of ad hoc bulk closing

Add a command such as:

```bash
python -m src.agent cleanup-backlog \
  --repo nadvolod/magic-social \
  --keep-recent 10 \
  --older-than-days 3 \
  --snapshot-output backlog_cleanup_20260414.json
```

Behavior:

- Select open unpublished issues.
- Keep the 10 most recent issues for continued human review.
- Archive older unpublished issues.
- Before archiving each issue:
  - harvest feedback
  - persist updates to `learning_state.json`
  - write an audit snapshot entry
- Archive consistently by:
  - updating the issue to `status:archived`
  - posting an explanatory comment
  - closing the issue

The snapshot artifact should include:

- issue number
- post id
- source commit SHA
- created_at
- labels
- reactions summary
- explicit feedback found
- implicit feedback inferred
- final archive reason
- whether the issue was retained or archived

### Step 4: Reduce generation pressure

After idempotency is in place:

- Reduce workflow generation from `--variations 3` to `--variations 1`.
- Keep `push` and daily scheduled runs.
- Add workflow `concurrency` so overlapping runs do not both execute the same scan.
- Raise `DEFAULT_MAX_OPEN_UNPUBLISHED` modestly from 10 to 20 so the system can absorb a normal batch without immediately deadlocking.

Rationale:

- Lowering variations cuts draft volume immediately.
- Concurrency reduces duplicate work from overlapping triggers.
- A moderate throttle increase gives breathing room without allowing runaway backlog.

### Step 5: Make archive behavior safer

If `AUTO_ARCHIVE_STALE_DAYS` is lowered from 14 to 7, the archive logic must become stricter first.

Required changes:

- Do not auto-archive drafts that already have explicit parsed feedback.
- Do not auto-archive published or explicitly approved content.
- Reuse the same archive helper used by manual cleanup so state stays consistent.
- Ensure archived issues end with both:
  - closed GitHub issue state
  - `status:archived` label

The current auto-archive path should not be tightened by age alone without these safeguards.

### Step 6: Add health-check visibility to the workflow

Add `health-check` before the scan step in the main workflow.

Goal:

- surface backlog counts and throttle risk every run
- warn clearly when generation is blocked
- avoid another multi-day silent stall

This should emit a workflow warning and step summary with exact counts. It does not need to fail the workflow as long as the problem is made visible.

## Verification

1. Idempotency:
   - run scan twice against the same commit window
   - confirm the second run does not create duplicate issues for existing commit SHAs
2. Cleanup:
   - run cleanup in dry-run mode
   - verify retained vs archived issue selection
   - run cleanup for real
   - confirm `learning_state.json` updates before issue closure
   - confirm snapshot artifact is written
   - confirm archived issues have explanatory comments, `status:archived`, and closed state
3. Generation pressure:
   - confirm workflow uses `--variations 1`
   - confirm concurrency prevents overlapping duplicate scans
4. Health visibility:
   - confirm `health-check` runs before scan
   - confirm blocked states are visible in workflow warnings/summary

## Key Files

| File | Role |
|------|------|
| `src/agent.py` | scan flow, backlog throttle, auto-archive, new cleanup command |
| `src/github_storage.py` | status updates, comment helpers, archive consistency |
| `.github/workflows/scan-commits.yml` | variations, concurrency, health-check wiring |
| `learning_state.json` | preserved learning signals from cleanup |
| `config.yaml` | documentation of intended generation settings |

## Implementation Notes

- The cleanup flow should preserve available data, but it should not pretend that bulk-archived drafts are equivalent to thoughtful human review.
- Use a dedicated archive reason key so future learning logic can down-weight or exclude these backlog-reset examples if needed.
- The first success condition is not "higher throttle." The first success condition is "re-running scan against the same window is safe."
