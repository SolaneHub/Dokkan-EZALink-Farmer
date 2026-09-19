import time
import threading
from typing import Callable, Optional, Dict, Any
from core.adb_client import ADBClient
from core.vision import Vision
from core.game_state import GameState, StateDetector
from core.i18n import t


class BaseTask:
    """Base class for all Dokkan Battle automation tasks."""

    def __init__(
        self,
        adb: ADBClient,
        vision: Vision,
        config: Dict[str, Any],
        on_status: Optional[Callable[[str], None]] = None,
        on_run_complete: Optional[Callable[[int, int], None]] = None
    ):
        self.adb = adb
        self.vision = vision
        self.config = config
        self.detector = StateDetector(vision)
        self.on_status = on_status or (lambda msg: None)
        self.on_run_complete = on_run_complete or (lambda curr, tot: None)

        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()  # Unpaused by default

        self.runs_completed = 0
        self.runs_target = 0
        self.current_state = GameState.UNKNOWN
        self.is_running = False

    def log(self, message: str):
        """Emits a log message to the registered callback."""
        self.on_status(message)

    def stop(self):
        """Requests the task loop to terminate."""
        self._stop_event.set()
        self._pause_event.set()
        self.is_running = False
        self.log(t("tasks.task_stop_requested"))

    def pause(self):
        """Pauses the task loop."""
        self._pause_event.clear()
        self.log(t("tasks.task_paused"))

    def resume(self):
        """Resumes the task loop."""
        self._pause_event.set()
        self.log(t("tasks.task_resumed"))

    def is_stopped(self) -> bool:
        """Returns True if the task has been asked to stop."""
        return self._stop_event.is_set()

    def wait_check(self, seconds: float):
        """Waits for specified duration while periodically checking stop and pause events."""
        start = time.time()
        while time.time() - start < seconds:
            if self._stop_event.is_set():
                return
            self._pause_event.wait()
            time.sleep(0.1)

    def handle_friend_select(self, screen_w: int, screen_h: int, meta: Optional[Dict[str, Any]] = None):
        """
        Selects a friend supporter by tapping the 'Refresh' button,
        which automatically assigns a friend in Dokkan.
        """
        if meta and "friend_refresh_button" in meta:
            x, y = meta["friend_refresh_button"]
            self.log(t("tasks.base.friend_auto_assign", x=x, y=y))
            self.adb.tap(x, y, delay_after=2.0)
        else:
            # Fallback coordinate for Refresh button in Friend Select header
            cfg_coords = self.config.get("farming", {}).get("friend_refresh_coords", [0.82, 0.18])
            rx, ry = cfg_coords[0], cfg_coords[1]
            tap_x = int(screen_w * rx)
            tap_y = int(screen_h * ry)
            self.log(t("tasks.base.friend_auto_assign", x=tap_x, y=tap_y))
            self.adb.tap(tap_x, tap_y, delay_after=2.0)

    def tap_friend_first(self, screen_w: int, screen_h: int, meta: Optional[Dict[str, Any]] = None):
        """Backwards-compatible alias for handle_friend_select."""
        self.handle_friend_select(screen_w, screen_h, meta)

    def tap_start_team(self, screen_w: int, screen_h: int, meta: Dict[str, Any]):
        """Taps the START button on the team preview screen."""
        if "start_button" in meta:
            x, y = meta["start_button"]
        else:
            # Fallback coordinate for START button: bottom right (~75% X, ~88% Y)
            x, y = int(screen_w * 0.75), int(screen_h * 0.88)
        self.log(t("tasks.base.mission_start", x=x, y=y))
        self.adb.tap(x, y, delay_after=2.0)

    def dismiss_results_and_popups(self, screen_w: int, screen_h: int, meta: Dict[str, Any]):
        """Taps to dismiss result screens, rank up, rewards, or OK popups."""
        if "ok_button" in meta:
            x, y = meta["ok_button"]
            self.log(t("tasks.base.ok_clicked", x=x, y=y))
            self.adb.tap(x, y, delay_after=1.5)
        elif "close_button" in meta:
            x, y = meta["close_button"]
            self.log(t("tasks.base.close_clicked", x=x, y=y))
            self.adb.tap(x, y, delay_after=1.5)
        elif "dont_send_button" in meta:
            x, y = meta["dont_send_button"]
            self.log(t("tasks.base.friend_request_rejected", x=x, y=y))
            self.adb.tap(x, y, delay_after=1.2)
        else:
            # Tap center to skip counting animations, then tap OK button (50% X, 85% Y)
            ok_x = int(screen_w * 0.50)
            ok_y = int(screen_h * 0.85)
            self.log(t("tasks.base.dismiss_advancing", x=ok_x, y=ok_y))
            self.adb.tap(ok_x, int(screen_h * 0.50), delay_after=0.4)
            self.adb.tap(ok_x, ok_y, delay_after=1.2)

    def handle_stamina_refill(self, screen_w: int, screen_h: int, meta: Dict[str, Any]) -> bool:
        """Handles stamina empty prompt based on settings. Returns True if handled, False to abort."""
        mode = self.config.get("farming", {}).get("stamina_refill_mode", "none")
        if mode == "none":
            self.log(t("tasks.base.stamina_depleted_abort"))
            if "cancel_button" in meta:
                self.adb.tap(*meta["cancel_button"])
            else:
                self.adb.tap(int(screen_w * 0.28), int(screen_h * 0.65))
            return False

        if mode == "meat":
            self.log(t("tasks.base.stamina_refill_meat"))
            if "meat_button" in meta:
                self.adb.tap(*meta["meat_button"], delay_after=1.5)
            else:
                # Meat option button location
                self.adb.tap(int(screen_w * 0.50), int(screen_h * 0.52), delay_after=1.5)
            # Confirm refill
            self.adb.tap(int(screen_w * 0.50), int(screen_h * 0.65), delay_after=1.5)
            return True

        return False

    def handle_battle(self, screen_w: int, screen_h: int, meta: Dict[str, Any]):
        """Ensures Auto-Battle and 2x speed are enabled, taps screen to advance dialogue."""
        if "auto_button" in meta:
            self.adb.tap(*meta["auto_button"], delay_after=0.5)
        # Tap the lower middle area occasionally to clear Dokkan mode target or any transition
        self.adb.tap(int(screen_w * 0.50), int(screen_h * 0.78), delay_after=0.8)

    def handle_map(self, screen_w: int, screen_h: int, meta: Dict[str, Any]):
        """Ensures Auto-Map is active or taps dice."""
        if "auto_map_button" in meta:
            self.adb.tap(*meta["auto_map_button"], delay_after=0.5)
        else:
            # Tap center dice button (~50% X, ~82% Y)
            self.adb.tap(int(screen_w * 0.50), int(screen_h * 0.82), delay_after=1.2)
