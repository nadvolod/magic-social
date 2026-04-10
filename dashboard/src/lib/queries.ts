import { getDb } from "./db";

// ---- Overview page queries ----

export interface HealthMetrics {
  postsGenerated7d: number;
  qualityGatePassRate: number;
  barRaiserPassRate: number;
  avgExplicitRating: number;
  explicitRatingsCount: number;
}

export interface WowDelta {
  current: number;
  previous: number;
  delta: number;
  direction: "up" | "down" | "flat";
}

export interface WeeklyMetricsRow {
  weekStart: string;
  postsGenerated: number;
  qualityGatePassRate: number | null;
  avgRubricScore: number | null;
  barRaiserPassRate: number | null;
  avgExplicitRating: number | null;
  postsPublished: number;
  postsRejected: number;
}

export async function getHealthMetrics(): Promise<HealthMetrics> {
  const sql = getDb();

  const [generated] = await sql`
    SELECT COUNT(*) as count FROM posts
    WHERE created_at > NOW() - INTERVAL '7 days'
  `;

  const [passRate] = await sql`
    SELECT
      COUNT(*) FILTER (WHERE rubric_score >= 75) as passed,
      COUNT(*) as total
    FROM posts
    WHERE created_at > NOW() - INTERVAL '7 days'
  `;

  const [barRaiser] = await sql`
    SELECT
      COUNT(*) FILTER (WHERE verdict = 'pass') as passed,
      COUNT(*) as total
    FROM agent_scores
    WHERE agent_name = 'bar_raiser'
      AND created_at > NOW() - INTERVAL '7 days'
  `;

  const [rating] = await sql`
    SELECT AVG(user_rating) as avg, COUNT(user_rating) as count
    FROM posts
    WHERE user_rating IS NOT NULL
      AND created_at > NOW() - INTERVAL '7 days'
  `;

  const total = Number(passRate?.total) || 0;

  return {
    postsGenerated7d: Number(generated?.count) || 0,
    qualityGatePassRate: total > 0
      ? Number(passRate?.passed) / total
      : 0,
    barRaiserPassRate:
      Number(barRaiser?.total) > 0
        ? Number(barRaiser?.passed) / Number(barRaiser?.total)
        : 0,
    avgExplicitRating: Number(rating?.avg) || 0,
    explicitRatingsCount: Number(rating?.count) || 0,
  };
}

export async function getWeeklyTrend(weeks: number = 8): Promise<WeeklyMetricsRow[]> {
  const sql = getDb();
  const rows = await sql`
    SELECT
      week_start,
      posts_generated,
      quality_gate_pass_rate,
      avg_rubric_score,
      bar_raiser_pass_rate,
      avg_explicit_rating,
      posts_published,
      posts_rejected
    FROM weekly_metrics
    ORDER BY week_start DESC
    LIMIT ${weeks}
  `;
  return rows.map((r) => ({
    weekStart: String(r.week_start),
    postsGenerated: Number(r.posts_generated),
    qualityGatePassRate: r.quality_gate_pass_rate != null ? Number(r.quality_gate_pass_rate) : null,
    avgRubricScore: r.avg_rubric_score != null ? Number(r.avg_rubric_score) : null,
    barRaiserPassRate: r.bar_raiser_pass_rate != null ? Number(r.bar_raiser_pass_rate) : null,
    avgExplicitRating: r.avg_explicit_rating != null ? Number(r.avg_explicit_rating) : null,
    postsPublished: Number(r.posts_published),
    postsRejected: Number(r.posts_rejected),
  })).reverse();
}

export function computeWow(current: number, previous: number): WowDelta {
  const delta = current - previous;
  const direction = delta > 0 ? "up" : delta < 0 ? "down" : "flat";
  return { current, previous, delta, direction } as const;
}

// ---- Posts page queries ----

export interface PostRow {
  id: string;
  hookPattern: string;
  rubricScore: number | null;
  status: string;
  issueNumber: number | null;
  userRating: number | null;
  userVerdict: string | null;
  createdAt: string;
  barRaiserVerdict: string | null;
}

export async function getPosts(
  status?: string,
  limit: number = 50,
  offset: number = 0
): Promise<PostRow[]> {
  const sql = getDb();
  let rows;
  if (status && status !== "all") {
    rows = await sql`
      SELECT
        p.id, p.hook_pattern, p.rubric_score, p.status,
        p.issue_number, p.user_rating, p.user_verdict, p.created_at,
        (SELECT verdict FROM agent_scores WHERE post_id = p.id AND agent_name = 'bar_raiser' LIMIT 1) as bar_verdict
      FROM posts p
      WHERE p.status = ${status}
      ORDER BY p.created_at DESC
      LIMIT ${limit} OFFSET ${offset}
    `;
  } else {
    rows = await sql`
      SELECT
        p.id, p.hook_pattern, p.rubric_score, p.status,
        p.issue_number, p.user_rating, p.user_verdict, p.created_at,
        (SELECT verdict FROM agent_scores WHERE post_id = p.id AND agent_name = 'bar_raiser' LIMIT 1) as bar_verdict
      FROM posts p
      ORDER BY p.created_at DESC
      LIMIT ${limit} OFFSET ${offset}
    `;
  }
  return rows.map((r) => ({
    id: String(r.id),
    hookPattern: String(r.hook_pattern ?? ""),
    rubricScore: r.rubric_score != null ? Number(r.rubric_score) : null,
    status: String(r.status ?? "draft"),
    issueNumber: r.issue_number != null ? Number(r.issue_number) : null,
    userRating: r.user_rating != null ? Number(r.user_rating) : null,
    userVerdict: r.user_verdict ? String(r.user_verdict) : null,
    createdAt: String(r.created_at),
    barRaiserVerdict: r.bar_verdict ? String(r.bar_verdict) : null,
  }));
}

