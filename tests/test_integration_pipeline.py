"""Integration-style tests for end-to-end run -> approval -> send flow."""

from __future__ import annotations

from pathlib import Path

from models import DraftStatus, RunStage
from tests.test_orchestrator import _build_orchestrator, _latest_run_id


def test_integration_full_dry_run_path(tmp_path: Path) -> None:
    orchestrator, draft_manager, run_state, _slack_client, sender, _config = _build_orchestrator(
        tmp_path,
        sender_dry_run=True,
    )

    run_outcome = orchestrator.trigger_run(trigger="manual")
    run_id = run_outcome.run_id or _latest_run_id(run_state)
    draft_manager.mark_status(status=DraftStatus.APPROVED)
    send_outcome = orchestrator.send_approved_run(run_id=run_id)

    assert run_outcome.accepted
    assert send_outcome.accepted
    assert sender.sent == 1
    assert run_state.get_run(run_id).stage == RunStage.BRAIN_UPDATED  # type: ignore[union-attr]


def test_integration_live_send_and_single_brain_update(tmp_path: Path) -> None:
    orchestrator, draft_manager, run_state, _slack_client, sender, _config = _build_orchestrator(
        tmp_path,
        sender_dry_run=False,
    )

    run_outcome = orchestrator.trigger_run(trigger="manual")
    run_id = run_outcome.run_id or _latest_run_id(run_state)
    draft_manager.mark_status(status=DraftStatus.APPROVED)

    first = orchestrator.send_approved_run(run_id=run_id)
    second = orchestrator.send_approved_run(run_id=run_id)

    assert first.accepted
    assert not second.accepted
    assert second.reason == "already_sent"
    assert sender.sent == 1

    brain_text = (tmp_path / "data" / "published_stories.md").read_text(encoding="utf-8")
    assert brain_text.count("Agent startup raises $25M") == 1
