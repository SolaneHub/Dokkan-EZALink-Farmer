"""In-memory virtual clock test harness for instant time simulation.

Intercepts time.time, time.sleep, and time.monotonic to eliminate busy-waiting
and real-time pauses in test loops without altering production semantics.
"""

from __future__ import annotations

import threading
from typing import Any
from unittest.mock import patch


class VirtualClock:
    """Simulates an instant in-memory clock for testing time-dependent loops.

    When time.sleep(seconds) is invoked under this harness, the virtual clock
    advances immediately by `seconds`, and any time.time() / time.monotonic()
    calls return the advanced simulated time without sleeping real CPU cycles.
    """

    def __init__(self, initial_time: float = 1_000_000.0) -> None:
        self._current_time: float = float(initial_time)
        self._lock = threading.Lock()
        self._sleep_history: list[float] = []
        self._patches: list[Any] = []

    @property
    def current_time(self) -> float:
        with self._lock:
            return self._current_time

    def time(self) -> float:
        """Returns the simulated current time."""
        with self._lock:
            return self._current_time

    def monotonic(self) -> float:
        """Returns the simulated monotonic time."""
        with self._lock:
            return self._current_time

    def sleep(self, seconds: float) -> None:
        """Advances virtual time instantly by `seconds` without real-time delay."""
        dur = max(0.0, float(seconds))
        with self._lock:
            self._current_time += dur
            self._sleep_history.append(dur)

    async def async_sleep(self, delay: float = 0.0, result: Any = None) -> Any:
        """Advances virtual time instantly by `delay` without awaiting real-time delay."""
        self.sleep(delay)
        return result

    def advance(self, seconds: float) -> float:
        """Manually advances simulated time by `seconds` and returns the new time."""
        dur = max(0.0, float(seconds))
        with self._lock:
            self._current_time += dur
            return self._current_time

    @property
    def total_slept(self) -> float:
        """Returns total seconds advanced via sleep."""
        with self._lock:
            return sum(self._sleep_history)

    def start(self) -> VirtualClock:
        """Applies monkeypatches to `time.time`, `time.monotonic`, `time.sleep`, and `asyncio.sleep`."""
        if self._patches:
            return self

        p_time = patch("time.time", side_effect=self.time)
        p_monotonic = patch("time.monotonic", side_effect=self.monotonic)
        p_sleep = patch("time.sleep", side_effect=self.sleep)
        p_asyncio_sleep = patch("asyncio.sleep", side_effect=self.async_sleep)

        self._patches = [p_time, p_monotonic, p_sleep, p_asyncio_sleep]
        for p in self._patches:
            p.start()
        return self

    def stop(self) -> None:
        """Restores patched time functions."""
        while self._patches:
            p = self._patches.pop()
            p.stop()

    def __enter__(self) -> VirtualClock:
        return self.start()

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()
