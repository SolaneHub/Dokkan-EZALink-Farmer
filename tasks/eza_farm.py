from typing import Dict, Any, Optional, Callable
from core.adb_client import ADBClient
from core.vision import Vision
from core.game_state import GameState
from tasks.base_task import BaseTask


class EZAFarmTask(BaseTask):
    """
    Automates Extreme Z-Battle (EZA) progression:
    - Automatically challenges consecutive levels (Lv. 1 -> Lv. 30+)
    - Auto selects friend leader
    - Auto battles boss
    - Collects awakening medals & Dragon Stones / Hercule statues
    - Advances to next level automatically until target level or loss
    """

    def __init__(
        self,
        adb: ADBClient,
        vision: Vision,
        config: Dict[str, Any],
        target_level: int = 30,
        on_status: Optional[Callable[[str], None]] = None,
        on_run_complete: Optional[Callable[[int, int], None]] = None
    ):
        super().__init__(adb, vision, config, on_status, on_run_complete)
        self.target_level = target_level
        self.current_level = 1

    def run(self):
        self.is_running = True
        self.runs_completed = 0
        self.log(f"Inizio farming Extreme Z-Battle (EZA) fino al livello {self.target_level}...")

        unknown_counter = 0
        in_battle = False
        loop_delay = self.config.get("bot", {}).get("loop_delay", 1.5)

        while not self._stop_event.is_set():
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

            if state == GameState.EZA_SELECT:
                unknown_counter = 0
                if "eza_button" in meta:
                    x, y = meta["eza_button"]
                else:
                    # Next Stage / Challenge button coordinate in EZA screen (~50% X, ~82% Y)
                    x, y = int(w * 0.50), int(h * 0.82)
                self.log(f"Avvio livello EZA successivo (tap a {x}, {y})...")
                self.adb.tap(x, y, delay_after=2.0)

            elif state == GameState.FRIEND_SELECT:
                unknown_counter = 0
                self.handle_friend_select(w, h, meta)
                self.wait_check(2.0)

            elif state == GameState.TEAM_CONFIRM:
                unknown_counter = 0
                self.tap_start_team(w, h, meta)
                in_battle = True
                self.wait_check(3.0)

            elif state == GameState.BATTLE_SCREEN:
                unknown_counter = 0
                in_battle = True
                self.handle_battle(w, h, meta)
                self.wait_check(1.5)

            elif state == GameState.KO_SCREEN:
                unknown_counter = 0
                self.log("EZA Boss sconfitto! Avanzamento K.O...")
                self.adb.tap(int(w * 0.50), int(h * 0.50), delay_after=1.0)

            elif state == GameState.RESULTS_SCREEN:
                unknown_counter = 0
                self.dismiss_results_and_popups(w, h, meta)
                self.wait_check(1.5)

            elif state == GameState.FRIEND_REQUEST:
                unknown_counter = 0
                self.dismiss_results_and_popups(w, h, meta)
                if in_battle:
                    self.runs_completed += 1
                    in_battle = False
                    self.log(f"Livello EZA completato! Totale livelli vinti: {self.runs_completed}")
                    self.on_run_complete(self.runs_completed, self.target_level)
                    if self.runs_completed >= self.target_level:
                        self.log(f"Raggiunto il livello target {self.target_level}! Fermo EZA.")
                        self.stop()
                        break
                self.wait_check(2.0)

            elif state == GameState.GAME_OVER:
                self.log("Sconfitta in EZA! Livello troppo difficile per il team attuale. Arresto.")
                self.adb.tap(int(w * 0.35), int(h * 0.60), delay_after=1.0) # Tap cancel
                self.stop()
                break

            else:
                unknown_counter += 1
                if unknown_counter % 5 == 0:
                    self.log(f"In attesa schermata EZA ({unknown_counter} cicli). Tap di avanzamento...")
                    self.adb.tap(int(w * 0.50), int(h * 0.50), delay_after=0.5)

            self.wait_check(loop_delay)

        self.is_running = False
        self.log("Sessione EZA conclusa.")
