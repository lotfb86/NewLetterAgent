"""Structured logging helpers for run and request observability."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

_LOGGER_NAME = "newsletter_agent"


@dataclass(frozen=True)
class LogContext:
    """Context values merged into every structured log event."""

    run_id: str | None = None
    draft_version: int | None = None
    request_id: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)


class StructuredLogger:
    """Emit JSON logs with stable event shape for run reconstruction."""

    def __init__(self) -> None:
        self._logger = logging.getLogger(_LOGGER_NAME)
        if not self._logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(message)s"))
            self._logger.addHandler(handler)
        self._logger.setLevel(logging.INFO)

    def info(self, event: str, *, context: LogContext | None = None, **fields: Any) -> None:
        self._emit("info", event, context=context, fields=fields)

    def error(self, event: str, *, context: LogContext | None = None, **fields: Any) -> None:
        self._emit("error", event, context=context, fields=fields)

    def _emit(
        self,
        level: str,
        event: str,
        *,
        context: LogContext | None,
        fields: dict[str, Any],
    ) -> None:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": level,
            "event": event,
        }
        if context is not None:
            if context.run_id:
                payload["run_id"] = context.run_id
            if context.draft_version is not None:
                payload["draft_version"] = context.draft_version
            if context.request_id:
                payload["request_id"] = context.request_id
            payload.update(context.extras)
        payload.update(fields)
        line = json.dumps(payload, sort_keys=True, default=str)
        if level == "error":
            self._logger.error(line)
        else:
            self._logger.info(line)


_default_logger: StructuredLogger | None = None


def get_logger() -> StructuredLogger:
    global _default_logger
    if _default_logger is None:
        _default_logger = StructuredLogger()
    return _default_logger
