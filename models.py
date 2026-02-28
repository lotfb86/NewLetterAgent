"""Core typed models used across the newsletter pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, StrEnum
from typing import Any


class Confidence(StrEnum):
    """Confidence classification for source claims."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SourceTier(int, Enum):
    """Source trust tier."""

    TIER_1 = 1
    TIER_2 = 2
    TIER_3 = 3


class DraftStatus(StrEnum):
    """Newsletter draft lifecycle status."""

    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    SENT = "sent"
    MAX_REVISIONS_REACHED = "max_revisions_reached"


class RunStage(StrEnum):
    """Persistent send ledger states."""

    DRAFT_READY = "draft_ready"
    SEND_REQUESTED = "send_requested"
    RENDER_VALIDATED = "render_validated"
    BROADCAST_CREATED = "broadcast_created"
    BROADCAST_SENT = "broadcast_sent"
    BRAIN_UPDATED = "brain_updated"


@dataclass(frozen=True)
class StoryCandidate:
    """Candidate story assembled from RSS/Perplexity sources."""

    title: str
    source_url: str
    source_name: str
    published_at: datetime | None
    confidence: Confidence
    source_tier: SourceTier
    summary: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TeamUpdate:
    """A team update captured from Slack."""

    message_ts: str
    user_id: str
    text: str
    thread_replies: tuple[str, ...] = ()


@dataclass(frozen=True)
class IndustryStoryDraft:
    """Story fields included in newsletter JSON output."""

    headline: str
    hook: str
    why_it_matters: str
    source_url: str
    source_name: str
    published_at: datetime
    confidence: Confidence


@dataclass(frozen=True)
class NewsletterDraft:
    """Canonical draft payload used for render and Slack preview."""

    newsletter_name: str
    issue_date: str
    subject_line: str
    preheader: str
    intro: str
    team_updates: tuple[dict[str, str], ...]
    industry_stories: tuple[IndustryStoryDraft, ...]
    cta: dict[str, str]


@dataclass(frozen=True)
class FeedbackEvent:
    """A feedback item from Slack tied to a draft version."""

    user_id: str
    message_ts: str
    text: str
    draft_version: int


@dataclass(frozen=True)
class RunLedgerRecord:
    """Persistent run state row from SQLite ledger."""

    run_id: str
    stage: RunStage
    payload_json: str
    last_error: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class DraftStateRecord:
    """Persistent draft state row from SQLite ledger."""

    run_id: str
    draft_version: int
    draft_status: DraftStatus
    draft_ts: str | None
    draft_json: str | None
    draft_html: str | None
    updated_at: datetime
