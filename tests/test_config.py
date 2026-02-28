"""Tests for config loading and validation."""

from __future__ import annotations

import pytest

from config import ConfigError, get_config, reset_config_cache

REQUIRED_ENV = {
    "OPENROUTER_API_KEY": "sk-or-v1-test",
    "SLACK_BOT_TOKEN": "xoxb-test",
    "SLACK_APP_TOKEN": "xapp-test",
    "NEWSLETTER_CHANNEL_ID": "C123456",
    "RESEND_API_KEY": "re_test",
    "RESEND_AUDIENCE_ID": "aud_test",
    "NEWSLETTER_FROM_EMAIL": "newsletter@example.com",
    "TIMEZONE": "America/Chicago",
    "RESEARCH_DAY": "thu",
    "RESEARCH_HOUR": "9",
    "BRAIN_FILE_PATH": "data/published_stories.md",
    "DEDUP_LOOKBACK_WEEKS": "12",
    "RUN_STATE_DB_PATH": "data/run_state.db",
    "FAILURE_LOG_DIR": "data/failures",
    "MAX_EXTERNAL_RETRIES": "4",
    "MAX_DRAFT_VERSIONS": "5",
    "ENABLE_DRY_RUN": "true",
}


def _apply_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)


def test_get_config_parses_values(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_config_cache()
    _apply_required_env(monkeypatch)
    monkeypatch.setenv("HEARTBEAT_HOUR_UTC", "14")
    monkeypatch.setenv(
        "SIGNUP_ALLOWED_ORIGINS",
        "https://example.com, https://newsletter.example.com",
    )

    config = get_config(load_dotenv_file=False)

    assert config.research_hour == 9
    assert config.max_draft_versions == 5
    assert config.enable_dry_run is True
    assert config.heartbeat_hour_utc == 14
    assert config.signup_allowed_origins == (
        "https://example.com",
        "https://newsletter.example.com",
    )


def test_get_config_missing_required_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_config_cache()
    _apply_required_env(monkeypatch)
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)

    with pytest.raises(ConfigError):
        get_config(load_dotenv_file=False)


def test_get_config_rejects_invalid_bool(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_config_cache()
    _apply_required_env(monkeypatch)
    monkeypatch.setenv("ENABLE_DRY_RUN", "sometimes")

    with pytest.raises(ConfigError):
        get_config(load_dotenv_file=False)
