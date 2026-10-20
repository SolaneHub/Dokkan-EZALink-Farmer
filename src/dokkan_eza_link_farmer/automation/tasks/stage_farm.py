from collections.abc import Callable
from typing import Any

import numpy as np

from dokkan_eza_link_farmer.automation.game_state import GameState
from dokkan_eza_link_farmer.automation.tasks.base_task import BaseTask
from dokkan_eza_link_farmer.automation.vision import Vision
from dokkan_eza_link_farmer.core.i18n import t
from dokkan_eza_link_farmer.integrations.adb_client import ADBClient


class StageFarmTask(BaseTask):
    """
    Automates repeated clearing of a manually selected stage until stamina runs out:
    - User selects stage manually in Dokkan Battle.
    - Bot takes over from current screen (Stage Select, Friend Select, Team Confirm, Map, Battle, Results).
    - Automatically assigns friend supporter.
    - Confirms team and enters stage.
    - Automates Map traversal and 2x Auto-Battle.
    - Smoothly dismisses rewards and uses 'Attempt Again' to restart immediately.
    - Automatically stops cleanly when stamina is depleted (STAMINA_EMPTY).
    - Supports optional max runs target and optional boost toggle.
    """

    def __init__(
        self,
        adb: ADBClient,
        vision: Vision,
        config: dict[str, Any],
        runs: int | None = None,
        use_boost: bool | None = None,
        preferred_difficulty: str | None = None,
        on_status: Callable[[str], None] | None = None,
        on_run_complete: Callable[[int, int], None] | None = None,
    ):
        super().__init__(adb, vision, config, on_status, on_run_complete)
        self.runs_target: int | None = runs if (runs is not None and runs > 0) else None
        self.use_boost: bool | None = use_boost
        self.preferred_difficulty: str | None = (
            preferred_difficulty.lower() if preferred_difficulty else None
        )
        self.stamina_depleted = False

    def handle_boost_toggle(self, screen: np.ndarray, w: int, h: int, meta: dict[str, Any]):
        """Controls the Boost feature according to self.use_boost flag."""
        if self.use_boost is None:
            return

        boost_off_coord = meta.get("boost_off") or self.vision.is_boost_off(screen)
        boost_btn_x = boost_off_coord[0] if boost_off_coord else int(w * 0.64)
        boost_btn_y = boost_off_coord[1] if boost_off_coord else int(h * 0.777)

        if self.use_boost:
            if boost_off_coord:
                self.log(t("tasks.link.boost_enable"))
                self.adb.tap(boost_btn_x, boost_btn_y, delay_after=0.6)
            else:
                self.log(t("tasks.link.boost_already_on"))
        else:
            if not boost_off_coord:
                self.log(t("tasks.link.boost_disable"))
                self.adb.tap(boost_btn_x, boost_btn_y, delay_after=0.6)
            else:
                self.log(t("tasks.link.boost_already_off"))

    def handle_stage_selection(self, screen: np.ndarray, w: int, h: int, meta: dict[str, Any]):
        """Selects difficulty or stage card on the Stage Select screen."""
        self.handle_boost_toggle(screen, w, h, meta)

        # 1. Preferred difficulty if explicitly requested
        if self.preferred_difficulty:
            pref_key = f"diff_{self.preferred_difficulty}"
            if pref_key in meta:
                self.log(t("tasks.stage_farm.select_diff", diff=self.preferred_difficulty.upper()))
                self.adb.tap(*meta[pref_key], delay_after=2.0)
                return

        # 2. Check available difficulty templates in hierarchy
        if "diff_super2" in meta:
            self.log(t("tasks.stage_farm.select_diff", diff="SUPER2"))
            self.adb.tap(*meta["diff_super2"], delay_after=2.0)
            return

        if "diff_super" in meta:
            self.log(t("tasks.stage_farm.select_diff", diff="SUPER"))
            self.adb.tap(*meta["diff_super"], delay_after=2.0)
            return

        if "diff_z_hard" in meta:
            self.log(t("tasks.stage_farm.select_diff", diff="Z-HARD"))
            self.adb.tap(*meta["diff_z_hard"], delay_after=2.0)
            return

        if "stage_saiyan_training" in meta:
            self.log(t("tasks.link.select_saiyan_training"))
            self.adb.tap(*meta["stage_saiyan_training"], delay_after=2.0)
            return

        if "stage_area39_3" in meta:
            self.adb.tap(int(w * 0.50), meta["stage_area39_3"][1], delay_after=2.0)
            return

        if "stage_area35_1" in meta:
            self.adb.tap(int(w * 0.50), meta["stage_area35_1"][1], delay_after=2.0)
            return

        # 3. Fallback: tap center (~50% X, ~55% Y) where Dokkan stage/difficulty cards are located
        self.log(t("tasks.stage_farm.tap_stage_card"))
        self.adb.tap(int(w * 0.50), int(h * 0.55), delay_after=2.0)

    def run(self):
        """Main Stage Auto-Clear loop."""
        self.is_running = True
        self.runs_completed = 0
        self.stamina_depleted = False

        runs_display = (
            str(self.runs_target) if self.runs_target is not None else t("cli.stage.runs_unlimited")
        )
        boost_display = (
            "ON" if self.use_boost is True else ("OFF" if self.use_boost is False else "AUTO")
        )
        diff_display = (
            self.preferred_difficulty.upper()
            if self.preferred_difficulty
            else t("cli.stage.diff_auto")
        )

        self.log(
            t(
                "tasks.stage_farm.started",
                runs=runs_display,
                boost=boost_display,
                diff=diff_display,
            )
        )

        unknown_counter = 0
        in_run = False
        battle_seen = False
        loop_delay = self.config.get("bot", {}).get("loop_delay", 1.5)

        while not self._stop_event.is_set() and (
            self.runs_target is None or self.runs_completed < self.runs_target
        ):
            self._pause_event.wait()

            try:
                screen = self.adb.screencap()
                if screen is None or not hasattr(screen, "shape") or len(screen.shape) < 2:
                    self.wait_check(2.0)
                    continue
            except Exception as e:
                self.log(t("tasks.stage.screencap_error", error=str(e)))
                self.wait_check(2.0)
                continue

            h, w = screen.shape[:2]
            state, meta = self.detector.detect(screen)
            self.current_state = state

            # Check for character box full safety
            if self.vision.find_template(screen, "popup_box_full"):
                self.log(t("tasks.eza.box_full"))
                self.stop()
                break

            # 1. Stamina Empty (Terminal condition: stops task cleanly)
            if state == GameState.STAMINA_EMPTY:
                unknown_counter = 0
                self.stamina_depleted = True
                self.log(t("tasks.stage_farm.stamina_depleted"))
                if "cancel_button" in meta:
                    self.adb.tap(*meta["cancel_button"], delay_after=1.5)
                else:
                    self.adb.tap(int(w * 0.50), int(h * 0.785), delay_after=1.5)
                self.stop()
                break

            # 2. Stage & Difficulty Selection
            elif state == GameState.STAGE_SELECT:
                unknown_counter = 0
                if in_run and battle_seen:
                    self.runs_completed += 1
                    in_run = False
                    battle_seen = False
                    tot_display = self.runs_target if self.runs_target is not None else "∞"
                    self.log(
                        t(
                            "tasks.stage_farm.run_completed",
                            curr=self.runs_completed,
                            tot=tot_display,
                        )
                    )
                    self.on_run_complete(
                        self.runs_completed, self.runs_target if self.runs_target is not None else 0
                    )

                if self.runs_target is not None and self.runs_completed >= self.runs_target:
                    self.log(t("tasks.stage_farm.runs_target_reached", curr=self.runs_completed))
                    self.stop()
                    break

                self.handle_stage_selection(screen, w, h, meta)
                self.wait_check(1.5)

            # 3. Friend Selection
            elif state == GameState.FRIEND_SELECT:
                unknown_counter = 0
                if in_run and battle_seen:
                    self.runs_completed += 1
                    in_run = False
                    battle_seen = False
                    tot_display = self.runs_target if self.runs_target is not None else "∞"
                    self.log(
                        t(
                            "tasks.stage_farm.run_completed",
                            curr=self.runs_completed,
                            tot=tot_display,
                        )
                    )
                    self.on_run_complete(
                        self.runs_completed, self.runs_target if self.runs_target is not None else 0
                    )

                if self.runs_target is not None and self.runs_completed >= self.runs_target:
                    self.log(t("tasks.stage_farm.runs_target_reached", curr=self.runs_completed))
                    self.stop()
                    break

                self.handle_friend_select(w, h, meta)
                self.wait_check(2.0)

            # 4. Team Confirmation Screen
            elif state == GameState.TEAM_CONFIRM:
                unknown_counter = 0
                self.tap_start_team(w, h, meta)
                in_run = True
                battle_seen = False
                self.wait_check(2.5)

            # 5. Map Screen
            elif state == GameState.MAP_SCREEN:
                unknown_counter = 0
                in_run = True
                battle_seen = True
                self.handle_map(w, h, meta)
                self.wait_check(1.5)

            # 6. Battle Screen
            elif state == GameState.BATTLE_SCREEN:
                unknown_counter = 0
                in_run = True
                battle_seen = True
                self.handle_battle(w, h, meta)
                self.wait_check(1.5)

            # 7. KO Screen
            elif state == GameState.KO_SCREEN:
                unknown_counter = 0
                battle_seen = True
                self.adb.tap(int(w * 0.50), int(h * 0.50), delay_after=0.8)

            # 8. Results Screen & Rewards
            elif state == GameState.RESULTS_SCREEN:
                unknown_counter = 0
                if in_run and battle_seen:
                    self.runs_completed += 1
                    in_run = False
                    battle_seen = False
                    tot_display = self.runs_target if self.runs_target is not None else "∞"
                    self.log(
                        t(
                            "tasks.stage_farm.run_completed",
                            curr=self.runs_completed,
                            tot=tot_display,
                        )
                    )
                    self.on_run_complete(
                        self.runs_completed, self.runs_target if self.runs_target is not None else 0
                    )

                    if self.runs_target is not None and self.runs_completed >= self.runs_target:
                        self.log(
                            t("tasks.stage_farm.runs_target_reached", curr=self.runs_completed)
                        )
                        self.dismiss_results_and_popups(w, h, meta, prefer_again=False)
                        self.stop()
                        break

                prefer_again = self.runs_target is None or self.runs_completed < self.runs_target
                self.dismiss_results_and_popups(w, h, meta, prefer_again=prefer_again)
                self.wait_check(1.2)

            # 9. Friend Request Popup
            elif state == GameState.FRIEND_REQUEST:
                unknown_counter = 0
                self.dismiss_results_and_popups(w, h, meta, prefer_again=False)
                if in_run and battle_seen:
                    self.runs_completed += 1
                    in_run = False
                    battle_seen = False
                    tot_display = self.runs_target if self.runs_target is not None else "∞"
                    self.log(
                        t(
                            "tasks.stage_farm.run_completed",
                            curr=self.runs_completed,
                            tot=tot_display,
                        )
                    )
                    self.on_run_complete(
                        self.runs_completed, self.runs_target if self.runs_target is not None else 0
                    )
                self.wait_check(1.5)

            # 10. Game Over Screen
            elif state == GameState.GAME_OVER:
                self.log(t("tasks.stage_farm.game_over"))
                if "cancel_button" in meta:
                    self.adb.tap(*meta["cancel_button"], delay_after=1.5)
                else:
                    self.adb.tap(int(w * 0.35), int(h * 0.60), delay_after=1.5)
                self.stop()
                break

            # 11. Home Screen notice
            elif state == GameState.HOME_SCREEN:
                self.log(t("tasks.stage_farm.home_screen_notice"))
                self.wait_check(2.0)

            # 12. Modal dialogs or unknown screens
            else:
                unknown_counter += 1
                if "ok_button" in meta:
                    self.log(
                        t("tasks.base.ok_clicked", x=meta["ok_button"][0], y=meta["ok_button"][1])
                    )
                    self.adb.tap(*meta["ok_button"], delay_after=1.5)
                elif "close_button" in meta:
                    self.log(
                        t(
                            "tasks.base.close_clicked",
                            x=meta["close_button"][0],
                            y=meta["close_button"][1],
                        )
                    )
                    self.adb.tap(*meta["close_button"], delay_after=1.5)
                elif "cancel_button" in meta:
                    self.adb.tap(*meta["cancel_button"], delay_after=1.5)
                elif in_run:
                    self.log(t("tasks.stage.post_stage_advance", cycles=unknown_counter))
                    self.adb.tap(int(w * 0.50), int(h * 0.50), delay_after=0.4)
                    self.adb.tap(int(w * 0.50), int(h * 0.88), delay_after=1.0)
                elif unknown_counter % 5 == 0:
                    self.log(t("tasks.stage_farm.waiting_action", cycles=unknown_counter))
                    self.adb.tap(int(w * 0.50), int(h * 0.50), delay_after=0.8)

            self.wait_check(loop_delay)

        self.is_running = False
        self.log(t("tasks.stage_farm.farming_finished", curr=self.runs_completed))
