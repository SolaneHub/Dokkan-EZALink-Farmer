"""Scenario integration tests for EZAFarmTask and LinkLevelFarmTask.

Validates multi-run battle progression, Attempt Again cycles, and clean limit exits
using AutomatedScenarioRunner in-memory without real ADB or emulator dependencies.
"""

from __future__ import annotations

from tests.harness.scenario_runner import AutomatedScenarioRunner

from dokkan_eza_link_farmer.automation.game_state import GameState
from dokkan_eza_link_farmer.automation.tasks.eza_farm import EZAFarmTask
from dokkan_eza_link_farmer.automation.tasks.link_level_farm import LinkLevelFarmTask


class TestScenarioFarmingIntegration:
    """End-to-end integration scenarios for farming tasks."""

    def test_eza_three_consecutive_runs_victory_and_attempt_again(self) -> None:
        """Simulates 3 consecutive EZA clears using synthetic state transitions.

        Verifies that:
        - Target level or runs completed reaches 3.
        - Platinum Hercule Statues earned increments to 3.
        - Task terminates cleanly when target level is reached.
        """
        runner = AutomatedScenarioRunner()
        config = runner.create_default_config()

        task = EZAFarmTask(
            adb=runner.adb,  # type: ignore[arg-type]
            vision=runner.vision,
            config=config,
            target_level=3,
            on_status=runner.on_status_handler,
        )

        # Initial screen: EZA_SELECT
        runner.set_initial_state(GameState.EZA_SELECT)

        # 3 complete cycles:
        # FRIEND_SELECT -> TEAM_CONFIRM -> BATTLE_SCREEN -> KO_SCREEN -> RESULTS_SCREEN -> EZA_SELECT
        sequence = []
        for _ in range(3):
            sequence.extend(
                [
                    GameState.FRIEND_SELECT,
                    GameState.TEAM_CONFIRM,
                    GameState.BATTLE_SCREEN,
                    GameState.KO_SCREEN,
                    GameState.RESULTS_SCREEN,
                    GameState.EZA_SELECT,
                ]
            )
        runner.register_state_sequence(sequence)

        # Execute
        runner.run_task_until_complete(task)

        assert task.runs_completed == 3
        assert task.platinum_statues_earned == 3
        assert not task.is_running
        assert task.is_stopped()
        # Verify status messages logged
        assert any("Platinum Statues: +3" in log or "Total: 3" in log for log in runner.status_logs)
        assert any("REACHED TARGET LEVEL 3" in log for log in runner.status_logs)

    def test_eza_stops_safely_on_stop_signal(self) -> None:
        """Verifies that an active EZA task terminates immediately and cleanly upon stop()."""
        runner = AutomatedScenarioRunner()
        config = runner.create_default_config()

        task = EZAFarmTask(
            adb=runner.adb,  # type: ignore[arg-type]
            vision=runner.vision,
            config=config,
            target_level=999,
            on_status=runner.on_status_handler,
        )

        runner.set_initial_state(GameState.EZA_SELECT)
        sequence = [
            GameState.FRIEND_SELECT,
            GameState.TEAM_CONFIRM,
            GameState.BATTLE_SCREEN,
        ]
        runner.register_state_sequence(sequence)

        # Trigger stop when entering battle screen
        runner.adb.add_transition(
            x=540,
            y=1200,
            radius=2000,
            callback=lambda _x, _y: (
                task.stop() if task.current_state == GameState.TEAM_CONFIRM else None
            ),
        )

        runner.run_task_until_complete(task)

        assert task.is_stopped()
        assert not task.is_running
        assert any("Task stop requested" in log for log in runner.status_logs)

    def test_link_level_farming_multi_run_and_limit_detection_exit(self) -> None:
        """Simulates Link Leveling runs using Attempt Again and clean exit upon limit reached.

        Verifies that:
        - LinkLevelFarmTask tracks runs_completed across consecutive battles.
        - Dismisses results with Attempt Again preference.
        - Exits cleanly when runs target is reached.
        """
        runner = AutomatedScenarioRunner()
        config = runner.create_default_config()

        task = LinkLevelFarmTask(
            adb=runner.adb,  # type: ignore[arg-type]
            vision=runner.vision,
            config=config,
            runs=2,
            target_stage="event",
            on_status=runner.on_status_handler,
        )

        # Start on STAGE_SELECT
        runner.set_initial_state(GameState.STAGE_SELECT)

        # Run 1: FRIEND_SELECT -> TEAM_CONFIRM -> MAP_SCREEN -> BATTLE_SCREEN -> KO_SCREEN -> RESULTS_ATTEMPT_AGAIN
        # Then Run 2 via Attempt Again: TEAM_CONFIRM -> MAP_SCREEN -> BATTLE_SCREEN -> KO_SCREEN -> RESULTS_SCREEN (reaches target 2)
        sequence = [
            # Run 1
            GameState.FRIEND_SELECT,
            GameState.TEAM_CONFIRM,
            GameState.MAP_SCREEN,
            GameState.BATTLE_SCREEN,
            GameState.KO_SCREEN,
            "RESULTS_ATTEMPT_AGAIN",
            # Run 2 via Attempt Again -> directly on TEAM_CONFIRM
            GameState.TEAM_CONFIRM,
            GameState.MAP_SCREEN,
            GameState.BATTLE_SCREEN,
            GameState.KO_SCREEN,
            GameState.RESULTS_SCREEN,
        ]
        runner.register_state_sequence(sequence)

        # Execute
        runner.run_task_until_complete(task)

        assert task.runs_completed == 2
        assert not task.is_running
        assert task.is_stopped()
        assert any("Target of 2 runs reached!" in log for log in runner.status_logs)
        assert any("2 runs executed" in log for log in runner.status_logs)

    def test_link_level_farming_limit_reached_clean_exit(self) -> None:
        """Simulates Link Leveling detecting daily/attempt limit popup and exiting cleanly."""
        runner = AutomatedScenarioRunner()
        config = runner.create_default_config()

        task = LinkLevelFarmTask(
            adb=runner.adb,  # type: ignore[arg-type]
            vision=runner.vision,
            config=config,
            runs=None,  # Infinite until limit reached
            target_stage="event",
            on_status=runner.on_status_handler,
        )

        runner.set_initial_state(GameState.STAGE_SELECT)
        runner.register_state_sequence(["DIALOG_LIMIT_OK"])

        # When OK on the limit dialog is tapped, signal task stop safely
        runner.adb.add_transition(
            x=540,
            y=1400,
            radius=2000,
            callback=lambda _x, _y: (
                task.stop() if task.current_state == GameState.RESULTS_SCREEN else None
            ),
        )

        runner.run_task_until_complete(task)

        assert task.is_stopped()
        assert not task.is_running
        assert any("Tapped OK at" in log or "OK press" in log for log in runner.status_logs)

    def test_scenario_stamina_depletion_and_recovery_stop(self) -> None:
        """Simulates full flow: Home -> Quest -> Fight -> Stamina Empty -> Safe Stop.

        Asserts invariants:
        - Task terminates safely (task.is_running is False, task.is_stopped() is True).
        - Completed runs is tracked accurately (runs_completed == 1).
        - Zero unhandled crashes and zero real sleeps (execution time < 300ms).
        """
        import time

        runner = AutomatedScenarioRunner()
        config = runner.create_default_config()
        config["link_leveling"]["rebuild_team_every_run"] = False
        config["link_leveling"]["auto_swap_maxed_units"] = False
        config["link_leveling"]["stamina_refill_mode"] = "none"

        task = LinkLevelFarmTask(
            adb=runner.adb,  # type: ignore[arg-type]
            vision=runner.vision,
            config=config,
            runs=None,
            target_stage="area_39_3",
            on_status=runner.on_status_handler,
        )

        runner.set_initial_state(GameState.HOME_SCREEN)
        sequence = [
            GameState.MODE_SELECT,
            GameState.QUEST_SELECT,
            GameState.STAGE_SELECT,
            GameState.FRIEND_SELECT,
            GameState.TEAM_CONFIRM,
            GameState.MAP_SCREEN,
            GameState.BATTLE_SCREEN,
            GameState.KO_SCREEN,
            GameState.RESULTS_SCREEN,
            GameState.STAMINA_EMPTY,
        ]
        runner.register_state_sequence(sequence)

        t0 = time.perf_counter()
        runner.run_task_until_complete(task)
        elapsed_sec = time.perf_counter() - t0

        # Invariant Assertions
        assert not task.is_running
        assert task.is_stopped()
        assert task.runs_completed == 1
        assert elapsed_sec < 0.3, f"Execution took too long: {elapsed_sec:.3f}s >= 0.300s"
        assert any("Stamina depleted" in log for log in runner.status_logs)
