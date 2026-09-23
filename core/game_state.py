import enum
from typing import Any

import numpy as np

from core.vision import Vision


class GameState(enum.Enum):
    UNKNOWN = "UNKNOWN"
    LOADING = "LOADING"
    TITLE_SCREEN = "TITLE_SCREEN"
    HOME_SCREEN = "HOME_SCREEN"
    STAGE_SELECT = "STAGE_SELECT"
    FRIEND_SELECT = "FRIEND_SELECT"
    TEAM_CONFIRM = "TEAM_CONFIRM"
    STAMINA_EMPTY = "STAMINA_EMPTY"
    MAP_SCREEN = "MAP_SCREEN"
    BATTLE_SCREEN = "BATTLE_SCREEN"
    DOKKAN_MODE = "DOKKAN_MODE"
    KO_SCREEN = "KO_SCREEN"
    RESULTS_SCREEN = "RESULTS_SCREEN"
    FRIEND_REQUEST = "FRIEND_REQUEST"
    GAME_OVER = "GAME_OVER"
    EZA_SELECT = "EZA_SELECT"
    Z_BATTLE_LIST = "Z_BATTLE_LIST"
    EVENT_SELECT = "EVENT_SELECT"
    MODE_SELECT = "MODE_SELECT"
    TEAM_EDIT = "TEAM_EDIT"
    CHARACTER_BOX = "CHARACTER_BOX"
    FILTER_MODAL = "FILTER_MODAL"


