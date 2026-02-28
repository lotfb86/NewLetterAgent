"""Tests for APScheduler runtime wiring."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from config import AppConfig
from scheduler import SchedulerRuntime


@dataclass
class _FakeOrchestrator:
    trigger_calls: int = 0
    heartbeat_calls: int = 0
    resume_calls: int = 0
    last_next_run: datetime | None = None

    def trigger_run(self, *, trigger: str, requested_by: str | None = None) -> Any:
        del requested_by
        if trigger == "scheduled":
            self.trigger_calls += 1
        return type("Outcome", (), {"accepted": True, "reason": "ok"})()

    def post_heartbeat(self, *, next_run_at: datetime | None) -> None:
        self.heartbeat_calls += 1
        self.last_next_run = next_run_at

    def resume_incomplete_runs(self) -> list[Any]:
        self.resume_calls += 1
        return []


def _build_config(tmp_path: Path) -> AppConfig:
    data_dir = tmp_path / "data"
    return AppConfig(
        openrouter_api_key="sk",
        slack_bot_token="xoxb",
        slack_app_token="xapp",
        newsletter_channel_id="C1",
        resend_api_key="re",
        resend_audience_id="aud",
        newsletter_from_email="newsletter@example.com",
        timezone="America/Chicago",
        research_day="thu",
        research_hour=9,
        brain_file_path=data_dir / "published_stories.md",
        dedup_lookback_weeks=12,
        run_state_db_path=data_dir / "run_state.db",
        failure_log_dir=data_dir / "failures",
        max_external_retries=3,
        max_draft_versions=5,
        enable_dry_run=True,
        heartbeat_channel_id="C_HEARTBEAT",
        heartbeat_hour_utc=None,
        signup_allowed_origins=(),
    )


def test_scheduler_start_sets_jobs_and_reconciles(tmp_path: Path) -> None:
    orchestrator = _FakeOrchestrator()
    runtime = SchedulerRuntime(
        config=_build_config(tmp_path),
        orchestrator=orchestrator,  # type: ignore[arg-type]
    )

    runtime.start()
    try:
        assert orchestrator.resume_calls == 1
        assert runtime.next_weekly_run_at() is not None
    finally:
        runtime.shutdown()


def test_scheduler_jobs_invoke_orchestrator_methods(tmp_path: Path) -> None:
    orchestrator = _FakeOrchestrator()
    runtime = SchedulerRuntime(
        config=_build_config(tmp_path),
        orchestrator=orchestrator,  # type: ignore[arg-type]
    )

    runtime.start()
    try:
        runtime._weekly_run_job()  # noqa: SLF001
        runtime._heartbeat_job()  # noqa: SLF001

        assert orchestrator.trigger_calls == 1
        assert orchestrator.heartbeat_calls == 1
        assert orchestrator.last_next_run is None or orchestrator.last_next_run.tzinfo is not None
    finally:
        runtime.shutdown()


def test_next_weekly_run_is_utc_when_available(tmp_path: Path) -> None:
    orchestrator = _FakeOrchestrator()
    runtime = SchedulerRuntime(
        config=_build_config(tmp_path),
        orchestrator=orchestrator,  # type: ignore[arg-type]
    )

    runtime.start()
    try:
        next_run = runtime.next_weekly_run_at()
        assert next_run is not None
        assert next_run.tzinfo == UTC
    finally:
        runtime.shutdown()
