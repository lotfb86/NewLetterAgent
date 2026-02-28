"""Tests for ConversationState SQLite persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from services.context_state import ConversationState
from services.run_state import RunStateStore


def _make_store(tmp_path: Path) -> RunStateStore:
    db_path = tmp_path / "data" / "run_state.db"
    store = RunStateStore(db_path)
    store.initialize()
    return store


def test_context_state_defaults_on_empty_db(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    loaded = store.load_context_state()

    assert loaded["newsletter_sent"] is False
    assert loaded["collection_cutoff_at"] is None
    assert loaded["pending_late_include_threads"] == []
    assert loaded["team_update_thread_roots"] == []
    assert loaded["team_update_bodies"] == {}


def test_context_state_save_and_load_round_trip(tmp_path: Path) -> None:
    store = _make_store(tmp_path)

    store.save_context_state(
        {
            "collection_cutoff_at": "2026-02-28T12:00:00+00:00",
            "newsletter_sent": True,
            "pending_late_include_threads": ["1.0", "2.0"],
            "team_update_thread_roots": ["1.0"],
            "team_update_bodies": {"1.0": "test update"},
        }
    )

    loaded = store.load_context_state()
    assert loaded["newsletter_sent"] is True
    assert loaded["collection_cutoff_at"] == "2026-02-28T12:00:00+00:00"
    assert set(loaded["pending_late_include_threads"]) == {"1.0", "2.0"}
    assert set(loaded["team_update_thread_roots"]) == {"1.0"}
    assert loaded["team_update_bodies"] == {"1.0": "test update"}


def test_conversation_state_persists_across_instances(tmp_path: Path) -> None:
    store = _make_store(tmp_path)

    state1 = ConversationState.from_store(store)
    state1.set_collection_cutoff(datetime(2026, 2, 28, 12, 0, tzinfo=UTC))
    state1.mark_sent()
    state1.record_team_update_root("1.0", "shipped feature X")

    # Simulate restart — create a new instance from the same store
    state2 = ConversationState.from_store(store)
    assert state2.newsletter_sent is True
    assert state2.collection_cutoff_at is not None
    assert state2.collection_cutoff_at.year == 2026
    assert "1.0" in state2.team_update_thread_roots
    assert state2.team_update_bodies.get("1.0") == "shipped feature X"


def test_pending_late_include_threads_persist(tmp_path: Path) -> None:
    store = _make_store(tmp_path)

    state1 = ConversationState.from_store(store)
    state1.record_late_update("5.0", "late update text")

    assert "5.0" in state1.pending_late_include_threads

    # Simulate restart
    state2 = ConversationState.from_store(store)
    assert "5.0" in state2.pending_late_include_threads

    # Resolve the late include
    state2.resolve_late_include("5.0")
    assert "5.0" not in state2.pending_late_include_threads

    state3 = ConversationState.from_store(store)
    assert "5.0" not in state3.pending_late_include_threads


def test_without_store_behaves_as_before(tmp_path: Path) -> None:
    """ConversationState without a store works identically to the old in-memory version."""
    state = ConversationState()
    state.set_collection_cutoff(datetime(2026, 2, 28, 12, 0, tzinfo=UTC))
    state.mark_sent()
    state.record_team_update_root("1.0", "update")

    assert state.newsletter_sent is True
    assert state.collection_cutoff_at is not None
    assert "1.0" in state.team_update_thread_roots
