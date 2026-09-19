import cv2
import numpy as np
from typing import Dict, Any, Optional, Callable
from core.adb_client import ADBClient
from core.vision import Vision
from core.game_state import GameState
from core.i18n import t
from tasks.base_task import BaseTask


class EZAFarmTask(BaseTask):
    """
    Automates Extreme Z-Battle (EZA) progression up to Level 999:
    - Automatically navigates to Z-Battle event list from Home/Events
    - Scrolls to the bottom and targets the first EZA below Level 999
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
        """Records cleared stage and calculates estimated Zeni earnings."""
        self.runs_completed += 1
        self.platinum_statues_earned += 1
        est_zeni = self.platinum_statues_earned * 1.5
        self.log(t("tasks.eza.victory", runs=self.runs_completed, statues=self.platinum_statues_earned, zeni=f"{est_zeni:.1f}"))
        self.on_run_complete(self.runs_completed, self.target_level)

    def scroll_to_bottom(self, max_flings: int = 15):
        """Fling-scrolls rapidly until reaching the very bottom of the Z-Battle list."""
        self.log(t("tasks.eza.scrolling_to_bottom"))
        prev_screen = None
        for i in range(max_flings):
            if self._stop_event.is_set():
                break

            screen = self.adb.screencap()
            h, w = screen.shape[:2]

            # Fast check: if tag_lv_999 is already visible in lower screen, we are at the bottom
            tag_bottom = self.vision.find_template(screen, "tag_lv_999")
            if tag_bottom and tag_bottom[1] > int(h * 0.70):
                self.log(t("tasks.eza.scroll_finished"))
                break

            # Fast fling swipe upwards
            self.adb.swipe(int(w * 0.50), int(h * 0.73), int(w * 0.50), int(h * 0.27), duration_ms=150)
            self.wait_check(0.45)

            curr_screen = self.adb.screencap()
            if prev_screen is not None:
                r_y1, r_y2 = int(h * 0.25), int(h * 0.75)
                r_x1, r_x2 = int(w * 0.05), int(w * 0.95)
                diff = float(np.mean(np.abs(prev_screen[r_y1:r_y2, r_x1:r_x2].astype(float) - curr_screen[r_y1:r_y2, r_x1:r_x2].astype(float))))
                if diff < 8.0:
                    self.log(t("tasks.eza.scroll_finished"))
                    break
            prev_screen = curr_screen

    def find_and_select_target_eza(self) -> bool:
        """
        Starting from the bottom of the list, scans banners upwards.
        Finds the first EZA banner that is not Lv 999, and taps it.
        If all visible banners are 999, scrolls up slightly and re-scans.
        Returns True if a target was tapped, False otherwise.
        """
        template_999 = self.vision.load_template("num_999")
        if template_999 is None:
            self.log(t("tasks.eza.num_999_missing"))
            return False

        max_scroll_ups = 10
        for attempt in range(max_scroll_ups):
            if self._stop_event.is_set():
                return False

            screen = self.adb.screencap()
            h, w = screen.shape[:2]

            # Find all banner badge centers on current screen
            badges = self.vision.find_all_templates(screen, "tag_next_lv", threshold=0.78, min_distance=80)
            if not badges:
                self.log(t("tasks.eza.no_banner_found"))
                self.wait_check(1.0)
                continue

            # Sort badges from bottom to top (descending Y)
            badges.sort(key=lambda b: b[1], reverse=True)
            self.log(t("tasks.eza.scanning_banners", count=len(badges)))

            for idx, (cx, cy, conf) in enumerate(badges):
                # Crop number area to the right of 'NEXT >> Lv.'
                num_crop = screen[max(0, cy - 50):min(h, cy + 50), max(0, cx + 20):min(w, cx + 240)]
                is_999 = False
                if num_crop.shape[0] >= template_999.shape[0] and num_crop.shape[1] >= template_999.shape[1]:
                    res_num = cv2.matchTemplate(num_crop, template_999, cv2.TM_CCOEFF_NORMED)
                    _, max_val, _, _ = cv2.minMaxLoc(res_num)
                    if max_val >= 0.85:
                        is_999 = True

                if is_999:
                    self.log(t("tasks.eza.banner_already_999", idx=idx + 1, y=cy))
                else:
                    self.log(t("tasks.eza.target_found", y=cy))
                    tap_x = int(w * 0.50)
                    tap_y = max(int(h * 0.25), cy - 80)
                    self.log(t("tasks.eza.select_tap", x=tap_x, y=tap_y))
                    self.adb.tap(tap_x, tap_y, delay_after=2.5)
                    return True

            # If all banners on screen are 999, scroll up to reveal preceding ones
            self.log(t("tasks.eza.scrolling_up"))
            self.adb.swipe(int(w * 0.50), int(h * 0.35), int(w * 0.50), int(h * 0.70), duration_ms=300)
            self.wait_check(1.0)

        self.log(t("tasks.eza.all_completed"))
        return False

    def run(self):
        """Main EZA loop."""
        self.is_running = True
        self.runs_completed = 0
        self.platinum_statues_earned = 0
        self.log(f"🔥 Extreme Z-Battle (EZA) farm started up to level {self.target_level}!")

        unknown_counter = 0
        in_battle = False
        loop_delay = self.config.get("bot", {}).get("loop_delay", 1.2)

        while not self._stop_event.is_set():
            self._pause_event.wait()

            try:
                screen = self.adb.screencap()
            except Exception as e:
                self.log(t("tasks.stage.screencap_error", error=str(e)))
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
                        self.log(t("tasks.eza.target_reached", level=self.target_level))
                        self.stop()
                        break

                if "eza_button" in meta:
                    x, y = meta["eza_button"]
                else:
                    # Challenge / Next Level button coordinate in EZA screen (~50% X, ~69% Y)
                    x, y = int(w * 0.50), int(h * 0.69)
                self.log(t("tasks.eza.starting_next_level", x=x, y=y))
                self.adb.tap(x, y, delay_after=2.0)

            # 2. Friend Supporter Selection
            elif state == GameState.FRIEND_SELECT:
                unknown_counter = 0
                if in_battle:
                    in_battle = False
                    self._record_victory()
                    if self.runs_completed >= self.target_level:
                        self.log(t("tasks.eza.target_reached", level=self.target_level))
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

            # 5. K.O. Screen
            elif state == GameState.KO_SCREEN:
                unknown_counter = 0
                self.log(t("tasks.eza.ko_advance"))
                self.adb.tap(int(w * 0.50), int(h * 0.50), delay_after=0.5)
                self.adb.tap(int(w * 0.50), int(h * 0.85), delay_after=1.0)

            # 6. Results / Clear / Rewards Screen: PRESS OK!
            elif state == GameState.RESULTS_SCREEN:
                unknown_counter = 0
                self.log(t("tasks.eza.results_ok"))
                if "ok_button" in meta:
                    self.adb.tap(*meta["ok_button"], delay_after=1.5)
                else:
                    self.adb.tap(int(w * 0.50), int(h * 0.50), delay_after=0.4)
                    self.adb.tap(int(w * 0.50), int(h * 0.85), delay_after=1.5)
                self.wait_check(1.0)

            # 7. Friend Request Popup
            elif state == GameState.FRIEND_REQUEST:
                unknown_counter = 0
                self.dismiss_results_and_popups(w, h, meta)
                self.wait_check(1.5)

            # 8. Game Over Safety Check
            elif state == GameState.GAME_OVER:
                self.log(t("tasks.eza.defeat_warning"))
                self.log(t("tasks.eza.game_over_abort"))
                self.adb.tap(int(w * 0.35), int(h * 0.60), delay_after=1.0)
                self.stop()
                break

            # 9. Box Full Detection
            elif self.vision.find_template(screen, "popup_box_full"):
                self.log(t("tasks.eza.box_full"))
                self.stop()
                break

            # 10. Title Screen (Touch Screen to Start)
            elif state == GameState.TITLE_SCREEN:
                unknown_counter = 0
                self.log(t("tasks.eza.touch_start"))
                if "touch_start" in meta:
                    self.adb.tap(*meta["touch_start"], delay_after=3.0)
                else:
                    self.adb.tap(int(w * 0.50), int(h * 0.70), delay_after=3.0)

            # 11. Home Screen -> Enter Event Selection via START
            elif state == GameState.HOME_SCREEN:
                unknown_counter = 0
                self.log(t("tasks.eza.home_detected"))
                if "start_button" in meta:
                    self.adb.tap(*meta["start_button"], delay_after=2.0)
                else:
                    self.adb.tap(int(w * 0.50), int(h * 0.64), delay_after=2.0)

            # 12. Mode Select Menu -> Tap Event
            elif state == GameState.MODE_SELECT:
                unknown_counter = 0
                self.log(t("tasks.eza.mode_select"))
                if "event_button" in meta:
                    self.adb.tap(*meta["event_button"], delay_after=2.5)
                else:
                    self.adb.tap(int(w * 0.50), int(h * 0.32), delay_after=2.5)

            # 13. Events Screen -> Tap Z-Battle Tab
            elif state == GameState.EVENT_SELECT:
                unknown_counter = 0
                self.log(t("tasks.eza.events_detected"))
                if "zbattle_tab" in meta:
                    self.adb.tap(*meta["zbattle_tab"], delay_after=2.0)
                else:
                    self.adb.tap(int(w * 0.83), int(h * 0.21), delay_after=2.0)

            # 14. Z-Battle Event List Screen -> Scroll down to bottom & pick lowest non-999 EZA
            elif state == GameState.Z_BATTLE_LIST:
                unknown_counter = 0
                self.log(t("tasks.eza.list_detected"))
                self.scroll_to_bottom()
                selected = self.find_and_select_target_eza()
                if not selected:
                    self.log(t("tasks.eza.no_banner_found"))
                self.wait_check(2.0)

            # 15. Unknown / Post-Battle Transition Screen
            else:
                unknown_counter += 1
                if "ok_button" in meta:
                    self.log(t("tasks.eza.ok_popup_detected", coords=str(meta["ok_button"])))
                    self.adb.tap(*meta["ok_button"], delay_after=1.2)
                elif "close_button" in meta:
                    self.log(t("tasks.eza.close_popup_detected", coords=str(meta["close_button"])))
                    self.adb.tap(*meta["close_button"], delay_after=1.2)
                elif "cancel_button" in meta:
                    self.adb.tap(*meta["cancel_button"], delay_after=1.2)
                elif in_battle:
                    self.log(t("tasks.eza.post_battle_advance", cycles=unknown_counter))
                    self.adb.tap(int(w * 0.50), int(h * 0.50), delay_after=0.4)
                    self.adb.tap(int(w * 0.50), int(h * 0.85), delay_after=0.8)
                elif unknown_counter >= 6 and not in_battle:
                    self.log(t("tasks.eza.reset_to_home", cycles=unknown_counter))
                    self.adb.tap(int(w * 0.10), int(h * 0.854), delay_after=2.0)
                    unknown_counter = 0
                elif unknown_counter % 2 == 0:
                    self.log(t("tasks.eza.waiting_screen", cycles=unknown_counter))
                    self.adb.tap(int(w * 0.50), int(h * 0.50), delay_after=0.3)
                    self.adb.tap(int(w * 0.50), int(h * 0.85), delay_after=0.5)

            self.wait_check(loop_delay)

        self.is_running = False
        tot_zeni = self.platinum_statues_earned * 1.5
        self.log(t("tasks.eza.session_finished", runs=self.runs_completed, zeni=f"{tot_zeni:.1f}"))
