import contextlib
import os
import sys
import threading
from collections.abc import Callable
from typing import Any

import cv2
import numpy as np
import yaml

from dokkan_eza_link_farmer.ai import AIConfig, DokkanAIClient, TeamBuilder
from dokkan_eza_link_farmer.automation.game_state import GameState, StateDetector
from dokkan_eza_link_farmer.automation.tasks.base_task import BaseTask
from dokkan_eza_link_farmer.automation.tasks.box_scanner import BoxScannerTask
from dokkan_eza_link_farmer.automation.tasks.challenge_task import ChallengeTask
from dokkan_eza_link_farmer.automation.tasks.eza_farm import EZAFarmTask
from dokkan_eza_link_farmer.automation.tasks.link_level_farm import LinkLevelFarmTask
from dokkan_eza_link_farmer.automation.tasks.stage_farm import StageFarmTask
from dokkan_eza_link_farmer.automation.vision import Vision
from dokkan_eza_link_farmer.core.i18n import set_language, t
from dokkan_eza_link_farmer.core.system_tools import ToolLocator, get_config_path
from dokkan_eza_link_farmer.integrations.adb_client import ADBClient
from dokkan_eza_link_farmer.integrations.dokkandb_client import DokkanDBClient


class BotEngine:
    """Central coordinator for Dokkan Battle automation."""

    def __init__(self, config_path: str = "config/settings.yaml"):
        self.config_path = get_config_path(config_path)
        self.config = self.load_config()

        # Initialize UI language from configuration
        set_language(self.config.get("language", "en"))

        self.adb = ADBClient(
            serial=self.config.get("device", {}).get("serial") or None,
            adb_path=self.config.get("device", {}).get("adb_path", "adb"),
        )
        self.vision = Vision(
            template_dir=self.config.get("vision", {}).get("template_dir", "templates/glb"),
            default_threshold=self.config.get("vision", {}).get("confidence_threshold", 0.78),
        )
        self.detector = StateDetector(self.vision)
        self.dokkandb = DokkanDBClient()

        # Initialize AI components (Qwen / DeepSeek-R1)
        self.ai_config = AIConfig.from_dict(
            self.config.get("ai_teambuilder") or self.config.get("ai")
        )
        self.ai_client = DokkanAIClient(self.ai_config)
        self.team_builder = TeamBuilder(dokkandb=self.dokkandb, ai_client=self.ai_client)

        self.current_task: BaseTask | None = None
        self._task_thread: threading.Thread | None = None

        self.log_callbacks: list[Callable[[str], None]] = []
        self.run_callbacks: list[Callable[[int, int], None]] = []

    def load_config(self) -> dict[str, Any]:
        """Loads configuration from YAML file."""
        if os.path.exists(self.config_path):
            with open(self.config_path, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}

    def save_config(self):
        """Saves current configuration to YAML file, ensuring directory exists."""
        target_path = self.config_path
        meipass = getattr(sys, "_MEIPASS", None)
        if getattr(sys, "frozen", False) and meipass and str(meipass) in target_path:
            exe_dir = os.path.dirname(sys.executable)
            target_path = os.path.join(exe_dir, "config", "settings.yaml")
            self.config_path = target_path

        os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as f:
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
            with contextlib.suppress(Exception):
                cb(msg)

    def emit_run(self, curr: int, tot: int):
        """Dispatches run progress to all registered listeners."""
        for cb in self.run_callbacks:
            with contextlib.suppress(Exception):
                cb(curr, tot)

    def connect(self, serial: str | None = None) -> str:
        """Connects to a specific Android device or auto-detects first available."""
        if serial:
            self.adb.serial = serial
            self.adb.get_screen_size(force_refresh=True)
            active_serial = serial
        else:
            active_serial = self.adb.auto_connect()
        self.emit_log(
            t("tasks.device_connected", serial=active_serial, res=str(self.adb.get_screen_size()))
        )
        return active_serial

    def list_devices(self) -> list[dict[str, Any]]:
        """Queries ADB for connected devices."""
        return self.adb.list_devices()

    def diagnose_environment(self) -> dict[str, Any]:
        """Runs complete system check for Python, ADB, scrcpy, and connected devices."""
        configured_adb = self.config.get("device", {}).get("adb_path")
        configured_scrcpy = self.config.get("device", {}).get("scrcpy_path")
        report = ToolLocator.diagnose_system(
            configured_adb=configured_adb, configured_scrcpy=configured_scrcpy
        )
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
        self, target_level: int = 999, target_eza: dict[str, Any] | None = None
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
            on_run_complete=self.emit_run,
        )
        self._start_task_thread()
        return True

    def start_link_level_farm(
        self,
        runs: int | None = None,
        target_event: dict[str, Any] | None = None,
        use_boost: bool | None = None,
        filter_ur: bool = False,
        filter_lr: bool = False,
        target_stage: str | None = None,
        stage_name: str | None = None,
    ) -> bool:
        """Starts Link Level farming with stage selection, rarity filtering, and auto-swap."""
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
            filter_ur=filter_ur,
            filter_lr=filter_lr,
            target_stage=target_stage,
            stage_name=stage_name,
            on_status=self.emit_log,
            on_run_complete=self.emit_run,
        )
        self._start_task_thread()
        return True

    def start_stage_farm(
        self,
        runs: int | None = None,
        use_boost: bool | None = None,
        preferred_difficulty: str | None = None,
    ) -> bool:
        """Starts repeated clearing of currently selected stage until stamina runs out."""
        if self.is_task_running():
            self.emit_log(t("tasks.task_already_running"))
            return False

        self.current_task = StageFarmTask(
            self.adb,
            self.vision,
            self.config,
            runs=runs,
            use_boost=use_boost,
            preferred_difficulty=preferred_difficulty,
            on_status=self.emit_log,
            on_run_complete=self.emit_run,
        )
        self._start_task_thread()
        return True

    def start_challenge_farm(
        self,
        target_event: dict[str, Any],
        stage_num: int = 1,
        stage_id: int | None = None,
        stage_name: str | None = None,
        max_retries_per_batch: int = 5,
    ) -> bool:
        """Starts autonomous Challenge & Mission solver task."""
        if self.is_task_running():
            self.emit_log(t("tasks.task_already_running"))
            return False

        self.current_task = ChallengeTask(
            self.adb,
            self.vision,
            self.config,
            dokkandb=self.dokkandb,
            ai_client=self.ai_client,
            target_event=target_event,
            stage_num=stage_num,
            stage_id=stage_id,
            stage_name=stage_name,
            max_retries_per_batch=max_retries_per_batch,
            on_status=self.emit_log,
            on_run_complete=self.emit_run,
        )
        self._start_task_thread()
        return True

    def start_box_scanner(
        self,
        output_file: str | None = None,
        max_cards_to_scan: int | None = None,
    ) -> bool:
        """Starts autonomous Character Box scanner with DokkanDB enrichment."""
        if self.is_task_running():
            self.emit_log(t("tasks.task_already_running"))
            return False

        from dokkan_eza_link_farmer.automation.tasks.box_scanner import DEFAULT_USER_BOX_PATH

        target_out = output_file if output_file is not None else DEFAULT_USER_BOX_PATH
        self.current_task = BoxScannerTask(
            self.adb,
            self.vision,
            self.config,
            dokkandb=self.dokkandb,
            output_file=target_out,
            max_cards_to_scan=max_cards_to_scan,
            on_status=self.emit_log,
            on_run_complete=self.emit_run,
        )
        self._start_task_thread()
        return True

    def start_ai_endgame(
        self,
        stage_identifier: int | str | Any = 10101,
        max_attempts: int | None = None,
        dry_run: bool = False,
        force_solve: bool = False,
        mission_batch: Any | None = None,
    ) -> bool:
        """Starts autonomous AI Endgame Trial & Error runner task in background."""
        if self.is_task_running():
            self.emit_log(t("tasks.task_already_running"))
            return False

        from dokkan_eza_link_farmer.ai.boss_catalog import get_boss_stage
        from dokkan_eza_link_farmer.ai.endgame_runner import EndgameRunner
        from dokkan_eza_link_farmer.ai.models import BossStage

        try:
            target_stage = (
                stage_identifier
                if isinstance(stage_identifier, BossStage)
                else get_boss_stage(stage_identifier, dokkandb=self.dokkandb)
            )
        except Exception as e:
            self.emit_log(f"Stage '{stage_identifier}' not found in catalog: {e}")
            return False

        attempts = (
            max_attempts
            or self.config.get("ai_teambuilder", {}).get("max_attempts")
            or getattr(self.ai_config, "max_attempts", 10)
        )
        runner = EndgameRunner(
            adb=self.adb,
            vision=self.vision,
            detector=self.detector,
            dokkandb=self.dokkandb,
            ai_client=self.ai_client,
            team_builder=self.team_builder,
            boss_stage=target_stage,
            max_attempts=attempts,
            dry_run=dry_run,
            force_solve=force_solve,
            mission_batch=mission_batch,
            on_status=self.emit_log,
            on_run_complete=self.emit_run,
        )

        class EndgameRunnerTask(BaseTask):
            def __init__(self, r: EndgameRunner, eng: BotEngine):
                super().__init__(eng.adb, eng.vision, eng.config, eng.emit_log, eng.emit_run)
                self.runner = r

            def run(self):
                self.is_running = True
                try:
                    self.runner.run()
                finally:
                    self.is_running = False

            def stop(self):
                self.runner.stop()
                super().stop()

        self.current_task = EndgameRunnerTask(runner, self)
        self._start_task_thread()
        return True

    def run_ai_endgame_sync(
        self,
        stage_identifier: int | str | Any = 10101,
        max_attempts: int | None = None,
        dry_run: bool = False,
        force_solve: bool = False,
        mission_batch: Any | None = None,
    ) -> Any:
        """Runs AI Endgame Trial & Error synchronously (for direct CLI execution)."""
        from dokkan_eza_link_farmer.ai.boss_catalog import get_boss_stage
        from dokkan_eza_link_farmer.ai.endgame_runner import EndgameRunner
        from dokkan_eza_link_farmer.ai.models import BossStage

        target_stage = (
            stage_identifier
            if isinstance(stage_identifier, BossStage)
            else get_boss_stage(stage_identifier, dokkandb=self.dokkandb)
        )
        attempts = (
            max_attempts
            or self.config.get("ai_teambuilder", {}).get("max_attempts")
            or getattr(self.ai_config, "max_attempts", 10)
        )
        runner = EndgameRunner(
            adb=self.adb,
            vision=self.vision,
            detector=self.detector,
            dokkandb=self.dokkandb,
            ai_client=self.ai_client,
            team_builder=self.team_builder,
            boss_stage=target_stage,
            max_attempts=attempts,
            dry_run=dry_run,
            force_solve=force_solve,
            mission_batch=mission_batch,
            on_status=self.emit_log,
            on_run_complete=self.emit_run,
        )
        return runner.run()

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

    def get_status_summary(self) -> dict[str, Any]:
        """Provides status dictionary for UI and Discord reporting."""
        running = self.is_task_running()
        return {
            "device_serial": self.adb.serial,
            "task_running": running,
            "task_type": type(self.current_task).__name__ if running else t("cli.status.none"),
            "runs_completed": self.current_task.runs_completed if self.current_task else 0,
            "runs_target": getattr(self.current_task, "runs_target", None)
            if self.current_task
            else 0,
            "current_state": self.current_task.current_state.value if self.current_task else "IDLE",
        }

    def _start_task_thread(self):
        """Spawns daemon thread for running task loop."""
        if self.current_task is not None:
            self._task_thread = threading.Thread(target=self.current_task.run, daemon=True)
            self._task_thread.start()