class StateDetector:
    """Detects current screen state in Dokkan Battle."""

    def __init__(self, vision: Vision):
        self.vision = vision

    def detect(self, screen: np.ndarray) -> tuple[GameState, dict[str, Any]]:
        """
        Analyzes the screen and returns (GameState, action_metadata).
        action_metadata contains coordinates of relevant clickable elements (e.g. 'start_button', 'ok_button').
        """
        h, w = screen.shape[:2]
        meta: dict[str, Any] = {"screen_width": w, "screen_height": h}

        # 1. Check for popups first: OK button / Cancel / Close
        # Dokkan popups have distinct OK / CANCEL buttons
        ok_match = self.vision.find_ok_button(screen)
        if ok_match:
            meta["ok_button"] = (ok_match[0], ok_match[1])

        cancel_match = self.vision.find_template(screen, "button_cancel")
        if cancel_match:
            meta["cancel_button"] = (cancel_match[0], cancel_match[1])

        close_match = self.vision.find_template(screen, "button_close")
        if close_match:
            meta["close_button"] = (close_match[0], close_match[1])
            if "ok_button" not in meta:
                meta["ok_button"] = (close_match[0], close_match[1])

        dont_send_match = self.vision.find_template(screen, "button_dont_send")
        if dont_send_match:
            meta["dont_send_button"] = (dont_send_match[0], dont_send_match[1])

        back_green_match = self.vision.find_template(screen, "button_back_green", threshold=0.80)
        if back_green_match:
            meta["back_green_button"] = (back_green_match[0], back_green_match[1])

        # 2. Friend Request Popup
        if dont_send_match or self.vision.find_template(screen, "popup_friend_request"):
            return (GameState.FRIEND_REQUEST, meta)

        # 3. Stamina Empty Popup
        stamina_empty_match = self.vision.find_template(screen, "popup_stamina_empty") or self.vision.find_template(
            screen, "header_restore_sta"
        )
        meat_match = self.vision.find_template(screen, "button_use_meat")
        if stamina_empty_match or meat_match:
            if meat_match:
                meta["meat_button"] = (meat_match[0], meat_match[1])
            return (GameState.STAMINA_EMPTY, meta)

        # 4. Game Over Popup
        game_over_match = self.vision.find_template(screen, "popup_game_over")
        if game_over_match:
            return (GameState.GAME_OVER, meta)

        # 4b. Filter / Sort Modal (Display Order / Filter Select dialog)
        filter_modal_match = self.vision.find_template(screen, "button_remove_all") or self.vision.find_template(
            screen, "header_link_skill_level"
        )
        if filter_modal_match:
            if "ok_button" in meta:
                meta["filter_ok_button"] = meta["ok_button"]
            return (GameState.FILTER_MODAL, meta)

        # 5. Results Screen or Modal OK / Close Dialog
        results_match = self.vision.find_template(screen, "header_clear") or self.vision.find_template(
            screen, "header_rewards"
        )
        if results_match or ok_match or close_match:
            return (GameState.RESULTS_SCREEN, meta)

        # 6. Team Confirmation Screen (Large Start button at bottom right)
        start_match = self.vision.find_template(screen, "button_start")
        if start_match:
            meta["start_button"] = (start_match[0], start_match[1])
            edit_team = self.vision.find_template(screen, "button_edit_team")
            if edit_team:
                meta["edit_team_button"] = (edit_team[0], edit_team[1])
            formation_btn = self.vision.find_template(screen, "button_team_formation")
            if formation_btn:
                meta["team_formation_button"] = (formation_btn[0], formation_btn[1])
            switch_disp = self.vision.find_template(screen, "button_switch_display")
            if switch_disp:
                meta["switch_display_button"] = (switch_disp[0], switch_disp[1])
            return (GameState.TEAM_CONFIRM, meta)

        # 6b. Team Edit Screen (Team Formation / Deck Editor)
        confirm_btn = self.vision.find_template(screen, "button_confirm_formation")
        deck_remove_all = self.vision.find_template(screen, "button_deck_remove_all")
        team_edit_match = (
            self.vision.find_template(screen, "header_team_formation")
            or self.vision.find_template(screen, "button_auto_formation")
            or confirm_btn
            or deck_remove_all
        )
        if team_edit_match:
            if confirm_btn:
                meta["button_confirm_formation"] = (confirm_btn[0], confirm_btn[1])
            if deck_remove_all:
                meta["button_deck_remove_all"] = (deck_remove_all[0], deck_remove_all[1])
            tag_sort_rel = self.vision.find_yellow_sort_button(screen)
            if tag_sort_rel:
                meta["tag_sort_released"] = tag_sort_rel
                meta["filter_button"] = tag_sort_rel
            else:
                meta["filter_button"] = (int(w * 0.80), int(h * 0.958))
            filter_on = self.vision.find_template(screen, "tag_filter_on")
            if filter_on:
                meta["filter_on"] = (filter_on[0], filter_on[1])
            return (GameState.TEAM_EDIT, meta)

        # 6c. Character Box / Character Selection List
        box_match = self.vision.find_template(screen, "header_character_list") or self.vision.find_template(
            screen, "button_filter"
        )
        if box_match:
            return (GameState.CHARACTER_BOX, meta)

        # 7. Friend Selection Screen
        friend_header = self.vision.find_template(screen, "header_select_friend")
        refresh_match = self.vision.find_template(
            screen, "button_friend_refresh", threshold=0.90
        ) or self.vision.find_template(screen, "button_friend_auto")
        if friend_header or refresh_match:
            if refresh_match:
                meta["friend_refresh_button"] = (refresh_match[0], refresh_match[1])
            return (GameState.FRIEND_SELECT, meta)

        # 8. Battle Screen (Auto Battle toggle, Battle Menu, Item button, x2 Speed)
        battle_menu = self.vision.find_template(screen, "button_battle_menu", threshold=0.75)
        auto_battle = (
            self.vision.find_template(screen, "button_auto_battle", threshold=0.75)
            or self.vision.find_template(screen, "battle_auto_on")
            or self.vision.find_template(screen, "battle_auto_off")
        )
        item_button = self.vision.find_template(screen, "button_item", threshold=0.75)
        speed_toggle = self.vision.find_template(screen, "battle_speed_2x") or self.vision.find_template(
            screen, "battle_speed_1x"
        )
        if battle_menu or auto_battle or item_button or speed_toggle:
            if auto_battle:
                meta["auto_button"] = (auto_battle[0], auto_battle[1])
            if speed_toggle:
                meta["speed_button"] = (speed_toggle[0], speed_toggle[1])
            if battle_menu:
                meta["battle_menu"] = (battle_menu[0], battle_menu[1])
            return (GameState.BATTLE_SCREEN, meta)

        # 9. Map / Quest Board Screen (Dice buttons 1, 2, 3 or Auto Map button)
        auto_map = self.vision.find_template(screen, "map_auto_on") or self.vision.find_template(screen, "map_auto_off")
        if auto_map:
            meta["auto_map_button"] = (auto_map[0], auto_map[1])
            return (GameState.MAP_SCREEN, meta)

        # 10. EZA (Extreme Z-Battle) Level Select Screen
        eza_battle_info = self.vision.find_template(screen, "button_eza_battle_info")
        eza_select_lv = self.vision.find_template(screen, "button_eza_select_lv")
        eza_fight = self.vision.find_template(screen, "button_eza_fight")
        text_fight = self.vision.find_template(screen, "text_eza_fight")
        eza_screen = (
            eza_battle_info
            or eza_select_lv
            or eza_fight
            or text_fight
            or self.vision.find_template(screen, "button_eza_challenge")
            or self.vision.find_template(screen, "button_eza_next_level")
        )
        if eza_screen:
            if eza_fight:
                meta["eza_button"] = (int(eza_fight[0]), int(eza_fight[1]))
            elif text_fight:
                meta["eza_button"] = (int(text_fight[0]), int(text_fight[1] + 25))
            else:
                meta["eza_button"] = (int(w * 0.50), int(h * 0.69))
            return (GameState.EZA_SELECT, meta)

        # 10b. Z-Battle List Screen (Extreme Z-Battle event selection list)
        zbattle_active = self.vision.find_template(screen, "tab_zbattle_active")
        if zbattle_active:
            meta["zbattle_tab"] = (zbattle_active[0], zbattle_active[1])
            return (GameState.Z_BATTLE_LIST, meta)

        # 10c. Event Select Screen (other tabs active: Story, Growth, Challenge, Bonus)
        zbattle_inactive = self.vision.find_template(screen, "tab_zbattle_inactive")
        if zbattle_inactive:
            meta["zbattle_tab"] = (zbattle_inactive[0], zbattle_inactive[1])
            bonus_tab = self.vision.find_template(screen, "tab_bonus")
            if bonus_tab:
                meta["bonus_tab"] = (bonus_tab[0], bonus_tab[1])
            growth_tab = self.vision.find_template(screen, "tab_growth")
            if growth_tab:
                meta["growth_tab"] = (growth_tab[0], growth_tab[1])
            return (GameState.EVENT_SELECT, meta)

        # 10d. Mode Select Menu (Start pressed -> Quest, Event, Dokkan Frontier)
        button_event = self.vision.find_template(screen, "button_event")
        if button_event:
            meta["event_button"] = (button_event[0], button_event[1])
            return (GameState.MODE_SELECT, meta)

        # 11. KO Animation Screen
        ko_match = self.vision.find_template(screen, "banner_ko")
        if ko_match:
            return (GameState.KO_SCREEN, meta)

        # 12. Title Screen ("Touch Screen")
        touch_start = self.vision.find_template(screen, "text_touch_start")
        if touch_start:
            meta["touch_start"] = (touch_start[0], touch_start[1])
            return (GameState.TITLE_SCREEN, meta)

        # 13. Home Screen
        home_match = (
            self.vision.find_template(screen, "nav_start_quest")
            or self.vision.find_template(screen, "nav_start")
            or self.vision.find_template(screen, "nav_events")
        )
        if home_match:
            meta["start_button"] = (home_match[0], home_match[1])
            return (GameState.HOME_SCREEN, meta)

        # 14. Stage Select Screen (Difficulty buttons or Event Stage List cards)
        diff_super = self.vision.find_template(screen, "diff_super")
        diff_z_hard = self.vision.find_template(screen, "diff_z_hard")
        diff_super2 = self.vision.find_template(screen, "diff_super2")
        cleared_tag = self.vision.find_template(screen, "tag_cleared")
        saiyan_training = self.vision.find_template(screen, "stage_saiyan_training")
        boost_off = self.vision.find_template(screen, "button_boost_off")
        stage_match = diff_super or diff_z_hard or diff_super2 or cleared_tag or saiyan_training or boost_off
        if stage_match:
            if diff_super:
                meta["diff_super"] = (diff_super[0], diff_super[1])
            if diff_z_hard:
                meta["diff_z_hard"] = (diff_z_hard[0], diff_z_hard[1])
            if diff_super2:
                meta["diff_super2"] = (diff_super2[0], diff_super2[1])
            if saiyan_training:
                meta["stage_saiyan_training"] = (saiyan_training[0], saiyan_training[1])
            if boost_off:
                meta["boost_off"] = (boost_off[0], boost_off[1])
            return (GameState.STAGE_SELECT, meta)

        return (GameState.UNKNOWN, meta)
