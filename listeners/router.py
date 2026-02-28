"""Message routing dispatcher for Slack events."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

from listeners.approval import ApprovalHandler, is_approval_text
from listeners.feedback import FeedbackHandler
from listeners.updates import TeamUpdateHandler
from services.command_controller import CommandResult
from services.context_state import ConversationState
from services.draft_manager import DraftManager


@dataclass(frozen=True)
class RoutingOutcome:
    """Result of message routing."""

    action: str
    detail: str
    payload: dict[str, Any] | None = None


class MessageDispatcher:
    """Route incoming Slack messages through ordered listener chain."""

    def __init__(
        self,
        *,
        bot_user_id: str,
        draft_manager: DraftManager,
        context_state: ConversationState,
        approval_handler: ApprovalHandler,
        feedback_handler: FeedbackHandler,
        update_handler: TeamUpdateHandler,
        on_manual_run: Callable[[], CommandResult],
        on_reset: Callable[[], CommandResult],
        on_include_late_update: Callable[[str], CommandResult],
        on_replay: Callable[[str], CommandResult] | None = None,
    ) -> None:
        self._bot_user_id = bot_user_id
        self._draft_manager = draft_manager
        self._context_state = context_state
        self._approval_handler = approval_handler
        self._feedback_handler = feedback_handler
        self._update_handler = update_handler
        self._on_manual_run = on_manual_run
        self._on_reset = on_reset
        self._on_include_late_update = on_include_late_update
        self._on_replay = on_replay or (lambda _run_id: CommandResult(False, "unsupported"))

    def dispatch(self, event: dict[str, Any]) -> RoutingOutcome:
        """Route event and execute matching branch."""
        text = str(event.get("text", "")).strip()
        user_id = str(event.get("user", "")).strip()
        message_ts = str(event.get("ts", "")).strip()
        thread_ts = str(event.get("thread_ts", "")).strip() or None
        subtype = str(event.get("subtype", "")).strip()

        # Use first line only for command matching (Slack apps may append attribution)
        first_line = text.split("\n", 1)[0].strip()

        logger.warning(
            "dispatch: text=%r first_line=%r user=%s subtype=%r bot_id=%r",
            text[:100],
            first_line,
            user_id,
            subtype,
            event.get("bot_id", ""),
        )

        if self._is_self_message(event, user_id):
            logger.warning("dispatch: filtered as self_message")
            return RoutingOutcome(action="ignore", detail="self_message")

        if first_line.lower() == "run":
            result = self._on_manual_run()
            if isinstance(result, bool):
                result = CommandResult(
                    accepted=result,
                    reason="run_completed" if result else "rejected",
                )
            return RoutingOutcome(
                action="manual_run",
                detail=result.reason,
            )

        if first_line.lower() == "reset":
            result = self._on_reset()
            if isinstance(result, bool):
                result = CommandResult(
                    accepted=result,
                    reason="run_completed" if result else "rejected",
                )
            return RoutingOutcome(
                action="reset",
                detail=result.reason,
            )

        replay_match = re.fullmatch(r"replay\s+([\w-]+)", first_line, flags=re.IGNORECASE)
        if replay_match:
            run_id = replay_match.group(1)
            result = self._on_replay(run_id)
            if isinstance(result, bool):
                result = CommandResult(
                    accepted=result,
                    reason="sent" if result else "rejected",
                )
            return RoutingOutcome(
                action="replay",
                detail=result.reason,
                payload={"run_id": run_id},
            )

        if is_approval_text(text):
            approval_outcome = self._approval_handler.handle(message_text=text, thread_ts=thread_ts)
            return RoutingOutcome(
                action="approval",
                detail=approval_outcome.reason,
                payload={"run_id": approval_outcome.run_id},
            )

        current_draft = self._draft_manager.get_current_draft()
        if (
            thread_ts
            and current_draft is not None
            and current_draft.draft_ts is not None
            and thread_ts == current_draft.draft_ts
        ):
            feedback_outcome = self._feedback_handler.handle(message_text=text, thread_ts=thread_ts)
            return RoutingOutcome(
                action="feedback",
                detail=feedback_outcome.reason,
                payload={"draft_version": feedback_outcome.draft_version},
            )

        if thread_ts and self._update_handler.is_late_update_thread(thread_ts):
            late_thread_outcome = self._update_handler.handle_thread_reply(
                thread_ts=thread_ts,
                text=text,
            )
            if late_thread_outcome.include_requested:
                include_result = self._on_include_late_update(thread_ts)
                if isinstance(include_result, bool):
                    include_result = CommandResult(
                        accepted=include_result,
                        reason="included" if include_result else "rejected",
                    )
                return RoutingOutcome(
                    action="late_update_include",
                    detail=include_result.reason,
                )
            return RoutingOutcome(action="late_update_thread", detail=late_thread_outcome.status)

        if thread_ts and self._context_state.is_team_update_thread(thread_ts):
            clarification_outcome = self._update_handler.handle_thread_reply(
                thread_ts=thread_ts,
                text=text,
            )
            return RoutingOutcome(
                action="clarification_context",
                detail=clarification_outcome.status,
            )

        posted_at = _parse_ts(message_ts)
        is_late = self._context_state.is_late_update(posted_at) if posted_at is not None else False

        update_outcome = self._update_handler.handle_top_level_update(
            message_ts=message_ts,
            text=text,
            is_late_update=is_late,
        )
        if update_outcome.status == "late_update_prompt":
            return RoutingOutcome(action="late_update_prompt", detail="late_update")

        if update_outcome.status == "clear":
            return RoutingOutcome(action="team_update", detail="clear")

        if update_outcome.status == "needs_clarification":
            return RoutingOutcome(
                action="team_update",
                detail="needs_clarification",
                payload={"questions": list(update_outcome.questions)},
            )

        return RoutingOutcome(action="team_update", detail=update_outcome.status)

    def _is_self_message(self, event: dict[str, Any], user_id: str) -> bool:
        subtype = str(event.get("subtype", "")).strip()
        if subtype == "bot_message":
            return True

        bot_id = str(event.get("bot_id", "")).strip()
        if bot_id:
            return True

        return bool(user_id and user_id == self._bot_user_id)


def _parse_ts(value: str) -> datetime | None:
    try:
        return datetime.fromtimestamp(float(value), tz=UTC)
    except (TypeError, ValueError):
        return None
