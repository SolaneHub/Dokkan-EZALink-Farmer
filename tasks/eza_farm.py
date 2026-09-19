from typing import Dict, Any, Optional, Callable
from core.adb_client import ADBClient
from core.vision import Vision
from core.game_state import GameState
from tasks.base_task import BaseTask


class EZAFarmTask(BaseTask):
    """
    Automates Extreme Z-Battle (EZA) progression up to Level 999:
    - Automatically challenges consecutive levels (Lv. 1 -> Lv. 999)
    - Auto selects friend leader via refresh button
    - Auto battles boss with 2x speed
    - Smoothly advances through results: taps to skip animations and presses OK
    - Detects level completions and tracks Platinum Hercule Statues (1.5M Zeni each)
    - Stops safely if defeated (Game Over) or if character box is full
    """

    def __init__(
        self,
        adb: ADBClient,
        vision: Vision,
        config: Dict[str, Any],
        target_level: int = 999,
        on_status: Optional[Callable[[str], None]] = None,
        on_run_complete: Optional[Callable[[int, int], None]] = None
    ):
        super().__init__(adb, vision, config, on_status, on_run_complete)
        self.target_level = target_level
        self.platinum_statues_earned = 0

    def _record_victory(self):
        self.runs_completed += 1
        self.platinum_statues_earned += 1
        est_zeni = self.platinum_statues_earned * 1.5
        self.log(f"🏆 Livello EZA superato! [Totale livelli: {self.runs_completed} | Statue Platino: +{self.platinum_statues_earned} (~{est_zeni:.1f}M Zeni)]")
        self.on_run_complete(self.runs_completed, self.target_level)

    def run(self):
        self.is_running = True
        self.runs_completed = 0
        self.platinum_statues_earned = 0
        self.log(f"🔥 Inizio scalata Extreme Z-Battle (EZA) fino al livello {self.target_level}!")
        self.log("💡 Nota: Livelli 31-999 a 0 Stamina con drop Statue Platino (1.5M Zeni cad.).")

        unknown_counter = 0
        in_battle = False
        loop_delay = self.config.get("bot", {}).get("loop_delay", 1.2)

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

            # 1. EZA Level Select Screen (Challenge Button / Next Level)
            if state == GameState.EZA_SELECT:
                unknown_counter = 0
                if in_battle:
                    in_battle = False
                    self._record_victory()
                    if self.runs_completed >= self.target_level:
                        self.log(f"🎉 RAGGIUNTO IL LIVELLO TARGET {self.target_level}! Scalata completata!")
                        self.stop()
                        break

                if "eza_button" in meta:
                    x, y = meta["eza_button"]
                else:
                    # Challenge / Next Level button coordinate in EZA screen (~50% X, ~82% Y)
                    x, y = int(w * 0.50), int(h * 0.82)
                self.log(f"Avvio livello EZA successivo (tap a {x}, {y})...")
                self.adb.tap(x, y, delay_after=2.0)

            # 2. Friend Supporter Selection
            elif state == GameState.FRIEND_SELECT:
                unknown_counter = 0
                if in_battle:
                    in_battle = False
                    self._record_victory()
                    if self.runs_completed >= self.target_level:
                        self.log(f"🎉 RAGGIUNTO IL LIVELLO TARGET {self.target_level}! Scalata completata!")
                        self.stop()
                        break

                self.handle_friend_select(w, h, meta)
                self.wait_check(2.0)

            # 3. Team Confirmation Screen
            elif state == GameState.TEAM_CONFIRM:
                unknown_counter = 0
                self.tap_start_team(w, h, meta)
                in_battle = True
                self.wait_check(2.5)

            # 4. Boss Battle Active
            elif state == GameState.BATTLE_SCREEN:
                unknown_counter = 0
                in_battle = True
                self.handle_battle(w, h, meta)
                self.wait_check(1.5)

            # 5. K.O. Explosion Screen
            elif state == GameState.KO_SCREEN:
                unknown_counter = 0
                self.log("💥 Boss sconfitto! Avanzamento K.O...")
                # Tap center to skip KO animation, then tap OK position (85% Y)
                self.adb.tap(int(w * 0.50), int(h * 0.50), delay_after=0.5)
                self.adb.tap(int(w * 0.50), int(h * 0.85), delay_after=1.0)

            # 6. Results / Clear / Rewards Screen: PRESS OK!
            elif state == GameState.RESULTS_SCREEN:
                unknown_counter = 0
                self.log("Schermata risultati: premuto OK...")
                if "ok_button" in meta:
                    self.adb.tap(*meta["ok_button"], delay_after=1.5)
                else:
                    # First tap to skip EXP/Zeni count animations, then tap OK at 85% Y
                    self.adb.tap(int(w * 0.50), int(h * 0.50), delay_after=0.4)
                    self.adb.tap(int(w * 0.50), int(h * 0.85), delay_after=1.5)
                self.wait_check(1.0)

            # 7. Friend Request Popup
            elif state == GameState.FRIEND_REQUEST:
                unknown_counter = 0
                self.dismiss_results_and_popups(w, h, meta)
                if in_battle:
                    in_battle = False
                    self._record_victory()
                    if self.runs_completed >= self.target_level:
                        self.log(f"🎉 RAGGIUNTO IL LIVELLO TARGET {self.target_level}! Scalata completata!")
                        self.stop()
                        break
                self.wait_check(2.0)

            # 8. Game Over Safety Check
            elif state == GameState.GAME_OVER:
                self.log("⚠️ Sconfitta in EZA! Il boss è troppo forte per il team attuale.")
                self.log("Annullamento continuazione (nessuna Dragon Stone usata). Fermo il bot.")
                self.adb.tap(int(w * 0.35), int(h * 0.60), delay_after=1.0)
                self.stop()
                break

            # 9. Box Full Detection
            elif self.vision.find_template(screen, "popup_box_full"):
                self.log("📦 Box Personaggi pieno! Vendi o allena le statue di Hercule e riavvia.")
                self.stop()
                break

            # 10. Unknown / Post-Battle Transition Screen
            else:
                unknown_counter += 1
                if "ok_button" in meta:
                    self.log(f"Pulsante OK rilevato ({meta['ok_button']}). Tap di conferma...")
                    self.adb.tap(*meta["ok_button"], delay_after=1.2)
                elif in_battle:
                    # Battle ended and game is cycling through Clear / Rewards / Dialog screens
                    self.log(f"Avanzamento post-battaglia (ciclo {unknown_counter}): tocco OK a ({int(w*0.50)}, {int(h*0.85)})...")
                    # Tap center to skip dialogue/animations
                    self.adb.tap(int(w * 0.50), int(h * 0.50), delay_after=0.4)
                    # Tap OK button position at center bottom
                    self.adb.tap(int(w * 0.50), int(h * 0.85), delay_after=1.0)
                elif unknown_counter % 4 == 0:
                    self.log(f"In attesa schermata EZA ({unknown_counter} cicli). Tap di avanzamento...")
                    self.adb.tap(int(w * 0.50), int(h * 0.85), delay_after=0.5)

            self.wait_check(loop_delay)

        self.is_running = False
        tot_zeni = self.platinum_statues_earned * 1.5
        self.log(f"🏁 Sessione EZA conclusa: {self.runs_completed} livelli vinti. Zeni stimati: ~{tot_zeni:.1f}M.")
