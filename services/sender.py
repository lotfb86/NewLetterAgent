"""Resend broadcast creation and send orchestration."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any

from config import AppConfig
from services.resilience import ResiliencePolicy


@dataclass(frozen=True)
class BroadcastResult:
    """Broadcast creation response."""

    broadcast_id: str
    dry_run: bool
    raw_response: dict[str, Any]


class ResendSender:
    """Send newsletter broadcasts through Resend with dry-run support."""

    def __init__(
        self,
        config: AppConfig,
        *,
        client: Any | None = None,
    ) -> None:
        self._config = config
        self._dry_run = config.enable_dry_run
        self._client = client or self._build_default_client(config)
        self._resilience = ResiliencePolicy(
            name="resend_api",
            max_attempts=config.max_external_retries,
        )

    @staticmethod
    def _build_default_client(config: AppConfig) -> Any:
        resend_module = importlib.import_module("resend")
        # Resend SDK v2.x uses module-level api_key + module-level resources
        resend_module.api_key = config.resend_api_key
        return resend_module

    def create_broadcast(
        self,
        *,
        audience_id: str,
        from_email: str,
        subject: str,
        html: str,
    ) -> BroadcastResult:
        """Create a broadcast in Resend or return a simulated dry-run payload."""
        if self._dry_run:
            return BroadcastResult(
                broadcast_id="dry-run-broadcast",
                dry_run=True,
                raw_response={
                    "id": "dry-run-broadcast",
                    "subject": subject,
                    "dry_run": True,
                },
            )

        payload = {
            "audience_id": audience_id,
            "from": from_email,
            "subject": subject,
            "html": html,
        }

        def _operation() -> Any:
            return self._client.broadcasts.create(payload)

        response = self._resilience.execute(_operation)
        response_id = _extract_id(response)
        return BroadcastResult(
            broadcast_id=response_id,
            dry_run=False,
            raw_response=_to_dict(response),
        )

    def send_broadcast(self, *, broadcast_id: str) -> dict[str, Any]:
        """Trigger a previously created broadcast unless in dry-run mode."""
        if self._dry_run:
            return {
                "id": broadcast_id,
                "status": "skipped_dry_run",
            }

        def _operation() -> Any:
            return self._client.broadcasts.send(broadcast_id)

        response = self._resilience.execute(_operation)
        return _to_dict(response)

    def get_broadcast(self, *, broadcast_id: str) -> dict[str, Any]:
        """Fetch broadcast status if supported by client."""
        if self._dry_run:
            return {
                "id": broadcast_id,
                "status": "dry_run",
            }

        broadcasts = getattr(self._client, "broadcasts", None)
        if broadcasts is None or not hasattr(broadcasts, "get"):
            return {
                "id": broadcast_id,
                "status": "unknown",
            }

        def _operation() -> Any:
            return broadcasts.get(broadcast_id)

        response = self._resilience.execute(_operation)
        return _to_dict(response)


def _extract_id(response: Any) -> str:
    as_dict = _to_dict(response)
    if "id" not in as_dict:
        raise ValueError("Resend response missing id")
    return str(as_dict["id"])


def _to_dict(response: Any) -> dict[str, Any]:
    if isinstance(response, dict):
        return response
    if hasattr(response, "model_dump"):
        return response.model_dump()
    if hasattr(response, "__dict__"):
        return {k: v for k, v in vars(response).items() if not k.startswith("_")}
    return {"raw": str(response)}
