/**
 * Integration tests for the dashboard query functions.
 *
 * These test the query logic with mocked DB responses to verify:
 * - Health metrics computation
 * - WoW delta calculations
 * - Post list filtering
 * - Null/empty handling
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { computeWow } from "@/lib/queries";

// Mock the DB module so we don't need a real database
vi.mock("@/lib/db", () => ({
  getDb: vi.fn(),
}));

describe("computeWow", () => {
  it("returns positive delta when current > previous", () => {
    const result = computeWow(10, 5);
    expect(result.current).toBe(10);
    expect(result.previous).toBe(5);
    expect(result.delta).toBe(5);
    expect(result.direction).toBe("up");
  });

  it("returns negative delta when current < previous", () => {
    const result = computeWow(3, 8);
    expect(result.delta).toBe(-5);
    expect(result.direction).toBe("down");
  });

  it("returns flat when current == previous", () => {
    const result = computeWow(7, 7);
    expect(result.delta).toBe(0);
    expect(result.direction).toBe("flat");
  });

  it("handles zero values", () => {
    const result = computeWow(0, 0);
    expect(result.direction).toBe("flat");
  });

  it("handles decimal values for pass rates", () => {
    const result = computeWow(0.75, 0.50);
    expect(result.delta).toBeCloseTo(0.25);
    expect(result.direction).toBe("up");
  });
});

describe("getHealthMetrics", () => {
  it("returns zeroed metrics when DB is empty", async () => {
    const { getDb } = await import("@/lib/db");
    const mockSql = vi.fn().mockResolvedValue([{ count: 0 }]);
    vi.mocked(getDb).mockReturnValue(mockSql as any);

    const { getHealthMetrics } = await import("@/lib/queries");
    const metrics = await getHealthMetrics();

    expect(metrics.postsGenerated7d).toBe(0);
    expect(metrics.qualityGatePassRate).toBe(0);
    expect(metrics.barRaiserPassRate).toBe(0);
    expect(metrics.avgExplicitRating).toBe(0);
  });
});

describe("getWeeklyTrend", () => {
  it("returns empty array when no weekly data", async () => {
    const { getDb } = await import("@/lib/db");
    const mockSql = vi.fn().mockResolvedValue([]);
    vi.mocked(getDb).mockReturnValue(mockSql as any);

    const { getWeeklyTrend } = await import("@/lib/queries");
    const trend = await getWeeklyTrend(8);

    expect(trend).toEqual([]);
  });

  it("reverses rows so oldest week is first", async () => {
    const { getDb } = await import("@/lib/db");
    const mockSql = vi.fn().mockResolvedValue([
      {
        week_start: "2026-04-07",
        posts_generated: 5,
        quality_gate_pass_rate: 0.6,
        avg_rubric_score: 78,
        bar_raiser_pass_rate: 0.4,
        avg_explicit_rating: 3.2,
        posts_published: 1,
        posts_rejected: 2,
      },
      {
        week_start: "2026-03-31",
        posts_generated: 8,
        quality_gate_pass_rate: 0.4,
        avg_rubric_score: 72,
        bar_raiser_pass_rate: 0.2,
        avg_explicit_rating: 2.1,
        posts_published: 0,
        posts_rejected: 5,
      },
    ]);
    vi.mocked(getDb).mockReturnValue(mockSql as any);

    const { getWeeklyTrend } = await import("@/lib/queries");
    const trend = await getWeeklyTrend(8);

    // Should be reversed: oldest first
    expect(trend).toHaveLength(2);
    expect(trend[0].weekStart).toBe("2026-03-31");
    expect(trend[1].weekStart).toBe("2026-04-07");
    expect(trend[1].postsGenerated).toBe(5);
    expect(trend[1].qualityGatePassRate).toBeCloseTo(0.6);
  });
});
