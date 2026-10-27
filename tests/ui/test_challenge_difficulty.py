"""Tests for Challenge Stage Difficulty selection, parsing, DokkanDB integration and UI wizards.

Verifies multi-difficulty stages (e.g. Event 1779 'Alternate Art Clash' with Hard & Super3),
declarative CLI flags, default fallback to highest difficulty, single-difficulty bypass,
and telemetry rendering.
"""

import io
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console

from dokkan_eza_link_farmer.ai.boss_models import (
    BossStage,
    infer_difficulty_from_stage_id,
    parse_difficulty_code,
)
from dokkan_eza_link_farmer.automation.tasks.challenge_task import ChallengeTask
from dokkan_eza_link_farmer.core.bot_engine import BotEngine
from dokkan_eza_link_farmer.ui import wizards
from dokkan_eza_link_farmer.ui.cli import TerminalCLI


def _create_test_console() -> tuple[Console, io.StringIO]:
    stream = io.StringIO()
    console = Console(file=stream, force_terminal=False, color_system=None, width=120)
    return console, stream


class TestDifficultyParsingAndDomain:
    """Tests domain model parsing and difficulty inference."""

    def test_parse_difficulty_code(self):
        assert parse_difficulty_code(0) == 0
        assert parse_difficulty_code(1) == 1
        assert parse_difficulty_code(5) == 5
        assert parse_difficulty_code("hard") == 1
        assert parse_difficulty_code("Super3") == 5
        assert parse_difficulty_code("--super3") == 5
        assert parse_difficulty_code("z-hard") == 2
        assert parse_difficulty_code("zhard") == 2
        assert parse_difficulty_code("normal") == 0
        assert parse_difficulty_code("super2") == 4
        assert parse_difficulty_code(99) is None
        assert parse_difficulty_code("invalid") is None
        assert parse_difficulty_code(None) is None

    def test_infer_difficulty_from_stage_id(self):
        # 1779 002 1 -> Hard (1)
        assert infer_difficulty_from_stage_id(17790021) == 1
        # 1779 002 5 -> Super3 (5)
        assert infer_difficulty_from_stage_id(17790025) == 5
        # 795 003 5 -> Super3 (5)
        assert infer_difficulty_from_stage_id("7950035") == 5
        # Invalid / unknown
        assert infer_difficulty_from_stage_id(None) is None
        assert infer_difficulty_from_stage_id("") is None
        assert infer_difficulty_from_stage_id("abc") is None

    def test_boss_stage_difficulty_model(self):
        stage = BossStage(
            stage_id=17790025,
            event_id=1779,
            stage_name="Vs. Super Gogeta",
            event_name="Alternate Art Clash",
            difficulty=5,
            total_battles=1,
            phases=[],
        )
        assert stage.difficulty == 5
        assert stage.difficulty_name == "Super3"

        # Test from_dokkandb with explicit difficulty
        stage_explicit = BossStage.from_dokkandb(
            {
                "stage_id": 17790021,
                "event_id": 1779,
                "stage_name": "Vs. Super Gogeta",
                "event_name": "Alternate Art Clash",
                "difficulty": 1,
                "phases": [],
            }
        )
        assert stage_explicit.difficulty == 1
        assert stage_explicit.difficulty_name == "Hard"

        # Test from_dokkandb with inferred difficulty from stage_id
        stage_inferred = BossStage.from_dokkandb(
            {
                "stage_id": 17790025,
                "event_id": 1779,
                "stage_name": "Vs. Super Gogeta",
                "event_name": "Alternate Art Clash",
                "phases": [],
            }
        )
        assert stage_inferred.difficulty == 5
        assert stage_inferred.difficulty_name == "Super3"


