"""Fast in-memory unit tests for farming automation flows.

Tests:
1. StateDetector transitions (Stage Select, Team Confirm, Filter Modal, Stamina Empty, etc.).
2. Friend Leader fallback selection logic (same ID, compatible category covering 5+ members, leader copy fallback).
3. Team Formation dry-run and in-memory execution.
4. ROI template matching benchmark limited to 10 iterations (no disk load overhead).
"""

from __future__ import annotations

import time

import cv2
import numpy as np

from dokkan_eza_link_farmer.ai.models import DokkanCard, LeaderSkillSpec
from dokkan_eza_link_farmer.ai.synergy import select_best_friend_leader
from dokkan_eza_link_farmer.automation.game_state import GameState, StateDetector
from dokkan_eza_link_farmer.automation.team_formation import apply_team_in_game
from dokkan_eza_link_farmer.automation.vision import Vision
from dokkan_eza_link_farmer.core.bot_engine import BotEngine
from dokkan_eza_link_farmer.integrations.adb_client import ADBClient


def _make_card(
    card_id: int,
    name: str,
    rarity: int = 4,
    element: int = 0,
    element_name: str = "Super AGL",
    card_class: str = "Super",
    category_ids: list[int] | None = None,
    main_cats: list[int] | None = None,
    base_boost: float = 170.0,
) -> DokkanCard:
    spec = None
    if main_cats:
        spec = LeaderSkillSpec(
            main_category_ids=set(main_cats),
            base_boost_pct=base_boost,
        )
    return DokkanCard(
        id=card_id,
        name=name,
        rarity=rarity,
        element=element,
        element_name=element_name,
        card_class=card_class,
        category_ids=category_ids or [10],
        leader_spec=spec,
    )


class TestStateDetectorTransitions:
    """Tests StateDetector recognition using clean synthetic patterns without disk loading."""

    def test_state_detector_stage_select(self) -> None:
        vision = Vision()
        vision.load_template = lambda name: vision._template_cache.get(name)  # type: ignore[assignment]
        detector = StateDetector(vision)
        canvas = np.zeros((2400, 1080, 3), dtype=np.uint8)

        vision._template_cache["diff_super"] = np.ones((50, 100, 3), dtype=np.uint8) * 200
        vision._template_cache["diff_z_hard"] = np.ones((50, 100, 3), dtype=np.uint8) * 200
        canvas[800:850, 490:590] = vision._template_cache["diff_super"]
        canvas[1000:1050, 490:590] = vision._template_cache["diff_z_hard"]

        state, meta = detector.detect(canvas)
        assert state == GameState.STAGE_SELECT
        assert "diff_super" in meta
        assert "diff_z_hard" in meta

    def test_state_detector_team_confirm(self) -> None:
        vision = Vision()
        vision.load_template = lambda name: vision._template_cache.get(name)  # type: ignore[assignment]
        detector = StateDetector(vision)
        canvas = np.zeros((2400, 1080, 3), dtype=np.uint8)

        vision._template_cache["button_start"] = np.ones((60, 120, 3), dtype=np.uint8) * 220
        vision._template_cache["button_team_formation"] = np.ones((50, 100, 3), dtype=np.uint8) * 220
        canvas[1900:1960, 750:870] = vision._template_cache["button_start"]
        canvas[1150:1200, 750:850] = vision._template_cache["button_team_formation"]

        state, meta = detector.detect(canvas)
        assert state == GameState.TEAM_CONFIRM
        assert "start_button" in meta
        assert "team_formation_button" in meta

    def test_state_detector_stamina_empty(self) -> None:
        vision = Vision()
        vision.load_template = lambda name: vision._template_cache.get(name)  # type: ignore[assignment]
        detector = StateDetector(vision)
        canvas = np.zeros((2400, 1080, 3), dtype=np.uint8)

        vision._template_cache["header_restore_sta"] = np.ones((60, 200, 3), dtype=np.uint8) * 180
        vision._template_cache["button_cancel"] = np.ones((40, 100, 3), dtype=np.uint8) * 180
        canvas[350:410, 440:640] = vision._template_cache["header_restore_sta"]
        canvas[1480:1520, 490:590] = vision._template_cache["button_cancel"]

        state, meta = detector.detect(canvas)
        assert state == GameState.STAMINA_EMPTY
        assert "cancel_button" in meta

    def test_state_detector_filter_modal(self) -> None:
        vision = Vision()
        vision.load_template = lambda name: vision._template_cache.get(name)  # type: ignore[assignment]
        detector = StateDetector(vision)
        canvas = np.zeros((2400, 1080, 3), dtype=np.uint8)

        vision._template_cache["button_remove_all"] = np.ones((50, 150, 3), dtype=np.uint8) * 150
        canvas[1575:1625, 465:615] = vision._template_cache["button_remove_all"]

        state, _ = detector.detect(canvas)
        assert state == GameState.FILTER_MODAL



