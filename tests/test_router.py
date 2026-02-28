"""Tests for message routing dispatcher."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from listeners.approval import ApprovalHandler
from listeners.feedback import FeedbackHandler
from listeners.intent import IntentClassifier, IntentResult
from listeners.router import MessageDispatcher
from listeners.updates import TeamUpdateHandler
from services.command_controller import CommandResult
from services.context_state import ConversationState
from services.draft_manager import DraftManager
from services.run_state import RunStateStore


class _FakeLLM:
    """Fake LLM that always returns CLEAR for team update validation."""

    def ask_claude(self, **kwargs: Any) -> Any:
        # Check if this is an intent classification call (has the system prompt)
        system_prompt = kwargs.get("system_prompt", "")
        if "CAPABILITIES" in (system_prompt or ""):
            # Intent classifier call — default to team_update
            return type("Resp", (), {"content": '{"intent": "team_update", "response": "TEAM_UPDATE"}'})()
        # Team update validation call
        return type("Resp", (), {"content": "CLEAR"})()


class _HelpLLM:
    """Fake LLM that classifies everything as help_request."""

    def ask_claude(self, **kwargs: Any) -> Any:
        system_prompt = kwargs.get("system_prompt", "")
        if "CAPABILITIES" in (system_prompt or ""):
            return type("Resp", (), {"content": '{"intent": "help_request", "response": "You can use /run to start."}'})()
        return type("Resp", (), {"content": "CLEAR"})()


class _CommandRequestLLM:
    """Fake LLM that classifies everything as command_request."""

    def ask_claude(self, **kwargs: Any) -> Any:
        system_prompt = kwargs.get("system_prompt", "")
        if "CAPABILITIES" in (system_prompt or ""):
            return type("Resp", (), {"content": '{"intent": "command_request", "response": "Use /run to start a manual run."}'})()
        return type("Resp", (), {"content": "CLEAR"})()


@dataclass
class _CommandRecorder:
    accepted: bool
    called: int = 0

    def __call__(self, *_: Any) -> CommandResult:
        self.called += 1
        return CommandResult(accepted=self.accepted, reason="ok")


def _build_dispatcher(
    tmp_path: Path, *, llm: Any | None = None
) -> MessageDispatcher:
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

    llm_client = llm or _FakeLLM()

    approval_handler = ApprovalHandler(draft_manager)
    feedback_handler = FeedbackHandler(
        draft_manager,
        revision_builder=lambda _text: ({"x": 2}, "<p>new</p>", "100.2"),
    )
    update_handler = TeamUpdateHandler(llm_client, context_state)  # type: ignore[arg-type]
    intent_classifier = IntentClassifier(llm_client)  # type: ignore[arg-type]

    return MessageDispatcher(
        bot_user_id="UBOT",
        draft_manager=draft_manager,
        context_state=context_state,
        approval_handler=approval_handler,
        feedback_handler=feedback_handler,
        update_handler=update_handler,
        intent_classifier=intent_classifier,
        on_include_late_update=_CommandRecorder(True),
    )


def test_router_ignores_self_message(tmp_path: Path) -> None:
    dispatcher = _build_dispatcher(tmp_path)

    outcome = dispatcher.dispatch({"user": "UBOT", "text": "hello", "ts": "1.0"})

    assert outcome.action == "ignore"


def test_router_classifies_team_update(tmp_path: Path) -> None:
    """'run' is no longer a command — it goes through intent classification."""
    dispatcher = _build_dispatcher(tmp_path)

    # With intent classifier, "run" is classified as team_update by default FakeLLM
    outcome = dispatcher.dispatch({"user": "U1", "text": "We shipped a new feature", "ts": "1.0"})

    assert outcome.action == "team_update"
    assert outcome.detail == "clear"


def test_router_classifies_help_request(tmp_path: Path) -> None:
    """Help requests get routed to agent_response."""
    dispatcher = _build_dispatcher(tmp_path, llm=_HelpLLM())

    outcome = dispatcher.dispatch({"user": "U1", "text": "How do I add subscribers?", "ts": "1.0"})

    assert outcome.action == "agent_response"
    assert outcome.detail == "help_request"
    assert "/run" in outcome.payload["response"]


def test_router_classifies_command_request(tmp_path: Path) -> None:
    """Typing 'run' as text now goes through intent classifier, not direct command."""
    dispatcher = _build_dispatcher(tmp_path, llm=_CommandRequestLLM())

    outcome = dispatcher.dispatch({"user": "U1", "text": "run the newsletter", "ts": "1.0"})

    assert outcome.action == "agent_response"
    assert outcome.detail == "command_request"
    assert "/run" in outcome.payload["response"]


def test_router_routes_approval_in_draft_thread(tmp_path: Path) -> None:
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


def test_router_strips_attribution_from_stored_update_text(tmp_path: Path) -> None:
    dispatcher = _build_dispatcher(tmp_path)

    raw_text = "We shipped v2 of the API *Sent using* <@U09J4E03THB>"
    dispatcher.dispatch({"user": "U1", "text": raw_text, "ts": "7.0"})

    bodies = dispatcher._context_state.team_update_bodies
    assert "7.0" in bodies
    assert "*Sent using*" not in bodies["7.0"]
    assert bodies["7.0"] == "We shipped v2 of the API"


def test_router_ignores_system_subtypes(tmp_path: Path) -> None:
    dispatcher = _build_dispatcher(tmp_path)

    for subtype in ("channel_purpose", "channel_topic", "channel_join", "channel_leave"):
        outcome = dispatcher.dispatch(
            {"user": "U1", "text": "something", "ts": "6.0", "subtype": subtype}
        )
        assert outcome.action == "ignore", f"subtype={subtype} was not ignored"
