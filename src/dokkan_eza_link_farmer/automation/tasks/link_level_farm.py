from collections.abc import Callable
from typing import Any

import cv2
import numpy as np

from dokkan_eza_link_farmer.automation.game_state import GameState
from dokkan_eza_link_farmer.automation.tasks.base_task import BaseTask
from dokkan_eza_link_farmer.automation.vision import Vision
from dokkan_eza_link_farmer.core.i18n import t
from dokkan_eza_link_farmer.integrations.adb_client import ADBClient
from dokkan_eza_link_farmer.integrations.dokkandb_client import DokkanDBClient


class LinkLevelFarmTask(BaseTask):
    """
    Automates Link Level farming with DokkanDB event integration:
    - Automatically discovers and targets rotating link level events
      (specifically 'Ultimate Leveling Up! Chamber of Spirit and Time' / Stanza dello Spirito e del Tempo).
    - Navigates from Home/Event screen to the Bonus tab.
    - Locates the event banner via DokkanDB template matching and enters it.
    - Selects Stage and Difficulty (SUPER / Z-HARD).
    - Auto-assigns friends and manages stamina refills.
    - Inspects team on pre-stage screen and automatically swaps units whose links
      are MAX (Lv. 10) using modern Dokkan UI (6-slot horizontal layout).
    - Fully automates Map traversal and 2x speed Auto-Battle.
    - Dismisses rewards, rank ups, and Link Level Up popups.
    - Detects when limited attempts (e.g. 10 attempts or daily limit) are reached and finishes cleanly.
    """

    def __init__(
        self,
        adb: ADBClient,
        vision: Vision,
        config: dict[str, Any],
        runs: int | None = None,
        target_event: dict[str, Any] | None = None,
        dokkandb: DokkanDBClient | None = None,
        use_boost: bool | None = None,
        filter_ur: bool = False,
        filter_lr: bool = False,
        target_stage: str | None = None,
        stage_name: str | None = None,
        on_status: Callable[[str], None] | None = None,
        on_run_complete: Callable[[int, int], None] | None = None,
    ):
        super().__init__(adb, vision, config, on_status, on_run_complete)
        self.runs_target: int | None = runs if (runs is not None and runs > 0) else None
        self.dokkandb = dokkandb or DokkanDBClient()
        self.target_event = target_event

        ll_cfg = self.config.get("link_leveling", {})
        self.auto_swap = ll_cfg.get("auto_swap_maxed_units", True)
        self.protected_slots: list[int] = ll_cfg.get("protected_slots", [])
        self.preferred_difficulty: str = ll_cfg.get("preferred_difficulty", "super").lower()

        if target_stage:
            self.target_stage: str = target_stage.lower()
        else:
            self.target_stage = ll_cfg.get("target_stage", "area_39_3").lower()

        self.stage_name: str = stage_name or (
            "Area 39 Stage 3: Great stamina-friendly option (also drops green gems) | 5 fights"
            if self.target_stage == "area_39_3"
            else (
                "Area 35 Stage 1: Good stamina-friendly option (also drops blue gems) | 4 fights"
                if self.target_stage == "area_35_1"
                else (
                    self.target_event.get("name", "Chamber of Spirit and Time")
                    if self.target_event
                    else "Chamber of Spirit and Time"
                )
            )
        )
        self.filter_ur: bool = bool(filter_ur or ll_cfg.get("filter_ur", False))
        self.filter_lr: bool = bool(filter_lr or ll_cfg.get("filter_lr", False))

        # Retrieve Chamber of Spirit and Time from DokkanDB if targeting spirit and not explicitly passed
        if not self.target_event and self.target_stage in (
            "spirit",
            "spirit_and_time",
            "saiyan_training",
        ):
            self.target_event = self.dokkandb.get_chamber_of_spirit_and_time()

        self._target_banner_img: np.ndarray | None = None
        if self.target_event and self.target_event.get("banner_local_path"):
            self._target_banner_img = cv2.imread(
                self.target_event["banner_local_path"], cv2.IMREAD_UNCHANGED
            )
        self.use_boost: bool = (
            use_boost if use_boost is not None else bool(ll_cfg.get("use_boost", False))
        )
        self.rebuild_team_every_run: bool = ll_cfg.get("rebuild_team_every_run", True)
        self.ensure_filter_every_run: bool = ll_cfg.get("ensure_filter_every_run", False)
        self.use_attempt_again: bool = bool(ll_cfg.get("use_attempt_again", True))

        # Modern UI box & team formation coordinates
        self.box_card_coords = ll_cfg.get("box_first_slot_coords", [0.18, 0.28])
        self.box_confirm_coords = ll_cfg.get(
            "box_confirm_coords", [0.88, 0.88]
        )  # Red Confirm button

        # State tracking
        self.event_banner_selected = False
        self.attempts_exhausted = False
        self.box_filter_initialized = False
        self._needs_team_link_check = True
        self._team_prepared_for_run = False

    def navigate_to_event_banner(
        self, _screen: np.ndarray, w: int, h: int, meta: dict[str, Any]
    ) -> bool:
        """
        Navigates to the event banner in the Event List (Bonus tab):
        1. Switches to Bonus tab if on Event Select screen.
        2. Searches for target event banner on screen.
        3. Scrolls downwards if not immediately found.
        4. Taps banner when located.
        """
        if self._target_banner_img is None:
            # If no cached banner, fallback to tapping first event under Bonus
            self.log(t("tasks.link.banner_missing_fallback"))
            self.adb.tap(int(w * 0.50), int(h * 0.58), delay_after=2.5)
            self.event_banner_selected = True
            return True

        target_name = (
            self.target_event.get("name") if self.target_event else None
        ) or "Chamber of Spirit and Time"
        self.log(t("tasks.link.searching_banner", name=target_name))

        # Ensure Bonus tab is active (Category 4 events are in Bonus tab)
        if "bonus_tab" in meta:
            bx, by = meta["bonus_tab"]
            self.adb.tap(bx, by, delay_after=1.2)
        else:
            # Fallback Bonus tab coordinate: Tab 2 of 5 at top (~X: 0.29, Y: 0.213)
            self.adb.tap(int(w * 0.29), int(h * 0.213), delay_after=1.2)

        # Scan and scroll for banner
        max_scrolls = 8
        prev_screen = None

        for _attempt in range(max_scrolls):
            if self._stop_event.is_set():
                return False

            curr_screen = self.adb.screencap()
            match = self.vision.find_banner_on_screen(
                curr_screen, self._target_banner_img, threshold=0.72
            )
            if match:
                cx, cy, conf = match
                self.log(t("tasks.link.banner_found", name=target_name, conf=f"{conf:.2f}"))
                tap_x = int(w * 0.50)
                tap_y = max(int(h * 0.25), min(int(h * 0.78), cy))
                self.adb.tap(tap_x, tap_y, delay_after=2.5)
                self.event_banner_selected = True
                return True

            # Scroll down to reveal more events
            self.log(t("tasks.link.scrolling_events"))
            self.adb.swipe(
                int(w * 0.50), int(h * 0.65), int(w * 0.50), int(h * 0.35), duration_ms=250
            )
            self.wait_check(0.8)

            if prev_screen is not None:
                diff = float(np.mean(np.abs(prev_screen.astype(float) - curr_screen.astype(float))))
                if diff < 4.0:
                    self.log(t("tasks.link.end_of_events_list"))
                    break
            prev_screen = curr_screen

        return False

    def handle_boost_toggle(self, screen: np.ndarray, w: int, h: int, meta: dict[str, Any]):
        """
        Controls the Boost feature according to self.use_boost flag:
        - If self.use_boost is True and Boost is OFF (button_boost_off detected), taps Boost to turn it ON.
        - If self.use_boost is False and Boost is ON (button_boost_off not detected), taps Boost to turn it OFF.
        """
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

    def handle_quest_navigation(
        self, screen: np.ndarray, w: int, h: int, meta: dict[str, Any]
    ) -> bool:
        """
        Navigates through Dokkan Quest Story hierarchy to reach the target stage:
        1. If on Difficulty Screen (diff_super or diff_z_hard present):
           Delegates to handle_stage_selection.
        2. If on Target Stage List (stage_area39_3 or stage_area35_1 visible):
           Taps the target stage card to open the difficulty screen.
        3. If on Area Stages List but stage 1 is not scrolled down yet (for Area 35):
           Swipes up to reveal stage 1.
        4. If on Chapter 6 Area List:
           - For Area 39: taps Area 39 badge / card.
           - For Area 35: scrolls down if needed, then taps Area 35 badge / card.
        5. If on Chapter Carousel (text_chapter_6 visible):
           - Centers Chapter 6 if below center, then taps center to enter Chapter 6.
        6. If stuck in wrong chapter (e.g. Chapter 7) with green back button:
           - Taps green back button (<<<) to return to Chapter Carousel.
        """
        # 1. If on difficulty selection screen
        if "diff_super" in meta or "diff_z_hard" in meta:
            self.handle_stage_selection(screen, w, h, meta)
            return True

        # 2. Target stage card is directly visible
        if self.target_stage == "area_39_3":
            s39_3 = meta.get("stage_area39_3") or self.vision.find_stage_area39_3(screen)
            if s39_3:
                self.log(t("tasks.link.select_stage_card_target", name="Area 39 Stage 3"))
                self.adb.tap(int(w * 0.50), s39_3[1], delay_after=2.0)
                return True
        elif self.target_stage == "area_35_1":
            s35_1 = meta.get("stage_area35_1") or self.vision.find_stage_area35_1(screen)
            if s35_1:
                self.log(t("tasks.link.select_stage_card_target", name="Area 35 Stage 1"))
                self.adb.tap(int(w * 0.50), s35_1[1], delay_after=2.0)
                return True

        # 3. Area badge is visible
        if self.target_stage == "area_39_3":
            b39 = meta.get("badge_area_39") or self.vision.find_badge_area_39(screen)
            if b39:
                self.log(t("tasks.link.select_quest_area", area="39"))
                self.adb.tap(int(w * 0.50), b39[1], delay_after=2.0)
                return True
        elif self.target_stage == "area_35_1":
            b35 = meta.get("badge_area_35") or self.vision.find_badge_area_35(screen)
            if b35:
                self.log(t("tasks.link.select_quest_area", area="35"))
                self.adb.tap(int(w * 0.50), b35[1], delay_after=2.0)
                return True

        # 4. Check if we are inside Chapter 6 Area List (badge_area_39 visible or header Chapter 6 at Y < 0.48 H)
        b39_any = meta.get("badge_area_39") or self.vision.find_badge_area_39(screen)
        c6 = meta.get("chapter_6") or self.vision.find_chapter_6(screen)
        is_inside_ch6 = b39_any is not None or (c6 is not None and c6[1] < int(h * 0.48))

        if is_inside_ch6 and self.target_stage == "area_35_1":
            # In Chapter 6 area list, Area 35 is further down: scroll inside scrollable region to reveal Area 35
            for _ in range(2):
                self.log(t("tasks.link.scrolling_quest_areas"))
                self.adb.swipe(
                    int(w * 0.50), int(h * 0.65), int(w * 0.50), int(h * 0.45), duration_ms=250
                )
                self.wait_check(1.0)
                curr = self.adb.screencap()
                b35 = self.vision.find_badge_area_35(curr)
                if b35:
                    self.log(t("tasks.link.select_quest_area", area="35"))
                    self.adb.tap(int(w * 0.50), b35[1], delay_after=2.0)
                    return True
            return True

        # 5. Chapter 6 is detected on the Carousel
        if c6 and not is_inside_ch6:
            # If Chapter 6 is below center in carousel (Y > 55% H)
            if c6[1] > int(h * 0.55):
                self.log(t("tasks.link.centering_chapter_6"))
                self.adb.swipe(
                    int(w * 0.50), int(h * 0.67), int(w * 0.50), int(h * 0.40), duration_ms=250
                )
                self.wait_check(1.0)
            self.log(t("tasks.link.entering_chapter_6"))
            self.adb.tap(int(w * 0.50), int(h * 0.50), delay_after=2.0)
            return True

        # 6. If inside stage list or wrong screen with green back button:
        back_btn = meta.get("back_green_button") or self.vision.find_template(
            screen, "button_back_green"
        )
        if back_btn and back_btn[1] < int(h * 0.88):
            # If targeting Area 35 Stage 1, we might be inside Area 35 stage list where Stage 1 is at the bottom!
            if self.target_stage == "area_35_1":
                for _ in range(3):
                    self.log(t("tasks.link.scrolling_stages"))
                    self.adb.swipe(
                        int(w * 0.50), int(h * 0.70), int(w * 0.50), int(h * 0.32), duration_ms=250
                    )
                    self.wait_check(1.0)
                    curr = self.adb.screencap()
                    s35_1 = self.vision.find_stage_area35_1(curr)
                    if s35_1:
                        self.log(t("tasks.link.select_stage_card_target", name="Area 35 Stage 1"))
                        self.adb.tap(int(w * 0.50), s35_1[1], delay_after=2.0)
                        return True

            # If not in target stage list, tap green back button to navigate backwards
            self.log(t("tasks.link.nav_back_to_carousel"))
            self.adb.tap(back_btn[0], back_btn[1], delay_after=2.0)
            return True

        return False

    def handle_stage_selection(self, screen: np.ndarray, w: int, h: int, meta: dict[str, Any]):
        """
        Handles stage difficulty selection (SUPER) and stage selection (Saiyan Training, Area 39-3, Area 35-1)
        with integrated Boost flag verification.
        """
        # 1. If on difficulty selection screen (SUPER / Z-HARD buttons present)
        if "diff_super" in meta or "diff_z_hard" in meta:
            # Control Boost feature according to user flag
            self.handle_boost_toggle(screen, w, h, meta)

            if "diff_super" in meta and self.preferred_difficulty == "super":
                sx, sy = meta["diff_super"]
                self.log(t("tasks.link.select_super_diff"))
                self.adb.tap(sx, sy, delay_after=2.0)
                return

            if "diff_z_hard" in meta and self.preferred_difficulty == "z_hard":
                zx, zy = meta["diff_z_hard"]
                self.log(t("tasks.link.select_zhard_diff"))
                self.adb.tap(zx, zy, delay_after=2.0)
                return

            if "diff_super" in meta:
                sx, sy = meta["diff_super"]
                self.log(t("tasks.link.select_super_diff"))
                self.adb.tap(sx, sy, delay_after=2.0)
                return

            if "diff_z_hard" in meta:
                zx, zy = meta["diff_z_hard"]
                self.log(t("tasks.link.select_zhard_diff"))
                self.adb.tap(zx, zy, delay_after=2.0)
                return

        # 2. If targeting specific stage in Stage List
        if self.target_stage == "area_39_3":
            s39_3 = meta.get("stage_area39_3") or self.vision.find_stage_area39_3(screen)
            if s39_3:
                self.log(t("tasks.link.select_stage_card_target", name="Area 39 Stage 3"))
                self.adb.tap(int(w * 0.50), s39_3[1], delay_after=2.0)
                return
            self.handle_quest_navigation(screen, w, h, meta)
            return

        if self.target_stage == "area_35_1":
            s35_1 = meta.get("stage_area35_1") or self.vision.find_stage_area35_1(screen)
            if s35_1:
                self.log(t("tasks.link.select_stage_card_target", name="Area 35 Stage 1"))
                self.adb.tap(int(w * 0.50), s35_1[1], delay_after=2.0)
                return
            self.handle_quest_navigation(screen, w, h, meta)
            return

        # Saiyan Training template match if chamber of spirit and time
        st_match = meta.get("stage_saiyan_training") or self.vision.find_stage_saiyan_training(
            screen
        )
        if st_match:
            self.log(t("tasks.link.select_saiyan_training"))
            self.adb.tap(st_match[0], st_match[1], delay_after=2.0)
            return

        # Fallback to Stage 1 at ~55% Y
        self.log(t("tasks.link.select_stage_card"))
        self.adb.tap(int(w * 0.50), int(h * 0.55), delay_after=2.0)

    def open_box_filter(
        self, screen_w: int, screen_h: int, meta: dict[str, Any] | None = None
    ) -> bool:
        """Opens the Character Box Filter / Sort modal from Team Formation screen via the yellow button in bottom right."""
        curr = self.adb.screencap()
        st, cur_meta = self.detector.detect(curr)
        meta = cur_meta or meta or {}

        # If on TEAM_CONFIRM, navigate to TEAM_EDIT first
        if st == GameState.TEAM_CONFIRM:
            if "team_formation_button" in meta:
                self.adb.tap(*meta["team_formation_button"], delay_after=2.5)
            elif "edit_team_button" in meta:
                self.adb.tap(*meta["edit_team_button"], delay_after=2.5)
            else:
                self.adb.tap(int(screen_w * 0.80), int(screen_h * 0.49), delay_after=2.5)
            curr = self.adb.screencap()
            st, cur_meta = self.detector.detect(curr)
            meta = cur_meta or meta

        self.log(t("tasks.link.opening_box_filter"))
        yellow_btn = self.vision.find_yellow_sort_button(curr)
        if yellow_btn:
            fx, fy = yellow_btn
        elif "tag_sort_released" in meta:
            fx, fy = meta["tag_sort_released"]
        else:
            fx = int(screen_w * 0.80)
            fy = int(screen_h * 0.958)
        self.adb.tap(fx, fy, delay_after=2.0)

        # Verify filter modal is open
        screen = self.adb.screencap()
        st, _ = self.detector.detect(screen)
        if st == GameState.FILTER_MODAL or self.vision.is_filter_dialog_open(screen):
            return True
        # Retry tap once if needed
        self.adb.tap(fx, fy, delay_after=2.0)
        screen = self.adb.screencap()
        return self.vision.is_filter_dialog_open(screen)

    def set_box_link_filter(
        self,
        mode: str = "level_up_possible",
        screen_w: int | None = None,
        screen_h: int | None = None,
    ) -> bool:
        """
        Configures the Display Order and Link Skill Level filter in the Filter / Sort modal:
        1. Ensures Filter Modal is opened via the yellow sort button in bottom right.
        2. Verifies 'Released' is selected under Display Order (taps it if not).
        3. Swipes up to scroll down to the 'Link Skill Level' section.
        4. Verifies 'Level Up Possible' is active (and 'All at Max Level' is deactivated).
        5. Taps OK to save and close the modal.
        """
        curr_screen = self.adb.screencap()
        h, w = curr_screen.shape[:2]
        if screen_w is None:
            screen_w = int(w)
        if screen_h is None:
            screen_h = int(h)

        # 1. Ensure Filter Modal is open
        if not self.vision.is_filter_dialog_open(curr_screen):
            opened = self.open_box_filter(screen_w, screen_h)
            if not opened:
                return False
            curr_screen = self.adb.screencap()

        # 2. Check Display Order 'Released' at top of dialog
        if not self.vision.is_filter_released_selected(curr_screen):
            self.log(t("tasks.link.setting_display_order_released"))
            rel_x = int(screen_w * 0.46)
            rel_y = int(screen_h * 0.40)
            self.adb.tap(rel_x, rel_y, delay_after=0.8)
            curr_screen = self.adb.screencap()
        else:
            self.log(t("tasks.link.released_already_selected"))

        # 2b. Configure Card Rarity filter if UR/LR flags are requested
        if self.filter_ur or self.filter_lr:
            ur_str = "ON" if self.filter_ur else "OFF"
            lr_str = "ON" if self.filter_lr else "OFF"
            self.log(t("tasks.link.setting_rarity_filter", ur=ur_str, lr=lr_str))

            # UR toggle
            ur_is_sel = self.vision.is_filter_ur_selected(curr_screen)
            if (self.filter_ur and not ur_is_sel) or (not self.filter_ur and ur_is_sel):
                ur_x, ur_y = self.vision.get_filter_ur_coords(curr_screen)
                self.adb.tap(ur_x, ur_y, delay_after=0.6)
                curr_screen = self.adb.screencap()

            # LR toggle
            lr_is_sel = self.vision.is_filter_lr_selected(curr_screen)
            if (self.filter_lr and not lr_is_sel) or (not self.filter_lr and lr_is_sel):
                lr_x, lr_y = self.vision.get_filter_lr_coords(curr_screen)
                self.adb.tap(lr_x, lr_y, delay_after=0.6)
                curr_screen = self.adb.screencap()

        # 3. Scroll down to Link Skill Level section
        self.log(t("tasks.link.scrolling_to_link_filter"))
        self.adb.swipe(
            int(screen_w * 0.50),
            int(screen_h * 0.68),
            int(screen_w * 0.50),
            int(screen_h * 0.22),
            duration_ms=300,
        )
        self.wait_check(1.0)

        # Ensure Link Skill Level section is visible
        scrolled_screen = self.adb.screencap()
        status = self.vision.get_link_level_filter_status(scrolled_screen)
        if not status.get("has_link_section", False):
            self.adb.swipe(
                int(screen_w * 0.50),
                int(screen_h * 0.68),
                int(screen_w * 0.50),
                int(screen_h * 0.30),
                duration_ms=250,
            )
            self.wait_check(1.0)
            scrolled_screen = self.adb.screencap()
            status = self.vision.get_link_level_filter_status(scrolled_screen)

        lu_sel = status["level_up_possible"]["selected"]
        max_sel = status["all_at_max"]["selected"]
        lu_coords = status["level_up_possible"]["coords"]
        max_coords = status["all_at_max"]["coords"]

        # 4. Toggle buttons to match target mode
        if mode == "level_up_possible":
            self.log(t("tasks.link.setting_filter_level_up"))
            if not lu_sel:
                self.adb.tap(lu_coords[0], lu_coords[1], delay_after=0.6)
            if max_sel:
                self.adb.tap(max_coords[0], max_coords[1], delay_after=0.6)
        elif mode == "all_max":
            self.log(t("tasks.link.setting_filter_all_max"))
            if not max_sel:
                self.adb.tap(max_coords[0], max_coords[1], delay_after=0.6)
            if lu_sel:
                self.adb.tap(lu_coords[0], lu_coords[1], delay_after=0.6)

        # 5. Confirm with OK button
        ok_coords = status["ok_button"] or (int(screen_w * 0.50), int(screen_h * 0.93))
        self.adb.tap(ok_coords[0], ok_coords[1], delay_after=2.0)
        self.log(t("tasks.link.filter_applied"))
        self.box_filter_initialized = True
        return True

    def check_team_links_via_filter(self, screen_w: int, screen_h: int) -> dict[int, bool]:
        """
        Directly determines link max status for the entire team (slots 1 to 6)
        using Dokkan's built-in 'All at Max Level' filter.
        Returns dict mapping slot_number (1..6) -> is_maxed (True/False).
        """
        self.log(t("tasks.link.checking_team_max_status"))
        # Set filter to All at Max Level
        self.set_box_link_filter("all_max", screen_w, screen_h)
        self.wait_check(1.5)

        # Inspect which team badges are visible in the filtered box
        box_screen = self.adb.screencap()
        maxed_slots = self.vision.get_team_slots_in_box(box_screen)

        status: dict[int, bool] = {}
        for slot in range(1, 7):
            is_max = slot in maxed_slots
            status[slot] = is_max
            if is_max:
                self.log(t("tasks.link.slot_links_maxed", slot=slot))
            else:
                self.log(t("tasks.link.slot_links_unmaxed", slot=slot))

        # Restore filter to Level Up Possible so replacements can be chosen
        self.set_box_link_filter("level_up_possible", screen_w, screen_h)
        return status

    def rebuild_team_from_box(
        self, screen_w: int, screen_h: int, meta: dict[str, Any] | None = None
    ) -> bool:
        """
        Implements pre-stage team management before starting the stage:
        1. Opens Team Formation from the pre-battle screen (TEAM_CONFIRM).
        2. Taps yellow Display Order & Filter button in bottom-right ("Released").
        3. Verifies 'Released' Display Order is selected.
        4. Scrolls down to 'Link Skill Level' and ensures 'Level Up Possible' is active.
        5. Confirms with OK.
        6. Taps 'Remove All' on the team deck to clear all characters.
        7. Inserts all 6 cards starting from top-to-bottom and left-to-right (Row 1 Cols 1..5, Row 2 Col 1).
        8. Confirms the new team formation and returns to TEAM_CONFIRM.
        """
        curr_screen = self.adb.screencap()
        st, cur_meta = self.detector.detect(curr_screen)
        meta = cur_meta or meta or {}

        # 1. If on TEAM_CONFIRM, navigate to TEAM_EDIT first
        if st == GameState.TEAM_CONFIRM:
            self.log(t("tasks.link.rebuilding_team_start"))
            if "team_formation_button" in meta:
                self.adb.tap(*meta["team_formation_button"], delay_after=2.5)
            elif "edit_team_button" in meta:
                self.adb.tap(*meta["edit_team_button"], delay_after=2.5)
            else:
                self.adb.tap(int(screen_w * 0.80), int(screen_h * 0.49), delay_after=2.5)
            curr_screen = self.adb.screencap()
            st, cur_meta = self.detector.detect(curr_screen)
            meta = cur_meta or meta

        # 2. Check and set filter ONLY on the very first run (or if explicitly configured to ensure filter every run)
        if not self.box_filter_initialized or self.ensure_filter_every_run:
            rarity_desc = (
                "UR + LR"
                if (self.filter_ur and self.filter_lr)
                else ("UR" if self.filter_ur else ("LR" if self.filter_lr else "All"))
            )
            self.log(t("tasks.link.filter_first_run_init", rarities=rarity_desc))
            self.set_box_link_filter("level_up_possible", screen_w, screen_h)
            curr_screen = self.adb.screencap()
            st, cur_meta = self.detector.detect(curr_screen)
            meta = cur_meta or meta
        else:
            self.log(t("tasks.link.filter_reused"))

        # 3. Tap 'Remove All' button on the team deck
        self.log(t("tasks.link.team_remove_all"))
        deck_rm = meta.get("button_deck_remove_all") or self.vision.find_deck_remove_all(
            curr_screen
        )
        if deck_rm:
            rx, ry = deck_rm
        else:
            rx, ry = int(screen_w * 0.91), int(screen_h * 0.80)
        self.adb.tap(rx, ry, delay_after=0.8)

        # Check for popup confirmation OK
        popup_screen = self.adb.screencap()
        ok_match = self.vision.find_ok_button(popup_screen)
        if ok_match:
            self.adb.tap(ok_match[0], ok_match[1], delay_after=0.8)
        self.wait_check(0.8)

        # 4. Insert 6 cards from the top, top-to-bottom and left-to-right
        self.log(t("tasks.link.team_inserting_cards"))
        curr_box = self.adb.screencap()
        candidate_coords = self.vision.get_top_box_card_coords(curr_box, count=10)
        for idx in range(min(6, len(candidate_coords))):
            cx, cy = candidate_coords[idx]
            self.log(t("tasks.link.team_card_inserted", idx=idx + 1, x=cx, y=cy))
            self.adb.tap(cx, cy, delay_after=0.45)

        # Check if all 6 slots were populated
        fresh = self.adb.screencap()
        slots_filled = self.vision.get_team_slots_in_box(fresh)
        if len(slots_filled) < 6:
            for cand in candidate_coords[6:]:
                if len(slots_filled) >= 6:
                    break
                self.adb.tap(cand[0], cand[1], delay_after=0.45)
                fresh = self.adb.screencap()
                slots_filled = self.vision.get_team_slots_in_box(fresh)

        # 5. Confirm team formation
        confirm_match = self.vision.find_template(fresh, "button_confirm_formation")
        if confirm_match:
            cx, cy = confirm_match[0], confirm_match[1]
        elif "button_confirm_formation" in meta:
            cx, cy = meta["button_confirm_formation"]
        else:
            cx, cy = (
                int(screen_w * self.box_confirm_coords[0]),
                int(screen_h * self.box_confirm_coords[1]),
            )

        self.log(t("tasks.link.confirm_char_select"))
        self.adb.tap(cx, cy, delay_after=2.5)

        # Verify return to TEAM_CONFIRM
        chk = self.adb.screencap()
        chk_st, _ = self.detector.detect(chk)
        if chk_st == GameState.TEAM_EDIT:
            self.log(t("tasks.link.confirm_team"))
            c_match = self.vision.find_template(chk, "button_confirm_formation")
            if c_match:
                self.adb.tap(c_match[0], c_match[1], delay_after=2.5)
            else:
                self.adb.tap(int(screen_w * 0.88), int(screen_h * 0.88), delay_after=2.5)

        self.log(t("tasks.link.team_rebuild_complete"))
        self._team_prepared_for_run = True
        return True

    def check_and_swap_team_via_filter(
        self, screen_w: int, screen_h: int, meta: dict[str, Any] | None = None
    ) -> bool:
        """
        Authoritative team link verification and automatic swap routine:
        1. Navigates to TEAM_EDIT from TEAM_CONFIRM if needed.
        2. Filters box by 'All at Max Level' to identify maxed team members.
        3. Filters box back to 'Level Up Possible' (guaranteeing unmaxed candidates).
        4. Swaps any maxed units (not in protected_slots) with unmaxed cards.
        5. Confirms team formation and returns cleanly to TEAM_CONFIRM.
        Returns True if any unit was swapped, False otherwise.
        """
        if not self.auto_swap:
            return False

        curr_screen = self.adb.screencap()
        st, cur_meta = self.detector.detect(curr_screen)
        meta = cur_meta or meta or {}

        # 1. Ensure we are in TEAM_EDIT
        if st == GameState.TEAM_CONFIRM:
            if "team_formation_button" in meta:
                self.adb.tap(*meta["team_formation_button"], delay_after=2.5)
            elif "edit_team_button" in meta:
                self.adb.tap(*meta["edit_team_button"], delay_after=2.5)
            else:
                self.adb.tap(int(screen_w * 0.80), int(screen_h * 0.49), delay_after=2.5)
            curr_screen = self.adb.screencap()
            st, cur_meta = self.detector.detect(curr_screen)
            meta = cur_meta or meta

        # 2. Check team link status via All at Max Level filter
        team_status = self.check_team_links_via_filter(screen_w, screen_h)
        maxed_slots = [slot for slot, is_max in team_status.items() if is_max]

        # 3. Swap any maxed swappable units
        swapped_any = False
        modern_slot_xs = [0.097, 0.231, 0.366, 0.500, 0.634, 0.769]
        slot_y = 0.75

        for slot_number in maxed_slots:
            if slot_number in self.protected_slots:
                continue

            slot_idx = slot_number - 1
            self.log(t("tasks.link.unit_maxed_swap", slot=slot_number))

            # Tap the slot in the deck
            if 0 <= slot_idx < len(modern_slot_xs):
                sx = modern_slot_xs[slot_idx]
                self.log(t("tasks.link.open_slot_select", slot=slot_number))
                self.adb.tap(int(screen_w * sx), int(screen_h * slot_y), delay_after=1.2)

            # Pick first unmaxed card
            fresh_box = self.adb.screencap()
            card_x, card_y = self.vision.find_first_unselected_card(fresh_box)
            self.log(t("tasks.link.select_unselected_card", x=card_x, y=card_y))
            self.adb.tap(card_x, card_y, delay_after=1.2)
            swapped_any = True

        # 4. Confirm Team Formation and return to TEAM_CONFIRM
        fresh_screen = self.adb.screencap()
        confirm_match = self.vision.find_template(fresh_screen, "button_confirm_formation")
        if confirm_match:
            cx, cy = confirm_match[0], confirm_match[1]
        elif "button_confirm_formation" in meta:
            cx, cy = meta["button_confirm_formation"]
        else:
            cx, cy = (
                int(screen_w * self.box_confirm_coords[0]),
                int(screen_h * self.box_confirm_coords[1]),
            )

        self.log(t("tasks.link.confirm_char_select"))
        self.adb.tap(cx, cy, delay_after=2.5)

        # Verify return to TEAM_CONFIRM (tap back if still in TEAM_EDIT)
        chk = self.adb.screencap()
        chk_st, _ = self.detector.detect(chk)
        if chk_st == GameState.TEAM_EDIT:
            self.log(t("tasks.link.confirm_team"))
            self.adb.tap(int(screen_w * 0.15), int(screen_h * 0.86), delay_after=2.0)

        return swapped_any

    def swap_maxed_unit(self, slot_idx: int, screen_w: int, screen_h: int, meta: dict[str, Any]):
        """Legacy helper kept for backward compatibility."""
        human_slot = slot_idx + 1
        self.log(t("tasks.link.unit_maxed_swap", slot=human_slot))
        self.check_and_swap_team_via_filter(screen_w, screen_h, meta)

    def check_and_swap_team_if_needed(
        self, _screen: Any, screen_w: int, screen_h: int, meta: dict[str, Any]
    ) -> bool:
        """
        Inspects all swappable slots (0 to 5) for MAX link level badges using the in-game filter.
        If a maxed slot is found, performs swap and returns True.
        """
        if not self.auto_swap:
            return False
        return self.check_and_swap_team_via_filter(screen_w, screen_h, meta)

    def run(self):
        """Main Link Level farm loop."""
        self.is_running = True
        self.runs_completed = 0
        event_name = (
            self.stage_name
            or (self.target_event.get("name") if self.target_event else None)
            or "Link Level Stage"
        )
        runs_display = str(self.runs_target) if self.runs_target is not None else "∞"
        self.log(t("tasks.link.started", runs=runs_display, event=event_name))
        rarity_tags = []
        if self.filter_ur:
            rarity_tags.append("UR")
        if self.filter_lr:
            rarity_tags.append("LR")
        if rarity_tags:
            self.log(t("tasks.link.rarity_active", rarities=" + ".join(rarity_tags)))
        if self.auto_swap:
            self.log(t("tasks.link.auto_swap_hint"))

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
            except Exception as e:
                self.log(t("tasks.stage.screencap_error", error=str(e)))
                self.wait_check(2.0)
                continue

            h, w = screen.shape[:2]
            state, meta = self.detector.detect(screen)
            self.current_state = state

            # 1. Navigation from Home / Mode Select
            if state == GameState.HOME_SCREEN:
                unknown_counter = 0
                self.log(t("tasks.link.nav_from_home"))
                if "start_button" in meta:
                    self.adb.tap(*meta["start_button"], delay_after=2.0)
                else:
                    self.adb.tap(int(w * 0.50), int(h * 0.65), delay_after=2.0)
                self.wait_check(1.5)

            elif state == GameState.MODE_SELECT:
                unknown_counter = 0
                if self.target_stage in ("area_39_3", "area_35_1"):
                    self.log(t("tasks.link.nav_to_quest", stage=self.stage_name))
                    if "quest_button" in meta:
                        self.adb.tap(*meta["quest_button"], delay_after=2.0)
                    else:
                        quest_btn = self.vision.find_quest_button(screen)
                        if quest_btn:
                            self.adb.tap(quest_btn[0], quest_btn[1], delay_after=2.0)
                        else:
                            self.adb.tap(int(w * 0.25), int(h * 0.54), delay_after=2.0)
                    self.wait_check(2.0)
                else:
                    self.log(t("tasks.link.nav_from_mode"))
                    if "event_button" in meta:
                        self.adb.tap(*meta["event_button"], delay_after=2.0)
                    else:
                        self.adb.tap(int(w * 0.50), int(h * 0.35), delay_after=2.0)
                    self.wait_check(1.5)

            # 2. Event Select screen (Bonus / Growth tabs)
            elif state == GameState.EVENT_SELECT:
                unknown_counter = 0
                if in_run and battle_seen:
                    self.runs_completed += 1
                    in_run = False
                    battle_seen = False
                    self._needs_team_link_check = True
                    self._team_prepared_for_run = False
                    tot_display = self.runs_target if self.runs_target is not None else "∞"
                    self.log(
                        t("tasks.link.run_completed", curr=self.runs_completed, tot=tot_display)
                    )
                    self.on_run_complete(
                        self.runs_completed, self.runs_target if self.runs_target is not None else 0
                    )

                if self.target_stage in ("area_39_3", "area_35_1"):
                    self.log(t("tasks.link.nav_to_quest", stage=self.stage_name))
                    back_btn = meta.get("back_green_button")
                    if back_btn:
                        self.adb.tap(*back_btn, delay_after=2.0)
                    else:
                        self.adb.tap(int(w * 0.14), int(h * 0.79), delay_after=2.0)
                    self.wait_check(1.5)
                    continue

                # Find and enter the event banner
                found = self.navigate_to_event_banner(screen, w, h, meta)
                if not found:
                    self.log(t("tasks.link.event_not_found_stop"))
                    self.stop()
                    break
                self.wait_check(2.5)

            # 2b. Quest Dokkan Story Navigation
            elif state == GameState.QUEST_SELECT:
                unknown_counter = 0
                if in_run and battle_seen:
                    self.runs_completed += 1
                    in_run = False
                    battle_seen = False
                    self._needs_team_link_check = True
                    self._team_prepared_for_run = False
                    tot_display = self.runs_target if self.runs_target is not None else "∞"
                    self.log(
                        t("tasks.link.run_completed", curr=self.runs_completed, tot=tot_display)
                    )
                    self.on_run_complete(
                        self.runs_completed, self.runs_target if self.runs_target is not None else 0
                    )

                self.handle_quest_navigation(screen, w, h, meta)
                self.wait_check(2.0)

            # 3. Stage & Difficulty Selection
            elif state == GameState.STAGE_SELECT:
                unknown_counter = 0
                if in_run and battle_seen:
                    self.runs_completed += 1
                    in_run = False
                    battle_seen = False
                    self._needs_team_link_check = True
                    self._team_prepared_for_run = False
                    tot_display = self.runs_target if self.runs_target is not None else "∞"
                    self.log(
                        t("tasks.link.run_completed", curr=self.runs_completed, tot=tot_display)
                    )
                    self.on_run_complete(
                        self.runs_completed, self.runs_target if self.runs_target is not None else 0
                    )

                if self.runs_target is not None and self.runs_completed >= self.runs_target:
                    self.log(t("tasks.link.runs_target_reached", curr=self.runs_completed))
                    break

                self.handle_stage_selection(screen, w, h, meta)
                self.wait_check(2.0)

            # 4. Friend Selection
            elif state == GameState.FRIEND_SELECT:
                unknown_counter = 0
                self.handle_friend_select(w, h, meta)
                self.wait_check(2.0)

            # 5. Team Confirmation & Pre-Battle
            elif state == GameState.TEAM_CONFIRM:
                unknown_counter = 0

                # Pre-stage team management: rebuild team or auto-swap maxed units before starting
                if not self._team_prepared_for_run:
                    if self.rebuild_team_every_run:
                        self.rebuild_team_from_box(w, h, meta)
                        self._team_prepared_for_run = True
                        continue
                    elif self.auto_swap and (
                        not self.box_filter_initialized or self._needs_team_link_check
                    ):
                        self.check_and_swap_team_via_filter(w, h, meta)
                        self.box_filter_initialized = True
                        self._needs_team_link_check = False
                        self._team_prepared_for_run = True
                        continue

                self.tap_start_team(w, h, meta)
                in_run = True
                battle_seen = False
                self.wait_check(3.0)

            # 5b. Team Formation / Edit screen (if currently in team edit)
            elif state == GameState.TEAM_EDIT:
                unknown_counter = 0
                if self.rebuild_team_every_run and not self._team_prepared_for_run:
                    self.rebuild_team_from_box(w, h, meta)
                    continue
                c_match = self.vision.find_template(screen, "button_confirm_formation")
                if c_match:
                    self.adb.tap(c_match[0], c_match[1], delay_after=2.5)
                else:
                    self.adb.tap(int(w * 0.88), int(h * 0.88), delay_after=2.5)
                self.wait_check(1.5)

            # 6. Stamina Refill
            elif state == GameState.STAMINA_EMPTY:
                unknown_counter = 0
                refill_ok = self.handle_stamina_refill(w, h, meta)
                if not refill_ok:
                    self.stop()
                    break
                self.wait_check(2.0)

            # 7. Map Screen
            elif state == GameState.MAP_SCREEN:
                unknown_counter = 0
                in_run = True
                battle_seen = True
                self.handle_map(w, h, meta)
                self.wait_check(1.5)

            # 8. Battle Screen
            elif state == GameState.BATTLE_SCREEN:
                unknown_counter = 0
                in_run = True
                battle_seen = True
                self.handle_battle(w, h, meta)
                self.wait_check(1.5)

            # 9. KO Screen
            elif state == GameState.KO_SCREEN:
                unknown_counter = 0
                battle_seen = True
                self.adb.tap(int(w * 0.50), int(h * 0.50), delay_after=0.8)

            # 10. Results Screen & Link Level Up popups
            elif state == GameState.RESULTS_SCREEN:
                unknown_counter = 0
                if in_run and battle_seen:
                    self.runs_completed += 1
                    in_run = False
                    battle_seen = False
                    self._needs_team_link_check = True
                    self._team_prepared_for_run = False
                    tot_display = self.runs_target if self.runs_target is not None else "∞"
                    self.log(
                        t("tasks.link.run_completed", curr=self.runs_completed, tot=tot_display)
                    )
                    self.on_run_complete(
                        self.runs_completed, self.runs_target if self.runs_target is not None else 0
                    )

                    if self.runs_target is not None and self.runs_completed >= self.runs_target:
                        self.log(t("tasks.link.runs_target_reached", curr=self.runs_completed))
                        self.dismiss_results_and_popups(w, h, meta, prefer_again=False)
                        self.stop()
                        break

                prefer_again = self.use_attempt_again and (
                    self.runs_target is None or self.runs_completed < self.runs_target
                )
                self.dismiss_results_and_popups(w, h, meta, prefer_again=prefer_again)
                self.wait_check(1.2)

            # 11. Friend Request
            elif state == GameState.FRIEND_REQUEST:
                unknown_counter = 0
                self.dismiss_results_and_popups(w, h, meta, prefer_again=False)
                if in_run and battle_seen:
                    self.runs_completed += 1
                    in_run = False
                    battle_seen = False
                    self._needs_team_link_check = True
                    self._team_prepared_for_run = False
                    tot_display = self.runs_target if self.runs_target is not None else "∞"
                    self.log(
                        t("tasks.link.run_completed", curr=self.runs_completed, tot=tot_display)
                    )
                    self.on_run_complete(
                        self.runs_completed, self.runs_target if self.runs_target is not None else 0
                    )
                self.wait_check(2.0)

            # 12. Game Over
            elif state == GameState.GAME_OVER:
                self.log(t("tasks.link.unexpected_game_over"))
                self.adb.tap(int(w * 0.35), int(h * 0.60), delay_after=1.0)
                self.stop()
                break

            else:
                unknown_counter += 1
                # Check for "You cannot make any more attempts" or limited attempt dialog OK
                if "ok_button" in meta:
                    self.log(t("tasks.link.popup_dismiss_ok"))
                    self.adb.tap(*meta["ok_button"], delay_after=1.5)
                elif self.target_stage in (
                    "area_39_3",
                    "area_35_1",
                ) and self.handle_quest_navigation(screen, w, h, meta):
                    unknown_counter = 0
                    self.wait_check(2.0)
                elif in_run:
                    self.log(t("tasks.stage.post_stage_advance", cycles=unknown_counter))
                    self.adb.tap(int(w * 0.50), int(h * 0.50), delay_after=0.4)
                    self.adb.tap(int(w * 0.50), int(h * 0.88), delay_after=1.0)
                elif unknown_counter % 5 == 0:
                    # Tap center if stuck on stage list
                    self.log(t("tasks.link.stage_card_advance", cycles=unknown_counter))
                    self.adb.tap(int(w * 0.50), int(h * 0.55), delay_after=0.8)

            self.wait_check(loop_delay)

        self.is_running = False
        self.log(t("tasks.link.farming_finished", curr=self.runs_completed))
