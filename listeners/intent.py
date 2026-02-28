"""LLM-powered intent classifier for conversational agent routing."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from services.llm import OpenRouterClient

logger = logging.getLogger(__name__)

AGENT_SYSTEM_PROMPT = """\
You are the Ruh Digest newsletter assistant, an AI agent that manages
a weekly AI industry newsletter for Ruh.ai. You run inside a Slack channel.

YOUR CAPABILITIES:
- Research AI industry news from RSS feeds, Hacker News, Perplexity, and Grok
- Generate weekly newsletter drafts with team updates + industry stories
- Accept team updates from users and validate them for clarity
- Send newsletters via email to subscribers (Resend Broadcasts)
- Import contacts/subscribers from CSV or email lists
- Revise drafts based on feedback in draft threads

SLASH COMMANDS AVAILABLE:
- /run — Start a manual research + draft generation cycle
- /reset — Clear current state and start a fresh cycle
- /replay <run_id> — Replay a previously failed run
- /approve — Approve the latest pending draft for email send
- /import-contacts — Bulk import subscribers (paste emails or upload CSV first)
- /help — Show all available commands and how to use them

HOW TEAM UPDATES WORK:
Users post updates as regular messages in the channel. You validate them for clarity
and ask follow-up questions if needed. Updates are collected and included in the next
newsletter draft. If an update arrives after the collection window closes, you prompt
the user to reply "include" in the thread to add it to the current draft.

HOW NEWSLETTERS WORK:
1. User posts team updates during the week
2. /run or /reset triggers research + draft generation
3. Draft is posted in channel for review
4. Users give feedback by replying in the draft thread
5. /approve sends the newsletter to all subscribers

HOW CONTACT IMPORT WORKS:
Upload a CSV file (with an "email" column) to the channel, then type /import-contacts.
Or type /import-contacts email1@test.com, email2@test.com for small lists.

YOUR TASK:
Classify the user's message and respond appropriately.
Respond with a JSON object: {"intent": "<intent>", "response": "<your response>"}

Intents:
- "team_update" — The message is a team update to include in the newsletter. \
Something the team accomplished, shipped, launched, or is working on. \
Set response to "TEAM_UPDATE" (the existing validation flow will handle it).
- "help_request" — The user is asking how to do something or asking about your capabilities. \
Set response to a helpful, conversational answer guiding them.
- "conversation" — General chat, greeting, or question not about newsletter operations. \
Set response to a friendly, brief reply.
- "command_request" — The user is trying to trigger an action (run, approve, send, import, etc.) \
without using a slash command. Set response to guidance pointing them to the correct slash command.

Be concise. Be helpful. Be human."""


@dataclass(frozen=True)
class IntentResult:
    """Classified intent with LLM-generated response."""

    intent: str  # team_update | help_request | conversation | command_request
    response: str


class IntentClassifier:
    """Classify user messages using LLM to distinguish team updates from other intents."""

    def __init__(self, llm_client: OpenRouterClient) -> None:
        self._llm = llm_client

    def classify(self, message_text: str) -> IntentResult:
        """Classify a user message and generate an appropriate response.

        Falls back to team_update intent if classification fails.
        """
        try:
            result = self._llm.ask_claude(
                system_prompt=AGENT_SYSTEM_PROMPT,
                user_prompt=message_text,
                temperature=0.1,
                max_tokens=500,
            )

            return _parse_intent_response(result.content)

        except Exception:  # noqa: BLE001
            logger.warning(
                "Intent classification failed, falling back to team_update",
                exc_info=True,
            )
            return IntentResult(intent="team_update", response="TEAM_UPDATE")


def _parse_intent_response(raw: str) -> IntentResult:
    """Parse JSON intent response from the LLM.

    Falls back to team_update if parsing fails.
    """
    content = raw.strip()

    # Try to extract JSON from the response (may be wrapped in markdown)
    json_start = content.find("{")
    json_end = content.rfind("}") + 1

    if json_start >= 0 and json_end > json_start:
        json_str = content[json_start:json_end]
        try:
            parsed = json.loads(json_str)
            intent = str(parsed.get("intent", "team_update")).strip().lower()
            response = str(parsed.get("response", "TEAM_UPDATE")).strip()

            valid_intents = {"team_update", "help_request", "conversation", "command_request"}
            if intent not in valid_intents:
                intent = "team_update"
                response = "TEAM_UPDATE"

            return IntentResult(intent=intent, response=response)

        except (json.JSONDecodeError, AttributeError, TypeError):
            pass

    logger.debug("Could not parse intent JSON, falling back to team_update: %s", content[:200])
    return IntentResult(intent="team_update", response="TEAM_UPDATE")
