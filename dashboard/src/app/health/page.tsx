export const dynamic = "force-dynamic";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  getRubricFailures,
  getAgentRejections,
  getWeeklyTrend,
  getPostStatusCounts,
} from "@/lib/queries";

function BarChart({
  items,
  maxCount,
  color = "bg-primary",
}: {
  items: { label: string; count: number }[];
  maxCount: number;
  color?: string;
}) {
  return (
    <div className="space-y-3">
      {items.map((item) => {
        const pct = maxCount > 0 ? (item.count / maxCount) * 100 : 0;
        return (
          <div key={item.label} className="space-y-1">
            <div className="flex justify-between text-sm">
              <span className="text-muted-foreground truncate max-w-[280px]">
                {item.label}
              </span>
              <span className="font-mono">{item.count}</span>
            </div>
            <div className="h-2 rounded-full bg-muted">
              <div
                className={`h-2 rounded-full ${color}`}
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default async function HealthPage() {
  let rubricFailures: { issue: string; count: number }[] = [];
  let agentRejections: { issue: string; count: number }[] = [];
  let weekly: Awaited<ReturnType<typeof getWeeklyTrend>> = [];
  let statusCounts: Record<string, number> = {};
  let dbConnected = true;

  try {
    [rubricFailures, agentRejections, weekly, statusCounts] = await Promise.all([
      getRubricFailures(30),
      getAgentRejections(30),
      getWeeklyTrend(8),
      getPostStatusCounts(),
    ]);
  } catch {
    dbConnected = false;
  }

  if (!dbConnected) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold">Pipeline Health</h1>
        <Card>
          <CardContent className="py-10 text-center text-muted-foreground">
            Database not connected.
          </CardContent>
        </Card>
      </div>
    );
  }

  const rubricMax = rubricFailures.length > 0 ? rubricFailures[0].count : 0;
  const agentMax = agentRejections.length > 0 ? agentRejections[0].count : 0;

  // WoW comparison: this week vs last week vs 4 weeks ago
  const thisWeek = weekly.length > 0 ? weekly[weekly.length - 1] : null;
  const lastWeek = weekly.length > 1 ? weekly[weekly.length - 2] : null;
  const fourWeeksAgo = weekly.length > 3 ? weekly[weekly.length - 4] : null;

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-bold">Pipeline Health</h1>

      {/* Status Distribution */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {["draft", "published", "rejected", "abandoned"].map((s) => (
          <Card key={s}>
            <CardContent className="pt-6">
              <div className="text-center">
                <p className="text-3xl font-bold font-mono">{statusCounts[s] ?? 0}</p>
                <p className="text-sm text-muted-foreground capitalize mt-1">{s}</p>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Failure breakdowns side by side */}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Rubric Failures (30d)</CardTitle>
          </CardHeader>
          <CardContent>
            {rubricFailures.length === 0 ? (
              <p className="text-sm text-muted-foreground">No rubric failures recorded.</p>
            ) : (
              <BarChart
                items={rubricFailures.map((f) => ({
                  label: f.issue,
                  count: f.count,
                }))}
                maxCount={rubricMax}
                color="bg-red-500"
              />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Agent Rejections (30d)</CardTitle>
          </CardHeader>
          <CardContent>
            {agentRejections.length === 0 ? (
              <p className="text-sm text-muted-foreground">No agent rejections recorded.</p>
            ) : (
              <BarChart
                items={agentRejections.map((f) => ({
                  label: f.issue.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
                  count: f.count,
                }))}
                maxCount={agentMax}
                color="bg-yellow-500"
              />
            )}
          </CardContent>
        </Card>
      </div>

      {/* WoW Comparison Table */}
      {weekly.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Week-over-Week Comparison</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Metric</TableHead>
                  <TableHead className="text-right">This Week</TableHead>
                  <TableHead className="text-right">Last Week</TableHead>
                  <TableHead className="text-right">4 Weeks Ago</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <WowRow
                  label="Posts Generated"
                  current={thisWeek?.postsGenerated}
                  prev={lastWeek?.postsGenerated}
                  fourAgo={fourWeeksAgo?.postsGenerated}
                />
                <WowRow
                  label="Quality Pass Rate"
                  current={thisWeek?.qualityGatePassRate}
                  prev={lastWeek?.qualityGatePassRate}
                  fourAgo={fourWeeksAgo?.qualityGatePassRate}
                  format="pct"
                />
                <WowRow
                  label="Avg Rubric Score"
                  current={thisWeek?.avgRubricScore}
                  prev={lastWeek?.avgRubricScore}
                  fourAgo={fourWeeksAgo?.avgRubricScore}
                  format="score"
                />
                <WowRow
                  label="Bar Raiser Pass Rate"
                  current={thisWeek?.barRaiserPassRate}
                  prev={lastWeek?.barRaiserPassRate}
                  fourAgo={fourWeeksAgo?.barRaiserPassRate}
                  format="pct"
                />
                <WowRow
                  label="Avg User Rating"
                  current={thisWeek?.avgExplicitRating}
                  prev={lastWeek?.avgExplicitRating}
                  fourAgo={fourWeeksAgo?.avgExplicitRating}
                  format="rating"
                />
                <WowRow
                  label="Posts Published"
                  current={thisWeek?.postsPublished}
                  prev={lastWeek?.postsPublished}
                  fourAgo={fourWeeksAgo?.postsPublished}
                />
                <WowRow
                  label="Posts Rejected"
                  current={thisWeek?.postsRejected}
                  prev={lastWeek?.postsRejected}
                  fourAgo={fourWeeksAgo?.postsRejected}
                />
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {/* Full Weekly Timeline */}
      {weekly.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Weekly Timeline (last 8 weeks)</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Week</TableHead>
                  <TableHead className="text-right">Generated</TableHead>
                  <TableHead className="text-right">Published</TableHead>
                  <TableHead className="text-right">Rejected</TableHead>
                  <TableHead className="text-right">Pass Rate</TableHead>
                  <TableHead className="text-right">Avg Rating</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {weekly.map((w) => (
                  <TableRow key={w.weekStart}>
                    <TableCell className="font-mono text-xs">{w.weekStart}</TableCell>
                    <TableCell className="text-right font-mono">{w.postsGenerated}</TableCell>
                    <TableCell className="text-right font-mono text-emerald-400">
                      {w.postsPublished}
                    </TableCell>
                    <TableCell className="text-right font-mono text-red-400">
                      {w.postsRejected}
                    </TableCell>
                    <TableCell className="text-right font-mono">
                      {w.qualityGatePassRate != null
                        ? `${(w.qualityGatePassRate * 100).toFixed(0)}%`
                        : "--"}
                    </TableCell>
                    <TableCell className="text-right font-mono">
                      {w.avgExplicitRating != null ? w.avgExplicitRating.toFixed(1) : "--"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function formatVal(
  val: number | null | undefined,
  format?: "pct" | "score" | "rating"
): string {
  if (val == null) return "--";
  switch (format) {
    case "pct":
      return `${(val * 100).toFixed(0)}%`;
    case "score":
      return val.toFixed(1);
    case "rating":
      return `${val.toFixed(1)}/5`;
    default:
      return String(val);
  }
}

function WowRow({
  label,
  current,
  prev,
  fourAgo,
  format,
}: {
  label: string;
  current: number | null | undefined;
  prev: number | null | undefined;
  fourAgo: number | null | undefined;
  format?: "pct" | "score" | "rating";
}) {
  function deltaColor(curr: number | null | undefined, prev: number | null | undefined) {
    if (curr == null || prev == null) return "";
    if (curr > prev) return "text-emerald-400";
    if (curr < prev) return "text-red-400";
    return "";
  }

  return (
    <TableRow>
      <TableCell className="text-sm">{label}</TableCell>
      <TableCell className="text-right font-mono">
        {formatVal(current, format)}
      </TableCell>
      <TableCell className={`text-right font-mono ${deltaColor(current, prev)}`}>
        {formatVal(prev, format)}
      </TableCell>
      <TableCell className={`text-right font-mono ${deltaColor(current, fourAgo)}`}>
        {formatVal(fourAgo, format)}
      </TableCell>
    </TableRow>
  );
}