class TestEvent1779MultiDifficultyFlows:
    """Verifies event 1779 (Hard & Super3) handling in CLI and interactive wizards."""

    @pytest.fixture
    def mock_event_1779_setup(self):
        engine = MagicMock(spec=BotEngine)
        engine.dokkandb = MagicMock()
        engine.adb = MagicMock()
        engine.adb.is_connected.return_value = True

        mock_event = {
            "id": 1779,
            "name": "Alternate Art Clash",
            "category": 20,
            "is_currently_open": True,
        }
        mock_other_event = {
            "id": 100,
            "name": "Cell Max",
            "category": 20,
            "is_currently_open": True,
        }
        engine.dokkandb.get_challenge_events.return_value = [mock_event, mock_other_event]
        engine.dokkandb.get_event_details.return_value = {
            "id": 1779,
            "quests": [
                {
                    "quest_id": 1779001,
                    "quest_name": "Vs. Super Vegito",
                    "stages": [
                        {"stage_id": 17790011, "difficulty": 1, "act": 20},
                        {"stage_id": 17790015, "difficulty": 5, "act": 25},
                    ],
                },
                {
                    "quest_id": 1779002,
                    "quest_name": "Vs. Super Gogeta",
                    "stages": [
                        {"stage_id": 17790021, "difficulty": 1, "act": 20},
                        {"stage_id": 17790025, "difficulty": 5, "act": 25},
                    ],
                },
            ],
        }
        engine.dokkandb.get_stage_boss_info.return_value = {
            "phases": [
                {
                    "phase": 1,
                    "bosses": [{"name": "Super Gogeta", "type_name": "Super STR", "mechanics": []}],
                }
            ]
        }
        engine.dokkandb.get_challenge_missions.return_value = []
        return engine, mock_event

    def test_declarative_cli_super3_flag(self, mock_event_1779_setup):
        """Specifying --super3 selects stage_id 17790025 with Super3 difficulty."""
        engine, mock_event = mock_event_1779_setup
        cli = TerminalCLI(engine)

        cli.handle_challenge_interactive(args=["1779", "2", "--super3", "-y"])

        engine.start_challenge_farm.assert_called_once_with(
            target_event=mock_event,
            stage_num=2,
            stage_id=17790025,
            stage_name="Vs. Super Gogeta",
            preferred_difficulty="super3",
            difficulty=5,
        )

    def test_declarative_cli_hard_flag(self, mock_event_1779_setup):
        """Specifying --hard selects stage_id 17790021 with Hard difficulty."""
        engine, mock_event = mock_event_1779_setup
        cli = TerminalCLI(engine)

        cli.handle_challenge_interactive(args=["1779", "2", "--hard", "-y"])

        engine.start_challenge_farm.assert_called_once_with(
            target_event=mock_event,
            stage_num=2,
            stage_id=17790021,
            stage_name="Vs. Super Gogeta",
            preferred_difficulty="hard",
            difficulty=1,
        )

    def test_declarative_cli_diff_argument_formats(self, mock_event_1779_setup):
        """Tests --diff super3, -d 1, and --difficulty=super3."""
        engine, mock_event = mock_event_1779_setup
        cli = TerminalCLI(engine)

        # --diff super3
        engine.reset_mock()
        cli.handle_challenge_interactive(args=["1779", "2", "--diff", "super3", "-y"])
        assert engine.start_challenge_farm.call_args[1]["difficulty"] == 5
        assert engine.start_challenge_farm.call_args[1]["stage_id"] == 17790025

        # -d 1
        engine.reset_mock()
        cli.handle_challenge_interactive(args=["1779", "2", "-d", "1", "-y"])
        assert engine.start_challenge_farm.call_args[1]["difficulty"] == 1
        assert engine.start_challenge_farm.call_args[1]["stage_id"] == 17790021

        # --difficulty=super3
        engine.reset_mock()
        cli.handle_challenge_interactive(args=["1779", "2", "--difficulty=super3", "-y"])
        assert engine.start_challenge_farm.call_args[1]["difficulty"] == 5
        assert engine.start_challenge_farm.call_args[1]["stage_id"] == 17790025

    def test_default_picks_highest_difficulty_when_not_specified(self, mock_event_1779_setup):
        """When difficulty is omitted in headless mode, defaults to highest difficulty (Super3)."""
        engine, mock_event = mock_event_1779_setup
        cli = TerminalCLI(engine)

        cli.handle_challenge_interactive(args=["1779", "2", "-y"])

        engine.start_challenge_farm.assert_called_once_with(
            target_event=mock_event,
            stage_num=2,
            stage_id=17790025,
            stage_name="Vs. Super Gogeta",
            preferred_difficulty="super3",
            difficulty=5,
        )

    def test_interactive_difficulty_prompt_when_multiple_stages(self, mock_event_1779_setup):
        """When interactive (no args), prompts for event, stage, difficulty, and confirmation."""
        engine, mock_event = mock_event_1779_setup
        console, _ = _create_test_console()

        with (
            patch("questionary.select") as mock_select,
            patch("questionary.confirm") as mock_confirm,
        ):
            mock_stage_choice = {
                "stage_num": 2,
                "stage_name": "Vs. Super Gogeta",
                "stages": [
                    {"stage_id": 17790021, "difficulty": 1, "act": 20},
                    {"stage_id": 17790025, "difficulty": 5, "act": 25},
                ],
            }
            mock_diff_choice = {"stage_id": 17790021, "difficulty": 1, "act": 20}

            # Prompt 1: select event
            mock_select_inst1 = MagicMock()
            mock_select_inst1.ask.return_value = mock_event
            # Prompt 2: select stage
            mock_select_inst2 = MagicMock()
            mock_select_inst2.ask.return_value = mock_stage_choice
            # Prompt 3: select difficulty
            mock_select_inst3 = MagicMock()
            mock_select_inst3.ask.return_value = mock_diff_choice
            mock_select.side_effect = [mock_select_inst1, mock_select_inst2, mock_select_inst3]

            mock_confirm_inst = MagicMock()
            mock_confirm_inst.ask.return_value = True
            mock_confirm.return_value = mock_confirm_inst

            wizards.handle_challenge_interactive(engine, console, [])

            assert mock_select.call_count == 3
            engine.start_challenge_farm.assert_called_once_with(
                target_event=mock_event,
                stage_num=2,
                stage_id=17790021,
                stage_name="Vs. Super Gogeta",
                preferred_difficulty="hard",
                difficulty=1,
            )

    def test_single_difficulty_event_skips_difficulty_prompt(self):
        """Single difficulty event (e.g. Red Zone / Union Master 1728) does not prompt for difficulty."""
        engine = MagicMock(spec=BotEngine)
        engine.dokkandb = MagicMock()
        engine.adb = MagicMock()
        engine.adb.is_connected.return_value = True

        mock_event = {"id": 1728, "name": "Union Master", "category": 20, "is_currently_open": True}
        mock_other_event = {
            "id": 100,
            "name": "Cell Max",
            "category": 20,
            "is_currently_open": True,
        }
        engine.dokkandb.get_challenge_events.return_value = [mock_event, mock_other_event]
        engine.dokkandb.get_event_details.return_value = {
            "id": 1728,
            "quests": [
                {
                    "quest_id": 1728020,
                    "quest_name": "Stage 20",
                    "stages": [{"stage_id": 17280205, "difficulty": 5, "act": 0}],
                }
            ],
        }
        engine.dokkandb.get_stage_boss_info.return_value = {"phases": []}
        engine.dokkandb.get_challenge_missions.return_value = []
        console, _ = _create_test_console()

        with (
            patch("questionary.select") as mock_select,
            patch("questionary.confirm") as mock_confirm,
        ):
            mock_stage_choice = {
                "stage_num": 20,
                "stage_name": "Stage 20",
                "stages": [{"stage_id": 17280205, "difficulty": 5, "act": 0}],
            }
            # Prompt 1: select event
            mock_select_inst1 = MagicMock()
            mock_select_inst1.ask.return_value = mock_event
            # Prompt 2: select stage
            mock_select_inst2 = MagicMock()
            mock_select_inst2.ask.return_value = mock_stage_choice
            mock_select.side_effect = [mock_select_inst1, mock_select_inst2]

            mock_confirm_inst = MagicMock()
            mock_confirm_inst.ask.return_value = True
            mock_confirm.return_value = mock_confirm_inst

            wizards.handle_challenge_interactive(engine, console, [])

            # Exactly 2 questionary.select calls (event and stage), 0 for difficulty!
            assert mock_select.call_count == 2
            engine.start_challenge_farm.assert_called_once_with(
                target_event=mock_event,
                stage_num=20,
                stage_id=17280205,
                stage_name="Stage 20",
                preferred_difficulty="super3",
                difficulty=5,
            )

    def test_select_challenge_boss_stage_wizard_with_multi_difficulty(self, mock_event_1779_setup):
        """Verifies select_challenge_boss_stage prompts for difficulty and constructs BossStage."""
        engine, mock_event = mock_event_1779_setup
        console, _ = _create_test_console()

        with patch("questionary.select") as mock_select:
            mock_stage_choice = {
                "stage_num": 2,
                "stage_name": "Vs. Super Gogeta",
                "stages": [
                    {"stage_id": 17790021, "difficulty": 1, "act": 20},
                    {"stage_id": 17790025, "difficulty": 5, "act": 25},
                ],
            }
            mock_diff_choice = {"stage_id": 17790021, "difficulty": 1, "act": 20}

            # Prompt 1: select event
            mock_select_inst1 = MagicMock()
            mock_select_inst1.ask.return_value = mock_event
            # Prompt 2: select stage
            mock_select_inst2 = MagicMock()
            mock_select_inst2.ask.return_value = mock_stage_choice
            # Prompt 3: select difficulty
            mock_select_inst3 = MagicMock()
            mock_select_inst3.ask.return_value = mock_diff_choice
            mock_select.side_effect = [mock_select_inst1, mock_select_inst2, mock_select_inst3]

            stage = wizards.select_challenge_boss_stage(engine, console)

            assert mock_select.call_count == 3
            assert stage is not None
            assert stage.stage_id == 17790021
            assert stage.difficulty == 1
            assert stage.difficulty_name == "Hard"


class TestChallengeTaskDifficultyAutomation:
    """Verifies that ChallengeTask stores preferred difficulty and difficulty level."""

    def test_challenge_task_difficulty_mapping(self):
        task = ChallengeTask(
            adb=MagicMock(),
            vision=MagicMock(),
            config={},
            dokkandb=MagicMock(),
            ai_client=MagicMock(),
            target_event={"id": 1779, "name": "Alternate Art Clash"},
            stage_num=2,
            stage_id=17790025,
            preferred_difficulty="super3",
            difficulty=5,
        )
        assert task.preferred_difficulty == "super3"
        assert task.difficulty == 5
