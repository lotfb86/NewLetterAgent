"""In-memory conversational context for routing and late update handling."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class ConversationState:
    """Runtime state for thread context and collection cutoff logic."""

    team_update_thread_roots: set[str] = field(default_factory=set)
    team_update_bodies: dict[str, str] = field(default_factory=dict)
    clarification_replies: dict[str, list[str]] = field(default_factory=dict)
    late_updates: dict[str, str] = field(default_factory=dict)
    collection_cutoff_at: datetime | None = None
    newsletter_sent: bool = False

    def record_team_update_root(self, message_ts: str, text: str) -> None:
        self.team_update_thread_roots.add(message_ts)
        self.team_update_bodies[message_ts] = text

    def is_team_update_thread(self, thread_ts: str) -> bool:
        return thread_ts in self.team_update_thread_roots

    def add_clarification_reply(self, thread_ts: str, text: str) -> None:
        if not text.strip():
            return
        self.clarification_replies.setdefault(thread_ts, []).append(text.strip())

    def record_late_update(self, message_ts: str, text: str) -> None:
        if text.strip():
            self.late_updates[message_ts] = text.strip()

    def pop_late_update(self, thread_ts: str) -> str | None:
        return self.late_updates.pop(thread_ts, None)

    def set_collection_cutoff(self, cutoff_at: datetime) -> None:
        self.collection_cutoff_at = cutoff_at.astimezone(UTC)

    def mark_sent(self) -> None:
        self.newsletter_sent = True

    def mark_not_sent(self) -> None:
        self.newsletter_sent = False

    def is_late_update(self, message_time: datetime) -> bool:
        if self.collection_cutoff_at is None or self.newsletter_sent:
            return False
        return message_time.astimezone(UTC) > self.collection_cutoff_at
