"""Manual command control hooks for run/reset/include flows."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class CommandResult:
    """Result payload for command handlers."""

    accepted: bool
    reason: str


@dataclass
class CommandController:
    """Coordinate manual run/reset/include command handling."""

    run_callback: Callable[[], CommandResult]
    reset_callback: Callable[[], CommandResult]
    include_late_update_callback: Callable[[str], CommandResult]
    replay_callback: Callable[[str], CommandResult]
    _run_lock: threading.Lock = field(default_factory=threading.Lock)
    _run_in_progress: bool = False

    def manual_run(self) -> CommandResult:
        """Trigger manual run when no run is currently active."""
        with self._run_lock:
            if self._run_in_progress:
                return CommandResult(accepted=False, reason="run_in_progress")
            self._run_in_progress = True

        try:
            return self.run_callback()
        finally:
            with self._run_lock:
                self._run_in_progress = False

    def reset(self) -> CommandResult:
        """Trigger reset callback."""
        return self.reset_callback()

    def include_late_update(self, thread_ts: str) -> CommandResult:
        """Handle include request for late update thread."""
        return self.include_late_update_callback(thread_ts)

    def replay(self, run_id: str) -> CommandResult:
        """Replay failed run by run ID."""
        return self.replay_callback(run_id)
