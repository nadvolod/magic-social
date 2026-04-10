import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { getPostDetail, getAgentScores } from "@/lib/queries";
import { notFound } from "next/navigation";

function RubricBar({
  label,
  score,
  max = 20,
}: {
  label: string;
  score: number;
  max?: number;
}) {
  const pct = Math.round((score / max) * 100);
  const color =
    pct >= 80 ? "bg-emerald-500" : pct >= 50 ? "bg-yellow-500" : "bg-red-500";
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-sm">
        <span className="capitalize">{label}</span>
        <span className="font-mono text-muted-foreground">
          {score.toFixed(0)}/{max}
        </span>
      </div>
      <div className="h-2 rounded-full bg-muted">
        <div
          className={`h-2 rounded-full ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function AgentCard({
  agentName,
  scores,
  verdict,
  details,
}: {
  agentName: string;
  scores: Record<string, number>;
  verdict: string | null;
  details: string | null;
}) {
  const displayName = agentName
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm">{displayName}</CardTitle>
          {verdict && (
            <Badge
              variant={
                verdict === "pass"
                  ? "default"
                  : verdict === "conditional"
                    ? "secondary"
                    : "destructive"
              }
            >
              {verdict}
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {Object.entries(scores).map(([key, value]) => (
          <div key={key} className="flex justify-between text-sm">
            <span className="text-muted-foreground capitalize">
              {key.replace(/_/g, " ")}
            </span>
            <span className="font-mono">{typeof value === "number" ? value.toFixed(0) : String(value)}</span>
          </div>
        ))}
        {details && (
          <p className="text-xs text-muted-foreground mt-2 pt-2 border-t border-border">
            {details}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

export default async function PostDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  let post;
  let agentScores;

  try {
    [post, agentScores] = await Promise.all([
      getPostDetail(id),
      getAgentScores(id),
    ]);
  } catch {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold">Post Detail</h1>
        <Card>
          <CardContent className="py-10 text-center text-muted-foreground">
            Database not connected.
          </CardContent>
        </Card>
      </div>
    );
  }

  if (!post) {
    notFound();
  }

  const statusVariant =
    post.status === "published"
      ? "default"
      : post.status === "draft"
        ? "secondary"
        : ("destructive" as const);

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-center gap-4">
        <h1 className="text-2xl font-bold font-mono">
          {post.issueNumber ? `#${post.issueNumber}` : post.id}
        </h1>
        <Badge variant={statusVariant}>{post.status}</Badge>
        <Badge variant="outline">{post.hookPattern}</Badge>
        {post.userRating != null && (
          <span className="font-mono text-sm">
            Rating: {post.userRating}/5
          </span>
        )}
      </div>

      {/* Meta */}
      <div className="flex flex-wrap gap-4 text-sm text-muted-foreground">
        {post.repo && <span>Repo: {post.repo}</span>}
        {post.sha && <span className="font-mono">SHA: {post.sha.slice(0, 8)}</span>}
        <span>Created: {new Date(post.createdAt).toLocaleDateString()}</span>
        {post.rewriteAttempts > 0 && (
          <span>{post.rewriteAttempts} rewrite attempt(s)</span>
        )}
      </div>

      <div className="grid gap-8 lg:grid-cols-3">
        {/* Post content */}
        <div className="lg:col-span-2 space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">LinkedIn Post</CardTitle>
            </CardHeader>
            <CardContent>
              {post.linkedinPost ? (
                <div className="whitespace-pre-wrap font-sans text-sm leading-relaxed">
                  {post.linkedinPost}
                </div>
              ) : (
                <p className="text-muted-foreground text-sm">No post content available.</p>
              )}
            </CardContent>
          </Card>

          {/* User Feedback */}
          {(post.userVerdict || post.userNotes) && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Your Feedback</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {post.userVerdict && (
                  <div className="flex gap-2 text-sm">
                    <span className="text-muted-foreground">Verdict:</span>
                    <Badge variant="outline">{post.userVerdict}</Badge>
                  </div>
                )}
                {post.userNotes && (
                  <p className="text-sm">{post.userNotes}</p>
                )}
              </CardContent>
            </Card>
          )}
        </div>

        {/* Sidebar: Scores */}
        <div className="space-y-6">
          {/* Rubric Score */}
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle className="text-base">Rubric Score</CardTitle>
                <span className="text-2xl font-bold font-mono">
                  {post.rubricScore != null ? post.rubricScore.toFixed(0) : "--"}
                  <span className="text-sm text-muted-foreground">/100</span>
                </span>
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              {post.rubricBreakdown &&
                Object.entries(post.rubricBreakdown).map(([key, val]) => (
                  <RubricBar key={key} label={key} score={val} />
                ))}

              {post.rubricIssues.length > 0 && (
                <>
                  <Separator className="my-3" />
                  <div className="space-y-1">
                    <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                      Issues
                    </p>
                    {post.rubricIssues.map((issue, i) => (
                      <p key={i} className="text-xs text-red-400">
                        {issue}
                      </p>
                    ))}
                  </div>
                </>
              )}
            </CardContent>
          </Card>

          {/* Agent Scores */}
          {agentScores.length > 0 &&
            agentScores.map((a, i) => (
              <AgentCard
                key={i}
                agentName={a.agentName}
                scores={a.scores}
                verdict={a.verdict}
                details={a.details}
              />
            ))}
        </div>
      </div>
    </div>
  );
}
