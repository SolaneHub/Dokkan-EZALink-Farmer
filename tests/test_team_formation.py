"""Unit tests for in-game team formation automation via Filters & Live Template Matching."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock, call

import cv2
import numpy as np

from dokkan_eza_link_farmer.ai.models import DokkanCard
from dokkan_eza_link_farmer.automation.game_state import GameState, StateDetector
from dokkan_eza_link_farmer.automation.team_formation import (
    CLASS_X_RATIOS,
    CLASS_Y_RATIO,
    ELEMENT_X_RATIOS,
    ELEMENT_Y_RATIO,
    SWIPE_DELTA_Y,
    apply_surgical_filter,
    apply_team_in_game,
    find_card_on_screen,
    get_card_thumb_id,
    open_filter_menu,
)
from dokkan_eza_link_farmer.automation.vision import Vision
from dokkan_eza_link_farmer.integrations.adb_client import ADBClient


def make_test_card(
    card_id: int,
    name: str,
    rarity: int = 4,
    element: int = 0,
    element_name: str = "Super AGL",
    card_class: str = "Super",
) -> DokkanCard:
    return DokkanCard(
        id=card_id,
        name=name,
        rarity=rarity,
        element=element,
        element_name=element_name,
        card_class=card_class,
        category_ids=[10],
    )


class TestTeamFormation:
    def test_apply_team_in_game_empty_team(self) -> None:
        """Calling with an empty team list returns False."""
        res = apply_team_in_game(None, None, None, team_cards=[])
        assert res is False

    def test_apply_team_in_game_dry_run_flag(self) -> None:
        """Explicit dry_run=True completes gracefully without ADB calls."""
        team = [make_test_card(1000 + i, f"Card {i}") for i in range(1, 7)]
        res = apply_team_in_game(None, None, None, team_cards=team, dry_run=True)
        assert res is True

    def test_apply_team_in_game_none_adb(self) -> None:
        """Calling without ADB connected completes in dry run simulation."""
        team = [make_test_card(1000 + i, f"Card {i}") for i in range(1, 7)]
        res = apply_team_in_game(None, None, None, team_cards=team)
        assert res is True

    def test_get_card_thumb_id(self) -> None:
        """Calculates thumbnail ID according to formula: str(cid)[:-1] + '0'."""
        card1 = make_test_card(1012901, "SSJ Goku")
        assert get_card_thumb_id(card1) == "1012900"

        card0 = make_test_card(0, "Empty")
        assert get_card_thumb_id(card0) == "0"

    def test_open_filter_menu_already_open(self) -> None:
        """If filter dialog is already open, does not tap sort button."""
        mock_adb = MagicMock(spec=ADBClient)
        mock_vision = MagicMock(spec=Vision)
        mock_vision.is_filter_dialog_open.return_value = True

        mock_adb.screencap.return_value = np.zeros((2400, 1080, 3), dtype=np.uint8)
        opened = open_filter_menu(mock_adb, mock_vision, 1080, 2400)
        assert opened is True
        mock_adb.tap.assert_not_called()

    def test_open_filter_menu_triggers_sort_button(self) -> None:
        """If filter dialog is closed, taps yellow sort button."""
        mock_adb = MagicMock(spec=ADBClient)
        mock_vision = MagicMock(spec=Vision)
        mock_vision.is_filter_dialog_open.side_effect = [False, True]
        mock_vision.find_yellow_sort_button.return_value = (864, 2300)

        mock_adb.screencap.return_value = np.zeros((2400, 1080, 3), dtype=np.uint8)
        opened = open_filter_menu(mock_adb, mock_vision, 1080, 2400)
        assert opened is True
        mock_adb.tap.assert_called_with(864, 2300, delay_after=1.2)

    def test_apply_surgical_filter(self) -> None:
        """Applies filter reset, sets exact Rarity, Element, Class, and taps OK."""
        mock_adb = MagicMock(spec=ADBClient)
        mock_vision = MagicMock(spec=Vision)

        mock_vision.find_template.return_value = (216, 2040)  # button_remove_all
        mock_vision.get_filter_ur_coords.return_value = (756, 1531)
        mock_vision.find_ok_button.return_value = (540, 2040)

        screen = np.zeros((2400, 1080, 3), dtype=np.uint8)
        mock_adb.screencap.return_value = screen

        card = make_test_card(
            1012901,
            "SSJ Goku",
            rarity=4,  # UR
            element=1,  # TEQ
            element_name="Super TEQ",
            card_class="Super",
        )

        ok = apply_surgical_filter(mock_adb, mock_vision, card, 1080, 2400)
        assert ok is True

        tap_calls = mock_adb.tap.call_args_list
        # 1. Reset filters (button_remove_all)
        assert tap_calls[0] == call(216, 2040, delay_after=0.4)
        # 2. Rarity UR
        assert tap_calls[1] == call(756, 1531, delay_after=0.4)
        # 3. Element TEQ (1080 * ELEMENT_X_RATIOS['TEQ'], 2400 * ELEMENT_Y_RATIO)
        expected_teq_x = int(1080 * ELEMENT_X_RATIOS["TEQ"])
        expected_teq_y = int(2400 * ELEMENT_Y_RATIO)
        assert tap_calls[2] == call(expected_teq_x, expected_teq_y, delay_after=0.4)
        # 4. Class Super (1080 * CLASS_X_RATIOS['Super'], 2400 * CLASS_Y_RATIO)
        expected_class_x = int(1080 * CLASS_X_RATIOS["Super"])
        expected_class_y = int(2400 * CLASS_Y_RATIO)
        assert tap_calls[3] == call(expected_class_x, expected_class_y, delay_after=0.4)
        # 5. OK button
        assert tap_calls[4] == call(540, 2040, delay_after=1.0)

    def test_find_card_on_screen_template_match(self) -> None:
        """Finds card via cv2.matchTemplate when thumbnail image is in thumbs_dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            thumb_id = "1012900"
            thumb_file = os.path.join(tmpdir, f"card_{thumb_id}_thumb.png")

            # Create a 250x250 RGBA thumbnail with textured non-flat pattern
            rng = np.random.RandomState(42)
            pattern = rng.randint(50, 250, (110, 110, 3), dtype=np.uint8)

            thumb_img = np.zeros((250, 250, 4), dtype=np.uint8)
            thumb_img[70:180, 70:180, 3] = 255  # Alpha > 80
            thumb_img[70:180, 70:180, :3] = pattern
            cv2.imwrite(thumb_file, thumb_img)

            card = make_test_card(1012901, "SSJ Goku")

            # Create a 2400x1080 canvas and place the exact scaled patch inside character grid
            canvas = np.zeros((2400, 1080, 3), dtype=np.uint8)
            scaled = cv2.resize(
                pattern, (int(pattern.shape[1] * 0.84), int(pattern.shape[0] * 0.84))
            )
            sh, sw = scaled.shape[:2]
            canvas[800 : 800 + sh, 500 : 500 + sw] = scaled

            mock_adb = MagicMock(spec=ADBClient)
            mock_adb.screencap.return_value = canvas
            mock_vision = MagicMock(spec=Vision)

            coords = find_card_on_screen(mock_adb, mock_vision, card, thumbs_dir=tmpdir)
            assert coords is not None
            cx, cy = coords
            expected_x = 500 + sw // 2
            expected_y = 800 + sh // 2
            assert abs(cx - expected_x) <= 3
            assert abs(cy - expected_y) <= 3

    def test_find_card_on_screen_with_slow_swipe(self) -> None:
        """If card is not on screen 1, swipes down slowly (up to 3 times) to match on screen 2."""
        with tempfile.TemporaryDirectory() as tmpdir:
            thumb_id = "1012900"
            thumb_file = os.path.join(tmpdir, f"card_{thumb_id}_thumb.png")

            rng = np.random.RandomState(123)
            pattern = rng.randint(50, 250, (110, 110, 3), dtype=np.uint8)

            thumb_img = np.zeros((250, 250, 4), dtype=np.uint8)
            thumb_img[70:180, 70:180, 3] = 255
            thumb_img[70:180, 70:180, :3] = pattern
            cv2.imwrite(thumb_file, thumb_img)

            card = make_test_card(1012901, "SSJ Goku")

            scaled = cv2.resize(
                pattern, (int(pattern.shape[1] * 0.84), int(pattern.shape[0] * 0.84))
            )
            sh, sw = scaled.shape[:2]

            screen1 = np.zeros((2400, 1080, 3), dtype=np.uint8)  # Card not on screen 1
            screen2 = np.zeros((2400, 1080, 3), dtype=np.uint8)  # Card on screen 2
            screen2[900 : 900 + sh, 400 : 400 + sw] = scaled

            mock_adb = MagicMock(spec=ADBClient)
            mock_adb.screencap.side_effect = [screen1, screen2, screen2]
            mock_vision = MagicMock(spec=Vision)

            coords = find_card_on_screen(mock_adb, mock_vision, card, thumbs_dir=tmpdir)
            assert coords is not None
            mock_adb.swipe.assert_called_once_with(
                540,
                int(2400 * 0.60),
                540,
                int(2400 * 0.60) - SWIPE_DELTA_Y,
                duration_ms=800,
                delay_after=0.8,
            )

    def test_apply_team_in_game_full_formation_mock_flow(self) -> None:
        """Full formation mock flow: navigation, deck clear + ok, filter + card match per card, confirm."""
        mock_adb = MagicMock(spec=ADBClient)
        mock_vision = MagicMock(spec=Vision)
        mock_detector = MagicMock(spec=StateDetector)

        team = [make_test_card(1001 + i, f"Hero {i}") for i in range(6)]

        canvas = np.zeros((2400, 1080, 3), dtype=np.uint8)
        mock_adb.screencap.return_value = canvas
        mock_adb.is_connected.return_value = True

        mock_detector.detect.side_effect = [
            (
                GameState.TEAM_CONFIRM,
                {
                    "screen_width": 1080,
                    "screen_height": 2400,
                    "team_formation_button": (850, 1180),
                },
            ),
            (
                GameState.TEAM_EDIT,
                {
                    "screen_width": 1080,
                    "screen_height": 2400,
                    "button_deck_remove_all": (980, 1920),
                    "button_confirm_formation": (950, 1920),
                },
            ),
            (GameState.TEAM_CONFIRM, {}),
        ]
        mock_vision.find_ok_button.return_value = (540, 1400)
        mock_vision.find_first_unselected_card.return_value = (110, 600)
        mock_vision.find_template.return_value = None
        mock_vision.get_filter_ur_coords.return_value = (756, 1531)
        mock_vision.is_filter_dialog_open.return_value = True

        success = apply_team_in_game(mock_adb, mock_vision, mock_detector, team)
        assert success is True

        tap_calls = mock_adb.tap.call_args_list
        assert len(tap_calls) >= 8

        # First tap is team formation button
        assert tap_calls[0] == call(850, 1180, delay_after=2.5)
        # Second tap is remove all deck cards
        assert tap_calls[1] == call(980, 1920, delay_after=0.8)
        # Third tap is ok confirmation dialog
        assert tap_calls[2] == call(540, 1400, delay_after=0.8)

        # Last tap is confirm formation
        assert tap_calls[-1] == call(950, 1920, delay_after=2.5)

    def test_apply_team_in_game_surgical_replacement_mock_flow(self) -> None:
        """Surgical replacement flow: taps badge_team_slot_{slot}, sets filter for that card, equips it."""
        mock_adb = MagicMock(spec=ADBClient)
        mock_vision = MagicMock(spec=Vision)
        mock_detector = MagicMock(spec=StateDetector)

        c_orig = [make_test_card(1001 + i, f"Hero {i}") for i in range(6)]
        c_new = list(c_orig)
        c_new[3] = make_test_card(2004, "Replacement Tank", rarity=5, element=0)  # Slot 4 changed

        canvas = np.zeros((2400, 1080, 3), dtype=np.uint8)
        mock_adb.screencap.return_value = canvas
        mock_adb.is_connected.return_value = True

        mock_detector.detect.return_value = (
            GameState.TEAM_EDIT,
            {
                "screen_width": 1080,
                "screen_height": 2400,
                "button_confirm_formation": (950, 1920),
            },
        )
        mock_vision.find_template.side_effect = lambda _screen, tmpl, **_kwargs: (
            (626, 500) if tmpl == "badge_team_slot_4" else None
        )
        mock_vision.find_first_unselected_card.return_value = (325, 750)
        mock_vision.find_ok_button.return_value = (540, 1400)
        mock_vision.get_filter_lr_coords.return_value = (907, 1531)
        mock_vision.is_filter_dialog_open.return_value = True

        # Pass previous_team_ids so it detects slot 4 changed
        prev_ids = [c.id for c in c_orig]
        success = apply_team_in_game(
            mock_adb,
            mock_vision,
            mock_detector,
            c_new,
            previous_team_ids=prev_ids,
        )
        assert success is True

        tap_calls = mock_adb.tap.call_args_list
        # First tap must be slot 4 badge (626, 500)
        assert tap_calls[0] == call(626, 500, delay_after=1.0)
        # Last tap must be confirm formation (950, 1920)
        assert tap_calls[-1] == call(950, 1920, delay_after=2.5)

    def test_apply_team_in_game_hardware_exception_graceful(self) -> None:
        """When hardware ADB screencap throws RuntimeError, gracefully recovers and returns True."""
        mock_adb = MagicMock(spec=ADBClient)
        mock_adb.screencap.side_effect = RuntimeError("device offline")
        mock_vision = MagicMock(spec=Vision)
        mock_detector = MagicMock(spec=StateDetector)

        team = [make_test_card(1001, "C1")]
        res = apply_team_in_game(mock_adb, mock_vision, mock_detector, team)
        assert res is True

    def test_open_filter_menu_tag_filter_on(self) -> None:
        """When tag_filter_on is present on screen, open_filter_menu taps tag_filter_on."""
        mock_adb = MagicMock(spec=ADBClient)
        mock_vision = MagicMock(spec=Vision)
        mock_vision.is_filter_dialog_open.side_effect = [False, True]
        mock_vision.find_template.side_effect = lambda _screen, tmpl, **_kw: (
            (920, 360) if "tag_filter_on" in tmpl else None
        )

        mock_adb.screencap.return_value = np.zeros((2400, 1080, 3), dtype=np.uint8)
        opened = open_filter_menu(mock_adb, mock_vision, 1080, 2400)
        assert opened is True
        mock_adb.tap.assert_called_with(920, 360, delay_after=1.2)

    def test_apply_surgical_filter_avoids_toggle_off(self) -> None:
        """When target rarity UR is already selected, does not tap UR button to avoid deselecting."""
        mock_adb = MagicMock(spec=ADBClient)
        mock_vision = MagicMock(spec=Vision)
        mock_vision.find_template.return_value = (216, 2040)
        mock_vision.is_filter_ur_selected.return_value = True  # Already selected!
        mock_vision.is_filter_lr_selected.return_value = False
        mock_vision.find_ok_button.return_value = (540, 2040)

        card = make_test_card(
            1012901, "SSJ Goku", rarity=4, element=0, element_name="Super AGL", card_class="Super"
        )
        mock_adb.screencap.return_value = np.zeros((2400, 1080, 3), dtype=np.uint8)

        ok = apply_surgical_filter(mock_adb, mock_vision, card, 1080, 2400)
        assert ok is True
        # Tap calls should NOT include get_filter_ur_coords
        mock_vision.get_filter_ur_coords.assert_not_called()
