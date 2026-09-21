import os
import sys
import unittest
import cv2
import numpy as np
from typing import Tuple

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.dokkandb_client import DokkanDBClient
from core.vision import Vision
from core.game_state import StateDetector, GameState
from tasks.link_level_farm import LinkLevelFarmTask
from core.adb_client import ADBClient


class TestLinkLeveling(unittest.TestCase):

    def setUp(self):
        self.dokkandb = DokkanDBClient()
        self.vision = Vision("templates/glb")
        self.detector = StateDetector(self.vision)

    def _create_canvas(self, width: int = 1080, height: int = 1920) -> np.ndarray:
        """Helper to create a blank canvas simulating an Android screen."""
        return np.zeros((height, width, 3), dtype=np.uint8)

    def _paste_template(self, canvas: np.ndarray, template_name: str, x: int, y: int) -> Tuple[int, int]:
        """Pastes a template image centered at (x, y) into the canvas."""
        tmpl = self.vision.load_template(template_name)
        self.assertIsNotNone(tmpl, f"Template '{template_name}' must exist to be pasted.")
        th, tw = tmpl.shape[:2]
        x1 = max(0, x - tw // 2)
        y1 = max(0, y - th // 2)
        x2 = min(canvas.shape[1], x1 + tw)
        y2 = min(canvas.shape[0], y1 + th)
        canvas[y1:y2, x1:x2] = tmpl[0:y2 - y1, 0:x2 - x1]
        return (x, y)

    def test_dokkandb_chamber_of_spirit_and_time(self):
        event = self.dokkandb.get_chamber_of_spirit_and_time()
        self.assertIsNotNone(event, "Chamber of Spirit and Time event not found in DokkanDB!")
        self.assertIn("chamber of spirit and time", event.get("name", "").lower())
        self.assertTrue(event.get("is_currently_open"), "Event should be currently open in GLB celebration!")
        banner_path = event.get("banner_local_path")
        self.assertIsNotNone(banner_path, "Banner local path missing!")
        self.assertTrue(os.path.exists(banner_path), f"Banner file does not exist at {banner_path}")

    def test_templates_exist_and_load(self):
        for tmpl in ["diff_super", "diff_z_hard", "button_team_formation", "tab_bonus", "tab_growth"]:
            img = self.vision.load_template(tmpl)
            self.assertIsNotNone(img, f"Template '{tmpl}' failed to load!")
            self.assertGreater(img.size, 0, f"Template '{tmpl}' is empty!")

    def test_stage_select_detection(self):
        canvas = self._create_canvas()
        self._paste_template(canvas, "diff_super", 540, 800)
        self._paste_template(canvas, "diff_z_hard", 540, 1000)

        state, meta = self.detector.detect(canvas)
        self.assertEqual(state, GameState.STAGE_SELECT)
        self.assertIn("diff_super", meta, "diff_super not detected on stage select screen")
        self.assertIn("diff_z_hard", meta, "diff_z_hard not detected on stage select screen")

    def test_team_confirm_detection(self):
        canvas = self._create_canvas()
        self._paste_template(canvas, "button_start", 850, 1500)
        self._paste_template(canvas, "button_team_formation", 850, 950)

        state, meta = self.detector.detect(canvas)
        self.assertEqual(state, GameState.TEAM_CONFIRM)
        self.assertIn("start_button", meta, "start_button not detected on team confirm screen")
        self.assertIn("team_formation_button", meta, "team_formation_button not detected on team confirm screen")

    def test_link_level_task_initialization(self):
        config = {
            "link_leveling": {
                "auto_swap_maxed_units": True,
                "protected_slots": [],
                "box_first_slot_coords": [0.18, 0.28],
                "box_confirm_coords": [0.81, 0.80],
                "preferred_difficulty": "super"
            }
        }
        task = LinkLevelFarmTask(
            adb=ADBClient(),
            vision=self.vision,
            config=config,
            runs=10,
            dokkandb=self.dokkandb
        )
        self.assertEqual(task.runs_target, 10)
        self.assertEqual(task.protected_slots, [])
        self.assertEqual(task.box_confirm_coords, [0.81, 0.80])
        self.assertEqual(task.preferred_difficulty, "super")
        self.assertIsNotNone(task.target_event)
        self.assertIsNotNone(task._target_banner_img)
        self.assertFalse(task.box_filter_initialized)

    def test_link_level_optional_and_unlimited_runs(self):
        config = {"link_leveling": {}}
        # None passed (default) -> runs_target should be None (run until stamina empty)
        task_none = LinkLevelFarmTask(adb=ADBClient(), vision=self.vision, config=config, runs=None, dokkandb=self.dokkandb)
        self.assertIsNone(task_none.runs_target)

        # 0 or negative passed -> runs_target should be None
        task_zero = LinkLevelFarmTask(adb=ADBClient(), vision=self.vision, config=config, runs=0, dokkandb=self.dokkandb)
        self.assertIsNone(task_zero.runs_target)

        task_neg = LinkLevelFarmTask(adb=ADBClient(), vision=self.vision, config=config, runs=-1, dokkandb=self.dokkandb)
        self.assertIsNone(task_neg.runs_target)

        # Explicit positive number passed -> runs_target set
        task_explicit = LinkLevelFarmTask(adb=ADBClient(), vision=self.vision, config=config, runs=5, dokkandb=self.dokkandb)
        self.assertEqual(task_explicit.runs_target, 5)

    def test_filter_templates_load(self):
        templates_to_test = [
            "btn_level_up_possible_selected",
            "btn_level_up_possible_unselected",
            "btn_all_at_max_selected",
            "btn_all_at_max_unselected",
            "header_link_skill_level",
            "tag_filter_on",
            "button_remove_all",
            "button_auto_formation",
            "button_confirm_formation",
            "header_team_formation"
        ]
        for tmpl in templates_to_test:
            img = self.vision.load_template(tmpl)
            self.assertIsNotNone(img, f"Template '{tmpl}' failed to load!")
            self.assertGreater(img.size, 0, f"Template '{tmpl}' is empty!")

        for slot in range(1, 7):
            tmpl = f"badge_team_slot_{slot}"
            img = self.vision.load_template(tmpl)
            self.assertIsNotNone(img, f"Badge template '{tmpl}' failed to load!")
            self.assertGreater(img.size, 0, f"Badge template '{tmpl}' is empty!")

    def test_filter_modal_detection(self):
        canvas = self._create_canvas()
        self._paste_template(canvas, "button_remove_all", 540, 1600)
        self._paste_template(canvas, "header_link_skill_level", 540, 1000)

        state, meta = self.detector.detect(canvas)
        self.assertEqual(state, GameState.FILTER_MODAL)
        self.assertTrue(self.vision.is_filter_dialog_open(canvas))

    def test_link_skill_level_filter_status_analysis(self):
        canvas = self._create_canvas()
        self._paste_template(canvas, "header_link_skill_level", 540, 1000)
        self._paste_template(canvas, "btn_level_up_possible_selected", 300, 1200)
        self._paste_template(canvas, "btn_all_at_max_unselected", 780, 1200)
        self._paste_template(canvas, "button_remove_all", 540, 1600)

        status = self.vision.get_link_level_filter_status(canvas)
        self.assertTrue(status["is_open"])
        self.assertTrue(status["has_link_section"])
        self.assertTrue(status["level_up_possible"]["selected"])
        self.assertFalse(status["all_at_max"]["selected"])

    def test_unscrolled_filter_modal_has_no_false_positive(self):
        canvas = self._create_canvas()
        self._paste_template(canvas, "button_remove_all", 540, 1600)
        status = self.vision.get_link_level_filter_status(canvas)
        self.assertTrue(status["is_open"])
        self.assertFalse(status["has_link_section"], "Unscrolled filter modal should not detect link section")
        self.assertFalse(status["level_up_possible"]["selected"])
        self.assertFalse(status["all_at_max"]["selected"])

    def test_team_edit_and_slot_badges(self):
        canvas = self._create_canvas()
        self._paste_template(canvas, "button_confirm_formation", 950, 1530)
        self._paste_template(canvas, "tag_filter_on", 900, 1670)

        for slot in range(1, 7):
            self._paste_template(canvas, f"badge_team_slot_{slot}", 100 + slot * 120, 500)

        state, meta = self.detector.detect(canvas)
        self.assertEqual(state, GameState.TEAM_EDIT)
        self.assertIn("filter_button", meta)

        slots = self.vision.get_team_slots_in_box(canvas)
        self.assertEqual(sorted(slots), [1, 2, 3, 4, 5, 6])

    def test_all_max_filtered_box_detection(self):
        canvas = self._create_canvas()
        self._paste_template(canvas, "button_confirm_formation", 950, 1530)
        slots = self.vision.get_team_slots_in_box(canvas)
        self.assertEqual(slots, [])

    def test_find_first_unselected_card_fallback(self):
        blank = np.zeros((2400, 1080, 3), dtype=np.uint8)
        coords = self.vision.find_first_unselected_card(blank)
        expected_x = int(1080 * 0.097)
        expected_y = int(2400 * 0.215)
        self.assertEqual(coords, (expected_x, expected_y))

    def test_saiyan_training_and_boost_detection(self):
        canvas = self._create_canvas()
        self._paste_template(canvas, "stage_saiyan_training", 540, 600)
        self._paste_template(canvas, "button_boost_off", 540, 1400)

        st_pos = self.vision.find_stage_saiyan_training(canvas)
        self.assertIsNotNone(st_pos, "Stage '1. Saiyan Training' should be detected")

        boost_off = self.vision.is_boost_off(canvas)
        self.assertIsNotNone(boost_off, "BOOST OFF button should be detected")

    def test_deck_remove_all_and_sort_released(self):
        canvas = self._create_canvas()
        self._paste_template(canvas, "button_deck_remove_all", 540, 700)
        self._paste_template(canvas, "tag_sort_released", 850, 1842)

        rm_all = self.vision.find_deck_remove_all(canvas)
        self.assertIsNotNone(rm_all, "Deck 'Remove All' button should be detected")
        self.assertTrue(self.vision.is_sort_released(canvas), "Sort order 'Released' should be detected")
        yellow_btn = self.vision.find_yellow_sort_button(canvas)
        self.assertIsNotNone(yellow_btn, "Yellow sort button should be detected")

        filter_canvas = self._create_canvas()
        self._paste_template(filter_canvas, "btn_released_selected", 300, 600)
        self.assertTrue(
            self.vision.is_filter_released_selected(filter_canvas),
            "Released filter button should be detected as selected"
        )

    def test_get_top_box_card_coords(self):
        blank = np.zeros((2400, 1080, 3), dtype=np.uint8)
        coords = self.vision.get_top_box_card_coords(blank, count=6)
        self.assertEqual(len(coords), 6)
        # Verify first card is Row 1 Col 1
        self.assertEqual(coords[0], (int(1080 * 0.10), int(2400 * 0.215)))
        # Verify 6th card is Row 2 Col 1
        self.assertEqual(coords[5], (int(1080 * 0.10), int(2400 * 0.323)))

    def test_auto_map_and_auto_battle_controls(self):
        # Verify templates load
        for tmpl in ["btn_auto_map_off", "btn_auto_map_on", "btn_auto_battle_off", "btn_auto_battle_on"]:
            img = self.vision.load_template(tmpl)
            self.assertIsNotNone(img, f"Template {tmpl} failed to load")

        # Canvas with Auto Map OFF and Auto Battle ON
        canvas1 = self._create_canvas()
        self._paste_template(canvas1, "btn_auto_map_off", 200, 300)
        self._paste_template(canvas1, "btn_auto_battle_on", 400, 300)

        self.assertIsNotNone(self.vision.find_auto_map_off(canvas1))
        self.assertIsNotNone(self.vision.find_auto_battle_on(canvas1))
        self.assertTrue(self.vision.has_auto_controls(canvas1))

        # Canvas with both ON
        canvas2 = self._create_canvas()
        self._paste_template(canvas2, "btn_auto_map_on", 200, 300)
        self._paste_template(canvas2, "btn_auto_battle_on", 400, 300)

        self.assertIsNotNone(self.vision.find_auto_map_on(canvas2))
        self.assertIsNotNone(self.vision.find_auto_battle_on(canvas2))
        self.assertTrue(self.vision.has_auto_controls(canvas2))

        # Blank screen (first-time stage without auto controls)
        blank = np.zeros((1920, 1080, 3), dtype=np.uint8)
        self.assertFalse(self.vision.has_auto_controls(blank), "Blank screen should report no auto controls")

    def test_attempt_again_detection(self):
        # 1. Single centered OK button (intermediate screens): Attempt Again should be None
        canvas1 = self._create_canvas()
        self._paste_template(canvas1, "button_ok", 540, 1600)
        self.assertIsNone(self.vision.find_attempt_again_button(canvas1))

        # 2. Left-shifted OK button (stage clear screen with Attempt Again on right)
        canvas2 = self._create_canvas()
        self._paste_template(canvas2, "button_ok", 300, 1600)
        again_coords = self.vision.find_attempt_again_button(canvas2)
        self.assertIsNotNone(again_coords)
        self.assertEqual(again_coords[0], int(1080 * 0.72))
        self.assertEqual(again_coords[1], 1600)


if __name__ == "__main__":
    unittest.main()
