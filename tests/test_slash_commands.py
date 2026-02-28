"""Tests for listeners.slash_commands."""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from listeners.approval import ApprovalHandler, ApprovalOutcome
from listeners.slash_commands import SlashCommandHandlers
from services.command_controller import CommandController, CommandResult
from services.contact_importer import ContactImporter


def _build_handlers(
    *,
    run_result: CommandResult | None = None,
    reset_result: CommandResult | None = None,
    replay_result: CommandResult | None = None,
    approval_outcome: ApprovalOutcome | None = None,
    send_accepted: bool = True,
) -> SlashCommandHandlers:
    command_controller = MagicMock(spec=CommandController)
    command_controller.manual_run.return_value = run_result or CommandResult(True, "run_completed")
    command_controller.reset.return_value = reset_result or CommandResult(True, "run_completed")
    command_controller.replay.return_value = replay_result or CommandResult(True, "run_completed")

    approval_handler = MagicMock(spec=ApprovalHandler)
    approval_handler.handle_slash.return_value = approval_outcome or ApprovalOutcome(
        accepted=True, reason="approved", run_id="run-1"
    )

    orchestrator = MagicMock()
    orchestrator.send_approved_run.return_value = MagicMock(
        accepted=send_accepted, reason="ok" if send_accepted else "send_failed"
    )

    mock_resend = MagicMock()
    contact_importer = ContactImporter(
        resend_api_key="re_test", audience_id="aud_test", resend_module=mock_resend
    )

    return SlashCommandHandlers(
        command_controller=command_controller,
        approval_handler=approval_handler,
        contact_importer=contact_importer,
        orchestrator=orchestrator,
        slack_client=MagicMock(),
        channel_id="C123",
    )


def test_handle_help_acks_and_responds() -> None:
    handlers = _build_handlers()
    ack = MagicMock()
    respond = MagicMock()

    handlers.handle_help(ack, respond, {"text": ""})

    ack.assert_called_once()
    respond.assert_called_once()
    response_text = respond.call_args[0][0]
    assert "/run" in response_text
    assert "/approve" in response_text
    assert "/import-contacts" in response_text


def test_handle_run_acks_immediately() -> None:
    handlers = _build_handlers()
    ack = MagicMock()
    respond = MagicMock()

    handlers.handle_run(ack, respond, {"text": ""})

    # ack is called immediately, respond comes from the thread
    ack.assert_called_once()
    ack_text = ack.call_args[0][0]
    assert "Starting" in ack_text


def test_handle_run_thread_completes(monkeypatch: Any) -> None:
    handlers = _build_handlers()
    ack = MagicMock()
    respond = MagicMock()

    # Call and wait for thread to finish
    handlers.handle_run(ack, respond, {"text": ""})
    time.sleep(0.5)  # Wait for daemon thread

    respond.assert_called_once()
    assert "completed" in respond.call_args[0][0].lower() or "complete" in respond.call_args[0][0].lower()


def test_handle_run_rejected() -> None:
    handlers = _build_handlers(run_result=CommandResult(False, "run_in_progress"))
    ack = MagicMock()
    respond = MagicMock()

    handlers.handle_run(ack, respond, {"text": ""})
    time.sleep(0.5)

    respond.assert_called_once()
    assert "run_in_progress" in respond.call_args[0][0]


def test_handle_reset_acks_and_completes() -> None:
    handlers = _build_handlers()
    ack = MagicMock()
    respond = MagicMock()

    handlers.handle_reset(ack, respond, {"text": ""})
    time.sleep(0.5)

    ack.assert_called_once()
    respond.assert_called_once()
    assert "completed" in respond.call_args[0][0].lower() or "fresh" in respond.call_args[0][0].lower()


def test_handle_replay_requires_run_id() -> None:
    handlers = _build_handlers()
    ack = MagicMock()
    respond = MagicMock()

    handlers.handle_replay(ack, respond, {"text": ""})

    ack.assert_called_once()
    ack_text = ack.call_args[0][0]
    assert "run_id" in ack_text.lower() or "Usage" in ack_text


def test_handle_replay_with_run_id() -> None:
    handlers = _build_handlers()
    ack = MagicMock()
    respond = MagicMock()

    handlers.handle_replay(ack, respond, {"text": "run-abc"})
    time.sleep(0.5)

    ack.assert_called_once()
    respond.assert_called_once()
    assert "completed" in respond.call_args[0][0].lower() or "run-abc" in respond.call_args[0][0]


def test_handle_approve_success() -> None:
    handlers = _build_handlers()
    ack = MagicMock()
    respond = MagicMock()

    handlers.handle_approve(ack, respond, {"text": ""})
    time.sleep(0.5)

    ack.assert_called_once()
    respond.assert_called_once()
    assert "sent" in respond.call_args[0][0].lower() or "approved" in respond.call_args[0][0].lower()


def test_handle_approve_no_active_draft() -> None:
    handlers = _build_handlers(
        approval_outcome=ApprovalOutcome(accepted=False, reason="no_active_draft")
    )
    ack = MagicMock()
    respond = MagicMock()

    handlers.handle_approve(ack, respond, {"text": ""})
    time.sleep(0.5)

    respond.assert_called_once()
    assert "/run" in respond.call_args[0][0] or "No active draft" in respond.call_args[0][0]


def test_handle_approve_send_failure() -> None:
    handlers = _build_handlers(send_accepted=False)
    ack = MagicMock()
    respond = MagicMock()

    handlers.handle_approve(ack, respond, {"text": ""})
    time.sleep(0.5)

    respond.assert_called_once()
    assert "send failed" in respond.call_args[0][0].lower() or "failed" in respond.call_args[0][0].lower()


def test_handle_import_contacts_inline() -> None:
    handlers = _build_handlers()
    # Mock the resend contacts create to succeed
    handlers._contact_importer._resend.contacts.create = MagicMock(return_value={"id": "c1"})

    ack = MagicMock()
    respond = MagicMock()

    handlers.handle_import_contacts(ack, respond, {"text": "a@test.com, b@test.com"})
    time.sleep(0.5)

    ack.assert_called_once()
    respond.assert_called_once()
    response_text = respond.call_args[0][0]
    assert "2" in response_text  # 2 imported


def test_handle_import_contacts_no_input_no_csv() -> None:
    handlers = _build_handlers()
    handlers._slack_client = MagicMock()
    handlers._slack_client.conversations_history.return_value = {"messages": []}

    ack = MagicMock()
    respond = MagicMock()

    handlers.handle_import_contacts(ack, respond, {"text": ""})
    time.sleep(0.5)

    respond.assert_called_once()
    assert "No emails" in respond.call_args[0][0] or "CSV" in respond.call_args[0][0]


def test_handle_import_contacts_with_invalid_emails() -> None:
    handlers = _build_handlers()
    handlers._contact_importer._resend.contacts.create = MagicMock(return_value={"id": "c1"})

    ack = MagicMock()
    respond = MagicMock()

    handlers.handle_import_contacts(ack, respond, {"text": "good@test.com, bad-email"})
    time.sleep(0.5)

    respond.assert_called_once()
    response_text = respond.call_args[0][0]
    assert "invalid" in response_text.lower() or "skipped" in response_text.lower()
