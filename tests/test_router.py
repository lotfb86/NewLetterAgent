"""Tests for message routing dispatcher."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from listeners.approval import ApprovalHandler
from listeners.feedback import FeedbackHandler
from listeners.router import MessageDispatcher
from listeners.updates import TeamUpdateHandler
from services.command_controller import CommandResult
from services.context_state import ConversationState
from services.draft_manager import DraftManager
from services.run_state import RunStateStore


class _FakeLLM:
    def ask_claude(self, **_: Any) -> Any:
        return type("Resp", (), {"content": "CLEAR"})()


@dataclass
class _CommandRecorder:
    accepted: bool
    called: int = 0

    def __call__(self, *_: Any) -> CommandResult:
        self.called += 1
        return CommandResult(accepted=self.accepted, reason="ok")


def _build_dispatcher(tmp_path: Path) -> MessageDispatcher:
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
        max_draft_versions=3,
        enable_dry_run=True,
        heartbeat_channel_id=None,
        heartbeat_hour_utc=None,
        signup_allowed_origins=(),
    )
    store = RunStateStore(config.run_state_db_path)
    store.initialize()
    store.create_run("run-1")
    draft_manager = DraftManager(config, store)
    draft_manager.create_or_replace_draft(
        run_id="run-1",
        draft_ts="100.1",
        draft_json={"x": 1},
        draft_html="<p>draft</p>",
    )

    context_state = ConversationState()
    context_state.set_collection_cutoff(datetime.now(UTC) - timedelta(minutes=5))

    approval_handler = ApprovalHandler(draft_manager)
    feedback_handler = FeedbackHandler(
        draft_manager,
        revision_builder=lambda _text: ({"x": 2}, "<p>new</p>", "100.2"),
    )
    update_handler = TeamUpdateHandler(_FakeLLM(), context_state)  # type: ignore[arg-type]

    return MessageDispatcher(
        bot_user_id="UBOT",
        draft_manager=draft_manager,
        context_state=context_state,
        approval_handler=approval_handler,
        feedback_handler=feedback_handler,
        update_handler=update_handler,
        on_manual_run=_CommandRecorder(True),
        on_reset=_CommandRecorder(True),
        on_include_late_update=_CommandRecorder(True),
        on_replay=_CommandRecorder(True),
    )


def test_router_ignores_self_message(tmp_path: Path) -> None:
    dispatcher = _build_dispatcher(tmp_path)

    outcome = dispatcher.dispatch({"user": "UBOT", "text": "hello", "ts": "1.0"})

    assert outcome.action == "ignore"


def test_router_routes_manual_run_and_reset(tmp_path: Path) -> None:
    dispatcher = _build_dispatcher(tmp_path)

    run_outcome = dispatcher.dispatch({"user": "U1", "text": "run", "ts": "1.0"})
    reset_outcome = dispatcher.dispatch({"user": "U1", "text": "reset", "ts": "1.1"})

    assert run_outcome.action == "manual_run"
    assert reset_outcome.action == "reset"


def test_router_routes_approval_and_feedback(tmp_path: Path) -> None:
    dispatcher = _build_dispatcher(tmp_path)

    approval = dispatcher.dispatch(
        {"user": "U1", "text": "approved", "ts": "2.0", "thread_ts": "100.1"}
    )
    feedback = dispatcher.dispatch(
        {"user": "U1", "text": "change this", "ts": "2.1", "thread_ts": "100.1"}
    )

    assert approval.action == "approval"
    assert feedback.action == "feedback"


def test_router_handles_late_update_prompt_and_include(tmp_path: Path) -> None:
    dispatcher = _build_dispatcher(tmp_path)
    late_ts = str((datetime.now(UTC) + timedelta(minutes=1)).timestamp())

    top_level = dispatcher.dispatch(
        {
            "user": "U1",
            "text": "Late update",
            "ts": late_ts,
        }
    )
    assert top_level.action == "late_update_prompt"

    include = dispatcher.dispatch(
        {
            "user": "U1",
            "text": "include",
            "ts": "3.1",
            "thread_ts": late_ts,
        }
    )
    assert include.action == "late_update_include"


def test_router_routes_replay_command(tmp_path: Path) -> None:
    dispatcher = _build_dispatcher(tmp_path)

    replay = dispatcher.dispatch({"user": "U1", "text": "replay run-1", "ts": "4.0"})

    assert replay.action == "replay"


def test_router_strips_slack_attribution(tmp_path: Path) -> None:
    dispatcher = _build_dispatcher(tmp_path)

    # Slack integrations may append "*Sent using* <@BOT_ID>" inline
    run = dispatcher.dispatch(
        {"user": "U1", "text": "run *Sent using* <@U09J4E03THB>", "ts": "5.0"}
    )
    reset = dispatcher.dispatch(
        {"user": "U1", "text": "reset *Sent using* <@U09J4E03THB>", "ts": "5.1"}
    )
    replay = dispatcher.dispatch(
        {"user": "U1", "text": "replay run-1 *Sent using* <@U09J4E03THB>", "ts": "5.2"}
    )

    assert run.action == "manual_run"
    assert reset.action == "reset"
    assert replay.action == "replay"


def test_router_ignores_system_subtypes(tmp_path: Path) -> None:
    dispatcher = _build_dispatcher(tmp_path)

    for subtype in ("channel_purpose", "channel_topic", "channel_join", "channel_leave"):
        outcome = dispatcher.dispatch(
            {"user": "U1", "text": "something", "ts": "6.0", "subtype": subtype}
        )
        assert outcome.action == "ignore", f"subtype={subtype} was not ignored"
