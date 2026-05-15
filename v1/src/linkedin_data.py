"""LinkedIn data ingestion and engagement analysis.

Parses LinkedIn Content Export Excel files and produces structured
insights that feed into the post generator's system prompt and the
learning state.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Length bucket boundaries (characters)
LENGTH_BUCKETS = [
    (0, 500, "<500"),
    (500, 800, "500-800"),
    (800, 1200, "800-1200"),
    (1200, 1500, "1200-1500"),
    (1500, float("inf"), ">1500"),
]

# Column name aliases (case-insensitive) for LinkedIn exports
COLUMN_ALIASES = {
    "date": ["date", "published date", "created date"],
    "post_text": ["post text", "content", "text", "title", "post"],
    "impressions": ["impressions", "views"],
    "reactions": ["reactions", "likes"],
    "comments": ["comments"],
    "reposts": ["reposts", "shares"],
    "saves": ["saves", "bookmarks"],
    "clicks": ["clicks", "click through", "click_through"],
}


def _parse_int(value) -> int:
    """Parse an integer from a cell value, handling commas and strings."""
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(str(value).replace(",", "").strip())
    except (ValueError, TypeError):
        return 0


def _resolve_columns(headers: list[str]) -> dict[str, Optional[int]]:
    """Map our field names to column indices using fuzzy matching."""
    header_lower = [h.strip().lower() if h else "" for h in headers]
    mapping: dict[str, Optional[int]] = {}
    for field_name, aliases in COLUMN_ALIASES.items():
        mapping[field_name] = None
        for alias in aliases:
            if alias in header_lower:
                mapping[field_name] = header_lower.index(alias)
                break
    return mapping


@dataclass
class LinkedInPostRecord:
    """A single row from the LinkedIn Content Export."""

    date: str = ""
    post_text: str = ""
    impressions: int = 0
    reactions: int = 0
    comments: int = 0
    reposts: int = 0
    saves: int = 0
    clicks: int = 0

    @property
    def engagement_score(self) -> float:
        """Weighted engagement — same formula as AnalyticsSnapshot.engagement_score."""
        return (
            self.saves * 4.0
            + self.reposts * 3.0
            + self.comments * 3.0
            + self.reactions * 1.0
            + self.clicks * 2.0
        )

    @property
    def engagement_rate(self) -> float:
        """Engagement rate as a percentage of impressions."""
        if self.impressions == 0:
            return 0.0
        return (self.reactions + self.comments + self.reposts + self.saves) / self.impressions * 100


@dataclass
class LinkedInDataInsights:
    """Aggregated insights from historical LinkedIn data."""

    total_posts: int = 0
    avg_engagement_score: float = 0.0
    avg_engagement_rate: float = 0.0
    top_posts: list[dict] = field(default_factory=list)
    engagement_by_length_bucket: dict[str, float] = field(default_factory=dict)
    engagement_by_day_of_week: dict[str, float] = field(default_factory=dict)
    high_engagement_patterns: list[str] = field(default_factory=list)
    optimal_length_range: tuple[int, int] = (800, 1500)
    version: int = 1

    def save(self, path: str) -> None:
        data = asdict(self)
        data["optimal_length_range"] = list(self.optimal_length_range)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        logger.info("Saved LinkedIn insights to %s", path)

    @classmethod
    def load(cls, path: str) -> "LinkedInDataInsights":
        try:
            with open(path) as f:
                data = json.load(f)
            if "optimal_length_range" in data:
                data["optimal_length_range"] = tuple(data["optimal_length_range"])
            return cls(**data)
        except (FileNotFoundError, json.JSONDecodeError):
            return cls()


def parse_linkedin_export(file_path: str) -> list[LinkedInPostRecord]:
    """Parse a LinkedIn Content Export .xlsx file into records."""
    import openpyxl  # noqa: PLC0415

    wb = openpyxl.load_workbook(file_path, read_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    if not rows:
        return []

    headers = [str(h) if h else "" for h in rows[0]]
    col_map = _resolve_columns(headers)

    records: list[LinkedInPostRecord] = []
    for row in rows[1:]:
        if not row or all(cell is None for cell in row):
            continue

        def _get(field_name: str, default=""):
            idx = col_map.get(field_name)
            if idx is None or idx >= len(row):
                return default
            return row[idx] if row[idx] is not None else default

        records.append(LinkedInPostRecord(
            date=str(_get("date", "")),
            post_text=str(_get("post_text", "")),
            impressions=_parse_int(_get("impressions", 0)),
            reactions=_parse_int(_get("reactions", 0)),
            comments=_parse_int(_get("comments", 0)),
            reposts=_parse_int(_get("reposts", 0)),
            saves=_parse_int(_get("saves", 0)),
            clicks=_parse_int(_get("clicks", 0)),
        ))

    logger.info("Parsed %d records from %s", len(records), file_path)
    return records


def _get_length_bucket(text: str) -> str:
    """Return the length bucket label for a post's character count."""
    length = len(text)
    for lo, hi, label in LENGTH_BUCKETS:
        if lo <= length < hi:
            return label
    return ">1500"


