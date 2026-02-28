"""Shared composition utilities for planner/writer stages."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CompositionFailure(RuntimeError):
    """Raised when planner/writer composition fails after retries."""

    stage: str
    attempts: int
    error_summary: str
    dead_letter_path: Path

    def __post_init__(self) -> None:
        # dataclass __init__ never calls RuntimeError.__init__, so
        # exception.args stays empty.  Fill it so logging / traceback
        # formatters that inspect .args work correctly.
        RuntimeError.__init__(self, str(self))

    def __str__(self) -> str:
        return (
            f"{self.stage} composition failed after {self.attempts} attempts: "
            f"{self.error_summary} (dead letter: {self.dead_letter_path})"
        )


def save_composition_dead_letter(
    *,
    failure_dir: Path,
    stage: str,
    attempts: int,
    error_summary: str,
    input_payload: dict[str, Any],
    last_model_output: str | None,
) -> Path:
    """Persist composition failure payload for later replay/debug."""
    failure_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = failure_dir / f"composition_{stage}_{timestamp}.json"

    payload = {
        "stage": stage,
        "attempts": attempts,
        "error_summary": error_summary,
        "input_payload": input_payload,
        "last_model_output": last_model_output,
        "created_at": datetime.now(UTC).isoformat(),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path
