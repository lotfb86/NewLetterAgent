"""Tests for runtime path bootstrap logic."""

from __future__ import annotations

from pathlib import Path

from config import AppConfig
from services.runtime_paths import bootstrap_runtime_paths


def test_bootstrap_runtime_paths_creates_expected_artifacts(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    config = AppConfig(
        openrouter_api_key="sk",
        slack_bot_token="xoxb",
        slack_app_token="xapp",
        newsletter_channel_id="C123",
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
        max_external_retries=4,
        max_draft_versions=5,
        enable_dry_run=True,
        heartbeat_channel_id=None,
        heartbeat_hour_utc=None,
        signup_allowed_origins=(),
    )

    bootstrap_runtime_paths(config)

    assert (data_dir / "archive").exists()
    assert (data_dir / "failures").exists()
    assert (data_dir / "published_stories.md").exists()
    assert (data_dir / "run_state.db").exists()
