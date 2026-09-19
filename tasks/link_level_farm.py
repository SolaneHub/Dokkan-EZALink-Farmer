from typing import Dict, Any, Optional, Callable
from core.adb_client import ADBClient
from core.vision import Vision
from core.game_state import GameState
from tasks.base_task import BaseTask


class LinkLevelFarmTask(BaseTask):
    """
    Automates Link Level farming (e.g., Quest Area 31-4, 34-4):
    - Loops selected stage
    - Uses Aged Meat or refills if configured
    - Automatically enables Auto-Map and Auto-Battle
    - Skips Link Level up popups and clears stages
    """

    def __init__(
        self,
        adb: ADBClient,
        vision: Vision,
        config: Dict[str, Any],
        runs: int = 20,
        on_status: Optional[Callable[[str], None]] = None,
        on_run_complete: Optional[Callable[[int, int], None]] = None
    ):
        super().__init__(adb, vision, config, on_status, on_run_complete)
        self.runs_target = runs

    def run(self):
        self.is_running = True
        self.runs_completed = 0
        self.log(f"Inizio Link Level farming su stage attuale: {self.runs_target} run programmate.")

        unknown_counter = 0
        in_run = False
        loop_delay = self.config.get("bot", {}).get("loop_delay", 1.5)

        while not self._stop_event.is_set() and self.runs_completed < self.runs_target:
            self._pause_event.wait()

            try:
                screen = self.adb.screencap()
            except Exception as e:
                self.log(f"Errore cattura schermo: {e}")
                self.wait_check(2.0)
                continue

            h, w = screen.shape[:2]
            state, meta = self.detector.detect(screen)
            self.current_state = state

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
                self.adb.tap(int(w * 0.50), int(h * 0.50), delay_after=0.8)

            elif state == GameState.RESULTS_SCREEN:
                unknown_counter = 0
                # Link Level increases show special level up animations; tap rapidly through them
                self.dismiss_results_and_popups(w, h, meta)
                self.wait_check(1.2)

            elif state == GameState.FRIEND_REQUEST:
                unknown_counter = 0
                self.dismiss_results_and_popups(w, h, meta)
                if in_run:
                    self.runs_completed += 1
                    in_run = False
                    self.log(f"Link Level run completata! [{self.runs_completed}/{self.runs_target}]")
                    self.on_run_complete(self.runs_completed, self.runs_target)
                self.wait_check(2.0)

            elif state == GameState.STAGE_SELECT:
                unknown_counter = 0
                if in_run:
                    self.runs_completed += 1
                    in_run = False
                    self.log(f"Link Level run completata! [{self.runs_completed}/{self.runs_target}]")
                    self.on_run_complete(self.runs_completed, self.runs_target)

                self.log("Rilancio stage Quest per link level...")
                self.adb.tap(int(w * 0.50), int(h * 0.60), delay_after=1.5)

            elif state == GameState.GAME_OVER:
                self.log("Game Over inaspettato! Arresto.")
                self.adb.tap(int(w * 0.35), int(h * 0.60), delay_after=1.0)
                self.stop()
                break

            else:
                unknown_counter += 1
                if unknown_counter % 5 == 0:
                    self.log(f"Schermata ({unknown_counter} cicli). Tap di avanzamento...")
                    self.adb.tap(int(w * 0.50), int(h * 0.50), delay_after=0.5)

            self.wait_check(loop_delay)

        self.is_running = False
        self.log(f"Link Level farming completato: {self.runs_completed} run eseguite.")
