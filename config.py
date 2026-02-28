"""Centralized configuration loading for the newsletter agent."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


class ConfigError(ValueError):
    """Raised when required configuration is missing or invalid."""


VALID_RESEARCH_DAYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}


@dataclass(frozen=True)
class AppConfig:
    """Typed application configuration loaded from environment variables."""

    openrouter_api_key: str
    slack_bot_token: str
    slack_app_token: str
    newsletter_channel_id: str
    resend_api_key: str
    resend_audience_id: str
    newsletter_from_email: str
    newsletter_reply_to_email: str | None
    timezone: str
    research_day: str
    research_hour: int
    brain_file_path: Path
    dedup_lookback_weeks: int
    run_state_db_path: Path
    failure_log_dir: Path
    max_external_retries: int
    max_draft_versions: int
    enable_dry_run: bool
    heartbeat_channel_id: str | None
    heartbeat_hour_utc: int | None
    signup_allowed_origins: tuple[str, ...]


_REQUIRED_ENV_VARS = (
    "OPENROUTER_API_KEY",
    "SLACK_BOT_TOKEN",
    "SLACK_APP_TOKEN",
    "NEWSLETTER_CHANNEL_ID",
    "RESEND_API_KEY",
    "RESEND_AUDIENCE_ID",
    "NEWSLETTER_FROM_EMAIL",
    "TIMEZONE",
    "RESEARCH_DAY",
    "RESEARCH_HOUR",
    "BRAIN_FILE_PATH",
    "DEDUP_LOOKBACK_WEEKS",
    "RUN_STATE_DB_PATH",
    "FAILURE_LOG_DIR",
    "MAX_EXTERNAL_RETRIES",
    "MAX_DRAFT_VERSIONS",
    "ENABLE_DRY_RUN",
)


def _get_required_env(name: str) -> str:
    import os

    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        raise ConfigError(f"Missing required environment variable: {name}")
    return raw.strip()


def _parse_bool(name: str, raw: str) -> bool:
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"Invalid boolean value for {name}: {raw!r}")


def _parse_int(name: str, raw: str, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"Invalid integer value for {name}: {raw!r}") from exc

    if minimum is not None and value < minimum:
        raise ConfigError(f"{name} must be >= {minimum}, got {value}")
    if maximum is not None and value > maximum:
        raise ConfigError(f"{name} must be <= {maximum}, got {value}")
    return value


def _parse_csv(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    values = [item.strip() for item in raw.split(",") if item.strip()]
    return tuple(values)


def _validate_required_envs() -> None:
    for name in _REQUIRED_ENV_VARS:
        _get_required_env(name)


@lru_cache(maxsize=1)
def get_config(load_dotenv_file: bool = True) -> AppConfig:
    """Load and cache app configuration."""
    if load_dotenv_file:
        load_dotenv()

    _validate_required_envs()

    import os

    research_day = _get_required_env("RESEARCH_DAY").lower()
    if research_day not in VALID_RESEARCH_DAYS:
        raise ConfigError(
            f"Invalid RESEARCH_DAY: {research_day!r}. Expected one of {sorted(VALID_RESEARCH_DAYS)}"
        )

    research_hour = _parse_int(
        "RESEARCH_HOUR",
        _get_required_env("RESEARCH_HOUR"),
        minimum=0,
        maximum=23,
    )
    dedup_lookback_weeks = _parse_int(
        "DEDUP_LOOKBACK_WEEKS",
        _get_required_env("DEDUP_LOOKBACK_WEEKS"),
        minimum=1,
    )
    max_external_retries = _parse_int(
        "MAX_EXTERNAL_RETRIES",
        _get_required_env("MAX_EXTERNAL_RETRIES"),
        minimum=1,
    )
    max_draft_versions = _parse_int(
        "MAX_DRAFT_VERSIONS",
        _get_required_env("MAX_DRAFT_VERSIONS"),
        minimum=1,
    )

    heartbeat_hour_utc_raw = os.environ.get("HEARTBEAT_HOUR_UTC")
    heartbeat_hour_utc = (
        _parse_int("HEARTBEAT_HOUR_UTC", heartbeat_hour_utc_raw, minimum=0, maximum=23)
        if heartbeat_hour_utc_raw
        else None
    )

    return AppConfig(
        openrouter_api_key=_get_required_env("OPENROUTER_API_KEY"),
        slack_bot_token=_get_required_env("SLACK_BOT_TOKEN"),
        slack_app_token=_get_required_env("SLACK_APP_TOKEN"),
        newsletter_channel_id=_get_required_env("NEWSLETTER_CHANNEL_ID"),
        resend_api_key=_get_required_env("RESEND_API_KEY"),
        resend_audience_id=_get_required_env("RESEND_AUDIENCE_ID"),
        newsletter_from_email=_get_required_env("NEWSLETTER_FROM_EMAIL"),
        newsletter_reply_to_email=os.environ.get("NEWSLETTER_REPLY_TO_EMAIL") or None,
        timezone=_get_required_env("TIMEZONE"),
        research_day=research_day,
        research_hour=research_hour,
        brain_file_path=Path(_get_required_env("BRAIN_FILE_PATH")),
        dedup_lookback_weeks=dedup_lookback_weeks,
        run_state_db_path=Path(_get_required_env("RUN_STATE_DB_PATH")),
        failure_log_dir=Path(_get_required_env("FAILURE_LOG_DIR")),
        max_external_retries=max_external_retries,
        max_draft_versions=max_draft_versions,
        enable_dry_run=_parse_bool("ENABLE_DRY_RUN", _get_required_env("ENABLE_DRY_RUN")),
        heartbeat_channel_id=os.environ.get("HEARTBEAT_CHANNEL_ID"),
        heartbeat_hour_utc=heartbeat_hour_utc,
        signup_allowed_origins=_parse_csv(os.environ.get("SIGNUP_ALLOWED_ORIGINS")),
    )


def reset_config_cache() -> None:
    """Clear memoized configuration for tests and process reloads."""
    get_config.cache_clear()
