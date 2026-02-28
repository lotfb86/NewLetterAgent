"""Tests for send idempotency behavior via run state ledger."""

from __future__ import annotations

from pathlib import Path

import pytest

from models import RunStage
from services.run_state import RunStateError, RunStateStore


def test_duplicate_run_creation_is_rejected(tmp_path: Path) -> None:
    """Creating a run with the same ID twice must raise."""
    db_path = tmp_path / "run_state.db"
    store = RunStateStore(db_path)
    store.initialize()

    store.create_run("weekly-2026-02-27")

    with pytest.raises(RunStateError, match="already exists"):
        store.create_run("weekly-2026-02-27")


def test_skipping_stages_is_rejected(tmp_path: Path) -> None:
    """Jumping from DRAFT_READY straight to BROADCAST_SENT must fail."""
    db_path = tmp_path / "run_state.db"
    store = RunStateStore(db_path)
    store.initialize()
    store.create_run("weekly-skip")

    with pytest.raises(RunStateError, match="Invalid transition"):
        store.transition_run("weekly-skip", RunStage.BROADCAST_SENT)


def test_full_send_pipeline_transitions_succeed(tmp_path: Path) -> None:
    """Walk the entire happy-path ledger sequence without errors."""
    db_path = tmp_path / "run_state.db"
    store = RunStateStore(db_path)
    store.initialize()

    run_id = "weekly-2026-02-27"
    record = store.create_run(run_id)
    assert record.stage == RunStage.DRAFT_READY

    for next_stage in (
        RunStage.SEND_REQUESTED,
        RunStage.RENDER_VALIDATED,
        RunStage.BROADCAST_CREATED,
        RunStage.BROADCAST_SENT,
        RunStage.BRAIN_UPDATED,
    ):
        record = store.transition_run(run_id, next_stage)
        assert record.stage == next_stage

    # Terminal stage — no further transitions allowed.
    with pytest.raises(RunStateError, match="Invalid transition"):
        store.transition_run(run_id, RunStage.BROADCAST_SENT)


def test_replay_same_transition_is_rejected(tmp_path: Path) -> None:
    """Once a run reaches SEND_REQUESTED, trying SEND_REQUESTED again must fail."""
    db_path = tmp_path / "run_state.db"
    store = RunStateStore(db_path)
    store.initialize()

    run_id = "weekly-replay"
    store.create_run(run_id)
    store.transition_run(run_id, RunStage.SEND_REQUESTED)

    with pytest.raises(RunStateError, match="Invalid transition"):
        store.transition_run(run_id, RunStage.SEND_REQUESTED)


def test_incomplete_runs_excludes_terminal(tmp_path: Path) -> None:
    """list_incomplete_runs should not include fully completed runs."""
    db_path = tmp_path / "run_state.db"
    store = RunStateStore(db_path)
    store.initialize()

    store.create_run("complete-run")
    for stage in (
        RunStage.SEND_REQUESTED,
        RunStage.RENDER_VALIDATED,
        RunStage.BROADCAST_CREATED,
        RunStage.BROADCAST_SENT,
        RunStage.BRAIN_UPDATED,
    ):
        store.transition_run("complete-run", stage)

    store.create_run("in-progress-run")

    incomplete = store.list_incomplete_runs()
    ids = [r.run_id for r in incomplete]
    assert "in-progress-run" in ids
    assert "complete-run" not in ids
