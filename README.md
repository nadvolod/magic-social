# magic-social — GitHub Commit → Social Post Agent

An AI agent that transforms your GitHub commits into high-quality LinkedIn posts, stores every post as a GitHub Issue, collects performance analytics, and continuously learns to improve future content.

---

## 📐 Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     GitHub Actions                          │
│   scan-commits.yml (push / cron)                            │
│   analytics-update.yml (cron / manual)                      │
└────────────────┬───────────────────────────────────────────┘
                 │
         ┌───────▼───────┐
         │  src/agent.py │  ← Orchestrator
         └───┬───────────┘
             │
    ┌────────┴────────────────────────────┐
    │                                     │
┌───▼──────────────┐   ┌─────────────────▼──────┐
│ commit_scanner   │   │  analytics.py           │
│ (GitHub API)     │   │  (LearningState)        │
└───┬──────────────┘   └─────────────────┬──────┘
    │                                     │
┌───▼──────────────┐   ┌─────────────────▼──────┐
│ scoring.py       │   │  experiments.py         │
│ (0-100 score)    │   │  (A/B variants)         │
└───┬──────────────┘   └─────────────────┬──────┘
    │                                     │
┌───▼──────────────────────────────────────────────┐
│              post_generator.py                   │
│  LinkedIn post + X thread + IG caption           │
│  (OpenAI gpt-4o or placeholder)                  │
└───┬──────────────────────────────────────────────┘
    │
┌───▼──────────────┐
│ github_storage   │
│ (GitHub Issues)  │
└──────────────────┘
```

### Components

| Component | File | Responsibility |
|-----------|------|----------------|
| Orchestrator | `src/agent.py` | End-to-end pipeline, CLI |
| Commit scanner | `src/commit_scanner.py` | Fetches + filters GitHub commits |
| Scoring | `src/scoring.py` | Rates commits 0–100 for lesson-worthiness |
| Post generator | `src/post_generator.py` | AI-powered LinkedIn/X/IG content |
| GitHub storage | `src/github_storage.py` | Creates/updates GitHub Issues |
| Analytics | `src/analytics.py` | Parses metrics, drives learning loop |
| Experiments | `src/experiments.py` | A/B test management |
| Data models | `src/models.py` | Typed schemas for all entities |

---

## 📊 Data Model

### `SourceCommit`
```python
sha: str                  # Git commit SHA
repo: str                 # owner/repo
message: str              # Commit message
author: str
timestamp: str            # ISO 8601
files_changed: list[str]
diff_summary: str         # Safe summary (no raw code)
score: float              # 0-100
score_breakdown: dict     # Per-dimension scores
```

### `Post`
```python
id: str                       # Deterministic: post-{sha[:12]}
source_commit_sha: str
repo: str
lesson: str                   # One-sentence lesson
linkedin_post: str            # LinkedIn-ready text
x_thread: str                 # X/Twitter thread
ig_caption: str               # Instagram caption
hook_pattern: str             # See hook patterns below
status: PostStatus            # draft | approved | published | archived
created_at: str
published_at: Optional[str]
github_issue_number: Optional[int]
experiment_id: Optional[str]
experiment_variant: Optional[str]
tags: list[str]               # e.g. ["ai", "distributed-systems"]
```

### `AnalyticsSnapshot`
```python
post_id: str
github_issue_number: int
impressions: int
reactions: int
comments: int
reposts: int
saves: int
follower_delta: int
click_through: int
recorded_at: str
# Derived:
engagement_score: float   # saves×4 + reposts×3 + comments×3 + reactions×1 + ctr×2
engagement_rate: float    # (reactions+comments+reposts+saves) / impressions %
```

### `Experiment`
```python
id: str
variable: ExperimentVariable  # hook_style | post_length | tone | cta_type | structure
variants: list[str]
hypothesis: str
start_date: str
end_date: Optional[str]
status: ExperimentStatus      # running | concluded | paused
winner: Optional[str]
results: dict                 # post_id → {variant, engagement_score, recorded_at}
```

---

## ⚙️ Setup

### Prerequisites
- Python 3.11+
- GitHub repository with commits to scan
- OpenAI API key (optional — placeholder content is generated without it)
- GitHub token with `repo` + `issues:write` permissions

### Installation

```bash
pip install -r requirements.txt
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GITHUB_TOKEN` | ✅ | GitHub PAT with repo + issues write access |
| `OPENAI_API_KEY` | ⬜ | OpenAI API key for AI-generated posts |

---

## 🚀 Usage

### CLI

```bash
# Scan commits and generate posts (dry run — no issues created)
python -m src.agent scan --repo owner/repo --dry-run