def _extract_hook(text: str) -> str:
    """Extract the first line/sentence as the hook."""
    if not text:
        return ""
    first_line = text.split("\n")[0].strip()
    if len(first_line) > 150:
        first_line = first_line[:150] + "..."
    return first_line


def analyze_linkedin_data(records: list[LinkedInPostRecord]) -> LinkedInDataInsights:
    """Analyze engagement patterns across all records."""
    if not records:
        return LinkedInDataInsights()

    # Sort by engagement score
    sorted_records = sorted(records, key=lambda r: r.engagement_score, reverse=True)
    total = len(sorted_records)

    # Compute averages
    total_engagement = sum(r.engagement_score for r in sorted_records)
    total_rate = sum(r.engagement_rate for r in sorted_records)
    avg_engagement = total_engagement / total
    avg_rate = total_rate / total

    # Top 10% (minimum 1)
    top_n = max(1, math.ceil(total * 0.10))
    top_posts = [
        {"text": _extract_hook(r.post_text), "score": round(r.engagement_score, 2)}
        for r in sorted_records[:top_n]
    ]

    # Engagement by length bucket
    bucket_scores: dict[str, list[float]] = {}
    for r in sorted_records:
        bucket = _get_length_bucket(r.post_text)
        bucket_scores.setdefault(bucket, []).append(r.engagement_score)
    engagement_by_length = {
        bucket: round(sum(scores) / len(scores), 2)
        for bucket, scores in bucket_scores.items()
    }

    # Find optimal length range (bucket with highest avg engagement)
    if engagement_by_length:
        best_bucket = max(engagement_by_length, key=engagement_by_length.get)  # type: ignore[arg-type]
        for lo, hi, label in LENGTH_BUCKETS:
            if label == best_bucket:
                optimal = (int(lo), int(min(hi, 2000)))
                break
        else:
            optimal = (800, 1500)
    else:
        optimal = (800, 1500)

    # Engagement by day of week
    day_scores: dict[str, list[float]] = {}
    for r in sorted_records:
        try:
            # Try common date formats
            for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
                try:
                    dt = datetime.strptime(str(r.date).strip(), fmt)
                    day_name = dt.strftime("%A")
                    day_scores.setdefault(day_name, []).append(r.engagement_score)
                    break
                except ValueError:
                    continue
        except Exception:  # noqa: BLE001
            pass
    engagement_by_day = {
        day: round(sum(scores) / len(scores), 2)
        for day, scores in day_scores.items()
    }

    # Extract hooks from top posts
    hooks = [_extract_hook(r.post_text) for r in sorted_records[:top_n] if r.post_text]

    return LinkedInDataInsights(
        total_posts=total,
        avg_engagement_score=round(avg_engagement, 2),
        avg_engagement_rate=round(avg_rate, 4),
        top_posts=top_posts,
        engagement_by_length_bucket=engagement_by_length,
        engagement_by_day_of_week=engagement_by_day,
        high_engagement_patterns=hooks,
        optimal_length_range=optimal,
    )
