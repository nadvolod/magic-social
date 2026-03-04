"""Scoring algorithm for selecting lesson-worthy commits."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Topics that resonate with the target audience.
# Entries are used as regex patterns — dots act as wildcards so that
# "fine.tun" matches "fine-tuning", "finetuning", "fine_tuning", etc.
# "event.driven" matches "event-driven" / "event_driven", etc.
RELEVANT_TOPICS = [
    "ai",
    "llm",
    "gpt",
    "openai",
    "claude",
    "agent",
    "langchain",
    "rag",
    "embedding",
    "fine.tun",
    "temporal",
    "workflow",
    "distributed",
    "async",
    "queue",
    "event.driven",
    "reliability",
    "observability",
    "tracing",
    "testing",
    "playwright",
    "selenium",
    "automation",
    "performance",
    "latency",
    "throughput",
    "scale",
    "kubernetes",
    "docker",
    "microservice",
    "api",
    "graphql",
    "grpc",
    "retry",
    "circuit.breaker",
    "idempotent",
    "saga",
    "cqrs",
    "event.sourcing",
]

# Signals that suggest the commit has measurable proof
PROOF_SIGNALS = [
    r"\d+%",                        # percentage improvements
    r"\d+x\s+faster",              # speed improvements
    r"reduce[sd]?\s+\w+\s+by",     # reductions
    r"improve[sd]?\s+\w+\s+by",    # improvements
    r"fix(ed)?\s+\w+\s+bug",       # bug fixes
    r"from\s+\d+\S*\s+to\s+\d+",      # before/after numbers (e.g. 2000ms to 200ms)
    r"latency\s+drop",              # latency improvements
    r"save[sd]?\s+\d+",            # time/resource savings
    r"prevent(ed)?\s+\w+",         # prevention
    r"eliminate[sd]?",              # eliminations
]

# Signals that suggest high impact / novelty
IMPACT_SIGNALS = [
    "refactor",
    "optimize",
    "fix",
    "improve",
    "add",
    "implement",
    "integrate",
    "migrate",
    "upgrade",
    "enable",
    "introduce",
    "discover",
    "lesson",
    "learn",
    "experiment",
]

# Low-value commit patterns to filter out
LOW_VALUE_PATTERNS = [
    r"^merge\s+",
    r"^wip\s*:",
    r"^typo",
    r"^bump\s+version",
    r"^update\s+changelog",
    r"^bump\s+\w+\s+from",
    r"initial\s+commit",
    r"add\s+\.gitignore",
    r"update\s+readme",
    r"minor\s+fix",
    r"minor\s+change",
    r"cleanup",
    r"formatting",
    r"lint",
    r"whitespace",
]


# Privacy/security-sensitive patterns that should never be published
SENSITIVE_PATTERNS = [
    r"api[_\s]?key",
    r"secret[_\s]?key",
    r"password",
    r"token",
    r"credential",
    r"private[_\s]?key",
    r"access[_\s]?key",
    r"auth[_\s]?token",
    r"bearer",
    r"client[_\s]?secret",
    r"database[_\s]?url",
    r"connection[_\s]?string",
    r"customer[_\s]?data",
    r"pii",
    r"ssn",
    r"credit[_\s]?card",
]


@dataclass
class ScoreBreakdown:
    """Detailed breakdown of a commit's lesson-worthiness score."""

    novelty: float = 0.0       # Is this a new pattern/approach?
    impact: float = 0.0        # Does it fix/improve something meaningful?
    teachability: float = 0.0  # Can the lesson be explained clearly?
    relevance: float = 0.0     # Does it match target topics?
    proof: float = 0.0         # Does it have measurable evidence?
    total: float = 0.0

    def to_dict(self) -> dict:
        return {
            "novelty": round(self.novelty, 2),
            "impact": round(self.impact, 2),
            "teachability": round(self.teachability, 2),
            "relevance": round(self.relevance, 2),
            "proof": round(self.proof, 2),
            "total": round(self.total, 2),
        }


