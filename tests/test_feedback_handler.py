"""Tests for feedback listener logic."""

from __future__ import annotations

from pathlib import Path

from listeners.feedback import FeedbackHandler
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
        timezone="America/Chicago",
        research_day="thu",
        research_hour=9,
        brain_file_path=tmp_path / "data/published_stories.md",
        dedup_lookback_weeks=12,
        run_state_db_path=tmp_path / "data/run_state.db",
        failure_log_dir=tmp_path / "data/failures",
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
    manager.create_or_replace_draft(
        run_id="run-1",
        draft_ts="10.1",
        draft_json={"x": 1},
        draft_html="<p>draft</p>",
    )
    return manager


def test_feedback_creates_revision(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    handler = FeedbackHandler(
        manager,
        revision_builder=lambda _feedback: ({"x": 2}, "<p>updated</p>", "10.2"),
    )

    outcome = handler.handle(message_text="Please tweak intro", thread_ts="10.1")

    assert outcome.accepted
    assert outcome.reason == "revised"
    assert outcome.draft_version == 2


def test_feedback_enforces_max_revisions(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    handler = FeedbackHandler(
        manager,
        revision_builder=lambda _feedback: ({"x": 2}, "<p>updated</p>", "10.2"),
    )

    handler.handle(message_text="1", thread_ts="10.1")
    capped = handler.handle(message_text="2", thread_ts="10.2")

    assert not capped.accepted
    assert capped.reason == "max_revisions_reached"
