"""Feedback listener for newsletter draft revision loop."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from models import DraftStatus
from services.draft_manager import DraftManager

RevisionBuilder = Callable[[str], tuple[dict[str, object], str, str]]


@dataclass(frozen=True)
class FeedbackOutcome:
    """Result of feedback processing."""

    accepted: bool
    reason: str
    draft_version: int | None = None


class FeedbackHandler:
    """Handle feedback replies on draft threads and create revisions."""

    def __init__(self, draft_manager: DraftManager, revision_builder: RevisionBuilder) -> None:
        self._draft_manager = draft_manager
        self._revision_builder = revision_builder

    def handle(self, *, message_text: str, thread_ts: str | None) -> FeedbackOutcome:
        """Apply feedback if message targets latest draft thread."""
        current = self._draft_manager.get_current_draft()
        if current is None:
            return FeedbackOutcome(accepted=False, reason="no_active_draft")

        if current.draft_status != DraftStatus.PENDING_REVIEW:
            return FeedbackOutcome(accepted=False, reason="draft_not_pending")

        if thread_ts != current.draft_ts:
            return FeedbackOutcome(accepted=False, reason="not_draft_thread")

        if not self._draft_manager.has_revision_capacity():
            updated = self._draft_manager.mark_max_revisions_reached()
            return FeedbackOutcome(
                accepted=False,
                reason="max_revisions_reached",
                draft_version=updated.draft_version,
            )

        new_json, new_html, new_ts = self._revision_builder(message_text)
        updated = self._draft_manager.create_revision(
            draft_json=new_json,
            draft_html=new_html,
            draft_ts=new_ts,
        )

        if updated.draft_status == DraftStatus.MAX_REVISIONS_REACHED:
            return FeedbackOutcome(
                accepted=False,
                reason="max_revisions_reached",
                draft_version=updated.draft_version,
            )

        return FeedbackOutcome(
            accepted=True,
            reason="revised",
            draft_version=updated.draft_version,
        )
