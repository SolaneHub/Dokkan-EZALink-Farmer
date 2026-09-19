import time
from typing import Dict, Any, Optional, Callable
from core.adb_client import ADBClient
from core.vision import Vision
from core.game_state import GameState
from core.i18n import t
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
        """Main stage farming loop."""
        self.is_running = True
        self.runs_completed = 0
        self.log(t("tasks.stage.started", runs=self.runs_target))

        unknown_counter = 0
        in_run = False
        loop_delay = self.config.get("bot", {}).get("loop_delay", 1.5)

        while not self._stop_event.is_set() and self.runs_completed < self.runs_target:
            self._pause_event.wait()

            # 1. Capture screen
            try:
                screen = self.adb.screencap()
            except Exception as e:
                self.log(t("tasks.stage.screencap_error", error=str(e)))
                self.wait_check(2.0)
                continue

            h, w = screen.shape[:2]

            # 2. Detect State
            state, meta = self.detector.detect(screen)
            self.current_state = state

            # Handle state transitions
            if state == GameState.FRIEND_SELECT:
                unknown_counter = 0
                self.handle_friend_select(w, h, meta)
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
                self.log(t("tasks.stage.enemy_defeated"))
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
                    self.log(t("tasks.stage.stage_completed", curr=self.runs_completed, tot=self.runs_target))
                    self.on_run_complete(self.runs_completed, self.runs_target)
                self.wait_check(2.0)

            elif state == GameState.STAGE_SELECT:
                unknown_counter = 0
                if in_run:
                    self.runs_completed += 1
                    in_run = False
                    self.log(t("tasks.stage.stage_completed", curr=self.runs_completed, tot=self.runs_target))
                    self.on_run_complete(self.runs_completed, self.runs_target)

                # Tap the selected stage again to restart run
                self.log(t("tasks.stage.restarting_stage"))
                self.adb.tap(int(w * 0.50), int(h * 0.60), delay_after=1.5)

            elif state == GameState.GAME_OVER:
                self.log(t("tasks.stage.game_over"))
                self.adb.tap(int(w * 0.35), int(h * 0.60), delay_after=1.0)
                self.stop()
                break

            else:
                # Unknown / post-run transition screen
                unknown_counter += 1
                if in_run:
                    self.log(t("tasks.stage.post_stage_advance", cycles=unknown_counter))
                    self.adb.tap(int(w * 0.50), int(h * 0.50), delay_after=0.4)
                    self.adb.tap(int(w * 0.50), int(h * 0.88), delay_after=1.0)
                elif unknown_counter % 5 == 0:
                    self.log(t("tasks.stage.unknown_screen_advance", cycles=unknown_counter))
                    self.adb.tap(int(w * 0.50), int(h * 0.50), delay_after=0.5)

            self.wait_check(loop_delay)

        self.is_running = False
        if self.runs_completed >= self.runs_target:
            self.log(t("tasks.stage.farming_finished", curr=self.runs_completed, tot=self.runs_target))
