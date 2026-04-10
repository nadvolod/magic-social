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
import { getPosts, getPostStatusCounts } from "@/lib/queries";
import Link from "next/link";

function statusVariant(status: string) {
  switch (status) {
    case "published":
      return "default" as const;
    case "draft":
      return "secondary" as const;
    case "rejected":
    case "abandoned":
      return "destructive" as const;
    default:
      return "outline" as const;
  }
}

function scoreColor(score: number | null): string {
  if (score == null) return "text-muted-foreground";
  if (score >= 80) return "text-emerald-400";
  if (score >= 65) return "text-yellow-400";
  return "text-red-400";
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

export default async function PostsPage({
  searchParams,
}: {
  searchParams: Promise<{ status?: string }>;
}) {
  const { status: filterStatus } = await searchParams;
  let posts: Awaited<ReturnType<typeof getPosts>> = [];
  let statusCounts: Record<string, number> = {};
  let dbConnected = true;

  try {
    [posts, statusCounts] = await Promise.all([
      getPosts(filterStatus, 50),
      getPostStatusCounts(),
    ]);
  } catch {
    dbConnected = false;
  }

  const totalPosts = Object.values(statusCounts).reduce((a, b) => a + b, 0);
  const statuses = ["all", "draft", "published", "rejected", "abandoned"];

  if (!dbConnected) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold">Posts</h1>
        <Card>
          <CardContent className="py-10 text-center text-muted-foreground">
            Database not connected.
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Posts</h1>
        <span className="text-sm text-muted-foreground">{totalPosts} total</span>
      </div>

      {/* Status filter tabs */}
      <div className="flex gap-2">
        {statuses.map((s) => {
          const count = s === "all" ? totalPosts : (statusCounts[s] ?? 0);
          const isActive = (filterStatus ?? "all") === s;
          return (
            <Link
              key={s}
              href={s === "all" ? "/posts" : `/posts?status=${s}`}
              className={`px-3 py-1.5 rounded-md text-sm transition-colors ${
                isActive
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground hover:text-foreground"
              }`}
            >
              {s} ({count})
            </Link>
          );
        })}
      </div>

      {/* Posts table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {filterStatus ? `${filterStatus} posts` : "All posts"}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {posts.length === 0 ? (
            <p className="text-sm text-muted-foreground">No posts found.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Post</TableHead>
                  <TableHead>Hook</TableHead>
                  <TableHead className="text-right">Rubric</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Bar Raiser</TableHead>
                  <TableHead>Rating</TableHead>
                  <TableHead>Age</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {posts.map((p) => (
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
                    <TableCell className={`text-right font-mono ${scoreColor(p.rubricScore)}`}>
                      {p.rubricScore != null ? p.rubricScore.toFixed(0) : "--"}
                    </TableCell>
                    <TableCell>
                      <Badge variant={statusVariant(p.status)}>{p.status}</Badge>
                    </TableCell>
                    <TableCell>
                      {p.barRaiserVerdict ? (
                        <Badge
                          variant={p.barRaiserVerdict === "pass" ? "default" : "destructive"}
                        >
                          {p.barRaiserVerdict}
                        </Badge>
                      ) : (
                        <span className="text-muted-foreground text-xs">--</span>
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
        </CardContent>
      </Card>
    </div>
  );
}
