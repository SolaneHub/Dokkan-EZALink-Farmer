import os
import yaml
import threading
from typing import Dict, Any, Optional, Callable, List
import numpy as np
import cv2

from core.adb_client import ADBClient
from core.vision import Vision
from core.game_state import StateDetector, GameState
from core.system_tools import get_config_path, ToolLocator
from core.i18n import t, set_language
from core.dokkandb_client import DokkanDBClient
from tasks.base_task import BaseTask
from tasks.eza_farm import EZAFarmTask
from tasks.link_level_farm import LinkLevelFarmTask


class BotEngine:
    """Central coordinator for Dokkan Battle automation."""

    def __init__(self, config_path: str = "config/settings.yaml"):
        self.config_path = get_config_path(config_path)
        self.config = self.load_config()
        
        # Initialize UI language from configuration
        set_language(self.config.get("language", "en"))

        self.adb = ADBClient(
            serial=self.config.get("device", {}).get("serial") or None,
            adb_path=self.config.get("device", {}).get("adb_path", "adb")
        )
        self.vision = Vision(
            template_dir=self.config.get("vision", {}).get("template_dir", "templates/glb"),
            default_threshold=self.config.get("vision", {}).get("confidence_threshold", 0.78)
        )
        self.detector = StateDetector(self.vision)
        self.dokkandb = DokkanDBClient()
        self.current_task: Optional[BaseTask] = None
        self._task_thread: Optional[threading.Thread] = None

        self.log_callbacks: List[Callable[[str], None]] = []
        self.run_callbacks: List[Callable[[int, int], None]] = []

    def load_config(self) -> Dict[str, Any]:
        """Loads configuration from YAML file."""
        if os.path.exists(self.config_path):
            with open(self.config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}

    def save_config(self):
        """Saves current configuration to YAML file."""
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(self.config, f)

    def register_log_callback(self, cb: Callable[[str], None]):
        """Registers a callback for text log messages."""
        self.log_callbacks.append(cb)

    def register_run_callback(self, cb: Callable[[int, int], None]):
        """Registers a callback for run completion counters."""
        self.run_callbacks.append(cb)

    def emit_log(self, msg: str):
        """Dispatches log message to all registered listeners."""
        for cb in self.log_callbacks:
            try:
                cb(msg)
            except Exception:
                pass

    def emit_run(self, curr: int, tot: int):
        """Dispatches run progress to all registered listeners."""
        for cb in self.run_callbacks:
            try:
                cb(curr, tot)
            except Exception:
                pass

    def connect(self, serial: Optional[str] = None) -> str:
        """Connects to a specific Android device or auto-detects first available."""
        if serial:
            self.adb.serial = serial
            self.adb.get_screen_size(force_refresh=True)
            active_serial = serial
        else:
            active_serial = self.adb.auto_connect()
        self.emit_log(t("tasks.device_connected", serial=active_serial, res=str(self.adb.get_screen_size())))
        return active_serial

    def list_devices(self) -> List[dict]:
        """Queries ADB for connected devices."""
        return self.adb.list_devices()

    def diagnose_environment(self) -> Dict[str, Any]:
        """Runs complete system check for Python, ADB, scrcpy, and connected devices."""
        configured_adb = self.config.get("device", {}).get("adb_path")
        configured_scrcpy = self.config.get("device", {}).get("scrcpy_path")
        report = ToolLocator.diagnose_system(configured_adb=configured_adb, configured_scrcpy=configured_scrcpy)
        try:
            report["devices"] = self.list_devices()
        except Exception as e:
            report["devices"] = []
            report["device_error"] = str(e)
        return report

    def start_scrcpy(self) -> bool:
        """Launches scrcpy mirror window."""
        scrcpy_path = self.config.get("device", {}).get("scrcpy_path", "scrcpy")
        ok = self.adb.start_scrcpy(scrcpy_path=scrcpy_path)
        if ok:
            self.emit_log(t("tasks.scrcpy_started"))
        else:
            self.emit_log(t("tasks.scrcpy_failed"))
        return ok

    def stop_scrcpy(self):
        """Terminates scrcpy mirror process."""
        self.adb.stop_scrcpy()
        self.emit_log(t("tasks.scrcpy_stopped"))

    def get_screenshot(self) -> np.ndarray:
        """Captures screen as OpenCV BGR image."""
        return self.adb.screencap()

    def save_screenshot_to_file(self, output_path: str) -> str:
        """Saves current screenshot to specified file path."""
        img = self.get_screenshot()
        cv2.imwrite(output_path, img)
        return output_path

    def inspect_current_state(self) -> GameState:
        """Takes screenshot and identifies current GameState."""
        screen = self.get_screenshot()
        state, _ = self.detector.detect(screen)
        return state


    def start_eza_farm(
        self,
        target_level: int = 999,
        target_eza: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Starts EZA continuous battle climbing task."""
        if self.is_task_running():
            self.emit_log(t("tasks.task_already_running"))
            return False

        self.current_task = EZAFarmTask(
            self.adb,
            self.vision,
            self.config,
            target_level=target_level,
            target_eza=target_eza,
            on_status=self.emit_log,
            on_run_complete=self.emit_run
        )
        self._start_task_thread()
        return True

    def start_link_level_farm(
        self,
        runs: Optional[int] = None,
        target_event: Optional[Dict[str, Any]] = None,
        use_boost: Optional[bool] = None
    ) -> bool:
        """Starts Link Level farming with DokkanDB event integration and auto-swap."""
        if self.is_task_running():
            self.emit_log(t("tasks.task_already_running"))
            return False

        self.current_task = LinkLevelFarmTask(
            self.adb,
            self.vision,
            self.config,
            runs=runs,
            target_event=target_event,
            dokkandb=self.dokkandb,
            use_boost=use_boost,
            on_status=self.emit_log,
            on_run_complete=self.emit_run
        )
        self._start_task_thread()
        return True

    def stop_task(self):
        """Stops active automation task."""
        if self.current_task and self.current_task.is_running:
            self.current_task.stop()
            self.emit_log(t("tasks.stopping_task"))
        else:
            self.emit_log(t("tasks.no_task_running"))

    def pause_task(self):
        """Pauses active automation task."""
        if self.current_task and self.current_task.is_running:
            self.current_task.pause()
            self.emit_log(t("tasks.task_paused"))

    def resume_task(self):
        """Resumes paused automation task."""
        if self.current_task and self.current_task.is_running:
            self.current_task.resume()
            self.emit_log(t("tasks.task_resumed"))

    def is_task_running(self) -> bool:
        """Returns True if a task is currently executing."""
        return self.current_task is not None and self.current_task.is_running

    def get_status_summary(self) -> Dict[str, Any]:
        """Provides status dictionary for UI and Discord reporting."""
        running = self.is_task_running()
        return {
            "device_serial": self.adb.serial,
            "task_running": running,
            "task_type": type(self.current_task).__name__ if running else t("cli.status.none"),
            "runs_completed": self.current_task.runs_completed if self.current_task else 0,
            "runs_target": getattr(self.current_task, "runs_target", None) if self.current_task else 0,
            "current_state": self.current_task.current_state.value if self.current_task else "IDLE"
        }

    def _start_task_thread(self):
        """Spawns daemon thread for running task loop."""
        self._task_thread = threading.Thread(target=self.current_task.run, daemon=True)
        self._task_thread.start()
