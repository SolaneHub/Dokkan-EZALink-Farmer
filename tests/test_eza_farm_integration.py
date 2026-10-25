"""Integration test for EZAFarmTask using FakeADBClient and synthetic frames.

Black-box verification of an entire EZA progression loop:
Start -> Fight -> Win -> Results (OK / Attempt Again) -> Next Level progression
Validating only final state, run counters, and statue earnings.
"""

from __future__ import annotations

import time

import pytest

from dokkan_eza_link_farmer.automation.tasks.eza_farm import EZAFarmTask
from dokkan_eza_link_farmer.automation.vision import Vision
from tests.harness.fake_adb import FakeADBClient
from tests.harness.fake_clock import VirtualClock
from tests.harness.fake_vision_frames import (
    create_synthetic_battle_frame,
    create_synthetic_eza_select_frame,
    create_synthetic_friend_select_frame,
    create_synthetic_results_frame,
    create_synthetic_team_confirm_frame,
)

pytestmark = pytest.mark.slow


def test_eza_farm_blackbox_progression_loop() -> None:
    """Verifies a full EZA climb cycle black-box without pixel assertions or internal spying."""
    adb = FakeADBClient(screen_size=(1080, 2400))
    vision = Vision()

    # Pre-generate synthetic Dokkan frames
    f_eza_select_1 = create_synthetic_eza_select_frame(vision=vision)
    f_friend_select = create_synthetic_friend_select_frame(vision=vision)
    f_team_confirm = create_synthetic_team_confirm_frame(vision=vision)
    f_battle = create_synthetic_battle_frame(auto_active=True, vision=vision)
    f_results = create_synthetic_results_frame(has_attempt_again=False, vision=vision)
    f_eza_select_2 = create_synthetic_eza_select_frame(vision=vision)
    f_team_confirm_2 = create_synthetic_team_confirm_frame(vision=vision)
    f_battle_2 = create_synthetic_battle_frame(auto_active=True, vision=vision)
    f_results_2 = create_synthetic_results_frame(has_attempt_again=False, vision=vision)
    f_eza_select_3 = create_synthetic_eza_select_frame(vision=vision)

    # Wire screen transitions:
    # 1. On EZA Select (Lv. 1 or Lv. 2): tap fight button (~50% X, ~75% Y) -> Friend Select
    def on_fight_tap(x: int, y: int) -> None:
        _ = (x, y)
        curr = adb.screencap()
        if curr is f_eza_select_1 or curr is f_eza_select_2:
            adb.set_current_frame(f_friend_select)

    adb.add_box_transition(400, 1600, 700, 1900, callback=on_fight_tap)

    # 2. On Friend Select: tap refresh button (~82% X, ~18% Y) -> Team Confirm
    run_idx = {"count": 1}

    def on_friend_tap(x: int, y: int) -> None:
        _ = (x, y)
        if run_idx["count"] == 1:
            adb.set_current_frame(f_team_confirm)
        else:
            adb.set_current_frame(f_team_confirm_2)

    adb.add_box_transition(750, 300, 1000, 550, callback=on_friend_tap)

    # 3. On Team Confirm: tap Start button (~75% X, ~88% Y) -> Battle Screen
    def on_start_tap(x: int, y: int) -> None:
        _ = (x, y)
        curr = adb.screencap()
        if curr is f_team_confirm:
            adb.set_current_frame(f_battle)
        elif curr is f_team_confirm_2:
            adb.set_current_frame(f_battle_2)

    adb.add_box_transition(700, 1950, 950, 2250, callback=on_start_tap)

    # 4. On Battle Screen: auto-battle active -> tap to clear / finish battle -> Results Screen
    # (BaseTask.handle_battle taps center sky area ~50% X, ~35% Y)
    def on_battle_tap(x: int, y: int) -> None:
        _ = (x, y)
        curr = adb.screencap()
        if curr is f_battle:
            adb.set_current_frame(f_results)
        elif curr is f_battle_2:
            adb.set_current_frame(f_results_2)

    adb.add_box_transition(400, 700, 700, 1000, callback=on_battle_tap)

    # 5. On Results Screen: tap OK button (~50% X, ~85% Y) -> Next EZA Select (Lv. 2 or Lv. 3)
    def on_results_tap(x: int, y: int) -> None:
        _ = (x, y)
        curr = adb.screencap()
        if curr is f_results:
            run_idx["count"] = 2
            adb.set_current_frame(f_eza_select_2)
        elif curr is f_results_2:
            adb.set_current_frame(f_eza_select_3)

    adb.add_box_transition(400, 1900, 700, 2200, callback=on_results_tap)

    adb.set_current_frame(f_eza_select_1)

    completed_runs: list[tuple[int, int]] = []
    status_messages: list[str] = []

    def on_run_complete(curr: int, tot: int) -> None:
        completed_runs.append((curr, tot))

    def on_status(msg: str) -> None:
        status_messages.append(msg)

    config = {"bot": {"loop_delay": 0.01}}
    task = EZAFarmTask(
        adb=adb,  # type: ignore[arg-type]
        vision=vision,
        config=config,
        target_level=2,  # Target reaching 2 completed levels
        on_status=on_status,
        on_run_complete=on_run_complete,
    )

    real_start_time = time.perf_counter()
    with VirtualClock():
        task.run()

    duration = time.perf_counter() - real_start_time

    # 1. Performance check: completed within reasonable time without hanging
    assert duration < 180.0, f"Integration test exceeded 180.0s threshold (took {duration:.2f}s)"

    # 2. State verification: cleanly completed and stopped
    assert not task.is_running, "Task should have stopped running upon reaching target_level"
    assert task.runs_completed == 2, f"Expected 2 runs completed, got {task.runs_completed}"
    assert task.platinum_statues_earned == 2, (
        f"Expected 2 platinum statues, got {task.platinum_statues_earned}"
    )
    assert completed_runs == [(1, 2), (2, 2)], (
        f"Expected completion callback [(1, 2), (2, 2)], got {completed_runs}"
    )
    assert any("Statues" in msg or "Vittoria" in msg or "Victory" in msg for msg in status_messages)