// ---- Post detail queries ----

export interface PostDetail {
  id: string;
  sha: string | null;
  repo: string | null;
  lesson: string | null;
  linkedinPost: string | null;
  hookPattern: string;
  status: string;
  rubricScore: number | null;
  rubricBreakdown: Record<string, number> | null;
  rubricIssues: string[];
  rewriteAttempts: number;
  issueNumber: number | null;
  createdAt: string;
  publishedAt: string | null;
  userRating: number | null;
  userVerdict: string | null;
  userNotes: string | null;
}

export interface AgentScoreRow {
  agentName: string;
  scores: Record<string, number>;
  verdict: string | null;
  details: string | null;
  createdAt: string;
}

export async function getPostDetail(id: string): Promise<PostDetail | null> {
  const sql = getDb();
  const rows = await sql`SELECT * FROM posts WHERE id = ${id}`;
  if (rows.length === 0) return null;
  const r = rows[0];
  return {
    id: String(r.id),
    sha: r.sha ? String(r.sha) : null,
    repo: r.repo ? String(r.repo) : null,
    lesson: r.lesson ? String(r.lesson) : null,
    linkedinPost: r.linkedin_post ? String(r.linkedin_post) : null,
    hookPattern: String(r.hook_pattern ?? ""),
    status: String(r.status ?? "draft"),
    rubricScore: r.rubric_score != null ? Number(r.rubric_score) : null,
    rubricBreakdown: r.rubric_breakdown as Record<string, number> | null,
    rubricIssues: (r.rubric_issues as string[]) || [],
    rewriteAttempts: Number(r.rewrite_attempts ?? 0),
    issueNumber: r.issue_number != null ? Number(r.issue_number) : null,
    createdAt: String(r.created_at),
    publishedAt: r.published_at ? String(r.published_at) : null,
    userRating: r.user_rating != null ? Number(r.user_rating) : null,
    userVerdict: r.user_verdict ? String(r.user_verdict) : null,
    userNotes: r.user_notes ? String(r.user_notes) : null,
  };
}

export async function getAgentScores(postId: string): Promise<AgentScoreRow[]> {
  const sql = getDb();
  const rows = await sql`
    SELECT agent_name, scores, verdict, details, created_at
    FROM agent_scores
    WHERE post_id = ${postId}
    ORDER BY created_at ASC
  `;
  return rows.map((r) => ({
    agentName: String(r.agent_name),
    scores: r.scores as Record<string, number>,
    verdict: r.verdict ? String(r.verdict) : null,
    details: r.details ? String(r.details) : null,
    createdAt: String(r.created_at),
  }));
}

// ---- Health page queries ----

export interface FailureBreakdown {
  issue: string;
  count: number;
}

export async function getRubricFailures(days: number = 30): Promise<FailureBreakdown[]> {
  const sql = getDb();
  const rows = await sql`
    SELECT unnest(rubric_issues) as issue, COUNT(*) as count
    FROM posts
    WHERE created_at > NOW() - INTERVAL '1 day' * ${days}
      AND rubric_issues IS NOT NULL
    GROUP BY issue
    ORDER BY count DESC
    LIMIT 10
  `;
  return rows.map((r) => ({
    issue: String(r.issue),
    count: Number(r.count),
  }));
}

export async function getAgentRejections(days: number = 30): Promise<FailureBreakdown[]> {
  const sql = getDb();
  const rows = await sql`
    SELECT agent_name as issue, COUNT(*) as count
    FROM agent_scores
    WHERE verdict = 'reject'
      AND created_at > NOW() - INTERVAL '1 day' * ${days}
    GROUP BY agent_name
    ORDER BY count DESC
  `;
  return rows.map((r) => ({
    issue: String(r.issue),
    count: Number(r.count),
  }));
}

export async function getPostStatusCounts(): Promise<Record<string, number>> {
  const sql = getDb();
  const rows = await sql`
    SELECT status, COUNT(*) as count FROM posts GROUP BY status
  `;
  const result: Record<string, number> = {};
  for (const r of rows) {
    result[String(r.status)] = Number(r.count);
  }
  return result;
}