# Scan and create GitHub Issues
python -m src.agent scan --repo owner/repo

# Scan only recent commits (last 14 days)
python -m src.agent scan --repo owner/repo --since 2024-01-01T00:00:00Z

# Limit posts per run
python -m src.agent scan --repo owner/repo --max-posts 2

# Collect analytics for published posts
python -m src.agent analytics --repo owner/repo --posts posts.json

# Show experiment summary
python -m src.agent experiments
```

### GitHub Actions

Two workflows are included:

| Workflow | File | Trigger |
|----------|------|---------|
| Scan commits | `.github/workflows/scan-commits.yml` | push to main, every Monday 08:00 UTC, manual |
| Collect analytics | `.github/workflows/analytics-update.yml` | Wed + Fri 09:00 UTC, manual |

**Required secrets:**
- `OPENAI_API_KEY` — set in repo Settings → Secrets

---

## 📋 GitHub Issues Format

Every generated post is stored as a GitHub Issue with:

**Labels applied automatically:**
- `social-post` — all posts
- `status:draft` → `status:approved` → `status:published`
- `platform:linkedin` (+ `platform:x`, `platform:instagram` when applicable)
- `analytics:pending` → `analytics:collected`
- Topic tags: `ai`, `distributed-systems`, `testing`, `performance`, `reliability`, `career`
- `experiment` — posts that are part of an A/B test

**Issue body structure:**
1. Post Metadata (table)
2. Lesson (one sentence)
3. LinkedIn post (copy-paste ready)
4. X thread
5. Instagram caption
6. Publishing checklist
7. Analytics input template
8. Raw JSON metadata (in collapsible block)

**Example analytics comment:**
```
## Analytics Update — 2024-02-01

