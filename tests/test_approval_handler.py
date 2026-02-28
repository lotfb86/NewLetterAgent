"""Tests for approval listener logic."""

from __future__ import annotations

from pathlib import Path

from listeners.approval import ApprovalHandler, is_approval_text
from services.draft_manager import DraftManager
from services.run_state import RunStateStore


def _manager(tmp_path: Path) -> DraftManager:
    from config import AppConfig

    config = AppConfig(
        openrouter_api_key="sk",
        slack_bot_token="xoxb",
        slack_app_token="xapp",
        newsletter_channel_id="C1",
        resend_api_key="re",
        resend_audience_id="aud",
        newsletter_from_email="newsletter@example.com",
        newsletter_reply_to_email=None,
        timezone="America/Chicago",
        research_day="thu",
        research_hour=9,
        brain_file_path=tmp_path / "data/published_stories.md",
        dedup_lookback_weeks=12,
        run_state_db_path=tmp_path / "data/run_state.db",
        failure_log_dir=tmp_path / "data/failures",
        max_external_retries=3,
        max_draft_versions=5,
        enable_dry_run=True,
        heartbeat_channel_id=None,
        heartbeat_hour_utc=None,
        signup_allowed_origins=(),
    )
    store = RunStateStore(config.run_state_db_path)
    store.initialize()
    store.create_run("run-1")
    manager = DraftManager(config, store)
    manager.create_or_replace_draft(
        run_id="run-1",
        draft_ts="10.1",
        draft_json={"x": 1},
        draft_html="<p>draft</p>",
    )
    return manager


def test_is_approval_text() -> None:
    assert is_approval_text("Looks good, approved!")
    assert not is_approval_text("Needs edits")


def test_approval_requires_latest_thread(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    handler = ApprovalHandler(manager)

    rejected = handler.handle(message_text="approved", thread_ts="wrong")
    assert not rejected.accepted
    assert rejected.reason == "not_latest_draft_thread"

    accepted = handler.handle(message_text="approved", thread_ts="10.1")
    assert accepted.accepted
    assert accepted.reason == "approved"
