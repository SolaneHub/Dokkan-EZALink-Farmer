import time
import threading
import numpy as np
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

    def dismiss_results_and_popups(
        self,
        screen_w: int,
        screen_h: int,
        meta: Dict[str, Any],
        prefer_again: bool = False
    ):
        """
        Taps to dismiss result screens, rank up, rewards, or OK popups.
        If prefer_again is True and 'Attempt Again' button is available on final results screen,
        taps 'Attempt Again' to restart the stage directly via team management.
        """
        if "dont_send_button" in meta:
            x, y = meta["dont_send_button"]
            self.log(t("tasks.base.friend_request_rejected", x=x, y=y))
            self.adb.tap(x, y, delay_after=1.2)
            return

        if "close_button" in meta:
            x, y = meta["close_button"]
            self.log(t("tasks.base.close_clicked", x=x, y=y))
            self.adb.tap(x, y, delay_after=1.5)
            return

        screen = self.adb.screencap()

        # Check for 'Attempt Again' on results screen if requested
        if prefer_again:
            again_pos = self.vision.find_attempt_again_button(screen)
            if again_pos:
                self.log(t("tasks.link.attempt_again_clicked", x=again_pos[0], y=again_pos[1]))
                self.adb.tap(again_pos[0], again_pos[1], delay_after=2.0)
                return

        if "ok_button" in meta:
            x, y = meta["ok_button"]
            self.log(t("tasks.base.ok_clicked", x=x, y=y))
            self.adb.tap(int(screen_w * 0.50), int(screen_h * 0.50), delay_after=0.2)
            self.adb.tap(x, y, delay_after=1.5)
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
                self.adb.tap(*meta["cancel_button"], delay_after=1.5)
            else:
                self.adb.tap(int(screen_w * 0.50), int(screen_h * 0.785), delay_after=1.5)
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

    def ensure_stage_auto_controls(self, screen: np.ndarray, screen_w: int, screen_h: int) -> bool:
        """
        Always verifies that Auto Map and Auto Battle are active whenever they appear in stage.
        If either appears and is currently OFF (grey), taps it to activate.
        Returns True if an inactive auto toggle was pressed, False otherwise.
        """
        map_off = self.vision.find_auto_map_off(screen)
        if map_off:
            self.log(t("tasks.base.enabling_auto_map", x=map_off[0], y=map_off[1]))
            self.adb.tap(map_off[0], map_off[1], delay_after=0.5)
            return True

        battle_off = self.vision.find_auto_battle_off(screen)
        if battle_off:
            self.log(t("tasks.base.enabling_auto_battle", x=battle_off[0], y=battle_off[1]))
            self.adb.tap(battle_off[0], battle_off[1], delay_after=0.5)
            return True

        return False

    def handle_battle(self, screen_w: int, screen_h: int, meta: Dict[str, Any]):
        """Ensures Auto-Battle and Auto-Map are enabled, advances dialogue/animations, or attacks manually."""
        if "back_green_button" in meta:
            # If a character details sheet was opened, tap the green 3-arrows button at bottom left to close it
            self.adb.tap(*meta["back_green_button"], delay_after=0.6)
            return

        screen = self.adb.screencap()
        if self.ensure_stage_auto_controls(screen, screen_w, screen_h):
            return

        # If auto controls are not present (e.g. first time entering stage)
        if not self.vision.has_auto_controls(screen):
            self.log(t("tasks.base.auto_controls_not_present"))
            # Tap Ki spheres in center to perform attack manually
            self.adb.tap(int(screen_w * 0.50), int(screen_h * 0.52), delay_after=0.8)
        else:
            # Tap the upper middle sky area to clear Dokkan mode target or dialogue safely without clicking characters
            self.adb.tap(int(screen_w * 0.50), int(screen_h * 0.35), delay_after=0.8)

    def handle_map(self, screen_w: int, screen_h: int, meta: Dict[str, Any]):
        """Ensures Auto-Map and Auto-Battle are enabled, or advances manually if auto controls are not present."""
        screen = self.adb.screencap()
        if self.ensure_stage_auto_controls(screen, screen_w, screen_h):
            return

        # Advance along the map path: tap center dice button (~50% X, ~80% Y)
        # to ensure movement if auto map is not present or paused at a STOP space
        self.adb.tap(int(screen_w * 0.50), int(screen_h * 0.80), delay_after=1.2)

    def navigate_to_zbattle_list(self, max_steps: int = 15) -> bool:
        """
        Universally navigates to the Z-Battle event list screen from any game screen:
        1. If already on Z_BATTLE_LIST -> done!
        2. If on EVENT_SELECT -> taps Z-Battle tab.
        3. If on MODE_SELECT -> taps Event button.
        4. If on HOME_SCREEN -> taps START button.
        5. If on TITLE_SCREEN -> taps to start.
        6. If on RESULTS_SCREEN -> taps to skip and confirms OK.
        7. If on FRIEND_REQUEST -> rejects or dismisses friend popup.
        8. If popups (Close, OK, Cancel) -> dismisses them.
        9. Anywhere else (EZA screen, Team, Box, Shop, etc.) -> taps bottom bar HOME icon to reset to Home.
        """
        self.log(t("tasks.nav.navigating_to_zbattle"))

        for step in range(1, max_steps + 1):
            if self._stop_event.is_set():
                return False

            try:
                screen = self.adb.screencap()
            except Exception as e:
                self.log(f"Screencap error during navigation: {e}")
                self.wait_check(1.5)
                continue

            h, w = screen.shape[:2]
            state, meta = self.detector.detect(screen)

            if state == GameState.Z_BATTLE_LIST:
                self.log(t("tasks.nav.zbattle_list_reached"))
                return True

            elif state == GameState.EVENT_SELECT:
                self.log(t("tasks.nav.event_select"))
                if "zbattle_tab" in meta:
                    self.adb.tap(*meta["zbattle_tab"], delay_after=2.0)
                else:
                    self.adb.tap(int(w * 0.83), int(h * 0.21), delay_after=2.0)

            elif state == GameState.MODE_SELECT:
                self.log(t("tasks.nav.mode_select"))
                if "event_button" in meta:
                    self.adb.tap(*meta["event_button"], delay_after=2.5)
                else:
                    self.adb.tap(int(w * 0.50), int(h * 0.32), delay_after=2.5)

            elif state == GameState.HOME_SCREEN:
                self.log(t("tasks.nav.home_screen"))
                if "start_button" in meta:
                    self.adb.tap(*meta["start_button"], delay_after=2.0)
                else:
                    self.adb.tap(int(w * 0.50), int(h * 0.64), delay_after=2.0)

            elif state == GameState.TITLE_SCREEN:
                self.log(t("tasks.nav.title_tap"))
                if "touch_start" in meta:
                    self.adb.tap(*meta["touch_start"], delay_after=3.0)
                else:
                    self.adb.tap(int(w * 0.50), int(h * 0.70), delay_after=3.0)

            elif state == GameState.RESULTS_SCREEN:
                self.log(t("tasks.eza.results_ok"))
                self.adb.tap(int(w * 0.50), int(h * 0.50), delay_after=0.3)
                if "ok_button" in meta:
                    self.adb.tap(*meta["ok_button"], delay_after=1.5)
                else:
                    self.adb.tap(int(w * 0.50), int(h * 0.85), delay_after=1.5)

            elif state == GameState.FRIEND_REQUEST:
                self.dismiss_results_and_popups(w, h, meta)

            elif "dont_send_button" in meta:
                self.log(t("tasks.base.friend_request_rejected", x=meta["dont_send_button"][0], y=meta["dont_send_button"][1]))
                self.adb.tap(*meta["dont_send_button"], delay_after=1.5)

            elif "close_button" in meta:
                self.log(t("tasks.nav.dismiss_close"))
                self.adb.tap(*meta["close_button"], delay_after=1.5)

            elif "ok_button" in meta:
                self.log(t("tasks.nav.dismiss_ok"))
                self.adb.tap(int(w * 0.50), int(h * 0.50), delay_after=0.2)
                self.adb.tap(*meta["ok_button"], delay_after=1.5)

            elif "cancel_button" in meta:
                self.log(t("tasks.nav.dismiss_cancel"))
                self.adb.tap(*meta["cancel_button"], delay_after=1.5)

            else:
                # Any other screen: tap bottom bar HOME button
                home_x = int(w * 0.095)
                home_y = int(h * 0.854)
                self.log(t("tasks.nav.reset_to_home", x=home_x, y=home_y))
                self.adb.tap(home_x, home_y, delay_after=2.5)

            self.wait_check(1.0)

        self.log(t("tasks.nav.nav_failed"))
        return False

