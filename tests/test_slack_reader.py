"""Tests for Slack reader service."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from services.slack_reader import SlackReader


class _FakeSlackClient:
    def conversations_history(self, **_: Any) -> dict[str, Any]:
        return {
            "messages": [
                {
                    "ts": "1.0",
                    "thread_ts": "1.0",
                    "reply_count": 1,
                    "user": "U1",
                    "text": "Top-level update",
                },
                {"ts": "1.1", "thread_ts": "1.0", "user": "U2", "text": "reply should skip"},
            ],
            "response_metadata": {"next_cursor": ""},
        }

    def conversations_replies(self, **kwargs: Any) -> dict[str, Any]:
        thread_ts = kwargs["ts"]
        return {
            "messages": [
                {"ts": thread_ts, "text": "parent"},
                {"ts": "1.2", "text": "clarification reply"},
            ]
        }


def test_collect_weekly_updates_includes_thread_replies(app_config: Any) -> None:
    reader = SlackReader(app_config)
    reader._client = _FakeSlackClient()  # type: ignore[assignment]

    updates = reader.collect_weekly_updates(
        channel_id=app_config.newsletter_channel_id,
        start_at=datetime.now(UTC) - timedelta(days=7),
        end_at=datetime.now(UTC),
    )

    assert len(updates) == 1
    assert updates[0].text == "Top-level update"
    assert updates[0].thread_replies == ("clarification reply",)
