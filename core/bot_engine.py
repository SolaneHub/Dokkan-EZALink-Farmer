import os
import yaml
import threading
from typing import Dict, Any, Optional, Callable, List
import numpy as np
import cv2

from core.adb_client import ADBClient
from core.vision import Vision
from core.game_state import StateDetector, GameState
from tasks.base_task import BaseTask
from tasks.stage_farm import StageFarmTask
from tasks.eza_farm import EZAFarmTask
from tasks.link_level_farm import LinkLevelFarmTask


class BotEngine:
    """Central coordinator for Dokkan Battle automation."""

    def __init__(self, config_path: str = "config/settings.yaml"):
        self.config_path = config_path
        self.config = self.load_config()
        self.adb = ADBClient(
            serial=self.config.get("device", {}).get("serial") or None,
            adb_path=self.config.get("device", {}).get("adb_path", "adb")
        )
        self.vision = Vision(
            template_dir=self.config.get("vision", {}).get("template_dir", "templates/glb"),
            default_threshold=self.config.get("vision", {}).get("confidence_threshold", 0.78)
        )
        self.detector = StateDetector(self.vision)
        self.current_task: Optional[BaseTask] = None
        self._task_thread: Optional[threading.Thread] = None

        self.log_callbacks: List[Callable[[str], None]] = []
        self.run_callbacks: List[Callable[[int, int], None]] = []

    def load_config(self) -> Dict[str, Any]:
        if os.path.exists(self.config_path):
            with open(self.config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}

    def save_config(self):
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(self.config, f)

    def register_log_callback(self, cb: Callable[[str], None]):
        self.log_callbacks.append(cb)

    def register_run_callback(self, cb: Callable[[int, int], None]):
        self.run_callbacks.append(cb)

    def emit_log(self, msg: str):
        for cb in self.log_callbacks:
            try:
                cb(msg)
            except Exception:
                pass

    def emit_run(self, curr: int, tot: int):
        for cb in self.run_callbacks:
            try:
                cb(curr, tot)
            except Exception:
                pass

    def connect(self, serial: Optional[str] = None) -> str:
        """Connects to a specific device or auto-detects."""
        if serial:
            self.adb.serial = serial
            self.adb.get_screen_size(force_refresh=True)
            active_serial = serial
        else:
            active_serial = self.adb.auto_connect()
        self.emit_log(f"Dispositivo connesso: {active_serial} (Risoluzione: {self.adb.get_screen_size()})")
        return active_serial

    def list_devices(self) -> List[dict]:
        return self.adb.list_devices()

    def start_scrcpy(self) -> bool:
        """Launches scrcpy mirror window."""
        scrcpy_path = self.config.get("device", {}).get("scrcpy_path", "scrcpy")
        ok = self.adb.start_scrcpy(scrcpy_path=scrcpy_path)
        if ok:
            self.emit_log("Finestra di mirroring scrcpy avviata con successo.")
        else:
            self.emit_log("Errore nell'avvio di scrcpy. Verifica che sia installato nel PATH.")
        return ok

    def stop_scrcpy(self):
        self.adb.stop_scrcpy()
        self.emit_log("Finestra scrcpy chiusa.")

    def get_screenshot(self) -> np.ndarray:
        return self.adb.screencap()

    def save_screenshot_to_file(self, output_path: str) -> str:
        img = self.get_screenshot()
        cv2.imwrite(output_path, img)
        return output_path

    def inspect_current_state(self) -> GameState:
        screen = self.get_screenshot()
        state, _ = self.detector.detect(screen)
        return state

    def start_stage_farm(self, runs: int = 10) -> bool:
        """Starts stage farm task."""
        if self.is_task_running():
            self.emit_log("Un'attività è già in esecuzione! Ferma l'attività corrente prima.")
            return False

        self.current_task = StageFarmTask(
            self.adb,
            self.vision,
            self.config,
            runs=runs,
            on_status=self.emit_log,
            on_run_complete=self.emit_run
        )
        self._start_task_thread()
        return True

    def start_eza_farm(self, target_level: int = 30) -> bool:
        """Starts EZA farm task."""
        if self.is_task_running():
            self.emit_log("Un'attività è già in esecuzione! Ferma l'attività corrente prima.")
            return False

        self.current_task = EZAFarmTask(
            self.adb,
            self.vision,
            self.config,
            target_level=target_level,
            on_status=self.emit_log,
            on_run_complete=self.emit_run
        )
        self._start_task_thread()
        return True

    def start_link_level_farm(self, runs: int = 20) -> bool:
        """Starts Link Level farm task."""
        if self.is_task_running():
            self.emit_log("Un'attività è già in esecuzione! Ferma l'attività corrente prima.")
            return False

        self.current_task = LinkLevelFarmTask(
            self.adb,
            self.vision,
            self.config,
            runs=runs,
            on_status=self.emit_log,
            on_run_complete=self.emit_run
        )
        self._start_task_thread()
        return True

    def stop_task(self):
        if self.current_task and self.current_task.is_running:
            self.current_task.stop()
            self.emit_log("Fermando l'attività...")
        else:
            self.emit_log("Nessuna attività in corso.")

    def pause_task(self):
        if self.current_task and self.current_task.is_running:
            self.current_task.pause()

    def resume_task(self):
        if self.current_task and self.current_task.is_running:
            self.current_task.resume()

    def is_task_running(self) -> bool:
        return self.current_task is not None and self.current_task.is_running

    def get_status_summary(self) -> Dict[str, Any]:
        running = self.is_task_running()
        return {
            "device_serial": self.adb.serial,
            "task_running": running,
            "task_type": type(self.current_task).__name__ if running else "Nessuna",
            "runs_completed": self.current_task.runs_completed if self.current_task else 0,
            "runs_target": self.current_task.runs_target if self.current_task else 0,
            "current_state": self.current_task.current_state.value if self.current_task else "IDLE"
        }

    def _start_task_thread(self):
        self._task_thread = threading.Thread(target=self.current_task.run, daemon=True)
        self._task_thread.start()
