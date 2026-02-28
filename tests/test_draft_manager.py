"""Tests for draft manager lifecycle behavior."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from models import DraftStatus
from services.draft_manager import DraftManager
from services.run_state import RunStateStore


def _setup_manager(tmp_path: Path):
    from config import AppConfig

    data_dir = tmp_path / "data"
    config = AppConfig(
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
        max_draft_versions=2,
        enable_dry_run=True,
        heartbeat_channel_id=None,
        heartbeat_hour_utc=None,
        signup_allowed_origins=(),
    )
    store = RunStateStore(config.run_state_db_path)
    store.initialize()
    store.create_run("run-1")
    manager = DraftManager(config, store)
    return manager, store, config


def test_create_and_revise_draft(tmp_path: Path) -> None:
    manager, _, _ = _setup_manager(tmp_path)

    created = manager.create_or_replace_draft(
        run_id="run-1",
        draft_ts="1.0",
        draft_json={"a": 1},
        draft_html="<p>a</p>",
    )
    assert created.draft_version == 1

    revised = manager.create_revision(
        draft_json={"a": 2},
        draft_html="<p>b</p>",
        draft_ts="2.0",
    )
    assert revised.draft_version == 2


def test_revision_cap_sets_max_status(tmp_path: Path) -> None:
    manager, _, _ = _setup_manager(tmp_path)
    manager.create_or_replace_draft(
        run_id="run-1",
        draft_ts="1.0",
        draft_json={"a": 1},
        draft_html="<p>a</p>",
    )
    manager.create_revision(draft_json={"a": 2}, draft_html="<p>b</p>", draft_ts="2.0")

    capped = manager.create_revision(draft_json={"a": 3}, draft_html="<p>c</p>", draft_ts="3.0")

    assert capped.draft_status == DraftStatus.MAX_REVISIONS_REACHED


def test_stale_check(tmp_path: Path) -> None:
    manager, store, _ = _setup_manager(tmp_path)
    manager.create_or_replace_draft(
        run_id="run-1",
        draft_ts="1.0",
        draft_json={"a": 1},
        draft_html="<p>a</p>",
    )

    old = datetime.now(UTC) - timedelta(hours=72)
    with store._connect() as conn:  # noqa: SLF001
        conn.execute(
            "UPDATE draft_state SET updated_at = ? WHERE run_id = ?",
            (old.isoformat(), "run-1"),
        )

    assert manager.is_current_draft_stale()
