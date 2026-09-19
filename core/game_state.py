import enum
from typing import Optional, Tuple, Dict, Any
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
    TEAM_EDIT = "TEAM_EDIT"
    CHARACTER_BOX = "CHARACTER_BOX"


class StateDetector:
    """Detects current screen state in Dokkan Battle."""

    def __init__(self, vision: Vision):
        self.vision = vision

    def detect(self, screen: np.ndarray) -> Tuple[GameState, Dict[str, Any]]:
        """
        Analyzes the screen and returns (GameState, action_metadata).
        action_metadata contains coordinates of relevant clickable elements (e.g. 'start_button', 'ok_button').
        """
        h, w = screen.shape[:2]
        meta: Dict[str, Any] = {"screen_width": w, "screen_height": h}

        # 1. Check for popups first: OK button / Cancel / Close
        # Dokkan popups have distinct OK / CANCEL buttons
        ok_match = self.vision.find_template(screen, "button_ok")
        if ok_match:
            meta["ok_button"] = (ok_match[0], ok_match[1])

        cancel_match = self.vision.find_template(screen, "button_cancel")
        if cancel_match:
            meta["cancel_button"] = (cancel_match[0], cancel_match[1])

        dont_send_match = self.vision.find_template(screen, "button_dont_send")
        if dont_send_match:
            meta["dont_send_button"] = (dont_send_match[0], dont_send_match[1])

        # 2. Friend Request Popup
        if dont_send_match or self.vision.find_template(screen, "popup_friend_request"):
            return (GameState.FRIEND_REQUEST, meta)

        # 3. Stamina Empty Popup
        stamina_empty_match = self.vision.find_template(screen, "popup_stamina_empty")
        meat_match = self.vision.find_template(screen, "button_use_meat")
        if stamina_empty_match or meat_match:
            if meat_match:
                meta["meat_button"] = (meat_match[0], meat_match[1])
            return (GameState.STAMINA_EMPTY, meta)

        # 4. Game Over Popup
        game_over_match = self.vision.find_template(screen, "popup_game_over")
        if game_over_match:
            return (GameState.GAME_OVER, meta)

        # 5. Results Screen (Stage Cleared / Exp / Drops / OK button)
        results_match = self.vision.find_template(screen, "header_clear") or self.vision.find_template(screen, "header_rewards")
        if results_match or (ok_match and ok_match[1] > int(h * 0.75)):
            # If an OK button is in the lower quadrant and no other popup
            return (GameState.RESULTS_SCREEN, meta)

        # 6. Team Confirmation Screen (Large Start button at bottom right)
        start_match = self.vision.find_template(screen, "button_start")
        if start_match:
            meta["start_button"] = (start_match[0], start_match[1])
            edit_team = self.vision.find_template(screen, "button_edit_team")
            if edit_team:
                meta["edit_team_button"] = (edit_team[0], edit_team[1])
            switch_disp = self.vision.find_template(screen, "button_switch_display")
            if switch_disp:
                meta["switch_display_button"] = (switch_disp[0], switch_disp[1])
            return (GameState.TEAM_CONFIRM, meta)

        # 6b. Team Edit Screen (Team Formation / Deck Editor)
        team_edit_match = self.vision.find_template(screen, "header_team_formation") or self.vision.find_template(screen, "button_auto_formation")
        if team_edit_match:
            return (GameState.TEAM_EDIT, meta)

        # 6c. Character Box / Character Selection List
        box_match = self.vision.find_template(screen, "header_character_list") or self.vision.find_template(screen, "button_filter")
        if box_match:
            return (GameState.CHARACTER_BOX, meta)

        # 7. Friend Selection Screen
        friend_header = self.vision.find_template(screen, "header_select_friend")
        if friend_header:
            return (GameState.FRIEND_SELECT, meta)

        # 8. Battle Screen (Auto Battle toggle, x2 Speed, Ki orbs, Character bubbles)
        auto_battle = self.vision.find_template(screen, "battle_auto_on") or self.vision.find_template(screen, "battle_auto_off")
        speed_toggle = self.vision.find_template(screen, "battle_speed_2x") or self.vision.find_template(screen, "battle_speed_1x")
        if auto_battle or speed_toggle:
            if auto_battle:
                meta["auto_button"] = (auto_battle[0], auto_battle[1])
            if speed_toggle:
                meta["speed_button"] = (speed_toggle[0], speed_toggle[1])
            return (GameState.BATTLE_SCREEN, meta)

        # 9. Map / Quest Board Screen (Dice buttons 1, 2, 3 or Auto Map button)
        auto_map = self.vision.find_template(screen, "map_auto_on") or self.vision.find_template(screen, "map_auto_off")
        if auto_map:
            meta["auto_map_button"] = (auto_map[0], auto_map[1])
            return (GameState.MAP_SCREEN, meta)

        # 10. EZA (Extreme Z-Battle) Level Select Screen
        eza_challenge = self.vision.find_template(screen, "button_eza_challenge") or self.vision.find_template(screen, "button_eza_next_level")
        if eza_challenge:
            meta["eza_button"] = (eza_challenge[0], eza_challenge[1])
            return (GameState.EZA_SELECT, meta)

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
        home_match = self.vision.find_template(screen, "nav_start_quest") or self.vision.find_template(screen, "nav_events")
        if home_match:
            return (GameState.HOME_SCREEN, meta)

        # 14. Stage Select Screen
        stage_match = self.vision.find_template(screen, "diff_z_hard") or self.vision.find_template(screen, "diff_super") or self.vision.find_template(screen, "diff_super2")
        if stage_match:
            return (GameState.STAGE_SELECT, meta)

        return (GameState.UNKNOWN, meta)
