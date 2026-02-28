"""Backup helpers for runtime state and brain data."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

from config import AppConfig


def backup_run_state_db(config: AppConfig) -> Path | None:
    """Create/refresh run_state.db.bak when DB exists."""
    db_path = config.run_state_db_path
    if not db_path.exists():
        return None
    backup_path = db_path.with_suffix(db_path.suffix + ".bak")
    shutil.copy2(db_path, backup_path)
    return backup_path


def backup_brain_snapshot(config: AppConfig, *, issue_date: str | None = None) -> Path | None:
    """Create weekly brain snapshot copy under archive directory."""
    brain_path = config.brain_file_path
    if not brain_path.exists():
        return None

    data_root = brain_path.parent
    archive_dir = data_root / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    resolved_date = issue_date or datetime.now(UTC).strftime("%Y-%m-%d")
    snapshot_path = archive_dir / f"published_stories_{resolved_date}.md"
    shutil.copy2(brain_path, snapshot_path)
    return snapshot_path