class TestFriendLeaderFallback:
    """Tests the Friend Leader resolution hierarchy and fallback logic."""

    def test_identical_card_highest_priority(self) -> None:
        leader = _make_card(1001, "SSJ Goku", main_cats=[10])
        cand1 = _make_card(1002, "SSJ Vegeta", main_cats=[10])
        cand2 = _make_card(1001, "SSJ Goku Dupe", main_cats=[10])

        friend = select_best_friend_leader([leader], [cand1, cand2])
        assert friend.id == 1001
        assert friend.is_friend_leader is True

    def test_compatible_candidate_selection_when_covering_five_members(self) -> None:
        leader = _make_card(1001, "SSJ Goku", category_ids=[10, 20], main_cats=[10])
        team = [leader] + [
            _make_card(2000 + i, f"Member {i}", category_ids=[10, 20]) for i in range(5)
        ]
        cand = _make_card(9001, "Compatible Leader", category_ids=[10], main_cats=[10], base_boost=200.0)

        friend = select_best_friend_leader(team, [cand])
        assert friend.id == 9001
        assert friend.is_friend_leader is True

    def test_fallback_to_exact_copy_of_leader_when_pool_incompatible_or_empty(self) -> None:
        leader = _make_card(1001, "SSJ Goku", category_ids=[10], main_cats=[10])
        team = [leader] + [
            _make_card(2000 + i, f"Member {i}", category_ids=[10]) for i in range(5)
        ]

        # Case 1: Empty candidate pool
        friend_empty = select_best_friend_leader(team, [])
        assert friend_empty.id == leader.id
        assert friend_empty.is_friend_leader is True

        # Case 2: Incompatible pool (does not cover leader category)
        cand_incompat = _make_card(9999, "Incompatible", category_ids=[99], main_cats=[99])
        friend_incompat = select_best_friend_leader(team, [cand_incompat])
        assert friend_incompat.id == leader.id
        assert friend_incompat.is_friend_leader is True


class TestTeamFormationDryRun:
    """Tests team formation logic in dry-run and disconnected environments."""

    def test_apply_team_in_game_empty_team(self) -> None:
        assert apply_team_in_game(None, None, None, team_cards=[]) is False

    def test_apply_team_in_game_dry_run_flag(self) -> None:
        team = [_make_card(1000 + i, f"Card {i}") for i in range(1, 7)]
        assert apply_team_in_game(None, None, None, team_cards=team, dry_run=True) is True

    def test_apply_team_in_game_none_adb(self) -> None:
        team = [_make_card(1000 + i, f"Card {i}") for i in range(1, 7)]
        assert apply_team_in_game(None, None, None, team_cards=team) is True

    def test_bot_engine_start_stage_farm_lifecycle(self) -> None:
        engine = BotEngine()
        engine.adb = ADBClient()
        engine.adb.is_connected = lambda: True  # type: ignore[assignment]
        engine.adb.screencap = lambda: np.zeros((2400, 1080, 3), dtype=np.uint8)  # type: ignore[assignment]

        assert not engine.is_task_running()
        ok = engine.start_stage_farm(runs=3, use_boost=False, preferred_difficulty="super")
        assert ok is True
        assert engine.is_task_running()
        assert engine.current_task is not None
        assert getattr(engine.current_task, "runs_target", None) == 3

        # Second launch prevented while running
        assert engine.start_stage_farm() is False
        engine.stop_task()
        assert not engine.is_task_running()


class TestVisionROIBenchmark:
    """Benchmark ROI template matching limited to 10 iterations to prevent latency regressions."""

    def test_vision_roi_match_benchmark_10_iterations(self) -> None:
        screen = np.zeros((2400, 1080, 3), dtype=np.uint8)
        tmpl = np.zeros((60, 120, 3), dtype=np.uint8)
        cv2.circle(tmpl, (60, 30), 20, (255, 200, 50), -1)

        y1, y2 = 1800, 2000
        x1, x2 = 500, 900
        screen[1850:1910, 600:720] = tmpl

        roi = screen[y1:y2, x1:x2]
        c_roi = np.ascontiguousarray(roi) if not roi.flags.c_contiguous else roi

        # Warm-up
        res = cv2.matchTemplate(c_roi, tmpl, cv2.TM_CCOEFF_NORMED)
        _ = cv2.minMaxLoc(res)

        t0 = time.perf_counter()
        for _ in range(10):
            res = cv2.matchTemplate(c_roi, tmpl, cv2.TM_CCOEFF_NORMED)
            _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(res)
        t1 = time.perf_counter()

        avg_ms = ((t1 - t0) * 1000.0) / 10.0
        assert max_val >= 0.99
        assert max_loc == (100, 50)
        assert avg_ms < 15.0, f"Average ROI matching took too long: {avg_ms:.2f}ms"
