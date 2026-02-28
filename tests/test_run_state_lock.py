"""Tests for run lock and payload patch behavior in run state store."""

from __future__ import annotations

import json
from pathlib import Path

from services.run_state import RunStateStore



def test_run_lock_acquire_and_release(tmp_path: Path) -> None:
    store = RunStateStore(tmp_path / "state.db")
    store.initialize()

    assert store.try_acquire_run_lock("run-1") is True
    assert store.get_locked_run_id() == "run-1"
    assert store.try_acquire_run_lock("run-2") is False

    store.release_run_lock("run-2")
    assert store.get_locked_run_id() == "run-1"

    store.release_run_lock("run-1")
    assert store.get_locked_run_id() is None



def test_patch_run_payload_merges_values(tmp_path: Path) -> None:
    store = RunStateStore(tmp_path / "state.db")
    store.initialize()
    store.create_run("run-1", payload={"a": 1})

    updated = store.patch_run_payload("run-1", {"b": 2})

    payload = json.loads(updated.payload_json)
    assert payload == {"a": 1, "b": 2}
