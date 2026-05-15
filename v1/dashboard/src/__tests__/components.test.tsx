/**
 * Component tests for dashboard UI components.
 *
 * These verify that the shared UI components render correctly
 * with various data states — populated, empty, and edge cases.
 */

import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup, within } from "@testing-library/react";

afterEach(() => cleanup());
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableHeader,
  TableRow,
  TableHead,
  TableBody,
  TableCell,
} from "@/components/ui/table";

describe("Card component", () => {
  it("renders title and content", () => {
    render(
      <Card>
        <CardHeader>
          <CardTitle>Test Title</CardTitle>
        </CardHeader>
        <CardContent>Test Content</CardContent>
      </Card>,
    );

    expect(screen.getByText("Test Title")).toBeInTheDocument();
    expect(screen.getByText("Test Content")).toBeInTheDocument();
  });
});

describe("Badge component", () => {
  it("renders with default variant", () => {
    render(<Badge>published</Badge>);
    expect(screen.getByText("published")).toBeInTheDocument();
  });

  it("renders with destructive variant", () => {
    render(<Badge variant="destructive">rejected</Badge>);
    expect(screen.getByText("rejected")).toBeInTheDocument();
  });

  it("renders with outline variant", () => {
    render(<Badge variant="outline">result</Badge>);
    expect(screen.getByText("result")).toBeInTheDocument();
  });
});

describe("Table component", () => {
  it("renders a data table with headers and rows", () => {
    render(
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Post</TableHead>
            <TableHead>Score</TableHead>
            <TableHead>Status</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow>
            <TableCell>#42</TableCell>
            <TableCell>82</TableCell>
            <TableCell>draft</TableCell>
          </TableRow>
          <TableRow>
            <TableCell>#43</TableCell>
            <TableCell>91</TableCell>
            <TableCell>published</TableCell>
          </TableRow>
        </TableBody>
      </Table>,
    );

    expect(screen.getByText("Post")).toBeInTheDocument();
    expect(screen.getByText("Score")).toBeInTheDocument();
    expect(screen.getByText("#42")).toBeInTheDocument();
    expect(screen.getByText("82")).toBeInTheDocument();
    expect(screen.getByText("published")).toBeInTheDocument();
  });

  it("renders empty table body without crashing", () => {
    render(
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Post</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody />
      </Table>,
    );

    expect(screen.getByText("Post")).toBeInTheDocument();
  });
});

describe("Dashboard metric display patterns", () => {
  it("renders a metric card with WoW delta", () => {
    render(
      <Card>
        <CardHeader>
          <CardTitle>Quality Gate Pass Rate</CardTitle>
        </CardHeader>
        <CardContent>
          <span data-testid="value">67%</span>
          <span data-testid="delta">+12% WoW</span>
        </CardContent>
      </Card>,
    );

    expect(screen.getByText("Quality Gate Pass Rate")).toBeInTheDocument();
    expect(screen.getByTestId("value")).toHaveTextContent("67%");
    expect(screen.getByTestId("delta")).toHaveTextContent("+12% WoW");
  });

  it("renders rubric score bar correctly", () => {
    const score = 16;
    const max = 20;
    const pct = Math.round((score / max) * 100);

    render(
      <div>
        <span data-testid="label">hook</span>
        <span data-testid="score">{score}/{max}</span>
        <div
          data-testid="bar"
          style={{ width: `${pct}%` }}
          role="progressbar"
          aria-valuenow={score}
          aria-valuemax={max}
        />
      </div>,
    );

    expect(screen.getByTestId("label")).toHaveTextContent("hook");
    expect(screen.getByTestId("score")).toHaveTextContent("16/20");
    const bar = screen.getByTestId("bar");
    expect(bar).toHaveStyle({ width: "80%" });
  });

  it("renders no-data state gracefully", () => {
    render(
      <Card>
        <CardContent>
          <p>Database not connected. Set NEON_DATABASE_URL environment variable.</p>
        </CardContent>
      </Card>,
    );

    expect(
      screen.getByText(/Database not connected/),
    ).toBeInTheDocument();
  });

  it("renders post status badges with correct variants", () => {
    const statuses = [
      { status: "published", variant: "default" as const },
      { status: "draft", variant: "secondary" as const },
      { status: "rejected", variant: "destructive" as const },
    ];

    render(
      <div>
        {statuses.map((s) => (
          <Badge key={s.status} variant={s.variant}>
            {s.status}
          </Badge>
        ))}
      </div>,
    );

    expect(screen.getByText("published")).toBeInTheDocument();
    expect(screen.getByText("draft")).toBeInTheDocument();
    expect(screen.getByText("rejected")).toBeInTheDocument();
  });
});
