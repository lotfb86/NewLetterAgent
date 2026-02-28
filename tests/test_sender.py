"""Tests for Resend sender service."""

from __future__ import annotations

from typing import Any

from services.sender import ResendSender


class _FakeBroadcasts:
    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"id": "b_123", **payload}

    def send(self, broadcast_id: str) -> dict[str, Any]:
        return {"id": broadcast_id, "status": "sent"}

    def get(self, broadcast_id: str) -> dict[str, Any]:
        return {"id": broadcast_id, "status": "queued"}


class _FakeResendClient:
    def __init__(self) -> None:
        self.Broadcasts = _FakeBroadcasts()


def test_sender_dry_run_never_calls_send(app_config: Any) -> None:
    sender = ResendSender(app_config, client=_FakeResendClient())

    created = sender.create_broadcast(
        audience_id=app_config.resend_audience_id,
        from_email=app_config.newsletter_from_email,
        subject="Subject",
        html="<p>html</p>",
    )

    assert created.dry_run is True
    assert created.broadcast_id == "dry-run-broadcast"

    send_result = sender.send_broadcast(broadcast_id=created.broadcast_id)
    assert send_result["status"] == "skipped_dry_run"


def test_sender_live_mode_calls_client(app_config: Any) -> None:
    live_config = app_config
    object.__setattr__(live_config, "enable_dry_run", False)

    sender = ResendSender(live_config, client=_FakeResendClient())

    created = sender.create_broadcast(
        audience_id=live_config.resend_audience_id,
        from_email=live_config.newsletter_from_email,
        subject="Subject",
        html="<p>html</p>",
    )
    assert created.dry_run is False
    assert created.broadcast_id == "b_123"

    sent = sender.send_broadcast(broadcast_id=created.broadcast_id)
    assert sent["status"] == "sent"

    status = sender.get_broadcast(broadcast_id=created.broadcast_id)
    assert status["status"] == "queued"