def is_sensitive(text: str) -> bool:
    """Return True if the text contains potentially sensitive information."""
    text_lower = text.lower()
    return any(re.search(pattern, text_lower) for pattern in SENSITIVE_PATTERNS)


def is_low_value(message: str) -> bool:
    """Return True if this commit message suggests a low-value commit."""
    message_lower = message.lower().strip()
    return any(re.search(pattern, message_lower) for pattern in LOW_VALUE_PATTERNS)


def score_novelty(message: str, diff_summary: str) -> float:
    """Score how novel/interesting this commit appears (0-20)."""
    text = f"{message} {diff_summary}".lower()
    novelty_words = [
        "new approach", "discovered", "experiment", "novel", "first time",
        "realized", "learned", "insight", "pattern", "anti-pattern",
        "unexpected", "surprise", "counter-intuitive", "trick", "hack",
        "workaround", "edge case", "gotcha",
    ]
    count = sum(1 for w in novelty_words if w in text)
    return min(20.0, count * 5.0 + (5.0 if len(message) > 60 else 0.0))


def score_impact(message: str, diff_summary: str, files_changed: list[str]) -> float:
    """Score the potential impact of this commit (0-20)."""
    text = f"{message} {diff_summary}".lower()
    score = 0.0
    for signal in IMPACT_SIGNALS:
        if signal in text:
            score += 3.0
    # More files changed = potentially more impact
    score += min(5.0, len(files_changed) * 0.5)
    return min(20.0, score)


def score_teachability(message: str, diff_summary: str) -> float:
    """Score how teachable/explainable this lesson is (0-20)."""
    # Longer, more descriptive commit messages are more teachable
    score = 0.0
    words = message.split()
    if len(words) >= 5:
        score += 5.0
    if len(words) >= 10:
        score += 5.0
    # Presence of causal language (why/because/so that)
    causal_words = ["because", "so that", "which", "allows", "prevents", "fixes", "enables"]
    if any(w in message.lower() for w in causal_words):
        score += 5.0
    # If diff summary has context
    if len(diff_summary) > 50:
        score += 5.0
    return min(20.0, score)


def score_relevance(message: str, diff_summary: str, files_changed: list[str]) -> float:
    """Score how relevant this commit is to target topics (0-20)."""
    text = f"{message} {diff_summary} {' '.join(files_changed)}".lower()
    matched = sum(1 for topic in RELEVANT_TOPICS if re.search(topic, text))
    return min(20.0, matched * 4.0)


def score_proof(message: str, diff_summary: str) -> float:
    """Score whether this commit has measurable evidence/proof (0-20)."""
    text = f"{message} {diff_summary}".lower()
    matched = sum(1 for pattern in PROOF_SIGNALS if re.search(pattern, text))
    return min(20.0, matched * 7.0)


def score_commit(
    message: str,
    diff_summary: str = "",
    files_changed: list[str] | None = None,
) -> tuple[float, ScoreBreakdown]:
    """
    Score a commit for lesson-worthiness.

    Returns (total_score, breakdown).
    Total score is 0-100.
    Commits below 30 are not worth posting.
    Commits above 60 are high-priority.
    """
    if files_changed is None:
        files_changed = []

    # Hard filters
    if is_sensitive(message) or is_sensitive(diff_summary):
        return 0.0, ScoreBreakdown()

    if is_low_value(message):
        return 0.0, ScoreBreakdown()

    novelty = score_novelty(message, diff_summary)
    impact = score_impact(message, diff_summary, files_changed)
    teachability = score_teachability(message, diff_summary)
    relevance = score_relevance(message, diff_summary, files_changed)
    proof = score_proof(message, diff_summary)

    total = novelty + impact + teachability + relevance + proof

    breakdown = ScoreBreakdown(
        novelty=novelty,
        impact=impact,
        teachability=teachability,
        relevance=relevance,
        proof=proof,
        total=total,
    )
    return total, breakdown


# Minimum score threshold to qualify a commit for post generation
SCORE_THRESHOLD = 15.0
