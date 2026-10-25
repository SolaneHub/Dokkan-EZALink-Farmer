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

    def test_bot_engine_start_stage_farm(self):
        engine = BotEngine()
        engine.adb = MagicMock()
        engine.adb.screencap.return_value = np.zeros((1920, 1080, 3), dtype=np.uint8)

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

        try:
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
        finally:
            set_language("en")


if __name__ == "__main__":
    unittest.main()
