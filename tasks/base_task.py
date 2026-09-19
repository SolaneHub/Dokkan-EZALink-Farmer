import time
import threading
from typing import Callable, Optional, Dict, Any
from core.adb_client import ADBClient
from core.vision import Vision
from core.game_state import GameState, StateDetector


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
        self._pause_event.set() # Unpaused by default

        self.runs_completed = 0
        self.runs_target = 0
        self.current_state = GameState.UNKNOWN
        self.is_running = False

    def log(self, message: str):
        self.on_status(message)

    def stop(self):
        """Requests the task to stop."""
        self._stop_event.set()
        self._pause_event.set()
        self.is_running = False
        self.log("Arresto attività richiesto...")

    def pause(self):
        """Pauses the task loop."""
        self._pause_event.clear()
        self.log("Attività in pausa.")

    def resume(self):
        """Resumes the task loop."""
        self._pause_event.set()
        self.log("Attività ripresa.")

    def is_stopped(self) -> bool:
        return self._stop_event.is_set()

    def wait_check(self, seconds: float):
        """Waits for specified seconds while respecting stop and pause events."""
        start = time.time()
        while time.time() - start < seconds:
            if self._stop_event.is_set():
                return
            self._pause_event.wait()
            time.sleep(0.1)

    def tap_friend_first(self, screen_w: int, screen_h: int):
        """Selects the first friend in the friend list."""
        # Top friend leader card is located around 50% X, 32% Y on typical 16:9/20:9 layouts
        tap_x = int(screen_w * 0.50)
        tap_y = int(screen_h * 0.32)
        self.log(f"Selezione Friend Leader (#1 a {tap_x}, {tap_y})...")
        self.adb.tap(tap_x, tap_y, delay_after=1.5)

    def tap_start_team(self, screen_w: int, screen_h: int, meta: Dict[str, Any]):
        """Taps the START button on the team preview screen."""
        if "start_button" in meta:
            x, y = meta["start_button"]
        else:
            # Fallback coordinate for START button: bottom right (~75% X, ~88% Y)
            x, y = int(screen_w * 0.75), int(screen_h * 0.88)
        self.log(f"Avvio missione (START a {x}, {y})...")
        self.adb.tap(x, y, delay_after=2.0)

    def dismiss_results_and_popups(self, screen_w: int, screen_h: int, meta: Dict[str, Any]):
        """Taps to dismiss result screens, rank up, rewards, or OK popups."""
        if "ok_button" in meta:
            x, y = meta["ok_button"]
            self.log(f"Click su OK a {x}, {y}...")
            self.adb.tap(x, y, delay_after=1.5)
        elif "dont_send_button" in meta:
            x, y = meta["dont_send_button"]
            self.log(f"Rifiuto richiesta amicizia a {x}, {y}...")
            self.adb.tap(x, y, delay_after=1.2)
        else:
            # Fallback: tap center/bottom to skip clear animations
            center_x, center_y = int(screen_w * 0.50), int(screen_h * 0.82)
            self.log(f"Avanzamento schermata risultati a {center_x}, {center_y}...")
            self.adb.tap(center_x, center_y, delay_after=1.0)

    def handle_stamina_refill(self, screen_w: int, screen_h: int, meta: Dict[str, Any]) -> bool:
        """Handles stamina empty prompt based on settings. Returns True if handled, False to abort."""
        mode = self.config.get("farming", {}).get("stamina_refill_mode", "none")
        if mode == "none":
            self.log("Stamina esaurita! Modalità refill disattivata. Fermo il bot.")
            # Click cancel
            if "cancel_button" in meta:
                self.adb.tap(*meta["cancel_button"])
            else:
                self.adb.tap(int(screen_w * 0.28), int(screen_h * 0.65))
            return False

        if mode == "meat":
            self.log("Stamina esaurita: utilizzo Aged Meat...")
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
        # Top-right corner has Auto and 2x speed buttons
        # In Dokkan, Auto button is located around 85% X, 6% Y or 85% X, 12% Y depending on aspect
        # If auto is off, tap it. If templates not found, ensure auto is active by tapping known spot
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
