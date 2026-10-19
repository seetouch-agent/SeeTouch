"""Cooperative task control. A changed revision invalidates any unexecuted decision."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable


class RunStopped(Exception):
    pass


class ReobserveRequired(Exception):
    pass


class ExecutionControl:
    def __init__(self, state_reader: Callable[[], dict] | None = None):
        self._reader = state_reader
        self._lock = threading.RLock()
        self._mode = "running"
        self._revision = 0
        self._pending_events: list[dict] = []
        self.event_sink: Callable[[dict], None] | None = None

    def set_mode(self, mode: str) -> None:
        if mode not in {"running", "paused", "waiting_user", "takeover", "stopped"}:
            raise ValueError(mode)
        with self._lock:
            if self._mode == "stopped":
                return
            self._mode = mode
            self._revision += 1

    def snapshot(self) -> tuple[str, int]:
        if self._reader is not None:
            state = self._reader()
            self._pending_events.extend(state.get("events", []))
            if self.event_sink:
                for event in self._pending_events:
                    self.event_sink(event)
                self._pending_events.clear()
            return str(state["mode"]), int(state["revision"])
        with self._lock:
            return self._mode, self._revision

    def checkpoint(self, revision: int | None = None) -> int:
        while True:
            mode, current = self.snapshot()
            if mode == "stopped":
                raise RunStopped()
            if mode == "running":
                if revision is not None and current != revision:
                    raise ReobserveRequired()
                return current
            time.sleep(0.05)

    def sleep(self, seconds: float) -> None:
        # Once an action has been dispatched, a pause must not replay it.
        deadline = time.monotonic() + max(0, seconds)
        while time.monotonic() < deadline:
            if self.snapshot()[0] != "running":
                return
            time.sleep(min(0.05, max(0, deadline - time.monotonic())))
