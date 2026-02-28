"""Slack history and thread context reader service."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from slack_sdk import WebClient

from config import AppConfig
from models import TeamUpdate
from services.resilience import ResiliencePolicy


class SlackReader:
    """Read channel messages and thread context from Slack."""

    def __init__(self, config: AppConfig) -> None:
        self._client = WebClient(token=config.slack_bot_token)
        self._resilience = ResiliencePolicy(
            name="slack_api",
            max_attempts=config.max_external_retries,
        )

    def fetch_channel_messages(
        self,
        *,
        channel_id: str,
        oldest_ts: str,
        latest_ts: str,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Fetch channel messages in time window with pagination."""
        messages: list[dict[str, Any]] = []
        cursor: str | None = None

        while True:
            request_cursor = cursor

            def _operation(request_cursor: str | None = request_cursor) -> Any:
                return self._client.conversations_history(
                    channel=channel_id,
                    oldest=oldest_ts,
                    latest=latest_ts,
                    limit=limit,
                    cursor=request_cursor,
                    inclusive=True,
                )

            response = self._resilience.execute(_operation)
            page_messages = response.get("messages", [])
            if isinstance(page_messages, list):
                messages.extend(m for m in page_messages if isinstance(m, dict))

            next_cursor = response.get("response_metadata", {}).get("next_cursor")
            if not next_cursor:
                break
            cursor = str(next_cursor)

        return messages

    def fetch_thread_replies(self, *, channel_id: str, thread_ts: str) -> list[dict[str, Any]]:
        """Fetch replies for a thread message."""

        def _operation() -> Any:
            return self._client.conversations_replies(
                channel=channel_id,
                ts=thread_ts,
                inclusive=True,
                limit=200,
            )

        response = self._resilience.execute(_operation)
        messages = response.get("messages", [])
        if not isinstance(messages, list):
            return []
        return [m for m in messages if isinstance(m, dict)]

    def collect_weekly_updates(
        self,
        *,
        channel_id: str,
        start_at: datetime,
        end_at: datetime,
    ) -> list[TeamUpdate]:
        """Collect top-level team updates and include thread replies as context."""
        oldest_ts = str(start_at.timestamp())
        latest_ts = str(end_at.timestamp())
        messages = self.fetch_channel_messages(
            channel_id=channel_id,
            oldest_ts=oldest_ts,
            latest_ts=latest_ts,
        )

        updates: list[TeamUpdate] = []
        for message in messages:
            if "thread_ts" in message and message.get("thread_ts") != message.get("ts"):
                # Skip child replies from main message stream.
                continue

            ts = str(message.get("ts", "")).strip()
            text = str(message.get("text", "")).strip()
            user_id = str(message.get("user", "")).strip()
            if not ts or not text:
                continue

            reply_texts: tuple[str, ...] = ()
            has_thread = message.get("thread_ts") == ts and int(message.get("reply_count", 0)) > 0
            if has_thread:
                replies = self.fetch_thread_replies(channel_id=channel_id, thread_ts=ts)
                reply_texts = tuple(
                    str(item.get("text", "")).strip()
                    for item in replies
                    if str(item.get("ts", "")) != ts and str(item.get("text", "")).strip()
                )

            updates.append(
                TeamUpdate(
                    message_ts=ts,
                    user_id=user_id,
                    text=text,
                    thread_replies=reply_texts,
                )
            )

        return updates
