"""Data models for the GitHub Commit → Social Post Agent."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class PostStatus(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class ExperimentStatus(str, Enum):
    RUNNING = "running"
    CONCLUDED = "concluded"
    PAUSED = "paused"


class ExperimentVariable(str, Enum):
    HOOK_STYLE = "hook_style"
    POST_LENGTH = "post_length"
    TOPIC_ANGLE = "topic_angle"
    TONE = "tone"
    CTA_TYPE = "cta_type"
    STRUCTURE = "structure"


@dataclass
class SourceCommit:
    """Represents a GitHub commit that was scanned as a potential post source."""

    sha: str
    repo: str
    message: str
    author: str
    timestamp: str
    files_changed: list[str] = field(default_factory=list)
    diff_summary: str = ""
    score: float = 0.0
    score_breakdown: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SourceCommit":
        return cls(**data)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


@dataclass
class Post:
    """Represents a generated social media post."""

    id: str
    source_commit_sha: str
    repo: str
    lesson: str
    linkedin_post: str
    x_thread: str
    ig_caption: str
    hook_pattern: str
    status: PostStatus = PostStatus.DRAFT
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    published_at: Optional[str] = None
    github_issue_number: Optional[int] = None
    experiment_id: Optional[str] = None
    experiment_variant: Optional[str] = None
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "Post":
        data = dict(data)
        data["status"] = PostStatus(data.get("status", PostStatus.DRAFT))
        return cls(**data)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


@dataclass
class AnalyticsSnapshot:
    """Analytics data collected after a post is published."""

    post_id: str
    github_issue_number: int
    impressions: int = 0
    reactions: int = 0
    comments: int = 0
    reposts: int = 0
    saves: int = 0
    follower_delta: int = 0
    click_through: int = 0
    recorded_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def engagement_score(self) -> float:
        """Weighted engagement score. Saves/shares/comments weighted > likes."""
        return (
            self.saves * 4.0
            + self.reposts * 3.0
            + self.comments * 3.0
            + self.reactions * 1.0
            + self.click_through * 2.0
        )

    @property
    def engagement_rate(self) -> float:
        """Engagement rate as a percentage of impressions."""
        if self.impressions == 0:
            return 0.0
        return (self.reactions + self.comments + self.reposts + self.saves) / self.impressions * 100

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AnalyticsSnapshot":
        return cls(**data)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


@dataclass
class PostFeedback:
    """Qualitative feedback from the user about a generated post."""

    post_id: str
    published: Optional[bool] = None
    not_published_reason: Optional[str] = None
    improvement_notes: Optional[str] = None
    rating: Optional[int] = None          # 1–5 scale
    recorded_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "PostFeedback":
        return cls(**data)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


@dataclass
class Experiment:
    """An A/B experiment to test post variables."""

    id: str
    variable: ExperimentVariable
    variants: list[str]
    hypothesis: str
    start_date: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    end_date: Optional[str] = None
    status: ExperimentStatus = ExperimentStatus.RUNNING
    winner: Optional[str] = None
    results: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["variable"] = self.variable.value
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "Experiment":
        data = dict(data)
        data["variable"] = ExperimentVariable(data["variable"])
        data["status"] = ExperimentStatus(data.get("status", ExperimentStatus.RUNNING))
        return cls(**data)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)
