"""Tests for persistent run state ledger."""

from __future__ import annotations

from pathlib import Path

import pytest

from models import DraftStatus, RunStage
from services.run_state import RunStateError, RunStateStore


def test_run_lifecycle_persists_across_store_instances(tmp_path: Path) -> None:
    db_path = tmp_path / "run_state.db"
    run_id = "2026-02-27-weekly"

    store = RunStateStore(db_path)
    store.initialize()
    created = store.create_run(run_id)
    assert created.stage == RunStage.DRAFT_READY

    transitioned = store.transition_run(run_id, RunStage.SEND_REQUESTED, {"attempt": 1})
    assert transitioned.stage == RunStage.SEND_REQUESTED

    reopened = RunStateStore(db_path)
    reopened.initialize()
    persisted = reopened.get_run(run_id)
    assert persisted is not None
    assert persisted.stage == RunStage.SEND_REQUESTED
    assert '"attempt": 1' in persisted.payload_json


def test_invalid_transition_raises(tmp_path: Path) -> None:
    db_path = tmp_path / "run_state.db"
    run_id = "invalid-transition-run"

    store = RunStateStore(db_path)
    store.initialize()
    store.create_run(run_id)

    with pytest.raises(RunStateError):
        store.transition_run(run_id, RunStage.BROADCAST_CREATED)


def test_upsert_and_read_draft_state(tmp_path: Path) -> None:
    db_path = tmp_path / "run_state.db"
    run_id = "draft-state-run"

    store = RunStateStore(db_path)
    store.initialize()
    store.create_run(run_id)

    draft_state = store.upsert_draft_state(
        run_id=run_id,
        draft_version=1,
        draft_status=DraftStatus.PENDING_REVIEW,
        draft_ts="123.456",
        draft_json='{"foo":"bar"}',
        draft_html="<p>draft</p>",
    )

    assert draft_state.draft_version == 1
    assert draft_state.draft_status == DraftStatus.PENDING_REVIEW

    persisted = store.get_draft_state(run_id)
    assert persisted is not None
    assert persisted.draft_ts == "123.456"
