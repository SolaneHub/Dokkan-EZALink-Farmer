from typing import Dict, Any, Optional, Callable
from core.adb_client import ADBClient
from core.vision import Vision
from core.game_state import GameState
from tasks.base_task import BaseTask


class EZAFarmTask(BaseTask):
    """
    Automates Extreme Z-Battle (EZA) progression up to Level 999:
    - Automatically challenges consecutive levels (Lv. 1 -> Lv. 999)
    - Auto selects friend leader via refresh
    - Auto battles boss with 2x speed
    - Collects awakening medals & Dragon Stones (1-30) and Platinum Hercule Statues (31-999)
    - Taps 'Next Stage' directly from results screen for maximum speed
    - Stops safely if defeated (Game Over) or if character box is full
    - Tracks estimated Zeni earned from Platinum statues (1.5M Zeni per statue)
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

    def run(self):
        self.is_running = True
        self.runs_completed = 0
        self.platinum_statues_earned = 0
        self.log(f"🔥 Inizio scalata Extreme Z-Battle (EZA) fino al livello {self.target_level}!")
        self.log("💡 Nota: I livelli 31-999 costano 0 Stamina e rilasciano Statue di Hercule Platino (1.5M Zeni ciascuna).")

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

            # 1. EZA Level Select Screen (Challenge Button)
            if state == GameState.EZA_SELECT:
                unknown_counter = 0
                if "eza_button" in meta:
                    x, y = meta["eza_button"]
                else:
                    # Next Stage / Challenge button coordinate in EZA screen (~50% X, ~82% Y)
                    x, y = int(w * 0.50), int(h * 0.82)
                self.log(f"Avvio livello EZA successivo (tap a {x}, {y})...")
                self.adb.tap(x, y, delay_after=2.0)

            # 2. Friend Supporter Selection
            elif state == GameState.FRIEND_SELECT:
                unknown_counter = 0
                self.handle_friend_select(w, h, meta)
                self.wait_check(2.0)

            # 3. Team Confirmation Screen
            elif state == GameState.TEAM_CONFIRM:
                unknown_counter = 0
                self.tap_start_team(w, h, meta)
                in_battle = True
                self.wait_check(3.0)

            # 4. Boss Battle
            elif state == GameState.BATTLE_SCREEN:
                unknown_counter = 0
                in_battle = True
                self.handle_battle(w, h, meta)
                self.wait_check(1.5)

            # 5. K.O. Screen
            elif state == GameState.KO_SCREEN:
                unknown_counter = 0
                self.log("💥 Boss sconfitto! Avanzamento K.O...")
                self.adb.tap(int(w * 0.50), int(h * 0.50), delay_after=1.0)

            # 6. Results Screen: Tap 'Next Stage' directly to bypass menu!
            elif state == GameState.RESULTS_SCREEN:
                unknown_counter = 0
                # In modern Dokkan EZA, 'Next Stage' is located at bottom right (~72% X, ~88% Y)
                next_stage_match = self.vision.find_template(screen, "button_eza_next_level")
                if next_stage_match:
                    self.log(f"Trovato pulsante 'Prossimo Livello' ({next_stage_match[0]}, {next_stage_match[1]}). Transizione rapida...")
                    self.adb.tap(next_stage_match[0], next_stage_match[1], delay_after=2.0)
                else:
                    # Fallback: tap Next Stage button position or dismiss
                    self.adb.tap(int(w * 0.72), int(h * 0.88), delay_after=1.5)
                self.wait_check(1.5)

            # 7. Friend Request Popup
            elif state == GameState.FRIEND_REQUEST:
                unknown_counter = 0
                self.dismiss_results_and_popups(w, h, meta)
                if in_battle:
                    self.runs_completed += 1
                    in_battle = False
                    self.platinum_statues_earned += 1
                    est_zeni = self.platinum_statues_earned * 1.5
                    self.log(f"🏆 Livello EZA completato! [Totale livelli: {self.runs_completed} | Statue Platino: +{self.platinum_statues_earned} (~{est_zeni:.1f}M Zeni)]")
                    self.on_run_complete(self.runs_completed, self.target_level)
                    if self.runs_completed >= self.target_level:
                        self.log(f"🎉 RAGGIUNTO IL LIVELLO TARGET {self.target_level}! Scalata EZA completata!")
                        self.stop()
                        break
                self.wait_check(2.0)

            # 8. Game Over Safety Check
            elif state == GameState.GAME_OVER:
                self.log("⚠️ Sconfitta rilevata! Il livello attuale è troppo difficile per il team.")
                self.log("Annullamento continuazione per non sprecare Dragon Stone. Fermo il bot.")
                self.adb.tap(int(w * 0.35), int(h * 0.60), delay_after=1.0) # Tap cancel / No
                self.stop()
                break

            # 9. Box Full Detection
            elif self.vision.find_template(screen, "popup_box_full"):
                self.log("📦 Box Personaggi pieno! Le statue di Hercule occupano spazio.")
                self.log("Vendi le statue di Hercule nel negozio o tramite 'Sell' e riavvia.")
                self.stop()
                break

            else:
                unknown_counter += 1
                if unknown_counter % 5 == 0:
                    self.log(f"In attesa schermata EZA ({unknown_counter} cicli). Tap di avanzamento...")
                    self.adb.tap(int(w * 0.50), int(h * 0.50), delay_after=0.5)

            self.wait_check(loop_delay)

        self.is_running = False
        tot_zeni = self.platinum_statues_earned * 1.5
        self.log(f"🏁 Sessione EZA 999 terminata: {self.runs_completed} livelli vinti. Zeni stimati: ~{tot_zeni:.1f}M.")
