"""Team update listener and clarification flow."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from services.context_state import ConversationState
from services.llm import OpenRouterClient

# Slack integrations may append inline attribution (e.g. "*Sent using* <@BOT>")
_ATTRIBUTION_RE = re.compile(r"\s*\*Sent\s+using\*.*$", re.IGNORECASE | re.DOTALL)

VALIDATOR_PROMPT = (
    "You are a newsletter editor. Evaluate this team update for clarity. "
    "If clear and complete, respond with CLEAR. "
    "If unclear, respond with one clarifying question per line."
)


@dataclass(frozen=True)
class TeamUpdateOutcome:
    """Outcome from processing a team update message."""

    status: str
    questions: tuple[str, ...] = ()
    include_requested: bool = False


@dataclass
class TeamUpdateHandler:
    """Validate team updates and manage late-update include flow."""

    llm_client: OpenRouterClient
    context_state: ConversationState
    _late_update_roots: set[str] = field(default_factory=set)

    def handle_top_level_update(
        self,
        *,
        message_ts: str,
        text: str,
        is_late_update: bool,
    ) -> TeamUpdateOutcome:
        """Validate top-level update or trigger late-update include prompt."""
        self.context_state.record_team_update_root(message_ts, text)

        if is_late_update:
            self.context_state.record_late_update(message_ts, text)
            self._late_update_roots.add(message_ts)
            return TeamUpdateOutcome(status="late_update_prompt")

        result = self._validate_with_llm(text)
        if result.status == "clear":
            return result
        return result

    def handle_thread_reply(self, *, thread_ts: str, text: str) -> TeamUpdateOutcome:
        """Handle clarification replies or late-update include replies."""
        # Strip Slack app attribution before matching command keywords.
        normalized = _ATTRIBUTION_RE.sub("", text).strip().lower()
        if thread_ts in self._late_update_roots and normalized == "include":
            self._late_update_roots.remove(thread_ts)
            return TeamUpdateOutcome(status="include_late_update", include_requested=True)

        self.context_state.add_clarification_reply(thread_ts, text)

        return TeamUpdateOutcome(status="clarification_context")

    def is_late_update_thread(self, thread_ts: str) -> bool:
        """Return whether thread belongs to a late update awaiting include/skip decision."""
        return thread_ts in self._late_update_roots

    def _validate_with_llm(self, text: str) -> TeamUpdateOutcome:
        response = self.llm_client.ask_claude(
            system_prompt=VALIDATOR_PROMPT,
            user_prompt=text,
            temperature=0.0,
            max_tokens=400,
        )

        normalized = response.content.strip()
        if normalized.upper() == "CLEAR":
            return TeamUpdateOutcome(status="clear")

        questions = tuple(
            line.strip("- ").strip() for line in normalized.splitlines() if line.strip()
        )
        return TeamUpdateOutcome(status="needs_clarification", questions=questions)
