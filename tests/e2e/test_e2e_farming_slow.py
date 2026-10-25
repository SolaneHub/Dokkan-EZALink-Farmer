"""End-to-end black-box progression tests on synthetic visual canvas frames.

Covers:
1. EZA Farm multi-level climb cycle (Fight -> Win -> Level progression -> Statues).
2. Link Leveling stage progression with deck rebuild.
3. Stage Farm multi-run completion and stamina depletion handling.
"""

from __future__ import annotations

import time

import pytest
from tests.harness.fake_adb import FakeADBClient
from tests.harness.fake_clock import VirtualClock
from tests.harness.fake_vision_frames import (
    create_synthetic_battle_frame,
    create_synthetic_difficulty_frame,
    create_synthetic_eza_select_frame,
    create_synthetic_friend_select_frame,
    create_synthetic_quest_stage_frame,
    create_synthetic_results_frame,
    create_synthetic_stamina_empty_frame,
    create_synthetic_team_confirm_frame,
    create_synthetic_team_edit_frame,
)

from dokkan_eza_link_farmer.automation.tasks.eza_farm import EZAFarmTask
from dokkan_eza_link_farmer.automation.tasks.link_level_farm import LinkLevelFarmTask
from dokkan_eza_link_farmer.automation.tasks.stage_farm import StageFarmTask
from dokkan_eza_link_farmer.automation.vision import Vision

pytestmark = pytest.mark.slow


def test_eza_farm_blackbox_progression_loop() -> None:
    """Verifies a full EZA climb cycle black-box without pixel assertions or internal spying."""
    adb = FakeADBClient(screen_size=(1080, 2400))
    vision = Vision()

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

    def on_fight_tap(x: int, y: int) -> None:
        _ = (x, y)
        curr = adb.screencap()
        if curr is f_eza_select_1 or curr is f_eza_select_2:
            adb.set_current_frame(f_friend_select)

    adb.add_box_transition(400, 1600, 700, 1900, callback=on_fight_tap)

    run_idx = {"count": 1}

    def on_friend_tap(x: int, y: int) -> None:
        _ = (x, y)
        if run_idx["count"] == 1:
            adb.set_current_frame(f_team_confirm)
        else:
            adb.set_current_frame(f_team_confirm_2)

    adb.add_box_transition(750, 300, 1000, 550, callback=on_friend_tap)

    def on_start_tap(x: int, y: int) -> None:
        _ = (x, y)
        curr = adb.screencap()
        if curr is f_team_confirm:
            adb.set_current_frame(f_battle)
        elif curr is f_team_confirm_2:
            adb.set_current_frame(f_battle_2)

    adb.add_box_transition(700, 1950, 950, 2250, callback=on_start_tap)

    def on_battle_tap(x: int, y: int) -> None:
        _ = (x, y)
        curr = adb.screencap()
        if curr is f_battle:
            adb.set_current_frame(f_results)
        elif curr is f_battle_2:
            adb.set_current_frame(f_results_2)

    adb.add_box_transition(400, 700, 700, 1000, callback=on_battle_tap)

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
        target_level=2,
        on_status=on_status,
        on_run_complete=on_run_complete,
    )

    real_start_time = time.perf_counter()
    with VirtualClock():
        task.run()

    duration = time.perf_counter() - real_start_time

    assert duration < 180.0
    assert not task.is_running
    assert task.runs_completed == 2
    assert task.platinum_statues_earned == 2
    assert completed_runs == [(1, 2), (2, 2)]
    assert any("Statues" in msg or "Vittoria" in msg or "Victory" in msg for msg in status_messages)


