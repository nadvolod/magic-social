# magic-social — GitHub Commit → Social Post Agent

An AI agent that transforms your GitHub commits into high-quality LinkedIn posts. It generates **multiple variations** per commit, stores each as a GitHub Issue for review, and continuously learns from your feedback and your own published posts (uploaded as screenshots).

**Starting baseline:** your real LinkedIn posts set the minimum quality bar. Generated posts must match your current style before publishing. But the goal isn't to match — it's to **surpass and grow**.

---

## Objective: 100% Follower Growth Per Year

The system's north star is **doubling your LinkedIn followers annually** through consistently high-performing content.

| Phase | Goal | Status |
|-------|------|--------|
| **1. Match** | Generate posts that match your current style | In progress |
| **2. Ship** | Get 3 AI-generated posts published | Not yet |
| **3. Learn** | Learning loop active, weights adjusting from real data | Waiting for published post analytics |
| **4. Outperform** | AI posts consistently beat your baseline engagement | Not yet |
| **5. Scale** | 100% follower growth year-over-year | Not yet |

Phase 1 uses your screenshot posts as the quality floor. Once the system ships posts that perform, it shifts to optimizing for **engagement and reach** — not just matching your voice.

---

## Metrics Dashboard

<!-- METRICS_DASHBOARD_START -->
View the live dashboard: **[magic-social dashboard](https://magic-social.vercel.app)**

Post pipeline metrics, quality scores, agent verdicts, and week-over-week trends — all updated automatically from pipeline runs.
<!-- METRICS_DASHBOARD_END -->

---

## Monitored Repos

The agent scans these repos for lesson-worthy commits. **Edit `config.yaml` → `agent.source_repos` to add or remove repos.**

| Repo | Topics |
|------|--------|
| [`nadvolod/LifeNotes`](https://github.com/nadvolod/LifeNotes) | AI (GPT-4o, Whisper), Playwright E2E, Next.js/Vercel, Clerk auth |
| [`nadvolod/temporal-learning`](https://github.com/nadvolod/temporal-learning) | Temporal.io, distributed systems, workflow orchestration, AI agents |
| [`nadvolod/ultimate-code-metrics`](https://github.com/nadvolod/ultimate-code-metrics) | Code quality metrics, engineering productivity |
| [`nadvolod/ceo-mission-control`](https://github.com/nadvolod/ceo-mission-control) | CEO tools, mission control, leadership engineering |
| [`nadvolod/magic-social`](https://github.com/nadvolod/magic-social) | This agent itself — meta-improvements, AI tooling |

To add a repo: edit `config.yaml` and add to `source_repos` list, then update `.github/workflows/scan-commits.yml` `--repos` argument to match.

---

## How It Works

1. **Scans** commits from monitored repos daily
2. **Scores** each commit 0-100 (novelty, impact, teachability, relevance, proof)
3. **Generates 3 variations** per qualifying commit (different hook patterns)
4. **Stores** each variation as a GitHub Issue for review
5. **Learns** from your feedback — which posts you publish, skip, or rate
6. **Benchmarks** against your real LinkedIn posts (uploaded as screenshot issues)

### Your Posts Set the Starting Bar

Upload screenshots of your published LinkedIn posts as [Social Screenshot issues](https://github.com/nadvolod/magic-social/issues/new?template=social-screenshot.md). The AI reads the content and engagement metrics, classifies them as top 10% vs bottom 90%, and uses those signals to improve future generation.

Right now, your posts are the quality floor — generated posts must meet this bar to ship. As the system learns from published post analytics, the goal shifts from matching your style to **beating your best engagement numbers** and driving follower growth.

---

## Quick Start

```bash
# Install
pip install -r requirements.txt

# Dry run — see what posts would be generated (no issues created)
python -m src.agent scan --repos nadvolod/LifeNotes nadvolod/temporal-learning --dry-run --variations 3

# Generate posts and create GitHub Issues
python -m src.agent scan --repos nadvolod/LifeNotes nadvolod/temporal-learning --issue-repo nadvolod/magic-social --variations 3

# Check system health
python -m src.agent health-check

# Refresh metrics dashboard
python -m src.agent metrics
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GITHUB_TOKEN` | Yes | GitHub PAT with repo + issues write access |
| `OPENAI_API_KEY` | Yes | OpenAI API key for AI-generated posts |
| `LINKEDIN_ACCESS_TOKEN` | No | LinkedIn OAuth 2.0 token for daily metrics polling |

---

## Giving Feedback

On any generated GitHub Issue:

- **Quick reactions:** 👍 good draft, 👎 bad draft, 🚀 published
- **Short comment:** `publish`, `rewrite`, `skip`, `too long`, `not relevant`, `weak hook`
- **Rating template:**
  ```
  ## Post Feedback
  - Verdict: published / skipped
  - Rating: 1-5
  - Improve: (what would make it better)
  ```

---

## Post Generation

Each commit gets **3 variations** with different hook patterns:

| Pattern | Template |
|---------|---------|
| `result` | "We cut {metric} by {amount}. Here's exactly how." |
| `contrarian` | "Most engineers {wrong_belief}. They're wrong." |
| `story` | "Yesterday I spent {time} debugging {problem}." |
| `number` | "{N} things I learned about {topic} the hard way:" |
| `question` | "Why does {bad_thing} keep happening in {system}?" |
| `confession` | "I made a mistake. {honest_statement}" |
| `revelation` | "I was wrong about {topic}. Here's what changed my mind." |

Each variation goes through a quality gate (scored 0-100, threshold 75) with up to 2 rewrite attempts.

---

## GitHub Actions

| Workflow | Schedule | What it does |
|----------|----------|-------------|
| Scan commits | Daily 08:00 UTC + push to main | Scans all monitored repos, generates 3 variations per commit |
| Collect analytics | Wed + Fri 09:00 UTC | Parses feedback from issues, updates learning state |
| LinkedIn poll | Daily 07:00 UTC | Polls LinkedIn API for engagement metrics |
| Self-improve | Monday 10:00 UTC | Analyzes backlog, tunes config |
| Screenshot learning | Daily 06:30 UTC + issue events | AI-classifies screenshot benchmark issues |

---

## Architecture

```
GitHub Actions → src/agent.py (orchestrator)
                    ↓
    ├─ commit_scanner.py  → scans repos for commits
    ├─ scoring.py         → scores 0-100
    ├─ post_generator.py  → generates 3 variations (OpenAI gpt-4o)
    ├─ github_storage.py  → creates GitHub Issues
    ├─ analytics.py       → learning loop
    └─ experiments.py     → A/B testing
```

| Component | File | Purpose |
|-----------|------|---------|
| Orchestrator | `src/agent.py` | Pipeline, CLI, metrics |
| Commit scanner | `src/commit_scanner.py` | Multi-repo scanning |
| Scoring | `src/scoring.py` | 0-100 with learned weights |
| Post generator | `src/post_generator.py` | AI content + quality gate |
| Storage | `src/github_storage.py` | GitHub Issues |
| Analytics | `src/analytics.py` | Feedback + learning |
| Experiments | `src/experiments.py` | A/B tests |
| Screenshot learning | `src/screenshot_learning.py` | Visual benchmark learning |
