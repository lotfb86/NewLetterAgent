"""Signup API endpoint with validation, CORS, and abuse protections."""

from __future__ import annotations

import importlib
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, cast

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
RATE_LIMIT_WINDOW_SECONDS = 3600
RATE_LIMIT_MAX_REQUESTS = 12

_REQUEST_LOG: dict[str, list[float]] = {}


@dataclass(frozen=True)
class EndpointResponse:
    """HTTP-like response shape used by tests and serverless adapters."""

    status_code: int
    headers: dict[str, str]
    body: dict[str, Any]


class SubscribeError(RuntimeError):
    """Raised when subscription operation fails irrecoverably."""


class ResendContactsClient:
    """Resend contacts client wrapper for dependency injection."""

    def __init__(self, api_key: str) -> None:
        resend_module = cast(Any, importlib.import_module("resend"))
        # Resend SDK v2.x uses module-level api_key + module-level resources
        resend_module.api_key = api_key
        self._resend = resend_module

    def create_contact(self, *, email: str, audience_id: str) -> dict[str, Any]:
        response = self._resend.contacts.create(
            {
                "email": email,
                "audience_id": audience_id,
            }
        )
        if isinstance(response, dict):
            return response
        if hasattr(response, "data") and isinstance(response.data, dict):
            return response.data
        return {"ok": True}


def process_request(
    *,
    method: str,
    headers: dict[str, str] | None,
    raw_body: str,
    resend_client: ResendContactsClient | None = None,
    now_ts: float | None = None,
) -> EndpointResponse:
    """Process a signup request for serverless and unit test use."""
    request_headers = _normalize_headers(headers)
    origin = request_headers.get("origin", "")
    allowed_origins = _parse_allowed_origins(os.environ.get("SIGNUP_ALLOWED_ORIGINS", ""))
    cors_headers = _cors_headers(origin=origin, allowed_origins=allowed_origins)

    if method.upper() == "OPTIONS":
        if not _is_origin_allowed(origin=origin, allowed_origins=allowed_origins):
            return EndpointResponse(
                status_code=403,
                headers=_base_headers(cors_headers),
                body={"error": "origin_not_allowed"},
            )
        return EndpointResponse(status_code=204, headers=_base_headers(cors_headers), body={})

    if method.upper() != "POST":
        return EndpointResponse(
            status_code=405,
            headers=_base_headers(cors_headers),
            body={"error": "method_not_allowed"},
        )

    if not _is_origin_allowed(origin=origin, allowed_origins=allowed_origins):
        return EndpointResponse(
            status_code=403,
            headers=_base_headers(cors_headers),
            body={"error": "origin_not_allowed"},
        )

    payload = _parse_payload(raw_body)
    if payload is None:
        return EndpointResponse(
            status_code=400,
            headers=_base_headers(cors_headers),
            body={"error": "invalid_json"},
        )

    honeypot = str(payload.get("company", "")).strip()
    if honeypot:
        # Silent bot sink: return success-like response without touching provider.
        return EndpointResponse(
            status_code=200,
            headers=_base_headers(cors_headers),
            body={"success": True},
        )

    email = str(payload.get("email", "")).strip().lower()
    if not _is_valid_email(email):
        return EndpointResponse(
            status_code=400,
            headers=_base_headers(cors_headers),
            body={"error": "invalid_email"},
        )

    now_value = now_ts if now_ts is not None else time.time()
    remote_addr = request_headers.get("x-forwarded-for", "") or request_headers.get("x-real-ip", "")
    client_key = remote_addr.split(",", 1)[0].strip() or "unknown"
    if _is_rate_limited(client_key=client_key, now_ts=now_value):
        return EndpointResponse(
            status_code=429,
            headers=_base_headers(cors_headers),
            body={"error": "rate_limited"},
        )

    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    audience_id = os.environ.get("RESEND_AUDIENCE_ID", "").strip()
    if not api_key or not audience_id:
        return EndpointResponse(
            status_code=500,
            headers=_base_headers(cors_headers),
            body={"error": "misconfigured_server"},
        )

    client = resend_client or ResendContactsClient(api_key=api_key)

    try:
        client.create_contact(email=email, audience_id=audience_id)
        return EndpointResponse(
            status_code=200,
            headers=_base_headers(cors_headers),
            body={"success": True, "duplicate": False},
        )
    except Exception as exc:  # noqa: BLE001
        error_text = str(exc).lower()
        if "already" in error_text and "exist" in error_text:
            return EndpointResponse(
                status_code=200,
                headers=_base_headers(cors_headers),
                body={"success": True, "duplicate": True},
            )
        raise SubscribeError(str(exc)) from exc


def handler(request: Any) -> Any:
    """Vercel-style handler adapter."""
    method = str(getattr(request, "method", "GET"))
    headers = dict(getattr(request, "headers", {}) or {})

    body_value = getattr(request, "body", b"")
    if isinstance(body_value, (bytes, bytearray)):
        raw_body = body_value.decode("utf-8")
    else:
        raw_body = str(body_value or "")

    try:
        response = process_request(method=method, headers=headers, raw_body=raw_body)
    except SubscribeError as exc:
        response = EndpointResponse(
            status_code=502,
            headers={"Content-Type": "application/json"},
            body={"error": "provider_error", "detail": str(exc)},
        )

    # Vercel python runtime accepts tuple (body, status, headers).
    return json.dumps(response.body), response.status_code, response.headers


def _parse_payload(raw_body: str) -> dict[str, Any] | None:
    if not raw_body.strip():
        return None
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _normalize_headers(headers: dict[str, str] | None) -> dict[str, str]:
    if not headers:
        return {}
    return {str(k).lower(): str(v) for k, v in headers.items()}


def _is_valid_email(email: str) -> bool:
    return bool(email and EMAIL_PATTERN.match(email))


def _parse_allowed_origins(raw: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _is_origin_allowed(*, origin: str, allowed_origins: tuple[str, ...]) -> bool:
    if not allowed_origins:
        return not origin
    return bool(origin and origin in allowed_origins)


def _cors_headers(*, origin: str, allowed_origins: tuple[str, ...]) -> dict[str, str]:
    headers = {
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
    }
    if _is_origin_allowed(origin=origin, allowed_origins=allowed_origins) and origin:
        headers["Access-Control-Allow-Origin"] = origin
    return headers


def _base_headers(cors_headers: dict[str, str]) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        **cors_headers,
    }


def _is_rate_limited(*, client_key: str, now_ts: float) -> bool:
    entries = _REQUEST_LOG.get(client_key, [])
    earliest = now_ts - RATE_LIMIT_WINDOW_SECONDS
    retained = [value for value in entries if value >= earliest]
    retained.append(now_ts)
    _REQUEST_LOG[client_key] = retained
    return len(retained) > RATE_LIMIT_MAX_REQUESTS
