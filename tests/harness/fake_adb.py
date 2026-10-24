from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass
class TapTransition:
    """Target region that, when tapped, advances the screen to a specific or next frame."""

    x_min: int
    y_min: int
    x_max: int
    y_max: int
    next_frame: np.ndarray | None = None
    action_callback: Callable[[int, int], None] | None = None

    def matches(self, x: int, y: int) -> bool:
        return self.x_min <= x <= self.x_max and self.y_min <= y <= self.y_max


class FakeADBClient:
    """Specialized in-memory test harness simulating ADBClient for Dokkan Battle automation.

    Operates entirely in-memory with zero disk/subprocess I/O and zero sleeps.
    Supports linear frame queues and coordinate-triggered deterministic screen transitions.
    """

    def __init__(
        self,
        screen_size: tuple[int, int] = (1080, 2400),
        serial: str = "fake_emulator_5554",
        max_taps: int = 50,
    ) -> None:
        self.max_taps: int = max_taps
        self.serial: str = serial
        self._screen_size: tuple[int, int] = screen_size
        self._frames: deque[np.ndarray] = deque()
        self._current_frame: np.ndarray | None = None
        self._transitions: list[TapTransition] = []
        self._on_tap_callbacks: list[Callable[[int, int, float], None]] = []

        self.tap_history: list[dict[str, Any]] = []
        self.swipe_history: list[dict[str, Any]] = []
        self.key_history: list[str] = []

    def is_connected(self) -> bool:
        """Always returns True to simulate an active connected device."""
        return True

    def get_screen_size(self, force_refresh: bool = False) -> tuple[int, int]:
        """Returns the simulated screen resolution."""
        _ = force_refresh
        return self._screen_size

    def set_screen_size(self, width: int, height: int) -> None:
        self._screen_size = (width, height)

    def queue_frame(self, frame: np.ndarray) -> None:
        """Pushes a frame to the screen queue."""
        self._frames.append(frame)
        if self._current_frame is None:
            self._current_frame = frame

    def queue_frames(self, frames: list[np.ndarray]) -> None:
        """Pushes multiple frames to the screen queue in sequence."""
        for f in frames:
            self.queue_frame(f)

    def set_current_frame(self, frame: np.ndarray) -> None:
        """Directly sets the active screen frame."""
        self._current_frame = frame

    def add_transition(
        self,
        x: int,
        y: int,
        radius: int = 50,
        next_frame: np.ndarray | None = None,
        callback: Callable[[int, int], None] | None = None,
    ) -> TapTransition:
        """Adds a circular/box coordinate target that advances the screen state when tapped."""
        trans = TapTransition(
            x_min=max(0, x - radius),
            y_min=max(0, y - radius),
            x_max=min(self._screen_size[0], x + radius),
            y_max=min(self._screen_size[1], y + radius),
            next_frame=next_frame,
            action_callback=callback,
        )
        self._transitions.append(trans)
        return trans

    def add_box_transition(
        self,
        x_min: int,
        y_min: int,
        x_max: int,
        y_max: int,
        next_frame: np.ndarray | None = None,
        callback: Callable[[int, int], None] | None = None,
    ) -> TapTransition:
        """Adds a bounding box transition."""
        trans = TapTransition(
            x_min=x_min,
            y_min=y_min,
            x_max=x_max,
            y_max=y_max,
            next_frame=next_frame,
            action_callback=callback,
        )
        self._transitions.append(trans)
        return trans

    def screencap(self) -> np.ndarray:
        """Returns the current screen frame.

        If a queue exists and current frame was consumed by a transition, pops the next.
        """
        if self._current_frame is not None:
            return self._current_frame

        if self._frames:
            self._current_frame = self._frames.popleft()
            return self._current_frame

        w, h = self._screen_size
        blank = np.zeros((h, w, 3), dtype=np.uint8)
        self._current_frame = blank
        return blank

    def tap(self, x: int, y: int, delay_after: float = 0.5) -> None:
        """Simulates tapping (x, y) without physical latency or sleep."""
        if len(self.tap_history) >= self.max_taps:
            raise RuntimeError(
                f"FakeADBClient safety limit exceeded ({self.max_taps} taps). "
                "The task is likely stuck in an infinite loop due to an unhandled or cycling game state."
            )

        record = {"x": int(x), "y": int(y), "delay_after": float(delay_after)}
        self.tap_history.append(record)

        for cb in self._on_tap_callbacks:
            cb(int(x), int(y), float(delay_after))

        matched = False
        for trans in list(self._transitions):
            if trans.matches(int(x), int(y)):
                matched = True
                if trans.action_callback:
                    trans.action_callback(int(x), int(y))
                if trans.next_frame is not None:
                    self._current_frame = trans.next_frame
                    break
                elif self._frames:
                    self._current_frame = self._frames.popleft()
                    break

        if not matched and self._frames:
            self._current_frame = self._frames.popleft()

    def tap_ratio(self, rx: float, ry: float, delay_after: float = 0.5) -> None:
        w, h = self._screen_size
        self.tap(int(w * rx), int(h * ry), delay_after=delay_after)

    def swipe(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int = 300,
        delay_after: float = 0.5,
    ) -> None:
        """Simulates swipe gesture without physical latency or sleep."""
        record = {
            "x1": int(x1),
            "y1": int(y1),
            "x2": int(x2),
            "y2": int(y2),
            "duration_ms": int(duration_ms),
            "delay_after": float(delay_after),
        }
        self.swipe_history.append(record)

        if self._frames:
            self._current_frame = self._frames.popleft()

    def key_back(self) -> None:
        self.key_history.append("KEYCODE_BACK")

    def key_home(self) -> None:
        self.key_history.append("KEYCODE_HOME")

    def is_app_running(self, package_name: str) -> bool:
        _ = package_name
        return True

    def launch_app(self, package_name: str) -> None:
        _ = package_name

    def clear_history(self) -> None:
        self.tap_history.clear()
        self.swipe_history.clear()
        self.key_history.clear()
