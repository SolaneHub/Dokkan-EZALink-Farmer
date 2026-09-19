import time
from typing import Dict, Any, Optional, Callable
from core.adb_client import ADBClient
from core.vision import Vision
from core.game_state import GameState
from tasks.base_task import BaseTask


class StageFarmTask(BaseTask):
    """
    Automates repeated farming of a selected event or quest stage.
    User selects the stage, and the bot handles:
    - Friend selection
    - Team confirmation & START
    - Map traversal (Auto-Map)
    - Battle execution (Auto-Battle)
    - Results screen & skipping rewards animations
    - Friend requests dismissal
    - Stamina checks
    """

    def __init__(
        self,
        adb: ADBClient,
        vision: Vision,
        config: Dict[str, Any],
        runs: int = 10,
        on_status: Optional[Callable[[str], None]] = None,
        on_run_complete: Optional[Callable[[int, int], None]] = None
    ):
        super().__init__(adb, vision, config, on_status, on_run_complete)
        self.runs_target = runs

    def run(self):
        self.is_running = True
        self.runs_completed = 0
        self.log(f"Inizio farming stage: obiettivo {self.runs_target} completamenti.")

        unknown_counter = 0
        in_run = False
        loop_delay = self.config.get("bot", {}).get("loop_delay", 1.5)

        while not self._stop_event.is_set() and self.runs_completed < self.runs_target:
            self._pause_event.wait()

            # 1. Capture screen
            try:
                screen = self.adb.screencap()
            except Exception as e:
                self.log(f"Errore cattura schermo: {e}")
                self.wait_check(2.0)
                continue

            h, w = screen.shape[:2]

            # 2. Detect State
            state, meta = self.detector.detect(screen)
            self.current_state = state

            # Handle state transitions
            if state == GameState.FRIEND_SELECT:
                unknown_counter = 0
                self.tap_friend_first(w, h)
                self.wait_check(2.0)

            elif state == GameState.TEAM_CONFIRM:
                unknown_counter = 0
                self.tap_start_team(w, h, meta)
                in_run = True
                self.wait_check(3.0)

            elif state == GameState.STAMINA_EMPTY:
                unknown_counter = 0
                refill_ok = self.handle_stamina_refill(w, h, meta)
                if not refill_ok:
                    self.stop()
                    break
                self.wait_check(2.0)

            elif state == GameState.MAP_SCREEN:
                unknown_counter = 0
                in_run = True
                self.handle_map(w, h, meta)
                self.wait_check(1.5)

            elif state == GameState.BATTLE_SCREEN:
                unknown_counter = 0
                in_run = True
                self.handle_battle(w, h, meta)
                self.wait_check(1.5)

            elif state == GameState.KO_SCREEN:
                unknown_counter = 0
                self.log("Nemico sconfitto! Avanzamento K.O...")
                self.adb.tap(int(w * 0.50), int(h * 0.50), delay_after=1.0)

            elif state == GameState.RESULTS_SCREEN:
                unknown_counter = 0
                self.dismiss_results_and_popups(w, h, meta)
                self.wait_check(1.5)

            elif state == GameState.FRIEND_REQUEST:
                unknown_counter = 0
                self.dismiss_results_and_popups(w, h, meta)
                if in_run:
                    self.runs_completed += 1
                    in_run = False
                    self.log(f"Stage completato! [{self.runs_completed}/{self.runs_target}]")
                    self.on_run_complete(self.runs_completed, self.runs_target)
                self.wait_check(2.0)

            elif state == GameState.STAGE_SELECT:
                unknown_counter = 0
                # If we returned to stage select and in_run was true
                if in_run:
                    self.runs_completed += 1
                    in_run = False
                    self.log(f"Stage completato! [{self.runs_completed}/{self.runs_target}]")
                    self.on_run_complete(self.runs_completed, self.runs_target)

                # Tap the selected stage again to restart run
                self.log("Riavvio stage...")
                self.adb.tap(int(w * 0.50), int(h * 0.60), delay_after=1.5)

            elif state == GameState.GAME_OVER:
                self.log("Game Over rilevato! Annullamento continuazione e fine task.")
                # Tap cancel / no
                self.adb.tap(int(w * 0.35), int(h * 0.60), delay_after=1.0)
                self.stop()
                break

            else:
                # Unknown screen
                unknown_counter += 1
                if unknown_counter % 5 == 0:
                    self.log(f"Schermata non riconosciuta ({unknown_counter} cicli). Tocco di avanzamento al centro...")
                    self.adb.tap(int(w * 0.50), int(h * 0.50), delay_after=0.5)

            self.wait_check(loop_delay)

        self.is_running = False
        if self.runs_completed >= self.runs_target:
            self.log(f"Farming completato con successo! {self.runs_completed}/{self.runs_target} run eseguite.")
