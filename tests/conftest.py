"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from config import AppConfig


@pytest.fixture
def app_config(tmp_path: Path) -> AppConfig:
    data_dir = tmp_path / "data"
    return AppConfig(
        openrouter_api_key="sk-or-v1-test",
        slack_bot_token="xoxb-test",
        slack_app_token="xapp-test",
        newsletter_channel_id="C123456",
        resend_api_key="re_test",
        resend_audience_id="aud_test",
        newsletter_from_email="newsletter@example.com",
        newsletter_reply_to_email=None,
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
        heartbeat_channel_id=None,
        heartbeat_hour_utc=None,
        signup_allowed_origins=("https://example.com",),
    )
