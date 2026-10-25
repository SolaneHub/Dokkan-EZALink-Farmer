"""Integration test for StageFarmTask using FakeADBClient and synthetic frames.

Black-box verification of Stage Farm clearing:
1. Two full runs up to the target_runs limit:
   Stage Select -> Friend Select -> Team Confirm -> Battle -> Results (OK / Attempt Again) -> Next Run -> Completion.
2. Premature termination when Stamina is Depleted:
   Stage Select -> Stamina Empty popup -> Cancel clicked -> Clean exit.

Validating only domain states, runs_completed counter, stamina_depleted flag,
and lifecycle callbacks (on_run_complete, on_status).
No pixel assertions or mock spy coordinate verifications.
"""

from __future__ import annotations

import time

import pytest

from dokkan_eza_link_farmer.automation.tasks.stage_farm import StageFarmTask
from dokkan_eza_link_farmer.automation.vision import Vision
from tests.harness.fake_adb import FakeADBClient
from tests.harness.fake_clock import VirtualClock
from tests.harness.fake_vision_frames import (
    create_synthetic_battle_frame,
    create_synthetic_difficulty_frame,
    create_synthetic_friend_select_frame,
    create_synthetic_quest_stage_frame,
    create_synthetic_results_frame,
    create_synthetic_stamina_empty_frame,
    create_synthetic_team_confirm_frame,
)

pytestmark = pytest.mark.slow


def test_stage_farm_blackbox_two_runs_target_reached() -> None:
    """Verifies 2 full stage farm runs black-box until reaching target runs limit."""
    adb = FakeADBClient(screen_size=(1080, 2400), max_taps=100)
    vision = Vision()

    # Pre-generate synthetic frames
    f_stage_select_1 = create_synthetic_difficulty_frame(vision=vision)
    f_friend_select_1 = create_synthetic_friend_select_frame(vision=vision)
    f_team_confirm_1 = create_synthetic_team_confirm_frame(vision=vision)
    f_battle_1 = create_synthetic_battle_frame(auto_active=True, vision=vision)
    f_results_1 = create_synthetic_results_frame(has_attempt_again=True, vision=vision)

    f_team_confirm_2 = create_synthetic_team_confirm_frame(vision=vision)
    f_battle_2 = create_synthetic_battle_frame(auto_active=True, vision=vision)
    f_results_2 = create_synthetic_results_frame(
        has_attempt_again=False, has_close_button=True, vision=vision
    )
    f_idle_after_2 = create_synthetic_quest_stage_frame(vision=vision)

    # 1. On Stage / Difficulty Select: tap difficulty (e.g. SUPER at 50% X, 40% Y -> ~540, 960)
    def on_diff_tap(x: int, y: int) -> None:
        _ = (x, y)
        if adb.screencap() is f_stage_select_1:
            adb.set_current_frame(f_friend_select_1)

    adb.add_box_transition(400, 800, 700, 1100, callback=on_diff_tap)

    # 2. On Friend Select: tap friend supporter / refresh (~82% X, ~18% Y)
    def on_friend_tap(x: int, y: int) -> None:
        _ = (x, y)
        if adb.screencap() is f_friend_select_1:
            adb.set_current_frame(f_team_confirm_1)

    adb.add_box_transition(750, 300, 1000, 550, callback=on_friend_tap)

    # 3. On Team Confirm: tap Start (~75% X, ~88% Y)
    def on_start_tap(x: int, y: int) -> None:
        _ = (x, y)
        curr = adb.screencap()
        if curr is f_team_confirm_1:
            adb.set_current_frame(f_battle_1)
        elif curr is f_team_confirm_2:
            adb.set_current_frame(f_battle_2)

    adb.add_box_transition(650, 1950, 900, 2250, callback=on_start_tap)

    # 4. On Battle Screen: auto battle active -> tap sky center (~50% X, ~35% Y)
    def on_battle_tap(x: int, y: int) -> None:
        _ = (x, y)
        curr = adb.screencap()
        if curr is f_battle_1:
            adb.set_current_frame(f_results_1)
        elif curr is f_battle_2:
            adb.set_current_frame(f_results_2)

    adb.add_box_transition(400, 700, 700, 1000, callback=on_battle_tap)

    # 5. On Results 1: dismiss_results_and_popups taps Attempt Again (~28% X, ~85% Y)
    # Transitions directly to Team Confirm 2
    def on_attempt_again_tap(x: int, y: int) -> None:
        _ = (x, y)
        if adb.screencap() is f_results_1:
            adb.set_current_frame(f_team_confirm_2)

    adb.add_box_transition(200, 1900, 400, 2200, callback=on_attempt_again_tap)

    # 6. On Results 2: Target reached (2 runs) -> dismisses with Close button (~50% X, ~85% Y)
    def on_close_tap(x: int, y: int) -> None:
        _ = (x, y)
        if adb.screencap() is f_results_2:
            adb.set_current_frame(f_idle_after_2)

    adb.add_box_transition(400, 1900, 700, 2200, callback=on_close_tap)

    # Start at stage selection
    adb.set_current_frame(f_stage_select_1)

    completed_runs: list[tuple[int, int]] = []
    status_messages: list[str] = []

    def on_run_complete(curr: int, tot: int) -> None:
        completed_runs.append((curr, tot))

    def on_status(msg: str) -> None:
        status_messages.append(msg)

    config = {"bot": {"loop_delay": 0.01}}
    task = StageFarmTask(
        adb=adb,  # type: ignore[arg-type]
        vision=vision,
        config=config,
        runs=2,
        preferred_difficulty="super",
        on_status=on_status,
        on_run_complete=on_run_complete,
    )

    real_start_time = time.perf_counter()
    with VirtualClock():
        task.run()

    duration = time.perf_counter() - real_start_time

    # Performance and boundary verification
    assert duration < 180.0, f"Integration test exceeded 180.0s threshold (took {duration:.2f}s)"

    # Black-box state verification:
    # 1. Task stopped cleanly upon reaching runs_target
    assert not task.is_running, "Task should have stopped running upon reaching target runs"
    assert task.runs_completed == 2, f"Expected 2 runs completed, got {task.runs_completed}"
    assert not task.stamina_depleted, "Stamina should not be marked depleted in successful run"

    # 2. Lifecycle callbacks verification
    assert completed_runs == [(1, 2), (2, 2)], (
        f"Expected completion callbacks [(1, 2), (2, 2)], got {completed_runs}"
    )
    assert any("2" in msg for msg in status_messages)


