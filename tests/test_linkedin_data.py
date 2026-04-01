"""Tests for the LinkedIn data ingestion and analysis module."""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from src.linkedin_data import (
    LinkedInDataInsights,
    LinkedInPostRecord,
    analyze_linkedin_data,
    parse_linkedin_export,
)


# ---------------------------------------------------------------------------
# LinkedInPostRecord tests
# ---------------------------------------------------------------------------


class TestLinkedInPostRecord:
    def test_engagement_score_matches_analytics_formula(self):
        """Must use the same weights as AnalyticsSnapshot.engagement_score."""
        record = LinkedInPostRecord(
            date="2025-06-01",
            post_text="Test post",
            impressions=1000,
            reactions=10,
            comments=5,
            reposts=3,
            saves=2,
            clicks=20,
        )
        # saves*4 + reposts*3 + comments*3 + reactions*1 + clicks*2
        expected = 2 * 4.0 + 3 * 3.0 + 5 * 3.0 + 10 * 1.0 + 20 * 2.0
        assert record.engagement_score == expected

    def test_engagement_rate_zero_impressions(self):
        record = LinkedInPostRecord(date="2025-01-01", post_text="", impressions=0, reactions=5)
        assert record.engagement_rate == 0.0

    def test_engagement_rate_calculation(self):
        record = LinkedInPostRecord(
            date="2025-01-01", post_text="", impressions=1000,
            reactions=10, comments=5, reposts=3, saves=2,
        )
        expected = (10 + 5 + 3 + 2) / 1000 * 100
        assert record.engagement_rate == pytest.approx(expected)


# ---------------------------------------------------------------------------
# LinkedInDataInsights tests
# ---------------------------------------------------------------------------


class TestLinkedInDataInsights:
    def test_roundtrip_serialization(self, tmp_path):
        insights = LinkedInDataInsights(
            total_posts=42,
            avg_engagement_score=15.5,
            avg_engagement_rate=2.1,
            top_posts=[{"text": "hook line", "score": 99.0}],
            engagement_by_length_bucket={"800-1200": 20.0},
            engagement_by_day_of_week={"Tuesday": 25.0},
            high_engagement_patterns=["I failed at X. Here's what I learned."],
            optimal_length_range=(900, 1300),
        )
        path = tmp_path / "insights.json"
        insights.save(str(path))
        loaded = LinkedInDataInsights.load(str(path))
        assert loaded.total_posts == 42
        assert loaded.avg_engagement_score == 15.5
        assert loaded.top_posts == [{"text": "hook line", "score": 99.0}]
        assert loaded.optimal_length_range == (900, 1300)

    def test_empty_data_produces_empty_insights(self):
        insights = analyze_linkedin_data([])
        assert insights.total_posts == 0
        assert insights.avg_engagement_score == 0.0
        assert insights.top_posts == []

    def test_load_missing_file_returns_default(self, tmp_path):
        loaded = LinkedInDataInsights.load(str(tmp_path / "nonexistent.json"))
        assert loaded.total_posts == 0


# ---------------------------------------------------------------------------
# Excel parsing tests
# ---------------------------------------------------------------------------


class TestParseExcelFile:
    def _write_xlsx(self, path, headers, rows):
        """Helper to write a minimal .xlsx file with openpyxl."""
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(headers)
        for row in rows:
            ws.append(row)
        wb.save(path)

    def test_parses_standard_linkedin_export(self, tmp_path):
        xlsx = tmp_path / "export.xlsx"
        self._write_xlsx(
            xlsx,
            ["Date", "Post text", "Impressions", "Reactions", "Comments", "Reposts", "Saves", "Clicks"],
            [
                ["2025-06-01", "My first hook.", 1000, 10, 5, 3, 2, 20],
                ["2025-06-02", "Second post.", 500, 5, 2, 1, 0, 10],
            ],
        )
        records = parse_linkedin_export(str(xlsx))
        assert len(records) == 2
        assert records[0].post_text == "My first hook."
        assert records[0].impressions == 1000
        assert records[1].clicks == 10

    def test_handles_missing_columns_gracefully(self, tmp_path):
        xlsx = tmp_path / "partial.xlsx"
        self._write_xlsx(
            xlsx,
            ["Date", "Impressions"],
            [["2025-06-01", 500]],
        )
        records = parse_linkedin_export(str(xlsx))
        assert len(records) == 1
        assert records[0].impressions == 500
        assert records[0].reactions == 0
        assert records[0].post_text == ""

    def test_handles_empty_file(self, tmp_path):
        xlsx = tmp_path / "empty.xlsx"
        self._write_xlsx(xlsx, ["Date", "Impressions"], [])
        records = parse_linkedin_export(str(xlsx))
        assert records == []

    def test_handles_comma_formatted_numbers(self, tmp_path):
        xlsx = tmp_path / "commas.xlsx"
        self._write_xlsx(
            xlsx,
            ["Date", "Post text", "Impressions"],
            [["2025-06-01", "post", "1,234"]],
        )
        records = parse_linkedin_export(str(xlsx))
        assert records[0].impressions == 1234


# ---------------------------------------------------------------------------
# Engagement analysis tests
# ---------------------------------------------------------------------------


class TestAnalyzeEngagement:
    def _make_records(self, n, base_score=10.0):
        """Create n records with linearly increasing engagement."""
        records = []
        for i in range(n):
            records.append(LinkedInPostRecord(
                date=f"2025-01-{i + 1:02d}",
                post_text=f"Post number {i}. " + "x" * (400 + i * 100),
                impressions=1000,
                reactions=int(base_score + i * 5),
                comments=i,
                reposts=i // 2,
                saves=i // 3,
                clicks=i * 2,
            ))
        return records

    def test_classifies_top_10_percent(self):
        records = self._make_records(20)
        insights = analyze_linkedin_data(records)
        assert insights.total_posts == 20
        # top 10% of 20 = top 2 posts
        assert len(insights.top_posts) == 2

    def test_length_bucket_analysis(self):
        records = [
            LinkedInPostRecord(date="2025-01-01", post_text="x" * 400, impressions=100, reactions=10),
            LinkedInPostRecord(date="2025-01-02", post_text="x" * 1000, impressions=100, reactions=20),
        ]
        insights = analyze_linkedin_data(records)
        assert len(insights.engagement_by_length_bucket) > 0

    def test_day_of_week_analysis(self):
        records = [
            LinkedInPostRecord(date="2025-06-02", post_text="Monday post", impressions=100, reactions=10),
            LinkedInPostRecord(date="2025-06-03", post_text="Tuesday post", impressions=100, reactions=20),
        ]
        insights = analyze_linkedin_data(records)
        assert "Monday" in insights.engagement_by_day_of_week or len(insights.engagement_by_day_of_week) > 0

    def test_extracts_high_engagement_hooks(self):
        records = self._make_records(20)
        insights = analyze_linkedin_data(records)
        # Top posts should have their first lines extracted as hooks
        assert len(insights.high_engagement_patterns) > 0
