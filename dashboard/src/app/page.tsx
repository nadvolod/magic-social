import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  getHealthMetrics,
  getWeeklyTrend,
  getPosts,
  computeWow,
  type HealthMetrics,
  type WeeklyMetricsRow,
  type PostRow,
} from "@/lib/queries";
import Link from "next/link";

export const dynamic = "force-dynamic";

function DeltaBadge({ delta, suffix = "" }: { delta: number; suffix?: string }) {
  if (delta === 0) return <span className="text-xs text-muted-foreground">--</span>;
  const isUp = delta > 0;
  return (
    <span className={`text-xs font-mono ${isUp ? "text-emerald-400" : "text-red-400"}`}>
      {isUp ? "+" : ""}
      {suffix === "%" ? (delta * 100).toFixed(0) : delta.toFixed(1)}
      {suffix} WoW
    </span>
  );
}

function MetricCard({
  title,
  value,
  wow,
  suffix = "",
}: {
  title: string;
  value: string;
  wow?: { delta: number };
  suffix?: string;
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex items-baseline gap-2">
          <span className="text-2xl font-bold font-mono">{value}</span>
          {wow && <DeltaBadge delta={wow.delta} suffix={suffix} />}
        </div>
      </CardContent>
    </Card>
  );
}

function ratingDisplay(rating: number | null) {
  if (rating == null) return <span className="text-muted-foreground">--</span>;
  const color =
    rating >= 4 ? "text-emerald-400" : rating >= 3 ? "text-yellow-400" : "text-red-400";
  return <span className={`font-mono font-bold ${color}`}>{rating}/5</span>;
}

function formatAge(dateStr: string): string {
  const created = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - created.getTime();
  const days = Math.floor(diffMs / (1000 * 60 * 60 * 24));
  if (days === 0) return "today";
  if (days === 1) return "1d ago";
  return `${days}d ago`;
}

export default async function OverviewPage() {
  let metrics: HealthMetrics | null = null;
  let weekly: WeeklyMetricsRow[] = [];
  let pendingPosts: PostRow[] = [];
  let dbConnected = true;

  try {
    [metrics, weekly, pendingPosts] = await Promise.all([
      getHealthMetrics(),
      getWeeklyTrend(8),
      getPosts("draft", 5),
    ]);
  } catch {
    dbConnected = false;
  }

  // Compute WoW deltas from weekly_metrics
  const thisWeek = weekly.length > 0 ? weekly[weekly.length - 1] : null;
  const lastWeek = weekly.length > 1 ? weekly[weekly.length - 2] : null;

  const postsWow = thisWeek && lastWeek
    ? computeWow(thisWeek.postsGenerated, lastWeek.postsGenerated)
    : undefined;
  const passRateWow = thisWeek?.qualityGatePassRate != null && lastWeek?.qualityGatePassRate != null
    ? computeWow(thisWeek.qualityGatePassRate, lastWeek.qualityGatePassRate)
    : undefined;
  const barWow = thisWeek?.barRaiserPassRate != null && lastWeek?.barRaiserPassRate != null
    ? computeWow(thisWeek.barRaiserPassRate, lastWeek.barRaiserPassRate)
    : undefined;
  const ratingWow = thisWeek?.avgExplicitRating != null && lastWeek?.avgExplicitRating != null
    ? computeWow(thisWeek.avgExplicitRating, lastWeek.avgExplicitRating)
    : undefined;

  if (!dbConnected) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold">Pipeline Overview</h1>
        <Card>
          <CardContent className="py-10 text-center">
            <p className="text-muted-foreground mb-2">
              Database not connected. Set <code className="font-mono text-sm bg-muted px-1.5 py-0.5 rounded">NEON_DATABASE_URL</code> environment variable.
            </p>
            <p className="text-sm text-muted-foreground">
              Run <code className="font-mono text-sm bg-muted px-1.5 py-0.5 rounded">schema.sql</code> against your NeonDB instance, then deploy with the env var set.
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-bold">Pipeline Overview</h1>

      {/* Health Cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard
          title="Posts Generated (7d)"
          value={String(metrics?.postsGenerated7d ?? 0)}
          wow={postsWow}
        />
        <MetricCard
          title="Quality Gate Pass Rate"
          value={`${((metrics?.qualityGatePassRate ?? 0) * 100).toFixed(0)}%`}
          wow={passRateWow}
          suffix="%"
        />
        <MetricCard
          title="Bar Raiser Pass Rate"
          value={`${((metrics?.barRaiserPassRate ?? 0) * 100).toFixed(0)}%`}
          wow={barWow}
          suffix="%"
        />
        <MetricCard
          title="Avg Explicit Rating"
          value={
            metrics?.explicitRatingsCount
              ? `${metrics.avgExplicitRating.toFixed(1)}/5`
              : "No ratings"
          }
          wow={ratingWow}
        />
      </div>

      {/* Weekly Trend */}
      {weekly.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Week-over-Week Trend</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Week</TableHead>
                    <TableHead className="text-right">Generated</TableHead>
                    <TableHead className="text-right">Pass Rate</TableHead>
                    <TableHead className="text-right">Avg Rubric</TableHead>
                    <TableHead className="text-right">Bar Raiser</TableHead>
                    <TableHead className="text-right">Avg Rating</TableHead>
                    <TableHead className="text-right">Published</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {weekly.map((w) => (
                    <TableRow key={w.weekStart}>
                      <TableCell className="font-mono text-xs">
                        {w.weekStart}
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {w.postsGenerated}
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {w.qualityGatePassRate != null
                          ? `${(w.qualityGatePassRate * 100).toFixed(0)}%`
                          : "--"}
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {w.avgRubricScore != null
                          ? w.avgRubricScore.toFixed(1)
                          : "--"}
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {w.barRaiserPassRate != null
                          ? `${(w.barRaiserPassRate * 100).toFixed(0)}%`
                          : "--"}
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {w.avgExplicitRating != null
                          ? w.avgExplicitRating.toFixed(1)
                          : "--"}
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {w.postsPublished}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Posts Needing Review */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Posts Needing Review</CardTitle>
        </CardHeader>
        <CardContent>
          {pendingPosts.length === 0 ? (
            <p className="text-sm text-muted-foreground">No pending posts.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Post</TableHead>
                  <TableHead>Hook</TableHead>
                  <TableHead className="text-right">Rubric</TableHead>
                  <TableHead>Bar Raiser</TableHead>
                  <TableHead>Rating</TableHead>
                  <TableHead>Age</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {pendingPosts.map((p) => (
                  <TableRow key={p.id}>
                    <TableCell>
                      <Link
                        href={`/posts/${p.id}`}
                        className="font-mono text-xs text-primary hover:underline"
                      >
                        {p.issueNumber ? `#${p.issueNumber}` : p.id.slice(0, 16)}
                      </Link>
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline">{p.hookPattern}</Badge>
                    </TableCell>
                    <TableCell className="text-right font-mono">
                      {p.rubricScore != null ? p.rubricScore.toFixed(0) : "--"}
                    </TableCell>
                    <TableCell>
                      {p.barRaiserVerdict && (
                        <Badge
                          variant={
                            p.barRaiserVerdict === "pass"
                              ? "default"
                              : "destructive"
                          }
                        >
                          {p.barRaiserVerdict}
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell>{ratingDisplay(p.userRating)}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {formatAge(p.createdAt)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
          {pendingPosts.length > 0 && (
            <div className="mt-4">
              <Link
                href="/posts?status=draft"
                className="text-sm text-primary hover:underline"
              >
                View all drafts
              </Link>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
