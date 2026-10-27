"""Custom Test Harness for simulating and executing end-to-end farming flows.

Runs EZAFarmTask and LinkLevelFarmTask deterministically in-memory using
FakeADBClient, VirtualClock, and synthetic frame sequences without emulators or ADB.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from tests.harness.fake_adb import FakeADBClient
from tests.harness.fake_clock import VirtualClock

from dokkan_eza_link_farmer.automation.game_state import GameState
from dokkan_eza_link_farmer.automation.tasks.base_task import BaseTask
from dokkan_eza_link_farmer.automation.vision import Vision


class FastSyntheticFrame(np.ndarray):
    """Synthetic in-memory frame holding structured element metadata for zero-latency StateDetector matching."""

    _state: GameState | str = GameState.UNKNOWN
    _meta_lookup: dict[str, Any] = {}

    def __array_finalize__(self, obj: Any) -> None:
        if obj is None:
            return
        self._state = getattr(obj, "_state", GameState.UNKNOWN)
        self._meta_lookup = dict(getattr(obj, "_meta_lookup", {}))


class AutomatedScenarioRunner:
    """Configures and runs deterministic in-memory automation flows.

    Uses FakeADBClient and VirtualClock to advance game states based on registered
    scenarios or screen state sequences, testing tasks like EZAFarmTask and LinkLevelFarmTask
    in fractions of a second with zero physical dependencies.
    """

    def __init__(
        self,
        screen_size: tuple[int, int] = (1080, 2400),
        serial: str = "fake_emulator_scenario",
        max_taps: int = 500,
    ) -> None:
        self.screen_size = screen_size
        self.adb = FakeADBClient(screen_size=screen_size, serial=serial, max_taps=max_taps)
        self.clock = VirtualClock()
        self.vision = Vision()
        self._setup_vision_hooks()
        self._state_frames: dict[GameState | str, FastSyntheticFrame] = {}
        self._prepare_synthetic_state_frames()
        self._current_task: BaseTask | None = None
        self.status_logs: list[str] = []

    def _setup_vision_hooks(self) -> None:
        """Configures Vision to resolve synthetic frame metadata with zero OpenCV overhead."""
        orig_find = self.vision.find_template

        def fast_find(
            screen: np.ndarray,
            template_name: str,
            threshold: float | None = None,
            scales: list[float] | None = None,
        ) -> tuple[int, int, float] | None:
            meta = getattr(screen, "_meta_lookup", None)
            if meta is not None:
                return meta.get(template_name)
            return orig_find(screen, template_name, threshold, scales)

        self.vision.find_template = fast_find  # type: ignore[assignment]

        orig_ok = self.vision.find_ok_button
        self.vision.find_ok_button = lambda s, threshold=0.80: (  # type: ignore[assignment]
            getattr(s, "_meta_lookup", {}).get("button_ok")
            if getattr(s, "_meta_lookup", None) is not None
            else orig_ok(s, threshold)
        )

        orig_again = self.vision.find_attempt_again_button
        self.vision.find_attempt_again_button = lambda s: (  # type: ignore[assignment]
            getattr(s, "_meta_lookup", {}).get("button_attempt_again")
            if getattr(s, "_meta_lookup", None) is not None
            else orig_again(s)
        )

        # Stage auto controls always report active
        self.vision.has_auto_controls = lambda _s: True  # type: ignore[assignment]
        self.vision.find_auto_map_off = lambda _s: None  # type: ignore[assignment]
        self.vision.find_auto_battle_off = lambda _s: None  # type: ignore[assignment]

    def _create_fast_frame(
        self, state: GameState | str, meta: dict[str, Any]
    ) -> FastSyntheticFrame:
        """Creates a FastSyntheticFrame tagged with state metadata."""
        w, h = self.screen_size
        f = np.zeros((h, w, 3), dtype=np.uint8).view(FastSyntheticFrame)
        f._state = state
        f._meta_lookup = meta
        return f

    def _prepare_synthetic_state_frames(self) -> None:
        """Registers synthetic frames stamped with element metadata for all game states."""
        w, h = self.screen_size

        # HOME_SCREEN
        self._state_frames[GameState.HOME_SCREEN] = self._create_fast_frame(
            GameState.HOME_SCREEN,
            {"nav_start": (int(w * 0.50), int(h * 0.64), 1.0)},
        )

        # MODE_SELECT
        self._state_frames[GameState.MODE_SELECT] = self._create_fast_frame(
            GameState.MODE_SELECT,
            {"button_event": (int(w * 0.50), int(h * 0.32), 1.0)},
        )

        # EVENT_SELECT
        self._state_frames[GameState.EVENT_SELECT] = self._create_fast_frame(
            GameState.EVENT_SELECT,
            {"tab_zbattle_inactive": (int(w * 0.83), int(h * 0.21), 1.0)},
        )

        # Z_BATTLE_LIST
        self._state_frames[GameState.Z_BATTLE_LIST] = self._create_fast_frame(
            GameState.Z_BATTLE_LIST,
            {"tab_zbattle_active": (int(w * 0.83), int(h * 0.21), 1.0)},
        )

        # EZA_SELECT
        self._state_frames[GameState.EZA_SELECT] = self._create_fast_frame(
            GameState.EZA_SELECT,
            {"button_eza_fight": (int(w * 0.50), int(h * 0.75), 1.0)},
        )

        # FRIEND_SELECT
        self._state_frames[GameState.FRIEND_SELECT] = self._create_fast_frame(
            GameState.FRIEND_SELECT,
            {
                "header_select_friend": (int(w * 0.50), int(h * 0.15), 1.0),
                "button_friend_refresh": (int(w * 0.82), int(h * 0.18), 1.0),
            },
        )

        # TEAM_CONFIRM
        self._state_frames[GameState.TEAM_CONFIRM] = self._create_fast_frame(
            GameState.TEAM_CONFIRM,
            {"button_start": (int(w * 0.75), int(h * 0.88), 1.0)},
        )

        # BATTLE_SCREEN
        self._state_frames[GameState.BATTLE_SCREEN] = self._create_fast_frame(
            GameState.BATTLE_SCREEN,
            {"button_auto_battle": (int(w * 0.85), int(h * 0.05), 1.0)},
        )

        # KO_SCREEN
        self._state_frames[GameState.KO_SCREEN] = self._create_fast_frame(
            GameState.KO_SCREEN,
            {"banner_ko": (int(w * 0.50), int(h * 0.50), 1.0)},
        )

        # MAP_SCREEN
        self._state_frames[GameState.MAP_SCREEN] = self._create_fast_frame(
            GameState.MAP_SCREEN,
            {"map_auto_on": (int(w * 0.15), int(h * 0.10), 1.0)},
        )

        # STAGE_SELECT
        self._state_frames[GameState.STAGE_SELECT] = self._create_fast_frame(
            GameState.STAGE_SELECT,
            {"diff_super": (int(w * 0.50), int(h * 0.55), 1.0)},
        )

        # RESULTS_SCREEN
        self._state_frames[GameState.RESULTS_SCREEN] = self._create_fast_frame(
            GameState.RESULTS_SCREEN,
            {"header_clear": (int(w * 0.50), int(h * 0.15), 1.0)},
        )

        # RESULTS_ATTEMPT_AGAIN
        self._state_frames["RESULTS_ATTEMPT_AGAIN"] = self._create_fast_frame(
            "RESULTS_ATTEMPT_AGAIN",
            {
                "header_clear": (int(w * 0.50), int(h * 0.15), 1.0),
                "button_attempt_again": (int(w * 0.65), int(h * 0.85)),
            },
        )

        # DIALOG_LIMIT_OK
        self._state_frames["DIALOG_LIMIT_OK"] = self._create_fast_frame(
            "DIALOG_LIMIT_OK",
            {"button_ok": (int(w * 0.50), int(h * 0.55), 1.0)},
        )

    def get_frame_for_state(self, state: GameState | str) -> np.ndarray:
        """Returns a synthetic frame matching the requested GameState or scenario label."""
        if state in self._state_frames:
            return self._state_frames[state].copy()
        w, h = self.screen_size
        return np.zeros((h, w, 3), dtype=np.uint8)

    def set_custom_frame(self, state: GameState | str, frame: np.ndarray) -> None:
        """Allows overriding or registering custom synthetic frames."""
        self._state_frames[state] = frame  # type: ignore[assignment]

    def register_state_sequence(self, sequence: list[GameState | str]) -> None:
        """Registers an ordered sequence of screen states for the task to consume."""
        frames = [self.get_frame_for_state(st) for st in sequence]
        self.adb.queue_frames(frames)

    def set_initial_state(self, state: GameState | str) -> None:
        """Sets the active screen frame immediately."""
        self.adb.set_current_frame(self.get_frame_for_state(state))

    def on_status_handler(self, message: str) -> None:
        """Captures task status log messages."""
        self.status_logs.append(message)

    def create_default_config(self) -> dict[str, Any]:
        """Returns standard bot config for fast in-memory execution."""
        return {
            "bot": {
                "loop_delay": 0.0,
            },
            "farming": {
                "stamina_refill_mode": "none",
                "friend_refresh_coords": [0.82, 0.18],
            },
            "link_leveling": {
                "auto_swap_maxed_units": False,
                "rebuild_team_every_run": False,
                "use_attempt_again": True,
                "preferred_difficulty": "super",
                "target_stage": "event",
            },
        }

    def run_task_until_complete(
        self,
        task: BaseTask,
    ) -> None:
        """Executes the task loop under the VirtualClock harness until stopped or target reached."""
        self._current_task = task
        with self.clock:
            task.run()

    def stop_current_task(self) -> None:
        """Signals stop event to the active task."""
        if self._current_task:
            self._current_task.stop()