- Impressions: 5,432
- Reactions: 123
- Comments: 45
- Reposts: 22
- Saves: 67
- Follower delta: +8
- Click-through: 30
- Notes: strong performance on saves
```

---

## 🎯 Commit Scoring Algorithm

Commits are scored 0–100 across five dimensions (20 points each):

| Dimension | What it measures |
|-----------|-----------------|
| **Novelty** | New patterns, insights, surprises, gotchas |
| **Impact** | Bug fixes, improvements, refactors, optimizations |
| **Teachability** | Descriptive message, causal language, context |
| **Relevance** | AI, LLMs, Temporal.io, distributed systems, testing |
| **Proof** | Percentages, before/after numbers, measurable outcomes |

**Hard filters (score = 0 automatically):**
- Sensitive data detected (API keys, passwords, tokens, credentials, PII)
- Low-value commits (merges, WIP, typos, version bumps, lint fixes)

**Threshold:** Commits scoring < 30 are not processed.

---

## ✍️ Post Generation Algorithm

### Hook Patterns

| Pattern | Template |
|---------|---------|
| `result` | "We cut {metric} by {amount}. Here's exactly how." |
| `contrarian` | "Most engineers {wrong_belief}. They're wrong." |
| `story` | "Yesterday I spent {time} debugging {problem}. Here's what I found." |
| `number` | "{N} things I learned about {topic} the hard way:" |
| `question` | "Why does {bad_thing} keep happening in {system}?" |
| `confession` | "I made a mistake. {honest_statement}" |
| `revelation` | "I was wrong about {topic}. Here's what changed my mind." |

### LinkedIn Post Structure
1. **Hook** — single sentence, creates tension or curiosity
2. **Context** — what were you trying to do?
3. **Problem** — what went wrong or what did you discover?
4. **Lesson** — the concrete, specific insight
5. **Proof** — a number, before/after, or specific outcome
6. **CTA** — open-ended question to invite comments

### Constraints
- 800–1,500 characters
- 1–2 sentences per paragraph
- Blank lines between paragraphs
- 0–2 hashtags maximum
- No LinkedIn Reels
- No fluff, clichés, or vague inspiration

### Platform Variants
- **X thread** — hook tweet + 3–4 breakdown tweets + CTA (280 chars each)
- **Instagram** — warmer tone, hook in first 125 chars, 5–10 hashtags, 12PM EST

---

## 🧪 Experiment Plan

Sequential A/B experiments run automatically:

| # | Variable | Variants | Hypothesis |
|---|----------|----------|------------|
| 1 | Hook style | result, contrarian, story, number | Result hooks drive more saves |
| 2 | Post length | short_600, medium_1000, long_1400 | Medium length maximises comments |
| 3 | Tone | technical_direct, conversational, confessional | Confessional generates more comments |
| 4 | CTA type | question_open, question_poll, no_cta | Open questions produce more comments |
| 5 | Structure | list_numbered, prose_flowing, before_after | Before/after drives more saves |

**Winner determination:** Average engagement score (saves×4 + reposts×3 + comments×3 + reactions×1 + ctr×2) after ≥3 posts per variant.

---

## 🔄 Learning Loop

1. After publishing, user adds analytics to the GitHub Issue comment
2. Analytics workflow reads the comment and parses metrics
3. `update_learning_state()` updates:
   - **Hook pattern scores** — tracks avg engagement per pattern
   - **Topic scores** — tracks which topics resonate most
   - **Scoring weights** — dimensions that correlate with high engagement get a small boost
4. Next scan uses the best hook pattern and highest-weight scoring dimensions

**Guardrails against overfitting:**
- Minimum 3 posts before any weight adjustments
- Maximum weight multiplier: 3.0×
- Minimum weight multiplier: 0.2×
- Step size per adjustment: 0.05 (gradual)
- Best-performing posts tracked (rolling window of 20)

---

## 🔐 Privacy & Security

The agent applies privacy-first defaults at every stage:

- **Sensitive pattern detection** scans commit messages AND diff summaries before processing
- **Diff summarization** converts raw code to line counts + structural keywords — never pastes actual code
- **Sensitive patterns blocked:** API keys, passwords, tokens, credentials, PII, database URLs, connection strings, customer data
- If any sensitive content is detected, the commit scores 0 and is skipped entirely

---

## ⚠️ Failure Modes & Mitigations

| Failure | Mitigation |
|---------|------------|
| Low-signal commits | Hard filters + score threshold (< 30 skipped) |
| Sensitive/confidential code | Privacy filter blocks entire commit; diff summarized, never pasted |
| Repeated topics | Experiment tracking + topic scores reduce redundancy over time |
| LLM hallucinations | One-idea rule + proof requirement + human approval checklist |
| Analytics not entered | Agent re-prompts on next run; non-blocking |
| Overfitting to one hook | Weight guardrails + minimum sample requirement |
| API rate limits | Per-commit try/except with graceful degradation to message-only scoring |

---

## 📦 MVP Plan

### Phase 1 — Manual Publish + Manual Analytics (Now)
- [x] Commit scanner with scoring algorithm
- [x] AI post generator (LinkedIn + X + IG)
- [x] GitHub Issues storage with labels + checklist
- [x] Learning state with adjustable weights
- [x] A/B experiment management
- [ ] Run `python -m src.agent scan --repo your/repo --dry-run`
- [ ] Review generated posts, approve, publish manually
- [ ] Add analytics as GitHub Issue comments after 48h

### Phase 2 — Automation
- [ ] LinkedIn API integration for direct publishing
- [ ] Automated analytics fetching (LinkedIn Analytics API)
- [ ] Slack/email notifications for post approval
- [ ] Dashboard for engagement trends
- [ ] Multi-repo support

---

## 🚫 Non-Goals

- Does **not** auto-publish without human approval
- Does **not** generate video/reel content
- Does **not** handle Instagram publishing (strategic only — manual)
- Does **not** guarantee post performance (learns over time)
- Does **not** access private customer data or proprietary algorithms
- Does **not** generate posts from low-signal commits (merges, typos, bumps)

---

## 📎 Example: End-to-End

**Commit:**
```
fix Temporal.io workflow saga timeout: make activities idempotent to prevent duplicate charges

Activities were not checking for existing results before executing.
This caused duplicate billing events under retry conditions.
Fixed by adding a deduplication check using the workflow ID.
p99 latency: 2000ms → 200ms after removing redundant DB writes.
```

**Score:** 87/100 (novelty=18, impact=20, teachability=17, relevance=20, proof=12)

**LinkedIn Post (generated):**
```
We had a silent billing bug for 3 weeks.

Users were getting charged twice on retries.

The fix wasn't in the payment code.
It was in how we wrote our Temporal.io activities.

Activities must be idempotent.
Ours weren't.

We added a deduplication check using the workflow ID before every execution.
p99 latency dropped from 2000ms to 200ms as a side effect —
we'd been doing redundant DB writes on every retry.

One small interface contract. Two problems fixed.

Have you ever had a correctness bug disguised as a performance issue?
```

**GitHub Issue:** `[Social Post] fix Temporal.io workflow saga timeout: make activities idempotent`  
Labels: `social-post`, `status:draft`, `platform:linkedin`, `analytics:pending`, `distributed-systems`

**Analytics request (48h after publish):**
```
📊 Analytics Request for Post #42
Please add your metrics to GitHub Issue #42.
```