def test_stage_farm_blackbox_stamina_depleted() -> None:
    """Verifies StageFarmTask stops cleanly when stamina depleted popup appears."""
    adb = FakeADBClient(screen_size=(1080, 2400), max_taps=100)
    vision = Vision()

    f_stage_select = create_synthetic_difficulty_frame(vision=vision)
    f_stamina_empty = create_synthetic_stamina_empty_frame(vision=vision)
    f_stage_select_after_cancel = create_synthetic_difficulty_frame(vision=vision)

    # 1. Tap difficulty -> stamina depleted popup appears
    def on_diff_tap(x: int, y: int) -> None:
        _ = (x, y)
        if adb.screencap() is f_stage_select:
            adb.set_current_frame(f_stamina_empty)

    adb.add_box_transition(400, 800, 700, 1100, callback=on_diff_tap)

    # 2. Cancel button on Stamina Empty popup (~50% X, ~70% Y) -> dismissed
    def on_cancel_tap(x: int, y: int) -> None:
        _ = (x, y)
        if adb.screencap() is f_stamina_empty:
            adb.set_current_frame(f_stage_select_after_cancel)

    adb.add_box_transition(400, 1500, 700, 1800, callback=on_cancel_tap)

    adb.set_current_frame(f_stage_select)

    status_messages: list[str] = []

    def on_status(msg: str) -> None:
        status_messages.append(msg)

    config = {"bot": {"loop_delay": 0.01}}
    task = StageFarmTask(
        adb=adb,  # type: ignore[arg-type]
        vision=vision,
        config=config,
        runs=5,
        preferred_difficulty="super",
        on_status=on_status,
    )

    real_start_time = time.perf_counter()
    with VirtualClock():
        task.run()

    duration = time.perf_counter() - real_start_time

    assert duration < 180.0, f"Integration test exceeded 180.0s threshold (took {duration:.2f}s)"

    # Black-box state verification:
    # 1. Terminated cleanly
    assert not task.is_running, "Task should stop after stamina is depleted"
    assert task.stamina_depleted, "Task stamina_depleted property must be True"
    assert task.runs_completed == 0, "No runs should be marked completed before entering battle"

    # 2. Status callback received stamina notification
    assert any("Stamina" in msg for msg in status_messages)
