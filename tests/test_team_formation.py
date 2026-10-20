"""Unit tests for in-game team formation automation (apply_team_in_game)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, call

import numpy as np

from dokkan_eza_link_farmer.ai.models import DokkanCard
from dokkan_eza_link_farmer.automation.game_state import GameState, StateDetector
from dokkan_eza_link_farmer.automation.team_formation import (
    COL_RATIOS,
    ROW_RATIOS,
    SWIPE_DELTA_Y,
    apply_team_in_game,
)
from dokkan_eza_link_farmer.automation.vision import Vision
from dokkan_eza_link_farmer.integrations.adb_client import ADBClient


def make_test_card(card_id: int, name: str) -> DokkanCard:
    return DokkanCard(
        id=card_id,
        name=name,
        element=0,
        rarity=5,
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

    def test_apply_team_in_game_mock_flow(self) -> None:
        """Full mock ADB flow validating navigation, deck clearing, grid taps, and confirmation."""
        mock_adb = MagicMock(spec=ADBClient)
        mock_vision = MagicMock(spec=Vision)
        mock_detector = MagicMock(spec=StateDetector)

        team = [make_test_card(1001 + i, f"Hero {i}") for i in range(6)]

        # Canvas screen 1080x2400
        canvas = np.zeros((2400, 1080, 3), dtype=np.uint8)
        mock_adb.screencap.return_value = canvas
        mock_adb.is_connected.return_value = True

        # State sequence: TEAM_CONFIRM -> TEAM_EDIT -> TEAM_EDIT (during selection) -> TEAM_CONFIRM
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
        mock_vision.is_sort_released.return_value = True
        mock_vision.get_team_slots_in_box.return_value = [1, 2, 3, 4, 5, 6]

        success = apply_team_in_game(mock_adb, mock_vision, mock_detector, team)
        assert success is True

        # Verify taps occurred:
        # 1. formation button
        # 2. deck remove all
        # 3. ok dialog
        # 4..9. 6 grid cards
        # 10. confirm formation
        tap_calls = mock_adb.tap.call_args_list
        assert len(tap_calls) >= 9

        # First tap is team formation button
        assert tap_calls[0] == call(850, 1180, delay_after=2.5)

        # Second tap is remove all
        assert tap_calls[1] == call(980, 1920, delay_after=0.8)

        # Third tap is ok dialog
        assert tap_calls[2] == call(540, 1400, delay_after=0.8)

    def test_apply_team_in_game_custom_box_coordinates(self, tmp_path: Path) -> None:
        """Custom user_box.json coordinates (swipe_page + grid_slot) are properly mapped and tapped."""
        box_file = tmp_path / "user_box.json"
        box_data = {
            "cards": [
                {"id": 2001, "swipe_page": 0, "grid_slot": 0},  # Col 0, Row 0
                {"id": 2002, "swipe_page": 1, "grid_slot": 7},  # Col 2, Row 1 (Page 1 -> requires 1 swipe)
            ]
        }
        box_file.write_text(json.dumps(box_data), encoding="utf-8")

        mock_adb = MagicMock(spec=ADBClient)
        mock_vision = MagicMock(spec=Vision)
        mock_detector = MagicMock(spec=StateDetector)

        canvas = np.zeros((2400, 1080, 3), dtype=np.uint8)
        mock_adb.screencap.return_value = canvas
        mock_detector.detect.return_value = (
            GameState.TEAM_EDIT,
            {
                "button_deck_remove_all": (980, 1920),
                "button_confirm_formation": (950, 1920),
            },
        )
        mock_vision.find_ok_button.return_value = None
        mock_vision.is_sort_released.return_value = True

        team = [make_test_card(2001, "Leader"), make_test_card(2002, "Sub")]
        apply_team_in_game(
            mock_adb,
            mock_vision,
            mock_detector,
            team,
            user_box_path=str(box_file),
        )

        # Should have called swipe once to go from Page 0 to Page 1
        expected_swipe_y = int(2400 * 0.58)
        mock_adb.swipe.assert_called_once_with(
            540,
            expected_swipe_y,
            540,
            expected_swipe_y - SWIPE_DELTA_Y,
            duration_ms=1000,
            delay_after=0.8,
        )

        # Slot 0: col 0, row 0 -> COL_RATIOS[0], ROW_RATIOS[0]
        expected_x0 = int(1080 * COL_RATIOS[0])
        expected_y0 = int(2400 * ROW_RATIOS[0])

        # Slot 7: col 2, row 1 -> COL_RATIOS[2], ROW_RATIOS[1]
        expected_x1 = int(1080 * COL_RATIOS[2])
        expected_y1 = int(2400 * ROW_RATIOS[1])

        tap_coords = [(c.args[0], c.args[1]) for c in mock_adb.tap.call_args_list]
        assert (expected_x0, expected_y0) in tap_coords
        assert (expected_x1, expected_y1) in tap_coords

    def test_apply_team_in_game_hardware_exception_graceful(self) -> None:
        """When hardware ADB screencap throws RuntimeError, gracefully recovers and returns True."""
        mock_adb = MagicMock(spec=ADBClient)
        mock_adb.screencap.side_effect = RuntimeError("device offline")
        mock_vision = MagicMock(spec=Vision)
        mock_detector = MagicMock(spec=StateDetector)

        team = [make_test_card(1001, "C1")]
        res = apply_team_in_game(mock_adb, mock_vision, mock_detector, team)
        assert res is True
