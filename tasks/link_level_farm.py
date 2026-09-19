import time
from typing import Dict, Any, Optional, Callable, List
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
    - Detects when a unit hits MAX (Lv. 10) on all links and replaces it
      automatically with the next available unit from the box!
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

        ll_cfg = self.config.get("link_leveling", {})
        self.auto_swap = ll_cfg.get("auto_swap_maxed_units", True)
        self.protected_slots: List[int] = ll_cfg.get("protected_slots", []) # Empty = all slots swappable
        self.box_card_coords = ll_cfg.get("box_first_slot_coords", [0.18, 0.28])
        self.box_confirm_coords = ll_cfg.get("box_confirm_coords", [0.50, 0.90])

    def swap_maxed_unit(self, slot_idx: int, screen_w: int, screen_h: int, meta: Dict[str, Any]):
        """
        Executes the replacement routine for a unit that reached MAX link level:
        1. Enters Team Formation
        2. Taps the maxed slot
        3. Taps the next eligible unit in the filtered Box (sorted by release date)
        4. Confirms and returns to stage
        """
        self.log(f"🔄 Sostituzione carta nello Slot {slot_idx + 1} (Link completati a Lv. 10)...")

        # 1. Open Team Formation / Edit Deck
        if "edit_team_button" in meta:
            self.adb.tap(*meta["edit_team_button"], delay_after=2.0)
        else:
            # Fallback coordinate for "Edit Deck" on pre-stage screen
            self.adb.tap(int(screen_w * 0.85), int(screen_h * 0.38), delay_after=2.0)

        # 2. Tap the specific character slot in Team Formation
        # Team formation 6 slots layout (2 rows x 3 columns)
        team_slot_coords = [
            (0.22, 0.30),  # Slot 1 (Leader)
            (0.50, 0.30),  # Slot 2
            (0.78, 0.30),  # Slot 3
            (0.22, 0.55),  # Slot 4
            (0.50, 0.55),  # Slot 5
            (0.78, 0.55),  # Slot 6
        ]

        if 0 <= slot_idx < len(team_slot_coords):
            rx, ry = team_slot_coords[slot_idx]
            self.log(f"Apertura selezione per Slot {slot_idx + 1}...")
            self.adb.tap(int(screen_w * rx), int(screen_h * ry), delay_after=2.5)

        # 3. In the Box (Character List):
        # Tap the first available card in the pre-filtered grid (Row 1, Column 1)
        bx, by = self.box_card_coords
        self.log(f"Selezione nuova carta dal Box (Row 1, Col 1 a {bx*100:.0f}%, {by*100:.0f}%)...")
        self.adb.tap(int(screen_w * bx), int(screen_h * by), delay_after=1.2)

        # 4. Confirm selection in Box
        cx, cy = self.box_confirm_coords
        self.log("Conferma selezione personaggio...")
        self.adb.tap(int(screen_w * cx), int(screen_h * cy), delay_after=2.0)

        # 5. Confirm Team Formation / Return to pre-stage screen
        self.log("Conferma nuovo team e ritorno alla missione...")
        self.adb.tap(int(screen_w * 0.50), int(screen_h * 0.90), delay_after=2.5)

    def check_and_swap_team_if_needed(self, screen: Any, screen_w: int, screen_h: int, meta: Dict[str, Any]) -> bool:
        """
        Inspects all swappable slots (0 to 5) for MAX link level badges.
        If a maxed slot is found, performs swap and returns True.
        """
        if not self.auto_swap:
            return False

        for slot_idx in range(6):
            human_slot_number = slot_idx + 1
            if human_slot_number in self.protected_slots:
                continue

            if self.vision.is_slot_link_max(screen, slot_idx):
                self.log(f"⭐ Rilevato MAX LINK su Slot {human_slot_number}!")
                self.swap_maxed_unit(slot_idx, screen_w, screen_h, meta)
                return True # Swapped one unit; screen refreshed

        return False

    def run(self):
        self.is_running = True
        self.runs_completed = 0
        self.log(f"Inizio Link Level farming su stage attuale: {self.runs_target} run programmate.")
        if self.auto_swap:
            self.log("Funzione Auto-Swap attiva: qualsiasi carta con link a Lv. 10 (MAX) verrà sostituita automaticamente.")

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
                self.handle_friend_select(w, h, meta)
                self.wait_check(2.0)

            elif state == GameState.TEAM_CONFIRM:
                unknown_counter = 0

                # Check if any slot has all links maxed before starting
                swapped = self.check_and_swap_team_if_needed(screen, w, h, meta)
                if swapped:
                    # After swap, let screen re-render before proceeding to start
                    self.wait_check(2.0)
                    continue

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
