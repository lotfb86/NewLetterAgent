"""Conversational context for routing and late update handling.

Supports optional SQLite persistence so critical state survives restarts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.run_state import RunStateStore


@dataclass
class ConversationState:
    """Runtime state for thread context and collection cutoff logic."""

    team_update_thread_roots: set[str] = field(default_factory=set)
    team_update_bodies: dict[str, str] = field(default_factory=dict)
    clarification_replies: dict[str, list[str]] = field(default_factory=dict)
    late_updates: dict[str, str] = field(default_factory=dict)
    pending_late_include_threads: set[str] = field(default_factory=set)
    collection_cutoff_at: datetime | None = None
    newsletter_sent: bool = False
    _store: RunStateStore | None = field(default=None, repr=False)

    @classmethod
    def from_store(cls, store: RunStateStore) -> ConversationState:
        """Load persisted state from SQLite."""
        data = store.load_context_state()
        cutoff_raw = data.get("collection_cutoff_at")
        cutoff = datetime.fromisoformat(cutoff_raw) if cutoff_raw else None
        return cls(
            team_update_thread_roots=set(data.get("team_update_thread_roots", [])),
            team_update_bodies=data.get("team_update_bodies", {}),
            pending_late_include_threads=set(data.get("pending_late_include_threads", [])),
            collection_cutoff_at=cutoff,
            newsletter_sent=data.get("newsletter_sent", False),
            _store=store,
        )

    def _persist(self) -> None:
        """Save critical fields to SQLite if store is available."""
        if self._store is None:
            return
        self._store.save_context_state(
            {
                "collection_cutoff_at": (
                    self.collection_cutoff_at.isoformat()
                    if self.collection_cutoff_at
                    else None
                ),
                "newsletter_sent": self.newsletter_sent,
                "pending_late_include_threads": sorted(self.pending_late_include_threads),
                "team_update_thread_roots": sorted(self.team_update_thread_roots),
                "team_update_bodies": self.team_update_bodies,
            }
        )

    def record_team_update_root(self, message_ts: str, text: str) -> None:
        self.team_update_thread_roots.add(message_ts)
        self.team_update_bodies[message_ts] = text
        self._persist()

    def is_team_update_thread(self, thread_ts: str) -> bool:
        return thread_ts in self.team_update_thread_roots

    def add_clarification_reply(self, thread_ts: str, text: str) -> None:
        if not text.strip():
            return
        self.clarification_replies.setdefault(thread_ts, []).append(text.strip())

    def record_late_update(self, message_ts: str, text: str) -> None:
        if text.strip():
            self.late_updates[message_ts] = text.strip()
            self.pending_late_include_threads.add(message_ts)
            self._persist()

    def get_late_update(self, thread_ts: str) -> str | None:
        """Return late update text without removing it (non-destructive read)."""
        return self.late_updates.get(thread_ts)

    def pop_late_update(self, thread_ts: str) -> str | None:
        result = self.late_updates.pop(thread_ts, None)
        self.pending_late_include_threads.discard(thread_ts)
        self._persist()
        return result

    def resolve_late_include(self, thread_ts: str) -> None:
        """Mark a late-update thread as resolved (include or skip)."""
        self.pending_late_include_threads.discard(thread_ts)
        self._persist()

    def set_collection_cutoff(self, cutoff_at: datetime) -> None:
        self.collection_cutoff_at = cutoff_at.astimezone(UTC)
        self._persist()

    def mark_sent(self) -> None:
        self.newsletter_sent = True
        self._persist()

    def mark_not_sent(self) -> None:
        self.newsletter_sent = False
        self._persist()

    def is_late_update(self, message_time: datetime) -> bool:
        if self.collection_cutoff_at is None or self.newsletter_sent:
            return False
        return message_time.astimezone(UTC) > self.collection_cutoff_at
