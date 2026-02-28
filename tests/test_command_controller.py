"""Tests for command controller manual run lock behavior."""

from __future__ import annotations

import threading

from services.command_controller import CommandController, CommandResult



def test_manual_run_rejects_when_command_already_in_progress() -> None:
    entered = threading.Event()
    release = threading.Event()

    def _slow_run() -> CommandResult:
        entered.set()
        release.wait(timeout=2)
        return CommandResult(accepted=True, reason="run_completed")

    controller = CommandController(
        run_callback=_slow_run,
        reset_callback=lambda: CommandResult(True, "run_completed"),
        include_late_update_callback=lambda _thread: CommandResult(True, "included"),
        replay_callback=lambda _run_id: CommandResult(True, "sent"),
    )

    result_holder: dict[str, CommandResult] = {}

    def _run_first() -> None:
        result_holder["first"] = controller.manual_run()

    worker = threading.Thread(target=_run_first)
    worker.start()

    assert entered.wait(timeout=1)
    second = controller.manual_run()

    release.set()
    worker.join(timeout=1)

    assert second.accepted is False
    assert second.reason == "run_in_progress"
    assert result_holder["first"].accepted is True



def test_reset_and_replay_passthrough() -> None:
    controller = CommandController(
        run_callback=lambda: CommandResult(True, "run_completed"),
        reset_callback=lambda: CommandResult(True, "run_completed"),
        include_late_update_callback=lambda _thread: CommandResult(True, "included"),
        replay_callback=lambda run_id: CommandResult(True, f"sent:{run_id}"),
    )

    assert controller.reset().accepted is True
    replay = controller.replay("run-123")
    assert replay.reason == "sent:run-123"
