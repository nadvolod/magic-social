-- Magic Social Dashboard Schema
-- Run this against your NeonDB instance to set up the tables.

CREATE TABLE IF NOT EXISTS posts (
  id TEXT PRIMARY KEY,
  sha TEXT,
  repo TEXT,
  lesson TEXT,
  linkedin_post TEXT,
  hook_pattern TEXT,
  tags TEXT[],
  status TEXT DEFAULT 'draft',
  rubric_score REAL,
  rubric_breakdown JSONB,
  rubric_issues TEXT[],
  rewrite_attempts INT DEFAULT 0,
  experiment_id TEXT,
  experiment_variant TEXT,
  issue_number INT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  published_at TIMESTAMPTZ,
  user_rating INT,
  user_verdict TEXT,
  user_notes TEXT
);

CREATE TABLE IF NOT EXISTS agent_scores (
  id SERIAL PRIMARY KEY,
  post_id TEXT REFERENCES posts(id),
  agent_name TEXT,
  scores JSONB,
  verdict TEXT,
  details TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS feedback (
  id SERIAL PRIMARY KEY,
  post_id TEXT REFERENCES posts(id),
  source TEXT,
  rating INT,
  reason TEXT,
  improvement_notes TEXT,
  recorded_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS metrics_snapshots (
  id SERIAL PRIMARY KEY,
  snapshot JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS weekly_metrics (
  id SERIAL PRIMARY KEY,
  week_start DATE,
  posts_generated INT DEFAULT 0,
  quality_gate_pass_rate REAL,
  avg_rubric_score REAL,
  avg_agent_score REAL,
  bar_raiser_pass_rate REAL,
  explicit_ratings_count INT DEFAULT 0,
  avg_explicit_rating REAL,
  posts_published INT DEFAULT 0,
  posts_rejected INT DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(week_start)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(status);
CREATE INDEX IF NOT EXISTS idx_posts_created_at ON posts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_scores_post_id ON agent_scores(post_id);
CREATE INDEX IF NOT EXISTS idx_feedback_post_id ON feedback(post_id);
CREATE INDEX IF NOT EXISTS idx_weekly_metrics_week ON weekly_metrics(week_start DESC);
