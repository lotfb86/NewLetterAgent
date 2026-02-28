"""Message routing dispatcher for Slack events."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from listeners.approval import ApprovalHandler, is_approval_text
from listeners.feedback import FeedbackHandler
from listeners.intent import IntentClassifier
from listeners.updates import TeamUpdateHandler
from services.command_controller import CommandResult
from services.context_state import ConversationState
from services.draft_manager import DraftManager

# Slack integrations may append inline attribution (e.g. "*Sent using* <@BOT>")
_ATTRIBUTION_RE = re.compile(r"\s*\*Sent\s+using\*.*$", re.IGNORECASE)


@dataclass(frozen=True)
class RoutingOutcome:
    """Result of message routing."""

    action: str
    detail: str
    payload: dict[str, Any] | None = None


class MessageDispatcher:
    """Route incoming Slack messages through ordered listener chain.

    Command detection (run/reset/replay/approved) has been moved to slash commands.
    Regular top-level messages now go through LLM-powered intent classification.
    """

    def __init__(
        self,
        *,
        bot_user_id: str,
        draft_manager: DraftManager,
        context_state: ConversationState,
        approval_handler: ApprovalHandler,
        feedback_handler: FeedbackHandler,
        update_handler: TeamUpdateHandler,
        intent_classifier: IntentClassifier,
        on_include_late_update: Callable[[str], CommandResult],
    ) -> None:
        self._bot_user_id = bot_user_id
        self._draft_manager = draft_manager
        self._context_state = context_state
        self._approval_handler = approval_handler
        self._feedback_handler = feedback_handler
        self._update_handler = update_handler
        self._intent_classifier = intent_classifier
        self._on_include_late_update = on_include_late_update

    def dispatch(self, event: dict[str, Any]) -> RoutingOutcome:
        """Route event and execute matching branch."""
        text = str(event.get("text", "")).strip()
        user_id = str(event.get("user", "")).strip()
        message_ts = str(event.get("ts", "")).strip()
        thread_ts = str(event.get("thread_ts", "")).strip() or None

        # Strip Slack app attribution from full text so stored updates are clean
        clean_text = _ATTRIBUTION_RE.sub("", text).strip()

        if self._is_self_message(event, user_id):
            return RoutingOutcome(action="ignore", detail="self_message")

        # --- Thread-based routing (unchanged) ---

        current_draft = self._draft_manager.get_current_draft()

        # Draft thread: approval check, then feedback
        if (
            thread_ts
            and current_draft is not None
            and current_draft.draft_ts is not None
            and thread_ts == current_draft.draft_ts
        ):
            if is_approval_text(text):
                approval_outcome = self._approval_handler.handle(
                    message_text=text, thread_ts=thread_ts
                )
                return RoutingOutcome(
                    action="approval",
                    detail=approval_outcome.reason,
                    payload={"run_id": approval_outcome.run_id},
                )

            feedback_outcome = self._feedback_handler.handle(
                message_text=text, thread_ts=thread_ts
            )
            return RoutingOutcome(
                action="feedback",
                detail=feedback_outcome.reason,
                payload={"draft_version": feedback_outcome.draft_version},
            )

        # Late-update thread replies
        if thread_ts and self._update_handler.is_late_update_thread(thread_ts):
            late_thread_outcome = self._update_handler.handle_thread_reply(
                thread_ts=thread_ts,
                text=clean_text,
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

        # Clarification thread replies
        if thread_ts and self._context_state.is_team_update_thread(thread_ts):
            clarification_outcome = self._update_handler.handle_thread_reply(
                thread_ts=thread_ts,
                text=clean_text,
            )
            return RoutingOutcome(
                action="clarification_context",
                detail=clarification_outcome.status,
            )

        # --- Top-level messages: intent classification ---

        intent_result = self._intent_classifier.classify(clean_text)

        if intent_result.intent == "team_update":
            posted_at = _parse_ts(message_ts)
            is_late = (
                self._context_state.is_late_update(posted_at) if posted_at is not None else False
            )

            update_outcome = self._update_handler.handle_top_level_update(
                message_ts=message_ts,
                text=clean_text,
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

        # help_request, conversation, command_request — respond with LLM text
        return RoutingOutcome(
            action="agent_response",
            detail=intent_result.intent,
            payload={"response": intent_result.response},
        )

    # Slack system subtypes the bot should never process as user messages.
    _SYSTEM_SUBTYPES = frozenset(
        {
            "bot_message",
            "channel_purpose",
            "channel_topic",
            "channel_name",
            "channel_join",
            "channel_leave",
            "channel_archive",
            "channel_unarchive",
        }
    )

    def _is_self_message(self, event: dict[str, Any], user_id: str) -> bool:
        subtype = str(event.get("subtype", "")).strip()
        if subtype in self._SYSTEM_SUBTYPES:
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
