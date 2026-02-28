"""Run state ledger persistence and transition helpers."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from models import DraftStateRecord, DraftStatus, RunLedgerRecord, RunStage


class RunStateError(RuntimeError):
    """Raised when run state operations fail or violate transitions."""


ALLOWED_TRANSITIONS: dict[RunStage, set[RunStage]] = {
    RunStage.DRAFT_READY: {RunStage.SEND_REQUESTED},
    RunStage.SEND_REQUESTED: {RunStage.RENDER_VALIDATED},
    RunStage.RENDER_VALIDATED: {RunStage.BROADCAST_CREATED},
    RunStage.BROADCAST_CREATED: {RunStage.BROADCAST_SENT},
    RunStage.BROADCAST_SENT: {RunStage.BRAIN_UPDATED},
    RunStage.BRAIN_UPDATED: set(),
}


class RunStateStore:
    """SQLite-backed store for run ledger and draft state."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def initialize(self) -> None:
        """Initialize SQLite tables if they do not exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS run_ledger (
                    run_id TEXT PRIMARY KEY,
                    stage TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS draft_state (
                    run_id TEXT PRIMARY KEY,
                    draft_version INTEGER NOT NULL,
                    draft_status TEXT NOT NULL,
                    draft_ts TEXT,
                    draft_json TEXT,
                    draft_html TEXT,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES run_ledger(run_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS run_lock (
                    lock_id INTEGER PRIMARY KEY CHECK (lock_id = 1),
                    run_id TEXT NOT NULL,
                    acquired_at TEXT NOT NULL
                )
                """
            )

    def create_run(
        self,
        run_id: str,
        initial_stage: RunStage = RunStage.DRAFT_READY,
        payload: dict[str, Any] | None = None,
    ) -> RunLedgerRecord:
        """Create a new run ledger row."""
        now = _now_iso()
        payload_json = json.dumps(payload or {}, sort_keys=True)
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO run_ledger (
                        run_id,
                        stage,
                        payload_json,
                        last_error,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (run_id, initial_stage.value, payload_json, None, now, now),
                )
        except sqlite3.IntegrityError as exc:
            raise RunStateError(f"Run already exists: {run_id}") from exc

        record = self.get_run(run_id)
        if record is None:
            raise RunStateError(f"Failed to create run: {run_id}")
        return record

    def get_run(self, run_id: str) -> RunLedgerRecord | None:
        """Return run ledger record by run ID."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT run_id, stage, payload_json, last_error, created_at, updated_at
                FROM run_ledger
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()

        if row is None:
            return None

        return RunLedgerRecord(
            run_id=row["run_id"],
            stage=RunStage(row["stage"]),
            payload_json=row["payload_json"],
            last_error=row["last_error"],
            created_at=_parse_iso(row["created_at"]),
            updated_at=_parse_iso(row["updated_at"]),
        )

    def transition_run(
        self,
        run_id: str,
        next_stage: RunStage,
        payload_patch: dict[str, Any] | None = None,
        last_error: str | None = None,
    ) -> RunLedgerRecord:
        """Transition a run to its next stage with transition validation."""
        current = self.get_run(run_id)
        if current is None:
            raise RunStateError(f"Run not found: {run_id}")

        allowed = ALLOWED_TRANSITIONS[current.stage]
        if next_stage not in allowed:
            raise RunStateError(
                f"Invalid transition for {run_id}: {current.stage.value} -> {next_stage.value}"
            )

        merged_payload = self._merge_payload(current.payload_json, payload_patch)
        now = _now_iso()

        with self._connect() as conn:
            conn.execute(
                """
                UPDATE run_ledger
                SET stage = ?, payload_json = ?, last_error = ?, updated_at = ?
                WHERE run_id = ?
                """,
                (next_stage.value, merged_payload, last_error, now, run_id),
            )

        updated = self.get_run(run_id)
        if updated is None:
            raise RunStateError(f"Failed to read transitioned run: {run_id}")
        return updated

    def list_incomplete_runs(self) -> list[RunLedgerRecord]:
        """Return all runs that have not reached the terminal stage."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT run_id, stage, payload_json, last_error, created_at, updated_at
                FROM run_ledger
                WHERE stage != ?
                ORDER BY created_at ASC
                """,
                (RunStage.BRAIN_UPDATED.value,),
            ).fetchall()

        return [
            RunLedgerRecord(
                run_id=row["run_id"],
                stage=RunStage(row["stage"]),
                payload_json=row["payload_json"],
                last_error=row["last_error"],
                created_at=_parse_iso(row["created_at"]),
                updated_at=_parse_iso(row["updated_at"]),
            )
            for row in rows
        ]

    def list_runs(self) -> list[RunLedgerRecord]:
        """Return all run ledger records ordered by creation time."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT run_id, stage, payload_json, last_error, created_at, updated_at
                FROM run_ledger
                ORDER BY created_at ASC
                """
            ).fetchall()

        return [
            RunLedgerRecord(
                run_id=row["run_id"],
                stage=RunStage(row["stage"]),
                payload_json=row["payload_json"],
                last_error=row["last_error"],
                created_at=_parse_iso(row["created_at"]),
                updated_at=_parse_iso(row["updated_at"]),
            )
            for row in rows
        ]

    def set_run_error(self, run_id: str, error_message: str) -> RunLedgerRecord:
        """Persist the latest error message for a run without changing stage."""
        current = self.get_run(run_id)
        if current is None:
            raise RunStateError(f"Run not found: {run_id}")

        with self._connect() as conn:
            conn.execute(
                """
                UPDATE run_ledger
                SET last_error = ?, updated_at = ?
                WHERE run_id = ?
                """,
                (error_message, _now_iso(), run_id),
            )

        updated = self.get_run(run_id)
        if updated is None:
            raise RunStateError(f"Failed to update run error for {run_id}")
        return updated

    def patch_run_payload(self, run_id: str, payload_patch: dict[str, Any]) -> RunLedgerRecord:
        """Merge payload keys for a run without changing stage."""
        current = self.get_run(run_id)
        if current is None:
            raise RunStateError(f"Run not found: {run_id}")
        merged_payload = self._merge_payload(current.payload_json, payload_patch)
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE run_ledger
                SET payload_json = ?, updated_at = ?
                WHERE run_id = ?
                """,
                (merged_payload, _now_iso(), run_id),
            )
        updated = self.get_run(run_id)
        if updated is None:
            raise RunStateError(f"Failed to patch payload for run {run_id}")
        return updated

    def upsert_draft_state(
        self,
        run_id: str,
        draft_version: int,
        draft_status: DraftStatus,
        draft_ts: str | None,
        draft_json: str | None,
        draft_html: str | None,
    ) -> DraftStateRecord:
        """Create or update draft state tied to a run."""
        if draft_version < 1:
            raise RunStateError("draft_version must be >= 1")

        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO draft_state (
                    run_id,
                    draft_version,
                    draft_status,
                    draft_ts,
                    draft_json,
                    draft_html,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    draft_version = excluded.draft_version,
                    draft_status = excluded.draft_status,
                    draft_ts = excluded.draft_ts,
                    draft_json = excluded.draft_json,
                    draft_html = excluded.draft_html,
                    updated_at = excluded.updated_at
                """,
                (
                    run_id,
                    draft_version,
                    draft_status.value,
                    draft_ts,
                    draft_json,
                    draft_html,
                    now,
                ),
            )

        record = self.get_draft_state(run_id)
        if record is None:
            raise RunStateError(f"Failed to persist draft state for run {run_id}")
        return record

    def get_draft_state(self, run_id: str) -> DraftStateRecord | None:
        """Get draft state by run ID."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    run_id,
                    draft_version,
                    draft_status,
                    draft_ts,
                    draft_json,
                    draft_html,
                    updated_at
                FROM draft_state
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()

        if row is None:
            return None

        return DraftStateRecord(
            run_id=row["run_id"],
            draft_version=row["draft_version"],
            draft_status=DraftStatus(row["draft_status"]),
            draft_ts=row["draft_ts"],
            draft_json=row["draft_json"],
            draft_html=row["draft_html"],
            updated_at=_parse_iso(row["updated_at"]),
        )

    def get_latest_draft_state(self) -> DraftStateRecord | None:
        """Get the most recently updated draft state across runs."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    run_id,
                    draft_version,
                    draft_status,
                    draft_ts,
                    draft_json,
                    draft_html,
                    updated_at
                FROM draft_state
                ORDER BY updated_at DESC
                LIMIT 1
                """
            ).fetchone()

        if row is None:
            return None

        return DraftStateRecord(
            run_id=row["run_id"],
            draft_version=row["draft_version"],
            draft_status=DraftStatus(row["draft_status"]),
            draft_ts=row["draft_ts"],
            draft_json=row["draft_json"],
            draft_html=row["draft_html"],
            updated_at=_parse_iso(row["updated_at"]),
        )

    def delete_draft_state(self, run_id: str) -> None:
        """Delete persisted draft state for a specific run."""
        with self._connect() as conn:
            conn.execute("DELETE FROM draft_state WHERE run_id = ?", (run_id,))

    def try_acquire_run_lock(self, run_id: str) -> bool:
        """Acquire singleton run lock for this run ID."""
        try:
            with self._connect() as conn:
                existing = conn.execute("SELECT run_id FROM run_lock WHERE lock_id = 1").fetchone()
                if existing is not None:
                    return False
                conn.execute(
                    """
                    INSERT INTO run_lock(lock_id, run_id, acquired_at)
                    VALUES (1, ?, ?)
                    """,
                    (run_id, _now_iso()),
                )
        except sqlite3.IntegrityError:
            return False
        return True

    def release_run_lock(self, run_id: str) -> None:
        """Release singleton run lock if held by the supplied run ID."""
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM run_lock WHERE lock_id = 1 AND run_id = ?",
                (run_id,),
            )

    def get_locked_run_id(self) -> str | None:
        """Return run ID currently holding singleton run lock."""
        with self._connect() as conn:
            row = conn.execute("SELECT run_id FROM run_lock WHERE lock_id = 1").fetchone()
        if row is None:
            return None
        return str(row["run_id"])

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _merge_payload(existing_payload_json: str, payload_patch: dict[str, Any] | None) -> str:
        payload = json.loads(existing_payload_json)
        if payload_patch:
            payload.update(payload_patch)
        return json.dumps(payload, sort_keys=True)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)
