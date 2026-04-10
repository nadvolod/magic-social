# AI Agent Operating Rules (Repo)

The rules below are the authoritative local copy. Follow them exactly for every change and PR.

---

## Non-Negotiables (for every PR)

1. **Behavior-first summary** – Provide a short "What changed" list focused on user-visible behavior and system contracts (UI, API, data, permissions).
2. **User Flow Coverage** – For every feature or change, document:
   1. Happy path
   2. Failure paths (validation errors, permissions, network/offline, empty states, 404/500, timeouts)
3. **Evidence** – Include at least one of: screenshot(s) for UI changes, short screen recording (10–45 s) showing the flow, or CLI output snippet for non-UI changes (commands + results).
4. **Test Proof** – Tests must exist and must be runnable locally/CI. Provide: what tests you added/updated, the exact commands to run, and the result summary (pass/fail, coverage deltas if available).
5. Act as an architect and review the PR for areas of weakness. Identify those clearly and prioritized.
6. Act as a tester and identify all of the edge cases. Write tests. The majority of tests should be integration tests that make real DB and API calls with no mocking. Minority of tests should be unit tests. Should also have main use case e2e tests that exercise real functionality. It's better to clean up test data than mock.
7. Code coverage must be measured and maintained.
8. Must have thorough monitoring.
9. Must include thorough logging.
10. Never skip any tests if an env variable isn't configured. Fail the tests with a clear error message that names the missing variable and how to set it.
11. **CI must validate required env vars** — A dedicated CI job must check that all required secrets/env vars (e.g. `DATABASE_URL`, `MONARCH_TOKEN`) are configured in the repo. If any are missing, the job must fail with a clear message listing which vars are absent. This catches misconfiguration before tests silently pass with mocked data.
12. **Playwright E2E tests are mandatory** — Every PR must maintain at least 5 Playwright E2E tests that verify the most critical user flows render correctly in a real browser. Tests must run in CI against a local Next.js server (not production URL) so they validate the PR's code before merge. They catch client-side JavaScript crashes, null reference errors, and rendering failures that unit tests and HTTP-based tests cannot detect. Always run Playwright on localhost in CI.
13. Push every feature into a PR and then wait for review from Copilot or Coderabbit, implement their feedback when it makes sense.
14. Deploy on Vercel has to be tested and working. You must deploy and run test suite against the preview URL. Fix any failures automatically.
15. **Always create a PR** — Never push directly to main. Every change goes through a PR that follows all the steps in this file. Only notify the human when every step is complete: CI green, bot feedback resolved, checklist checked, and PR is ready to merge.
16. **CI-green before handoff** – After pushing a PR, monitor CI and reviewer bots (CodeRabbit, Copilot). Address all valuable feedback, re-push, and only notify the human once every check is green and bot comments are resolved. Do not hand off a red PR.

## Social Post Quality Rules

- For creating good social posts, they should follow the examples in the /good-social-posts folder. These are the gold standard as a starting point until we gather enough data to prove otherwise.

---

## PR Checklist — MANDATORY

> **CI will fail** if these items are missing or unchecked in the PR description.

- [x] Was canonical Agents.md followed?
<!-- CI matches "Agents.md" (title-case) — keep this exact casing even though the file is AGENTS.md -->
- [x] Was code coverage report included?
- [x] Was a behavior-first summary provided?
- [x] Were all user flows documented (happy path + failure paths)?
- [x] Was evidence included (screenshot, recording, or CLI output)?
- [x] Was an architectural review completed (areas of weakness identified)?
- [x] Were edge cases identified and tested?
- [x] Was monitoring and logging addressed?
- [x] Was new feature tests on the preview environment?

### If CI fails on the PR Checklist job

1. Read the workflow log to identify which checklist items are missing or unchecked.
2. Edit the PR description to add / check the missing items.
3. The workflow triggers on PR description edits (`edited` event), so updating the description is enough to re-run CI. If it doesn't re-trigger, push a new commit or manually re-run the workflow.
