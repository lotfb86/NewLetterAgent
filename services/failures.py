"""Dead-letter utilities for unrecoverable run/send failures."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def save_dead_letter(
    *,
    failure_dir: Path,
    stage: str,
    run_id: str,
    error: str,
    payload: dict[str, Any] | None = None,
) -> Path:
    """Persist a dead-letter event payload for manual replay/recovery."""
    failure_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_path = failure_dir / f"failure_{run_id}_{stage}_{timestamp}.json"
    body = {
        "run_id": run_id,
        "stage": stage,
        "error": error,
        "payload": payload or {},
        "created_at": datetime.now(UTC).isoformat(),
    }
    out_path.write_text(json.dumps(body, indent=2, sort_keys=True), encoding="utf-8")
    return out_path