def test_link_level_farm_blackbox_two_runs_with_deck_rebuild() -> None:
    """Verifies 2 full Link Leveling runs with team deck rebuild."""
    adb = FakeADBClient(screen_size=(1080, 2400), max_taps=100)
    vision = Vision()

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

    def on_stage_or_diff_tap(x: int, y: int) -> None:
        _ = (x, y)
        curr = adb.screencap()
        if curr is f_quest_stage:
            adb.set_current_frame(f_difficulty)
        elif curr is f_difficulty:
            adb.set_current_frame(f_friend)

    adb.add_box_transition(400, 750, 700, 1050, callback=on_stage_or_diff_tap)
    adb.add_box_transition(750, 300, 1000, 550, next_frame=f_team_confirm_1)

    def on_team_formation_tap(x: int, y: int) -> None:
        _ = (x, y)
        if adb.screencap() is f_team_confirm_1:
            adb.set_current_frame(f_team_edit)

    adb.add_box_transition(700, 1000, 1000, 1300, callback=on_team_formation_tap)

    def on_confirm_formation_tap(x: int, y: int) -> None:
        _ = (x, y)
        if adb.screencap() is f_team_edit:
            adb.set_current_frame(f_team_confirm_1)

    adb.add_box_transition(800, 1950, 1050, 2250, callback=on_confirm_formation_tap)

    def on_start_tap(x: int, y: int) -> None:
        _ = (x, y)
        if adb.screencap() is f_team_confirm_1:
            adb.set_current_frame(f_battle_1)
        elif adb.screencap() is f_team_confirm_2:
            adb.set_current_frame(f_battle_2)

    adb.add_box_transition(650, 1950, 880, 2250, callback=on_start_tap)

    def on_battle_tap(x: int, y: int) -> None:
        _ = (x, y)
        if adb.screencap() is f_battle_1:
            adb.set_current_frame(f_results_1)
        elif adb.screencap() is f_battle_2:
            adb.set_current_frame(f_results_2)

    adb.add_box_transition(400, 700, 700, 1000, callback=on_battle_tap)
    adb.add_box_transition(200, 1900, 450, 2200, next_frame=f_team_confirm_2)

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
    task.box_filter_initialized = True

    start_time = time.perf_counter()
    with VirtualClock():
        task.run()

    duration = time.perf_counter() - start_time

    assert duration < 180.0
    assert not task.is_running
    assert task.runs_completed == 2
    assert completed_runs == [(1, 2), (2, 2)]
    assert any("Run 2/2" in msg or "run_completed" in msg or "2" in msg for msg in status_messages)


def test_stage_farm_blackbox_two_runs_target_reached() -> None:
    """Verifies 2 full stage farm runs black-box until reaching target runs limit."""
    adb = FakeADBClient(screen_size=(1080, 2400), max_taps=100)
    vision = Vision()

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

    def on_diff_tap(x: int, y: int) -> None:
        _ = (x, y)
        if adb.screencap() is f_stage_select_1:
            adb.set_current_frame(f_friend_select_1)

    adb.add_box_transition(400, 800, 700, 1100, callback=on_diff_tap)

    def on_friend_tap(x: int, y: int) -> None:
        _ = (x, y)
        if adb.screencap() is f_friend_select_1:
            adb.set_current_frame(f_team_confirm_1)

    adb.add_box_transition(750, 300, 1000, 550, callback=on_friend_tap)

    def on_start_tap(x: int, y: int) -> None:
        _ = (x, y)
        curr = adb.screencap()
        if curr is f_team_confirm_1:
            adb.set_current_frame(f_battle_1)
        elif curr is f_team_confirm_2:
            adb.set_current_frame(f_battle_2)

    adb.add_box_transition(650, 1950, 900, 2250, callback=on_start_tap)

    def on_battle_tap(x: int, y: int) -> None:
        _ = (x, y)
        curr = adb.screencap()
        if curr is f_battle_1:
            adb.set_current_frame(f_results_1)
        elif curr is f_battle_2:
            adb.set_current_frame(f_results_2)

    adb.add_box_transition(400, 700, 700, 1000, callback=on_battle_tap)

    def on_attempt_again_tap(x: int, y: int) -> None:
        _ = (x, y)
        if adb.screencap() is f_results_1:
            adb.set_current_frame(f_team_confirm_2)

    adb.add_box_transition(200, 1900, 400, 2200, callback=on_attempt_again_tap)

    def on_close_tap(x: int, y: int) -> None:
        _ = (x, y)
        if adb.screencap() is f_results_2:
            adb.set_current_frame(f_idle_after_2)

    adb.add_box_transition(400, 1900, 700, 2200, callback=on_close_tap)

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

    assert duration < 180.0
    assert not task.is_running
    assert task.runs_completed == 2
    assert not task.stamina_depleted
    assert completed_runs == [(1, 2), (2, 2)]
    assert any("2" in msg for msg in status_messages)


def test_stage_farm_blackbox_stamina_depleted() -> None:
    """Verifies StageFarmTask stops cleanly when stamina depleted popup appears."""
    adb = FakeADBClient(screen_size=(1080, 2400), max_taps=100)
    vision = Vision()

    f_stage_select = create_synthetic_difficulty_frame(vision=vision)
    f_stamina_empty = create_synthetic_stamina_empty_frame(vision=vision)
    f_stage_select_after_cancel = create_synthetic_difficulty_frame(vision=vision)

    def on_diff_tap(x: int, y: int) -> None:
        _ = (x, y)
        if adb.screencap() is f_stage_select:
            adb.set_current_frame(f_stamina_empty)

    adb.add_box_transition(400, 800, 700, 1100, callback=on_diff_tap)

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

    assert duration < 180.0
    assert not task.is_running
    assert task.stamina_depleted
    assert task.runs_completed == 0
    assert any("Stamina" in msg for msg in status_messages)
