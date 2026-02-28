"""Draft state tracking and guardrails."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from config import AppConfig
from models import DraftStatus
from services.run_state import RunStateStore


@dataclass(frozen=True)
class DraftContext:
    """Current draft context used by Slack handlers."""

    run_id: str
    draft_version: int
    draft_status: DraftStatus
    draft_ts: str | None
    draft_json: str | None
    draft_html: str | None
    updated_at: datetime


class DraftManager:
    """Manage persisted draft lifecycle state."""

    def __init__(self, config: AppConfig, run_state: RunStateStore) -> None:
        self._config = config
        self._run_state = run_state

    def get_current_draft(self) -> DraftContext | None:
        """Return latest known draft state."""
        record = self._run_state.get_latest_draft_state()
        if record is None:
            return None
        return DraftContext(
            run_id=record.run_id,
            draft_version=record.draft_version,
            draft_status=record.draft_status,
            draft_ts=record.draft_ts,
            draft_json=record.draft_json,
            draft_html=record.draft_html,
            updated_at=record.updated_at,
        )

    def create_or_replace_draft(
        self,
        *,
        run_id: str,
        draft_ts: str,
        draft_json: dict[str, Any],
        draft_html: str,
    ) -> DraftContext:
        """Create an initial draft version for a run."""
        record = self._run_state.upsert_draft_state(
            run_id=run_id,
            draft_version=1,
            draft_status=DraftStatus.PENDING_REVIEW,
            draft_ts=draft_ts,
            draft_json=_to_json(draft_json),
            draft_html=draft_html,
        )
        return DraftContext(
            run_id=record.run_id,
            draft_version=record.draft_version,
            draft_status=record.draft_status,
            draft_ts=record.draft_ts,
            draft_json=record.draft_json,
            draft_html=record.draft_html,
            updated_at=record.updated_at,
        )

    def create_revision(
        self,
        *,
        draft_json: dict[str, Any],
        draft_html: str,
        draft_ts: str,
    ) -> DraftContext:
        """Create next revision for the active draft, enforcing max version cap."""
        current = self.get_current_draft()
        if current is None:
            raise ValueError("No active draft exists")
        if current.draft_status != DraftStatus.PENDING_REVIEW:
            raise ValueError("Cannot revise a non-pending draft")

        next_version = current.draft_version + 1
        if next_version > self._config.max_draft_versions:
            record = self._run_state.upsert_draft_state(
                run_id=current.run_id,
                draft_version=current.draft_version,
                draft_status=DraftStatus.MAX_REVISIONS_REACHED,
                draft_ts=current.draft_ts,
                draft_json=current.draft_json,
                draft_html=current.draft_html,
            )
            return DraftContext(
                run_id=record.run_id,
                draft_version=record.draft_version,
                draft_status=record.draft_status,
                draft_ts=record.draft_ts,
                draft_json=record.draft_json,
                draft_html=record.draft_html,
                updated_at=record.updated_at,
            )

        record = self._run_state.upsert_draft_state(
            run_id=current.run_id,
            draft_version=next_version,
            draft_status=DraftStatus.PENDING_REVIEW,
            draft_ts=draft_ts,
            draft_json=_to_json(draft_json),
            draft_html=draft_html,
        )
        return DraftContext(
            run_id=record.run_id,
            draft_version=record.draft_version,
            draft_status=record.draft_status,
            draft_ts=record.draft_ts,
            draft_json=record.draft_json,
            draft_html=record.draft_html,
            updated_at=record.updated_at,
        )

    def mark_status(self, *, status: DraftStatus) -> DraftContext:
        """Set status on the current draft context."""
        current = self.get_current_draft()
        if current is None:
            raise ValueError("No draft exists")

        record = self._run_state.upsert_draft_state(
            run_id=current.run_id,
            draft_version=current.draft_version,
            draft_status=status,
            draft_ts=current.draft_ts,
            draft_json=current.draft_json,
            draft_html=current.draft_html,
        )
        return DraftContext(
            run_id=record.run_id,
            draft_version=record.draft_version,
            draft_status=record.draft_status,
            draft_ts=record.draft_ts,
            draft_json=record.draft_json,
            draft_html=record.draft_html,
            updated_at=record.updated_at,
        )

    def clear_current_draft(self) -> bool:
        """Delete the current draft state record."""
        current = self.get_current_draft()
        if current is None:
            return False
        self._run_state.delete_draft_state(current.run_id)
        return True

    def has_revision_capacity(self) -> bool:
        """Return whether another revision can be created for current draft."""
        current = self.get_current_draft()
        if current is None:
            return False
        return current.draft_version < self._config.max_draft_versions

    def mark_max_revisions_reached(self) -> DraftContext:
        """Mark active draft as max revisions reached."""
        return self.mark_status(status=DraftStatus.MAX_REVISIONS_REACHED)

    def is_current_draft_stale(
        self,
        *,
        now: datetime | None = None,
        max_age_hours: int = 48,
    ) -> bool:
        """Return whether the current draft age exceeds stale threshold."""
        current = self.get_current_draft()
        if current is None:
            return False

        now_utc = now.astimezone(UTC) if now else datetime.now(UTC)
        return current.updated_at < now_utc - timedelta(hours=max_age_hours)


def _to_json(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, sort_keys=True)
