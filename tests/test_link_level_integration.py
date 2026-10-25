"""Integration test for LinkLevelFarmTask using FakeADBClient and synthetic frames.

Black-box verification of 2 consecutive Link Leveling runs with deck change:
Run 1: Quest Stage Select -> Difficulty Select -> Friend Select -> Team Confirm -> Team Edit (rebuild deck) -> Battle -> Results
Run 2: Attempt Again / Team Confirm -> Battle -> Results (Goal reached: 2 runs)
Validating only final state, run counters, and completion callbacks.
"""

from __future__ import annotations

import time

from dokkan_eza_link_farmer.automation.tasks.link_level_farm import LinkLevelFarmTask
from dokkan_eza_link_farmer.automation.vision import Vision
from tests.harness.fake_adb import FakeADBClient
from tests.harness.fake_clock import VirtualClock
from tests.harness.fake_vision_frames import (
    create_synthetic_battle_frame,
    create_synthetic_difficulty_frame,
    create_synthetic_friend_select_frame,
    create_synthetic_quest_stage_frame,
    create_synthetic_results_frame,
    create_synthetic_team_confirm_frame,
    create_synthetic_team_edit_frame,
)


def test_link_level_farm_blackbox_two_runs_with_deck_rebuild() -> None:
    """Verifies 2 full Link Leveling runs with team deck rebuild without pixel spying."""
    adb = FakeADBClient(screen_size=(1080, 2400), max_taps=100)
    vision = Vision()

    # Pre-generate synthetic Dokkan frames
    f_quest_stage = create_synthetic_quest_stage_frame("area_39_3", vision=vision)
    f_difficulty = create_synthetic_difficulty_frame(vision=vision)
    f_friend = create_synthetic_friend_select_frame(vision=vision)
    f_team_confirm_1 = create_synthetic_team_confirm_frame(vision=vision)
    f_team_edit = create_synthetic_team_edit_frame(filled_slots=6, vision=vision)
    f_battle_1 = create_synthetic_battle_frame(auto_active=True, vision=vision)
    f_results_1 = create_synthetic_results_frame(has_attempt_again=True, vision=vision)

    f_team_confirm_2 = create_synthetic_team_confirm_frame(vision=vision)
    f_battle_2 = create_synthetic_battle_frame(auto_active=True, vision=vision)
    f_results_2 = create_synthetic_results_frame(has_attempt_again=True, vision=vision)

    # Transition wiring:
    # 1. On Stage Select (Quest Area 39-3): tap stage card (~50% X, ~35% Y, y=840) -> Difficulty Select
    # 2. On Difficulty Select: tap SUPER (~50% X, ~40% Y, y=960) -> Friend Select
    def on_stage_or_diff_tap(x: int, y: int) -> None:
        _ = (x, y)
        curr = adb.screencap()
        if curr is f_quest_stage:
            adb.set_current_frame(f_difficulty)
        elif curr is f_difficulty:
            adb.set_current_frame(f_friend)

    adb.add_box_transition(400, 750, 700, 1050, callback=on_stage_or_diff_tap)

    # 3. On Friend Select: tap refresh button (~82% X, ~18% Y) -> Team Confirm 1
    adb.add_box_transition(750, 300, 1000, 550, next_frame=f_team_confirm_1)

    # 4. On Team Confirm 1: rebuild_team_from_box taps team formation (~80% X, ~49% Y) -> Team Edit
    def on_team_formation_tap(x: int, y: int) -> None:
        _ = (x, y)
        if adb.screencap() is f_team_confirm_1:
            adb.set_current_frame(f_team_edit)

    adb.add_box_transition(700, 1000, 1000, 1300, callback=on_team_formation_tap)

    # 5. On Team Edit: rebuild_team_from_box removes all, inserts cards, and taps Confirm Formation (~88% X, ~88% Y)
    # Returning to Team Confirm 1 (prepared for run)
    def on_confirm_formation_tap(x: int, y: int) -> None:
        _ = (x, y)
        if adb.screencap() is f_team_edit:
            adb.set_current_frame(f_team_confirm_1)

    adb.add_box_transition(800, 1950, 1050, 2250, callback=on_confirm_formation_tap)

    # 6. On Team Confirm (prepared): tap Start button (~75% X, ~88% Y) -> Battle 1 or Battle 2
    def on_start_tap(x: int, y: int) -> None:
        _ = (x, y)
        if adb.screencap() is f_team_confirm_1:
            adb.set_current_frame(f_battle_1)
        elif adb.screencap() is f_team_confirm_2:
            adb.set_current_frame(f_battle_2)

    adb.add_box_transition(650, 1950, 880, 2250, callback=on_start_tap)

    # 7. On Battle Screen: auto-battle active -> tap sky center (~50% X, ~35% Y)
    def on_battle_tap(x: int, y: int) -> None:
        _ = (x, y)
        if adb.screencap() is f_battle_1:
            adb.set_current_frame(f_results_1)
        elif adb.screencap() is f_battle_2:
            adb.set_current_frame(f_results_2)

    adb.add_box_transition(400, 700, 700, 1000, callback=on_battle_tap)

    # 8. On Results 1: dismiss_results_and_popups taps Attempt Again (~28% X, ~85% Y) -> Team Confirm 2
    adb.add_box_transition(200, 1900, 450, 2200, next_frame=f_team_confirm_2)

    # 9. On Results 2: target runs (2) is reached -> dismisses results and stops

    adb.set_current_frame(f_quest_stage)

    completed_runs: list[tuple[int, int]] = []
    status_messages: list[str] = []

    def on_run_complete(curr: int, tot: int) -> None:
        completed_runs.append((curr, tot))

    def on_status(msg: str) -> None:
        status_messages.append(msg)

    config = {
        "bot": {"loop_delay": 0.01},
        "link_leveling": {
            "rebuild_team_every_run": True,
            "use_attempt_again": True,
            "preferred_difficulty": "super",
        },
    }

    task = LinkLevelFarmTask(
        adb=adb,  # type: ignore[arg-type]
        vision=vision,
        config=config,
        runs=2,
        target_stage="area_39_3",
        on_status=on_status,
        on_run_complete=on_run_complete,
    )
    # Ensure filter initialized to test deck change path smoothly without dialog scroll overhead
    task.box_filter_initialized = True

    start_time = time.perf_counter()
    with VirtualClock():
        task.run()

    duration = time.perf_counter() - start_time

    # 1. Performance check: completed within reasonable time without hanging
    assert duration < 180.0, (
        f"Link Leveling integration test exceeded 180.0s threshold (took {duration:.2f}s)"
    )

    # 2. Black-box state verification:
    assert not task.is_running, "Task should have stopped running upon reaching target runs"
    assert task.runs_completed == 2, f"Expected 2 runs completed, got {task.runs_completed}"
    assert completed_runs == [(1, 2), (2, 2)], (
        f"Expected completion records [(1, 2), (2, 2)], got {completed_runs}"
    )
    assert any("Run 2/2" in msg or "run_completed" in msg or "2" in msg for msg in status_messages)
