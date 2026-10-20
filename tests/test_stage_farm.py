import os
import sys
import unittest
from unittest.mock import MagicMock

import numpy as np

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dokkan_eza_link_farmer.automation.game_state import StateDetector
from dokkan_eza_link_farmer.automation.tasks.stage_farm import StageFarmTask
from dokkan_eza_link_farmer.automation.vision import Vision
from dokkan_eza_link_farmer.core.bot_engine import BotEngine
from dokkan_eza_link_farmer.core.i18n import t
from dokkan_eza_link_farmer.integrations.adb_client import ADBClient
from dokkan_eza_link_farmer.ui.cli import TerminalCLI


class TestStageFarm(unittest.TestCase):
    def setUp(self):
        self.vision = Vision("templates/glb")
        self.detector = StateDetector(self.vision)

    def _create_canvas(self, width: int = 1080, height: int = 1920) -> np.ndarray:
        """Helper to create a blank canvas simulating an Android screen."""
        return np.zeros((height, width, 3), dtype=np.uint8)

    def _paste_template(
        self, canvas: np.ndarray, template_name: str, x: int, y: int
    ) -> tuple[int, int]:
        """Pastes a template image centered at (x, y) into the canvas."""
        tmpl = self.vision.load_template(template_name)
        self.assertIsNotNone(tmpl, f"Template '{template_name}' must exist to be pasted.")
        assert tmpl is not None
        th, tw = tmpl.shape[:2]
        x1 = max(0, x - tw // 2)
        y1 = max(0, y - th // 2)
        x2 = min(canvas.shape[1], x1 + tw)
        y2 = min(canvas.shape[0], y1 + th)
        canvas[y1:y2, x1:x2] = tmpl[0 : y2 - y1, 0 : x2 - x1]
        return (x, y)

    def test_stage_farm_task_initialization(self):
        config = {"bot": {"loop_delay": 0.5}}
        task = StageFarmTask(
            adb=ADBClient(),
            vision=self.vision,
            config=config,
            runs=None,
            use_boost=True,
            preferred_difficulty="super",
        )
        self.assertIsNone(task.runs_target)
        self.assertTrue(task.use_boost)
        self.assertEqual(task.preferred_difficulty, "super")
        self.assertFalse(task.stamina_depleted)
        self.assertEqual(task.runs_completed, 0)

    def test_stage_farm_task_runs_target(self):
        config = {"bot": {"loop_delay": 0.5}}
        task = StageFarmTask(
            adb=ADBClient(),
            vision=self.vision,
            config=config,
            runs=15,
        )
        self.assertEqual(task.runs_target, 15)

    def test_stamina_depleted_clean_termination(self):
        mock_adb = MagicMock()
        config = {"bot": {"loop_delay": 0.01}}
        task = StageFarmTask(
            adb=mock_adb,
            vision=self.vision,
            config=config,
        )

        canvas = self._create_canvas()
        self._paste_template(canvas, "header_restore_sta", 540, 380)
        self._paste_template(canvas, "button_cancel", 540, 1500)
        mock_adb.screencap.return_value = canvas

        logs = []
        task.on_status = lambda msg: logs.append(msg)

        # Run task loop
        task.run()

        self.assertTrue(task.stamina_depleted)
        self.assertFalse(task.is_running)
        # Cancel button tapped to dismiss popup
        mock_adb.tap.assert_called_once_with(540, 1500, delay_after=1.5)
        self.assertTrue(any("Stamina" in msg for msg in logs))

    def test_stage_selection_difficulty_hierarchy(self):
        mock_adb = MagicMock()
        task = StageFarmTask(
            adb=mock_adb,
            vision=self.vision,
            config={},
            preferred_difficulty="super",
        )

        canvas = self._create_canvas()
        meta = {"diff_super": (540, 800), "diff_z_hard": (540, 1000)}
        task.handle_stage_selection(canvas, 1080, 1920, meta)
        mock_adb.tap.assert_called_once_with(540, 800, delay_after=2.0)

    def test_stage_selection_fallback_to_highest_available(self):
        mock_adb = MagicMock()
        task = StageFarmTask(
            adb=mock_adb,
            vision=self.vision,
            config={},
            preferred_difficulty=None,
        )

        canvas = self._create_canvas()
        meta = {"diff_z_hard": (540, 1000)}
        task.handle_stage_selection(canvas, 1080, 1920, meta)
        mock_adb.tap.assert_called_once_with(540, 1000, delay_after=2.0)

    def test_stage_selection_fallback_center_tap(self):
        mock_adb = MagicMock()
        task = StageFarmTask(
            adb=mock_adb,
            vision=self.vision,
            config={},
        )

        canvas = self._create_canvas()
        meta = {}
        task.handle_stage_selection(canvas, 1080, 1920, meta)
        mock_adb.tap.assert_called_once_with(540, 1056, delay_after=2.0)

    def test_boost_toggle_handling(self):
        mock_adb = MagicMock()
        task = StageFarmTask(
            adb=mock_adb,
            vision=self.vision,
            config={},
            use_boost=True,
        )

        canvas = self._create_canvas()
        meta = {"boost_off": (700, 1400)}
        task.handle_boost_toggle(canvas, 1080, 1920, meta)
        mock_adb.tap.assert_called_once_with(700, 1400, delay_after=0.6)

    def test_run_completed_and_target_reached(self):
        mock_adb = MagicMock()
        config = {"bot": {"loop_delay": 0.01}}
        task = StageFarmTask(
            adb=mock_adb,
            vision=self.vision,
            config=config,
            runs=1,
        )

        # Sequence of screens:
        # 1. TEAM_CONFIRM -> taps START
        # 2. BATTLE_SCREEN -> handles battle
        # 3. RESULTS_SCREEN -> completes run 1 of 1, stops
        c_team = self._create_canvas()
        self._paste_template(c_team, "button_start", 850, 1500)

        c_battle = self._create_canvas()
        self._paste_template(c_battle, "button_battle_menu", 150, 200)

        c_results = self._create_canvas()
        self._paste_template(c_results, "button_close", 540, 1600)

        mock_adb.screencap.side_effect = [c_team, c_battle, c_results, c_results]

        runs_recorded = []
        task.on_run_complete = lambda curr, tot: runs_recorded.append((curr, tot))

        task.run()

        self.assertEqual(task.runs_completed, 1)
        self.assertFalse(task.is_running)
        self.assertEqual(runs_recorded, [(1, 1)])

    def test_bot_engine_start_stage_farm(self):
        engine = BotEngine()
        engine.adb = MagicMock()
        engine.adb.screencap.return_value = self._create_canvas()

        self.assertFalse(engine.is_task_running())
        ok = engine.start_stage_farm(runs=5, use_boost=False, preferred_difficulty="z_hard")
        self.assertTrue(ok)
        self.assertTrue(engine.is_task_running())
        self.assertIsInstance(engine.current_task, StageFarmTask)
        assert isinstance(engine.current_task, StageFarmTask)
        self.assertEqual(engine.current_task.runs_target, 5)
        self.assertFalse(engine.current_task.use_boost)
        self.assertEqual(engine.current_task.preferred_difficulty, "z_hard")

        # Second start while running returns False
        ok2 = engine.start_stage_farm()
        self.assertFalse(ok2)

        engine.stop_task()

    def test_cli_handle_stage_farm_interactive_args(self):
        engine = BotEngine()
        engine.start_stage_farm = MagicMock()
        cli = TerminalCLI(engine)

        # 1. Direct arguments: runs, boost, difficulty
        cli.handle_stage_farm_interactive(["25", "--boost", "--super2"])
        engine.start_stage_farm.assert_called_once()
        _, kwargs = engine.start_stage_farm.call_args
        self.assertEqual(kwargs["runs"], 25)
        self.assertTrue(kwargs["use_boost"])
        self.assertEqual(kwargs["preferred_difficulty"], "super2")

        # 2. No arguments (default unlimited until stamina depleted)
        engine.start_stage_farm.reset_mock()
        cli.handle_stage_farm_interactive([])
        engine.start_stage_farm.assert_called_once()
        _, kwargs = engine.start_stage_farm.call_args
        self.assertIsNone(kwargs["runs"])
        self.assertIsNone(kwargs["use_boost"])
        self.assertIsNone(kwargs["preferred_difficulty"])

    def test_translations_exist(self):
        from dokkan_eza_link_farmer.core.i18n import set_language

        for lang in ("en", "it"):
            set_language(lang)
            self.assertNotEqual(t("cli.help.desc_stage"), "cli.help.desc_stage")
            self.assertNotEqual(
                t("tasks.stage_farm.stamina_depleted"), "tasks.stage_farm.stamina_depleted"
            )
            self.assertNotEqual(
                t("tasks.stage_farm.started", runs="∞", boost="AUTO", diff="AUTO"),
                "tasks.stage_farm.started",
            )
            self.assertNotEqual(
                t("cli.stage.summary", runs="∞", boost="ON", diff="SUPER"), "cli.stage.summary"
            )


if __name__ == "__main__":
    unittest.main()
