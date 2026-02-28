"""Approval listener for newsletter draft send trigger."""

from __future__ import annotations

import re
from dataclasses import dataclass

from models import DraftStatus
from services.draft_manager import DraftManager

_APPROVAL_PATTERN = re.compile(r"\bapproved\b", flags=re.IGNORECASE)


@dataclass(frozen=True)
class ApprovalOutcome:
    """Result of approval processing."""

    accepted: bool
    reason: str
    run_id: str | None = None


def is_approval_text(text: str) -> bool:
    """Detect approval token from message text."""
    return bool(_APPROVAL_PATTERN.search(text or ""))


class ApprovalHandler:
    """Apply approval guardrails for latest active draft."""

    def __init__(self, draft_manager: DraftManager) -> None:
        self._draft_manager = draft_manager

    def handle(self, *, message_text: str, thread_ts: str | None) -> ApprovalOutcome:
        """Validate and apply approval status change."""
        if not is_approval_text(message_text):
            return ApprovalOutcome(accepted=False, reason="not_approval_message")

        current = self._draft_manager.get_current_draft()
        if current is None:
            return ApprovalOutcome(accepted=False, reason="no_active_draft")

        if current.draft_status != DraftStatus.PENDING_REVIEW:
            return ApprovalOutcome(
                accepted=False,
                reason="draft_not_pending",
                run_id=current.run_id,
            )

        if current.draft_ts is None:
            return ApprovalOutcome(accepted=False, reason="draft_missing_ts", run_id=current.run_id)

        if thread_ts != current.draft_ts:
            return ApprovalOutcome(
                accepted=False,
                reason="not_latest_draft_thread",
                run_id=current.run_id,
            )

        if self._draft_manager.is_current_draft_stale():
            return ApprovalOutcome(accepted=False, reason="draft_stale", run_id=current.run_id)

        updated = self._draft_manager.mark_status(status=DraftStatus.APPROVED)
        return ApprovalOutcome(accepted=True, reason="approved", run_id=updated.run_id)

    def handle_slash(self) -> ApprovalOutcome:
        """Approve the latest pending draft without requiring thread context.

        Used by the /approve slash command where there is no thread_ts.
        """
        current = self._draft_manager.get_current_draft()
        if current is None:
            return ApprovalOutcome(accepted=False, reason="no_active_draft")

        if current.draft_status != DraftStatus.PENDING_REVIEW:
            return ApprovalOutcome(
                accepted=False,
                reason="draft_not_pending",
                run_id=current.run_id,
            )

        if current.draft_ts is None:
            return ApprovalOutcome(accepted=False, reason="draft_missing_ts", run_id=current.run_id)

        if self._draft_manager.is_current_draft_stale():
            return ApprovalOutcome(accepted=False, reason="draft_stale", run_id=current.run_id)

        updated = self._draft_manager.mark_status(status=DraftStatus.APPROVED)
        return ApprovalOutcome(accepted=True, reason="approved", run_id=updated.run_id)
