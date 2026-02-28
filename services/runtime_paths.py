"""Runtime directory/database bootstrap helpers."""

from __future__ import annotations

from pathlib import Path

from config import AppConfig
from services.brain import ensure_brain_file
from services.run_state import RunStateStore

ARCHIVE_DIR_NAME = "archive"


def bootstrap_runtime_paths(config: AppConfig) -> None:
    """Create runtime directories/files and initialize persistent state storage."""
    data_root = _resolve_data_root(config.brain_file_path, config.run_state_db_path)
    data_root.mkdir(parents=True, exist_ok=True)

    archive_dir = data_root / ARCHIVE_DIR_NAME
    archive_dir.mkdir(parents=True, exist_ok=True)

    config.failure_log_dir.mkdir(parents=True, exist_ok=True)
    ensure_brain_file(config.brain_file_path)

    store = RunStateStore(config.run_state_db_path)
    store.initialize()


def _resolve_data_root(brain_path: Path, db_path: Path) -> Path:
    if brain_path.parent == db_path.parent:
        return brain_path.parent
    return db_path.parent
