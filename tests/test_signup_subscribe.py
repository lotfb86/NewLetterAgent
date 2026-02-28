"""Tests for signup subscribe endpoint behavior."""

from __future__ import annotations

import json
from typing import Any

from signup.api import subscribe


class _FakeResendClient:
    def __init__(self, *, should_duplicate: bool = False) -> None:
        self.called = 0
        self.should_duplicate = should_duplicate

    def create_contact(self, *, email: str, audience_id: str) -> dict[str, Any]:
        self.called += 1
        if self.should_duplicate:
            raise RuntimeError("contact already exists")
        return {"id": f"contact:{email}:{audience_id}"}


def _set_env(monkeypatch: Any) -> None:
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("RESEND_AUDIENCE_ID", "aud_test")
    monkeypatch.setenv(
        "SIGNUP_ALLOWED_ORIGINS",
        "https://newsletter.example.com,https://site.example.com",
    )
    subscribe._REQUEST_LOG.clear()  # noqa: SLF001


def test_options_preflight_allows_allowed_origin(monkeypatch: Any) -> None:
    _set_env(monkeypatch)

    response = subscribe.process_request(
        method="OPTIONS",
        headers={"Origin": "https://newsletter.example.com"},
        raw_body="",
    )

    assert response.status_code == 204
    assert response.headers["Access-Control-Allow-Origin"] == "https://newsletter.example.com"


def test_options_preflight_rejects_unknown_origin(monkeypatch: Any) -> None:
    _set_env(monkeypatch)

    response = subscribe.process_request(
        method="OPTIONS",
        headers={"Origin": "https://evil.example.com"},
        raw_body="",
    )

    assert response.status_code == 403


def test_post_rejects_invalid_email(monkeypatch: Any) -> None:
    _set_env(monkeypatch)

    response = subscribe.process_request(
        method="POST",
        headers={"Origin": "https://site.example.com", "X-Forwarded-For": "1.2.3.4"},
        raw_body=json.dumps({"email": "bad-email"}),
    )

    assert response.status_code == 400
    assert response.body["error"] == "invalid_email"


def test_post_handles_duplicate_email(monkeypatch: Any) -> None:
    _set_env(monkeypatch)
    fake_client = _FakeResendClient(should_duplicate=True)

    response = subscribe.process_request(
        method="POST",
        headers={"Origin": "https://site.example.com", "X-Forwarded-For": "1.2.3.4"},
        raw_body=json.dumps({"email": "user@example.com"}),
        resend_client=fake_client,  # type: ignore[arg-type]
    )

    assert response.status_code == 200
    assert response.body["success"] is True
    assert response.body["duplicate"] is True


def test_post_rate_limits_by_client_ip(monkeypatch: Any) -> None:
    _set_env(monkeypatch)
    fake_client = _FakeResendClient()
    headers = {
        "Origin": "https://site.example.com",
        "X-Forwarded-For": "9.8.7.6",
    }

    limited_status = 200
    for index in range(subscribe.RATE_LIMIT_MAX_REQUESTS + 1):
        response = subscribe.process_request(
            method="POST",
            headers=headers,
            raw_body=json.dumps({"email": f"user{index}@example.com"}),
            resend_client=fake_client,  # type: ignore[arg-type]
            now_ts=10_000.0,
        )
        limited_status = response.status_code

    assert limited_status == 429


def test_post_honeypot_sinks_bot_without_provider_call(monkeypatch: Any) -> None:
    _set_env(monkeypatch)
    fake_client = _FakeResendClient()

    response = subscribe.process_request(
        method="POST",
        headers={"Origin": "https://site.example.com", "X-Forwarded-For": "2.2.2.2"},
        raw_body=json.dumps({"email": "user@example.com", "company": "spam"}),
        resend_client=fake_client,  # type: ignore[arg-type]
    )

    assert response.status_code == 200
    assert response.body["success"] is True
    assert fake_client.called == 0


def test_post_rejects_disallowed_origin(monkeypatch: Any) -> None:
    _set_env(monkeypatch)

    response = subscribe.process_request(
        method="POST",
        headers={"Origin": "https://bad.example.com", "X-Forwarded-For": "1.1.1.1"},
        raw_body=json.dumps({"email": "user@example.com"}),
    )

    assert response.status_code == 403
    assert response.body["error"] == "origin_not_allowed"
