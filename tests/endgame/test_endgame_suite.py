"""Unified test suite for Combat Telemetry, Endgame Runner, and Subsystem Isolation.

Consolidates:
- Telemetry & Ring Buffer FIFO (10-frame / configurable capacity)
- Culprit Attribution (direct culprit, ambiguous AoE, elemental weighting)
- Friend Leader immunity in slot 7 (0 penalty to player deck, instant retry)
- Episodic Memory & Post-Defeat Decision Tree (InstantRetry, SurgicalReplace, DemoteLeader)
- Consecutive early defeats tracking & reset mechanics
- Orphan partner link checks and rotation pair-swap fallbacks
- EndgameRunner 3-run lifecycle, dry run execution, and in-game formation calls
- Boss catalog loading & numeric DokkanDB stage resolution
- Subsystem & API isolation (in-memory AST & sys.modules verification without subprocesses)
"""

from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import dokkan_eza_link_farmer.ai as ai
from dokkan_eza_link_farmer.ai.boss_catalog import get_boss_stage, list_boss_stages
from dokkan_eza_link_farmer.ai.endgame import (
    CombatRingBuffer,
    EndgameResult,
    EndgameRunner,
    EndgameRunnerState,
)
from dokkan_eza_link_farmer.ai.endgame.telemetry import (
    CombatFrame,
    CombatTelemetryTracker,
    CulpritAttribution,
    EpisodicMemory,
    TurnSnapshot,
    attribute_culprit,
    create_failure_report,
    is_debug_telemetry_enabled,
    set_debug_telemetry,
)
from dokkan_eza_link_farmer.ai.models import (
    BossEnemy,
    BossPhase,
    BossStage,
    CardForm,
    DokkanCard,
    LeaderSkillSpec,
    PassiveTags,
    SATags,
)
from dokkan_eza_link_farmer.ai.solver import DokkanConstraintSolver
from dokkan_eza_link_farmer.automation.tasks import (
    box_scanner,
    challenge_task,
    eza_farm,
    link_level_farm,
    stage_farm,
)
from dokkan_eza_link_farmer.core import bot_engine
from dokkan_eza_link_farmer.core.bot_engine import BotEngine


def make_card(
    card_id: int,
    name: str,
    element: int = 0,
    links: list[str] | None = None,
    category_ids: list[int] | None = None,
    leader_spec: LeaderSkillSpec | None = None,
    slot1_viable: bool = False,
    dr_pct: int = 0,
    has_guard: bool = False,
    stacks_def: bool = False,
    is_rainbow: bool = False,
) -> DokkanCard:
    """Helper to synthesize fully valid DokkanCard fixtures."""
    links_list = links or [
        "Super Saiyan",
        "Prepared for Battle",
        "Fierce Battle",
        "Kamehameha",
    ]
    cats = category_ids or [10, 20]
    base_form = CardForm(
        form_id=card_id,
        form_index=0,
        form_name=name,
        element=element,
        links=list(links_list),
        passive_tags=PassiveTags(
            slot1_viable=slot1_viable,
            dr_base_percent=dr_pct,
            has_guard=has_guard,
        ),
        sa_tags=SATags(stacks_def=stacks_def),
    )
    return DokkanCard(
        id=card_id,
        name=name,
        element=element,
        category_ids=cats,
        links=list(links_list),
        leader_spec=leader_spec,
        base_form=base_form,
        is_rainbow=is_rainbow,
    )


# ==============================================================================
# 1. Telemetry & Ring Buffer Tests
# ==============================================================================


class TestTurnSnapshot:
    """Tests TurnSnapshot model capturing pre-turn combat telemetry."""

    def test_turn_snapshot_recording(self) -> None:
        c1 = make_card(101, "Goku", element=0)
        c2 = make_card(102, "Vegeta", element=3)
        c3 = make_card(103, "Trunks", element=4)

        snapshot = TurnSnapshot(
            turn_number=3,
            boss_phase_index=2,
            boss_element=3,
            boss_element_name="Extreme STR",
            boss_hp_percent=65.5,
            player_hp_percent=82.0,
            active_rotation=[c1, c2, c3],
            active_item="Whis",
        )

        assert snapshot.turn_number == 3
        assert snapshot.boss_phase_index == 2
        assert snapshot.boss_element == 3
        assert snapshot.boss_element_name == "Extreme STR"
        assert snapshot.boss_hp_percent == 65.5
        assert snapshot.player_hp_percent == 82.0
        assert len(snapshot.active_rotation) == 3
        assert snapshot.active_rotation[0].id == 101
        assert snapshot.active_rotation[1].id == 102
        assert snapshot.active_rotation[2].id == 103
        assert snapshot.active_item == "Whis"
        assert snapshot.timestamp > 0

        data = snapshot.to_dict()
        assert data["turn_number"] == 3
        assert data["active_rotation_ids"] == [101, 102, 103]
        assert data["active_item"] == "Whis"


class TestCombatRingBuffer:
    """Tests the rolling FIFO window of the pre-KO ring buffer."""

    def test_ring_buffer_fifo_capacity(self) -> None:
        ring = CombatRingBuffer(capacity=4)
        assert ring.capacity == 4
        assert len(ring) == 0

        # Push 5 frames to exceed capacity 4
        frames = [
            CombatFrame(frame_id=i, timestamp=float(i), player_hp_after=100.0 - i * 10)
            for i in range(1, 6)
        ]
        for f in frames:
            ring.record_frame(f)

        assert len(ring) == 4
        pre_ko = ring.get_pre_ko_frames()
        assert len(pre_ko) == 4
        # Frame 1 dropped, frames 2..5 preserved in FIFO order
        assert [f.frame_id for f in pre_ko] == [2, 3, 4, 5]

        # Push another frame
        ring.record_frame(CombatFrame(frame_id=6, timestamp=6.0, is_lethal=True))
        assert len(ring) == 4
        assert [f.frame_id for f in ring.get_pre_ko_frames()] == [3, 4, 5, 6]

        ring.clear()
        assert len(ring) == 0

    def test_ring_buffer_ten_frame_fifo_standard(self) -> None:
        """Sanfilippo spec: verifies standard 10-frame FIFO combat ring buffer behavior."""
        ring = CombatRingBuffer(capacity=10)
        assert ring.capacity == 10

        for i in range(1, 15):
            ring.record_frame(
                CombatFrame(
                    frame_id=i,
                    active_slot=(i % 3) + 1,
                    incoming_damage=10000 * i,
                    player_hp_after=max(0.0, 100.0 - i * 5),
                    is_lethal=(i == 14),
                )
            )

        assert len(ring) == 10
        frames = ring.get_pre_ko_frames()
        assert len(frames) == 10
        assert [f.frame_id for f in frames] == list(range(5, 15))
        assert frames[-1].is_lethal is True

    def test_ring_buffer_invalid_capacity(self) -> None:
        with pytest.raises(ValueError, match="capacity must be > 0"):
            CombatRingBuffer(capacity=0)


class TestTelemetryFreezing:
    """Verifies that extended telemetry ring-buffer accumulation is disabled during standard farming."""

    def test_standard_farming_ring_buffer_frozen_by_default(self) -> None:
        """In standard mode without --debug-telemetry, CombatTelemetryTracker skips non-lethal frames."""
        set_debug_telemetry(False)
        assert is_debug_telemetry_enabled() is False

        ring = CombatRingBuffer(capacity=4)
        tracker = CombatTelemetryTracker(ring_buffer=ring)

        frame = tracker.record_action(
            active_slot=1,
            target_card_id=101,
            incoming_damage=50000,
            player_hp_after=80.0,
            is_lethal=False,
        )

        assert frame is not None
        assert len(ring) == 0

        # But lethal frames must always be recorded for post-defeat culprit attribution
        lethal_frame = tracker.record_action(
            active_slot=2,
            target_card_id=102,
            incoming_damage=700000,
            player_hp_after=0.0,
            is_lethal=True,
        )
        assert lethal_frame is not None
        assert len(ring) == 1
        assert ring.get_pre_ko_frames()[0].target_card_id == 102

    def test_debug_telemetry_flag_enables_ring_buffer_accumulation(self) -> None:
        """When --debug-telemetry is set or debug_telemetry=True, ring_buffer records non-lethal frames."""
        try:
            set_debug_telemetry(True)
            assert is_debug_telemetry_enabled() is True

            ring = CombatRingBuffer(capacity=4)
            tracker = CombatTelemetryTracker(ring_buffer=ring)

            frame = tracker.record_action(
                active_slot=2,
                target_card_id=102,
                incoming_damage=700000,
                player_hp_after=50.0,
                is_lethal=False,
            )

            assert frame is not None
            assert len(ring) == 1
            assert ring.get_pre_ko_frames()[0].target_card_id == 102
        finally:
            set_debug_telemetry(False)


# ==============================================================================
# 2. Culprit Attribution & Friend Leader Immunity
# ==============================================================================


class TestCulpritAttribution:
    """Tests direct culprit identification, friend leader immunity, and vulnerability sharing."""

    def test_direct_culprit_attribution(self) -> None:
        c1 = make_card(101, "Slot 1 Unit")
        c2 = make_card(102, "Slot 2 Unit (Vulnerable)")
        c3 = make_card(103, "Slot 3 Unit")
        snapshot = TurnSnapshot(
            turn_number=4,
            boss_phase_index=1,
            boss_element=3,
            boss_element_name="STR",
            boss_hp_percent=50.0,
            player_hp_percent=0.0,
            active_rotation=[c1, c2, c3],
        )

        ring = CombatRingBuffer(capacity=4)
        ring.record_frame(CombatFrame(frame_id=1, active_slot=1, player_hp_after=80.0))
        ring.record_frame(
            CombatFrame(
                frame_id=2,
                active_slot=2,
                target_card_id=102,
                incoming_damage=550000,
                player_hp_after=0.0,
                is_lethal=True,
            )
        )

        attribution = attribute_culprit(ring, snapshot)
        assert attribution.direct_culprit_slot == 2
        assert attribution.direct_culprit_id == 102
        assert attribution.is_friend_leader is False
        assert attribution.is_ambiguous is False
        assert attribution.vulnerability_shares == {102: 1.0}

    def test_vulnerability_sharing_ambiguous(self) -> None:
        c1 = make_card(101, "Slot 1 Neutral", element=0)
        c2 = make_card(102, "Slot 2 Neutral", element=0)
        c3 = make_card(103, "Slot 3 Neutral", element=0)
        snapshot = TurnSnapshot(
            turn_number=3,
            boss_phase_index=1,
            boss_element=0,
            boss_element_name="AGL",
            boss_hp_percent=70.0,
            player_hp_percent=0.0,
            active_rotation=[c1, c2, c3],
        )

        ring = CombatRingBuffer(capacity=4)
        ring.record_frame(
            CombatFrame(
                frame_id=1,
                active_slot=None,
                action_type="aoe",
                incoming_damage=400000,
                player_hp_after=0.0,
                is_lethal=True,
            )
        )

        attribution = attribute_culprit(ring, snapshot)
        assert attribution.is_ambiguous is True
        assert attribution.direct_culprit_id is None
        assert attribution.direct_culprit_slot is None
        assert len(attribution.vulnerability_shares) == 3
        for card_id in (101, 102, 103):
            assert attribution.vulnerability_shares[card_id] == pytest.approx(0.33, abs=0.01)

    def test_elemental_weighting_ambiguous(self) -> None:
        c1 = make_card(101, "AGL Tank", element=0, has_guard=True)
        c2 = make_card(102, "AGL Sub", element=0)
        c3 = make_card(103, "PHY Fragile", element=4, dr_pct=0, has_guard=False)

        snapshot = TurnSnapshot(
            turn_number=3,
            boss_phase_index=1,
            boss_element=3,
            boss_element_name="STR",
            boss_hp_percent=60.0,
            player_hp_percent=0.0,
            active_rotation=[c1, c2, c3],
        )

        ring = CombatRingBuffer(capacity=4)
        ring.record_frame(
            CombatFrame(
                frame_id=1,
                active_slot=None,
                action_type="aoe",
                player_hp_after=0.0,
                is_lethal=True,
            )
        )

        boss_phase = BossPhase(phase_index=1, element=3, element_name="STR", has_aoe=True)
        attribution = attribute_culprit(ring, snapshot, boss_phase=boss_phase)
        assert attribution.is_ambiguous is True
        assert attribution.vulnerability_shares[103] == pytest.approx(0.60, abs=0.01)
        assert attribution.vulnerability_shares[101] == pytest.approx(0.20, abs=0.01)
        assert attribution.vulnerability_shares[102] == pytest.approx(0.20, abs=0.01)

    def test_friend_leader_immunity_slot7(self, tmp_path: Path) -> None:
        friend = make_card(999, "Friend Lead", element=0)
        c1 = make_card(101, "Player Unit 1")
        c2 = make_card(102, "Player Unit 2")
        c3 = make_card(103, "Player Unit 3")

        snapshot = TurnSnapshot(
            turn_number=2,
            boss_phase_index=1,
            boss_element=1,
            boss_element_name="TEQ",
            boss_hp_percent=85.0,
            player_hp_percent=0.0,
            active_rotation=[c1, c2, c3],
        )

        ring = CombatRingBuffer(capacity=4)
        ring.record_frame(
            CombatFrame(
                frame_id=1,
                active_slot=7,
                target_card_id=999,
                incoming_damage=700000,
                player_hp_after=0.0,
                is_lethal=True,
            )
        )

        attribution = attribute_culprit(ring, snapshot, friend_leader=friend)
        assert attribution.is_friend_leader is True
        assert attribution.direct_culprit_slot == 7
        assert attribution.direct_culprit_id == 999
        assert attribution.vulnerability_shares == {}

        mem_file = tmp_path / "test_ai_memory.json"
        memory = EpisodicMemory(cache_path=mem_file)
        player_team = [c1, c2, c3, make_card(104, "P4"), make_card(105, "P5"), make_card(106, "P6")]

        decision = memory.evaluate_post_defeat(
            stage_id=101,
            snapshot=snapshot,
            attribution=attribution,
            current_team=player_team,
            user_box=player_team,
        )

        assert decision.action == "InstantRetry"
        assert decision.team == player_team
        assert decision.replaced_card_ids == []
        assert "Friend Leader (Slot 7)" in decision.reason
        assert "Bad RNG" in decision.reason
        penalties = memory.get_death_penalties(101)
        assert len(penalties) == 0


# ==============================================================================
# 3. Episodic Memory Decision Tree & Culprit Replacement
# ==============================================================================


class TestEpisodicMemoryDecisionTree:
    """Tests the 3-tier post-defeat decision tree, leader demotion, and persistence."""

    @pytest.fixture
    def test_team_and_box(self) -> tuple[list[DokkanCard], list[DokkanCard]]:
        spec = LeaderSkillSpec(main_category_ids=[10], base_boost_pct=170)
        leader = make_card(1001, "LR Super Vegito", element=0, leader_spec=spec, category_ids=[10])
        core1 = make_card(
            1002,
            "Super Gogeta",
            element=3,
            category_ids=[10],
            links=["Super Saiyan", "Kamehameha", "Warrior Gods", "Prepared for Battle"],
        )
        core2 = make_card(
            1003,
            "Gotenks",
            element=4,
            category_ids=[10],
            links=["Super Saiyan", "Kamehameha", "Fusion", "Prepared for Battle"],
        )
        floater1 = make_card(1004, "Piccolo", element=1, category_ids=[10])
        floater2 = make_card(1005, "Gohan", element=2, category_ids=[10])
        floater3 = make_card(1006, "Krillin", element=3, category_ids=[10])

        current_team = [leader, core1, core2, floater1, floater2, floater3]

        spec2 = LeaderSkillSpec(main_category_ids=[10], base_boost_pct=170)
        second_lead = make_card(
            2001,
            "LR Beast Gohan",
            element=3,
            leader_spec=spec2,
            category_ids=[10],
            slot1_viable=True,
        )
        sub_agl = make_card(
            2002, "AGL Tank Vegito", element=0, category_ids=[10], has_guard=True, dr_pct=50
        )
        sub_high_link = make_card(
            2003,
            "Gogeta Blue",
            element=0,
            category_ids=[10],
            links=[
                "Super Saiyan",
                "Kamehameha",
                "Warrior Gods",
                "Prepared for Battle",
                "Fierce Battle",
            ],
        )

        box = list(current_team) + [second_lead, sub_agl, sub_high_link]
        return current_team, box

    def test_decision_tree_instant_retry_low_hp(
        self, tmp_path: Path, test_team_and_box: tuple[list[DokkanCard], list[DokkanCard]]
    ) -> None:
        current_team, box = test_team_and_box
        memory = EpisodicMemory(cache_path=tmp_path / "memory.json")

        snapshot = TurnSnapshot(
            turn_number=6,
            boss_phase_index=3,
            boss_element=0,
            boss_element_name="AGL",
            boss_hp_percent=12.0,
            player_hp_percent=0.0,
            active_rotation=current_team[:3],
        )
        attribution = CulpritAttribution(
            direct_culprit_id=1004,
            direct_culprit_slot=3,
            is_friend_leader=False,
            is_ambiguous=False,
            vulnerability_shares={1004: 1.0},
        )

        decision = memory.evaluate_post_defeat(
            stage_id=2001,
            snapshot=snapshot,
            attribution=attribution,
            current_team=current_team,
            user_box=box,
            is_final_phase=True,
        )

        assert decision.action == "InstantRetry"
        assert decision.team == current_team
        assert decision.replaced_card_ids == []
        assert "Tactical RNG" in decision.reason

    def test_consecutive_turn1_2_defeats_demotes_leader(
        self, tmp_path: Path, test_team_and_box: tuple[list[DokkanCard], list[DokkanCard]]
    ) -> None:
        current_team, box = test_team_and_box
        memory = EpisodicMemory(cache_path=tmp_path / "memory.json")
        solver = DokkanConstraintSolver()

        attribution = CulpritAttribution(
            direct_culprit_id=1004,
            direct_culprit_slot=3,
            is_friend_leader=False,
            is_ambiguous=False,
            vulnerability_shares={1004: 1.0},
        )

        # Defeat 1: Turn 1
        snap1 = TurnSnapshot(
            turn_number=1,
            boss_phase_index=1,
            boss_element=1,
            boss_element_name="TEQ",
            boss_hp_percent=90.0,
            player_hp_percent=0.0,
            active_rotation=current_team[:3],
        )
        d1 = memory.evaluate_post_defeat(100, snap1, attribution, current_team, box, solver)
        assert d1.action == "SurgicalReplace"
        assert memory.get_consecutive_early_defeats(100) == 1

        # Defeat 2: Turn 2
        snap2 = TurnSnapshot(
            turn_number=2,
            boss_phase_index=1,
            boss_element=1,
            boss_element_name="TEQ",
            boss_hp_percent=85.0,
            player_hp_percent=0.0,
            active_rotation=current_team[:3],
        )
        d2 = memory.evaluate_post_defeat(100, snap2, attribution, current_team, box, solver)
        assert d2.action == "SurgicalReplace"
        assert memory.get_consecutive_early_defeats(100) == 2

        # Defeat 3: Turn 1 (Triggers Leader Demotion)
        snap3 = TurnSnapshot(
            turn_number=1,
            boss_phase_index=1,
            boss_element=1,
            boss_element_name="TEQ",
            boss_hp_percent=95.0,
            player_hp_percent=0.0,
            active_rotation=current_team[:3],
        )
        d3 = memory.evaluate_post_defeat(100, snap3, attribution, current_team, box, solver)
        assert d3.action == "DemoteLeader"
        assert d3.demoted_leader_id == 1001
        assert d3.new_leader_id == 2001
        assert d3.team[0].id == 2001
        assert memory.get_consecutive_early_defeats(100) == 0

    def test_consecutive_early_defeat_resets_on_turn3(
        self, tmp_path: Path, test_team_and_box: tuple[list[DokkanCard], list[DokkanCard]]
    ) -> None:
        current_team, box = test_team_and_box
        memory = EpisodicMemory(cache_path=tmp_path / "memory.json")
        solver = DokkanConstraintSolver()

        attribution = CulpritAttribution(
            direct_culprit_id=1004,
            direct_culprit_slot=3,
            is_friend_leader=False,
            is_ambiguous=False,
            vulnerability_shares={1004: 1.0},
        )

        snap1 = TurnSnapshot(
            turn_number=1,
            boss_phase_index=1,
            boss_element=1,
            boss_element_name="TEQ",
            boss_hp_percent=90.0,
            player_hp_percent=0.0,
            active_rotation=current_team[:3],
        )
        memory.evaluate_post_defeat(200, snap1, attribution, current_team, box, solver)
        snap2 = TurnSnapshot(
            turn_number=2,
            boss_phase_index=1,
            boss_element=1,
            boss_element_name="TEQ",
            boss_hp_percent=85.0,
            player_hp_percent=0.0,
            active_rotation=current_team[:3],
        )
        memory.evaluate_post_defeat(200, snap2, attribution, current_team, box, solver)
        assert memory.get_consecutive_early_defeats(200) == 2

        # Defeat on Turn 4 (survived early game) -> streak resets to 0
        snap3 = TurnSnapshot(
            turn_number=4,
            boss_phase_index=2,
            boss_element=1,
            boss_element_name="TEQ",
            boss_hp_percent=60.0,
            player_hp_percent=0.0,
            active_rotation=current_team[:3],
        )
        d3 = memory.evaluate_post_defeat(200, snap3, attribution, current_team, box, solver)
        assert d3.action != "DemoteLeader"
        assert memory.get_consecutive_early_defeats(200) == 0

    def test_surgical_replacement_max_death_penalty(
        self, tmp_path: Path, test_team_and_box: tuple[list[DokkanCard], list[DokkanCard]]
    ) -> None:
        current_team, box = test_team_and_box
        memory = EpisodicMemory(cache_path=tmp_path / "memory.json")

        stage_data = memory.get_stage_data(300)
        stage_data["card_death_penalties"] = {"1004": 1.0, "1005": 2.5}
        memory.save()

        snapshot = TurnSnapshot(
            turn_number=4,
            boss_phase_index=2,
            boss_element=3,
            boss_element_name="STR",
            boss_hp_percent=55.0,
            player_hp_percent=0.0,
            active_rotation=[current_team[3], current_team[4], current_team[5]],
        )
        attribution = CulpritAttribution(
            direct_culprit_id=None,
            is_friend_leader=False,
            is_ambiguous=True,
            vulnerability_shares={1004: 0.33, 1005: 0.33, 1006: 0.33},
        )

        decision = memory.evaluate_post_defeat(
            300, snapshot, attribution, current_team, box, is_final_phase=False
        )

        assert decision.action == "SurgicalReplace"
        assert 1005 in decision.replaced_card_ids
        assert 1004 not in decision.replaced_card_ids

    def test_orphan_partner_link_check_substitute(
        self, tmp_path: Path, test_team_and_box: tuple[list[DokkanCard], list[DokkanCard]]
    ) -> None:
        current_team, _ = test_team_and_box
        memory = EpisodicMemory(cache_path=tmp_path / "memory.json")

        c_culprit = current_team[1]
        p_partner = current_team[2]

        cand_low_link = make_card(
            3001,
            "Generic Tank (Low Synergy)",
            element=0,
            category_ids=[10],
            links=["Super Saiyan", "Shocking Speed", "Fierce Battle"],
            dr_pct=60,
        )
        cand_high_link = make_card(
            3002,
            "Gotenks SS3 (High Synergy Sub)",
            element=0,
            category_ids=[10],
            links=["Super Saiyan", "Kamehameha", "Fusion", "Prepared for Battle"],
            dr_pct=40,
        )

        custom_box = list(current_team) + [cand_low_link, cand_high_link]

        snapshot = TurnSnapshot(
            turn_number=4,
            boss_phase_index=2,
            boss_element=3,
            boss_element_name="STR",
            boss_hp_percent=60.0,
            player_hp_percent=0.0,
            active_rotation=[c_culprit, p_partner, current_team[3]],
        )
        attribution = CulpritAttribution(
            direct_culprit_id=c_culprit.id,
            direct_culprit_slot=1,
            is_friend_leader=False,
            is_ambiguous=False,
            vulnerability_shares={c_culprit.id: 1.0},
        )

        decision = memory.evaluate_post_defeat(
            400, snapshot, attribution, current_team, custom_box, is_final_phase=False
        )

        assert decision.action == "SurgicalReplace"
        assert decision.replaced_card_ids == [c_culprit.id]
        assert decision.new_card_ids == [cand_high_link.id]
        assert cand_high_link.id in [c.id for c in decision.team]
        assert p_partner.id in [c.id for c in decision.team]

    def test_orphan_partner_pair_swap_fallback(
        self, tmp_path: Path, test_team_and_box: tuple[list[DokkanCard], list[DokkanCard]]
    ) -> None:
        current_team, _ = test_team_and_box
        memory = EpisodicMemory(cache_path=tmp_path / "memory.json")

        c_culprit = current_team[1]
        p_partner = current_team[2]

        cand_isolated_1 = make_card(
            4001,
            "Solo Sub 1",
            element=0,
            category_ids=[10],
            links=["Super Saiyan", "Shocking Speed"],
        )
        cand_isolated_2 = make_card(
            4002,
            "Solo Sub 2",
            element=3,
            category_ids=[10],
            links=["Super Saiyan", "Over in a Flash"],
        )

        pair_u1 = make_card(
            5001,
            "LR SS4 Goku",
            element=0,
            category_ids=[10],
            links=["Super Saiyan", "GT", "Prepared for Battle", "Fierce Battle"],
            slot1_viable=True,
        )
        pair_u2 = make_card(
            5002,
            "LR SS4 Vegeta",
            element=3,
            category_ids=[10],
            links=["Super Saiyan", "GT", "Prepared for Battle", "Fierce Battle"],
        )

        custom_box = list(current_team) + [cand_isolated_1, cand_isolated_2, pair_u1, pair_u2]

        snapshot = TurnSnapshot(
            turn_number=4,
            boss_phase_index=2,
            boss_element=3,
            boss_element_name="STR",
            boss_hp_percent=60.0,
            player_hp_percent=0.0,
            active_rotation=[c_culprit, p_partner, current_team[3]],
        )
        attribution = CulpritAttribution(
            direct_culprit_id=c_culprit.id,
            direct_culprit_slot=1,
            is_friend_leader=False,
            is_ambiguous=False,
            vulnerability_shares={c_culprit.id: 1.0},
        )

        decision = memory.evaluate_post_defeat(
            500, snapshot, attribution, current_team, custom_box, is_final_phase=False
        )

        assert decision.action == "SurgicalReplace"
        assert set(decision.replaced_card_ids) == {c_culprit.id, p_partner.id}
        assert set(decision.new_card_ids) == {pair_u1.id, pair_u2.id}
        team_ids = [c.id for c in decision.team]
        assert pair_u1.id in team_ids
        assert pair_u2.id in team_ids
        assert c_culprit.id not in team_ids
        assert p_partner.id not in team_ids
        assert len(decision.team) == 6

    def test_ai_memory_json_serialization(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "ai_memory.json"
        mem1 = EpisodicMemory(cache_path=cache_file)

        snap = TurnSnapshot(
            turn_number=5,
            boss_phase_index=4,
            boss_element=0,
            boss_element_name="AGL",
            boss_hp_percent=14.2,
            player_hp_percent=0.0,
            active_rotation=[make_card(1, "A"), make_card(2, "B"), make_card(3, "C")],
        )
        attr = CulpritAttribution(
            direct_culprit_id=1004,
            direct_culprit_slot=2,
            is_friend_leader=False,
            is_ambiguous=False,
            vulnerability_shares={1004: 1.0},
        )
        dec = EpisodicMemory().evaluate_post_defeat(
            1001,
            snap,
            attr,
            [make_card(i, f"C{i}") for i in range(1, 7)],
            [make_card(i, f"C{i}") for i in range(1, 7)],
            is_final_phase=True,
        )

        mem1.record_defeat(1001, snap, attr, dec)
        stage_data = mem1.get_stage_data(1001)
        stage_data["card_death_penalties"] = {"1004": 2.0, "1003": 0.66}
        stage_data["current_leader_id"] = 1012901
        mem1.save()

        mem2 = EpisodicMemory(cache_path=cache_file)
        s_data = mem2.get_stage_data(1001)
        assert s_data["stage_id"] == 1001
        assert s_data["current_leader_id"] == 1012901
        assert mem2.get_death_penalties(1001) == {1004: 2.0, 1003: 0.66}
        assert len(s_data["history"]) == 1
        assert s_data["history"][0]["turn"] == 5
        assert s_data["history"][0]["decision"] == "InstantRetry"
        assert s_data["history"][0]["boss_hp_percent"] == 14.2

    def test_failure_report_generation(self) -> None:
        snap = TurnSnapshot(
            turn_number=4,
            boss_phase_index=2,
            boss_element=3,
            boss_element_name="STR",
            boss_hp_percent=45.0,
            player_hp_percent=0.0,
            active_rotation=[make_card(1, "A"), make_card(2, "B"), make_card(3, "C")],
        )
        attr = CulpritAttribution(
            direct_culprit_id=2,
            direct_culprit_slot=2,
            is_friend_leader=False,
            is_ambiguous=False,
            vulnerability_shares={2: 1.0},
        )
        dec = EpisodicMemory().evaluate_post_defeat(
            10,
            snap,
            attr,
            [make_card(i, f"C{i}") for i in range(1, 7)],
            [make_card(i, f"C{i}") for i in range(1, 7)],
            is_final_phase=False,
        )

        report = create_failure_report(snap, attr, dec)
        assert report.defeat_turn == 4
        assert report.phase_index == 2
        assert report.boss_element == 3
        assert report.culprit_card_id == 2
        assert report.classification == "Card Vulnerability"
        assert "Surgically replaced" in report.reason


# ==============================================================================
# 4. EndgameRunner Lifecycle & Execution
# ==============================================================================


@pytest.fixture
def test_box_and_stage(tmp_path: Path):
    """Fixture providing user box cards, a 3-phase challenge stage, and file paths."""
    box_path = tmp_path / "user_box.json"
    memory_path = tmp_path / "ai_memory.json"

    lead_spec = LeaderSkillSpec(
        base_boost_pct=170,
        extra_boost_pct=30,
        main_category_ids=[10],
        extra_category_ids=[20],
    )
    c1_lead = make_card(
        101, "LR AGL Goku Lead", element=0, leader_spec=lead_spec, slot1_viable=True, dr_pct=50
    )
    c2_tank = make_card(
        102, "LR TEQ Vegeta Tank", element=1, slot1_viable=True, has_guard=True, dr_pct=40
    )
    c3_dps = make_card(103, "UR PHY Trunks DPS", element=4, slot1_viable=False, dr_pct=20)
    c4_sup = make_card(104, "UR INT Gohan Support", element=2, slot1_viable=False, dr_pct=30)
    c5_weak = make_card(105, "UR STR Yamcha Floater", element=3, slot1_viable=False, dr_pct=0)
    c6_fill = make_card(106, "UR AGL Krillin", element=0, slot1_viable=False, dr_pct=20)

    c7_sub = make_card(
        107, "LR STR Piccolo Tank", element=3, slot1_viable=True, has_guard=True, dr_pct=60
    )
    c8_sub2 = make_card(108, "UR TEQ Tien", element=1, slot1_viable=False, dr_pct=40)

    cards = [c1_lead, c2_tank, c3_dps, c4_sup, c5_weak, c6_fill, c7_sub, c8_sub2]

    box_data = {"cards": [c.to_dict() for c in cards]}
    box_path.write_text(json.dumps(box_data, indent=2), encoding="utf-8")

    stage = BossStage(
        stage_id=9901,
        event_id=99,
        stage_name="Stage 1: Test Challenge Boss",
        event_name="Ultimate Red Zone: Test Edition",
        difficulty=1,
        phases=[
            BossPhase(
                phase_index=1,
                element=24,
                element_name="Extreme PHY",
                hp=15000000,
                atk=300000,
                bosses=[BossEnemy(card_id=901, name="Phase 1 Boss", element=24)],
            ),
            BossPhase(
                phase_index=2,
                element=22,
                element_name="Extreme INT",
                hp=25000000,
                atk=500000,
                bosses=[BossEnemy(card_id=902, name="Phase 2 Boss", element=22)],
            ),
            BossPhase(
                phase_index=3,
                element=21,
                element_name="Extreme TEQ",
                hp=45000000,
                atk=800000,
                cancels_dodge=True,
                bosses=[BossEnemy(card_id=903, name="Phase 3 Final Boss", element=21)],
            ),
        ],
    )

    return cards, stage, box_path, memory_path


class TestEndgameRunnerFullLifecycle:
    """Simulates the 3-Run End-to-End Orchestrator Loop."""

    def test_endgame_runner_3_run_lifecycle(self, test_box_and_stage) -> None:
        _cards, stage, box_path, memory_path = test_box_and_stage

        formation_calls: list[list[int]] = []
        formation_slots: list[int | None] = []

        def mock_formation(team_cards, target_slot=None, **_kwargs):
            formation_calls.append([c.id for c in team_cards])
            formation_slots.append(target_slot)
            return True

        recorded_culprit_id: list[int] = []

        def battle_simulator(
            attempt_num: int, current_team: list[DokkanCard], _target_stage: BossStage
        ):
            if attempt_num == 1:
                culprit_card = current_team[4]
                recorded_culprit_id.append(culprit_card.id)
                snap = TurnSnapshot(
                    turn_number=3,
                    boss_phase_index=2,
                    boss_element=22,
                    boss_element_name="Extreme INT",
                    boss_hp_percent=60.0,
                    player_hp_percent=15.0,
                    active_rotation=[current_team[0], current_team[1], culprit_card],
                )
                frames = [
                    CombatFrame(
                        frame_id=1,
                        active_slot=1,
                        target_card_id=current_team[0].id,
                        incoming_damage=20000,
                        player_hp_after=80.0,
                    ),
                    CombatFrame(
                        frame_id=2,
                        active_slot=2,
                        target_card_id=current_team[1].id,
                        incoming_damage=15000,
                        player_hp_after=65.0,
                    ),
                    CombatFrame(
                        frame_id=3,
                        active_slot=3,
                        target_card_id=culprit_card.id,
                        incoming_damage=500000,
                        player_hp_after=0.0,
                        is_lethal=True,
                    ),
                ]
                return ("defeat", snap, frames)

            elif attempt_num == 2:
                snap = TurnSnapshot(
                    turn_number=6,
                    boss_phase_index=3,
                    boss_element=21,
                    boss_element_name="Extreme TEQ",
                    boss_hp_percent=12.0,
                    player_hp_percent=5.0,
                    active_rotation=[current_team[0], current_team[1], current_team[2]],
                )
                frames = [
                    CombatFrame(
                        frame_id=1,
                        active_slot=1,
                        target_card_id=current_team[0].id,
                        incoming_damage=500000,
                        player_hp_after=0.0,
                        is_lethal=True,
                    )
                ]
                return ("defeat", snap, frames)

            elif attempt_num == 3:
                snap = TurnSnapshot(
                    turn_number=7,
                    boss_phase_index=3,
                    boss_element=21,
                    boss_element_name="Extreme TEQ",
                    boss_hp_percent=0.0,
                    player_hp_percent=45.0,
                    active_rotation=[current_team[0], current_team[1], current_team[2]],
                )
                return ("victory", snap, [])

            raise AssertionError(f"Unexpected attempt number: {attempt_num}")

        memory = EpisodicMemory(cache_path=memory_path)
        tracker = CombatTelemetryTracker(episodic_memory=memory)

        runner = EndgameRunner(
            user_box_path=box_path,
            memory_path=memory_path,
            memory=memory,
            telemetry_tracker=tracker,
            boss_stage=stage,
            max_attempts=10,
            dry_run=True,
            battle_simulator=battle_simulator,
        )

        with patch(
            "dokkan_eza_link_farmer.ai.endgame.runner.apply_team_in_game",
            side_effect=mock_formation,
        ):
            result: EndgameResult = runner.run(stage)

        assert result.success is True
        assert result.attempts == 3
        assert len(result.winning_team) == 6

        assert len(result.decisions) == 2
        decision_run1 = result.decisions[0]
        assert decision_run1.action == "SurgicalReplace"
        assert recorded_culprit_id[0] in decision_run1.replaced_card_ids
        assert len(decision_run1.new_card_ids) == 1

        decision_run2 = result.decisions[1]
        assert decision_run2.action == "InstantRetry"
        assert decision_run2.replaced_card_ids == []
        assert "Final Phase Boss HP < 20%" in decision_run2.reason

        assert len(formation_calls) == 2
        assert formation_slots == [None, 5]

        assert memory_path.exists()
        saved_memory = json.loads(memory_path.read_text(encoding="utf-8"))
        stage_data = saved_memory["stages"][str(stage.stage_id)]
        assert stage_data["cleared"] is True
        assert stage_data["winning_team"] == [c.id for c in result.winning_team]
        assert stage_data["attempts"] == 3
        assert stage_data["victories"] == 1
        assert len(stage_data["history"]) == 3


class TestEndgameRunnerEdgeCases:
    """Verifies boundary conditions, max attempts limit, and error handling."""

    def test_max_attempts_limit_reached(self, test_box_and_stage) -> None:
        cards, stage, box_path, memory_path = test_box_and_stage

        def always_die(_attempt_num, current_team, _target_stage):
            snap = TurnSnapshot(
                turn_number=1,
                boss_phase_index=1,
                boss_element=24,
                boss_element_name="Extreme PHY",
                boss_hp_percent=95.0,
                player_hp_percent=0.0,
                active_rotation=[current_team[0], current_team[1], current_team[2]],
            )
            return ("defeat", snap, [])

        runner = EndgameRunner(
            user_box_path=box_path,
            memory_path=memory_path,
            boss_stage=stage,
            max_attempts=3,
            dry_run=True,
            battle_simulator=always_die,
        )

        with patch(
            "dokkan_eza_link_farmer.ai.endgame.runner.apply_team_in_game", return_value=True
        ):
            res = runner.run(stage)

        assert res.success is False
        assert res.attempts == 3
        assert runner.current_state == EndgameRunnerState.MAX_ATTEMPTS_REACHED
        assert "Failed to clear stage" in res.message

    def test_runner_stop_signal(self, test_box_and_stage) -> None:
        _cards, stage, box_path, memory_path = test_box_and_stage
        runner = EndgameRunner(
            user_box_path=box_path,
            memory_path=memory_path,
            boss_stage=stage,
            max_attempts=5,
            dry_run=True,
        )
        runner.stop()
        assert runner.is_stopped() is True
        res = runner.run(stage)
        assert res.success is False
        assert res.attempts == 0

    def test_endgame_runner_with_catalog_stage_broly(self, test_box_and_stage) -> None:
        _cards, _, box_path, memory_path = test_box_and_stage
        broly_stage = get_boss_stage("rz_broly")

        def instant_win_sim(_attempt_num, current_team, _target_stage):
            snap = TurnSnapshot(
                turn_number=4,
                boss_phase_index=4,
                boss_element=20,
                boss_element_name="Extreme AGL",
                boss_hp_percent=0.0,
                player_hp_percent=80.0,
                active_rotation=[current_team[0], current_team[1], current_team[2]],
            )
            return ("victory", snap, [])

        runner = EndgameRunner(
            user_box_path=box_path,
            memory_path=memory_path,
            boss_stage=broly_stage,
            max_attempts=3,
            dry_run=True,
            battle_simulator=instant_win_sim,
        )

        with patch(
            "dokkan_eza_link_farmer.ai.endgame.runner.apply_team_in_game", return_value=True
        ):
            res = runner.run(broly_stage)

        assert res.success is True
        assert res.attempts == 1
        assert len(res.winning_team) == 6
        assert res.stage is not None and res.stage.stage_id == 10101

    def test_endgame_runner_friend_leader_immunity(self, test_box_and_stage) -> None:
        _cards, stage, box_path, memory_path = test_box_and_stage

        def friend_death_then_win(attempt_num, current_team, _target_stage):
            if attempt_num == 1:
                snap = TurnSnapshot(
                    turn_number=3,
                    boss_phase_index=2,
                    boss_element=22,
                    boss_element_name="Extreme INT",
                    boss_hp_percent=70.0,
                    player_hp_percent=0.0,
                    active_rotation=[current_team[0], current_team[1], current_team[2]],
                )
                frames = [
                    CombatFrame(
                        frame_id=1,
                        active_slot=7,
                        target_card_id=999,
                        incoming_damage=600000,
                        player_hp_after=0.0,
                        is_lethal=True,
                    )
                ]
                return ("defeat", snap, frames)
            else:
                snap = TurnSnapshot(
                    turn_number=5,
                    boss_phase_index=3,
                    boss_element=21,
                    boss_element_name="Extreme TEQ",
                    boss_hp_percent=0.0,
                    player_hp_percent=100.0,
                    active_rotation=[current_team[0], current_team[1], current_team[2]],
                )
                return ("victory", snap, [])

        runner = EndgameRunner(
            user_box_path=box_path,
            memory_path=memory_path,
            boss_stage=stage,
            max_attempts=3,
            dry_run=True,
            battle_simulator=friend_death_then_win,
        )

        with patch(
            "dokkan_eza_link_farmer.ai.endgame.runner.apply_team_in_game", return_value=True
        ):
            res = runner.run(stage)

        assert res.success is True
        assert res.attempts == 2
        assert len(res.decisions) == 1
        assert res.decisions[0].action == "InstantRetry"
        assert "Friend Leader (Slot 7)" in res.decisions[0].reason

    def test_bot_engine_run_ai_endgame_sync(self, test_box_and_stage) -> None:
        cards, stage, _box_path, _memory_path = test_box_and_stage
        engine = BotEngine()

        with patch("dokkan_eza_link_farmer.ai.endgame.runner.EndgameRunner.run") as mock_runner_run:
            mock_runner_run.return_value = EndgameResult(
                success=True,
                attempts=1,
                winning_team=cards[:6],
                stage=stage,
            )
            res = engine.run_ai_endgame_sync(10101, dry_run=True, max_attempts=5)
            assert res.success is True
            assert res.attempts == 1
            assert mock_runner_run.called

    def test_bot_engine_start_ai_endgame_background(self, test_box_and_stage) -> None:
        cards, stage, _box_path, _memory_path = test_box_and_stage
        engine = BotEngine()

        with patch("dokkan_eza_link_farmer.ai.endgame.runner.EndgameRunner.run") as mock_runner_run:
            mock_runner_run.return_value = EndgameResult(
                success=True,
                attempts=1,
                winning_team=cards[:6],
                stage=stage,
            )
            started = engine.start_ai_endgame(10101, dry_run=True, max_attempts=2)
            assert started is True
            assert engine.current_task is not None
            engine.stop_task()
            assert engine.is_task_running() is False

    def test_cli_ai_run_argument_parsing(self) -> None:
        from dokkan_eza_link_farmer.__main__ import main

        with (
            patch("dokkan_eza_link_farmer.ui.cli.TerminalCLI.handle_ai_endgame_run") as mock_handle,
            patch("sys.argv", ["dokkan-farmer", "ai-run", "--stage", "10101", "--dry-run"]),
            patch(
                "dokkan_eza_link_farmer.core.system_tools.SingleInstanceMutex.acquire",
                return_value=True,
            ),
            patch("dokkan_eza_link_farmer.core.system_tools.SingleInstanceMutex.release"),
        ):
            main()
        mock_handle.assert_called_once_with("10101", dry_run=True, max_attempts=None)

    def test_cli_ai_run_interactive_selection_when_no_stage(self) -> None:
        from dokkan_eza_link_farmer.__main__ import main

        with (
            patch("dokkan_eza_link_farmer.ui.cli.TerminalCLI.handle_ai_endgame_run") as mock_handle,
            patch("sys.argv", ["dokkan-farmer", "ai-run", "--dry-run"]),
            patch(
                "dokkan_eza_link_farmer.core.system_tools.SingleInstanceMutex.acquire",
                return_value=True,
            ),
            patch("dokkan_eza_link_farmer.core.system_tools.SingleInstanceMutex.release"),
        ):
            main()
        mock_handle.assert_called_once_with(None, dry_run=True, max_attempts=None)

    def test_dokkandb_user_box_cache_path_priority(self, tmp_path: Path) -> None:
        from dokkan_eza_link_farmer.integrations.dokkandb_client import DokkanDBClient

        test_box = tmp_path / "user_box.json"
        test_payload = {"cards": [{"id": 1099991, "name": "Test Card"}]}
        test_box.write_text(json.dumps(test_payload), encoding="utf-8")

        db = DokkanDBClient(cache_dir=str(tmp_path))
        with patch(
            "dokkan_eza_link_farmer.integrations.dokkandb_client.DEFAULT_USER_BOX_PATH",
            str(test_box),
        ):
            box_ids = db.get_user_box_card_ids()
            assert 1099991 in box_ids

    def test_get_boss_stage_dokkandb_numeric_stage_id(self) -> None:
        mock_dokkandb = MagicMock()
        mock_dokkandb.get_stage_boss_info.return_value = {
            "event_id": 1737,
            "stage_id": 17370775,
            "event_name": "Ultimate Red Zone",
            "stage_name": "DAIMA Edition Stage 1",
            "difficulty": 5,
            "phases": [
                {
                    "phase": 1,
                    "bosses": [
                        {
                            "name": "Tamagami Number Three",
                            "element": 10,
                            "type_name": "Super AGL",
                            "card_id": 9130881,
                        }
                    ],
                }
            ],
        }

        stage = get_boss_stage(17370775, dokkandb=mock_dokkandb)
        assert stage.stage_id == 17370775
        assert stage.event_id == 1737
        assert stage.event_name == "Ultimate Red Zone"
        assert stage.stage_name == "DAIMA Edition Stage 1"
        assert len(stage.phases) == 1
        assert stage.phases[0].element_name == "Super AGL"
        mock_dokkandb.get_stage_boss_info.assert_called_once_with(1737, 17370775)


# ==============================================================================
# 5. Subsystem Isolation & Zero-Dependency In-Memory Verification
# ==============================================================================


class TestSubsystemIsolation:
    """Verifies that core bot startup and farming tasks are completely decoupled from endgame subsystem."""

    def test_core_bot_startup_zero_endgame_telemetry_imports(self) -> None:
        """Verifies through AST and runtime inspection that BotEngine does not eagerly import or allocate endgame telemetry."""
        source = inspect.getsource(bot_engine)
        tree = ast.parse(source)

        for stmt in tree.body:
            if isinstance(stmt, ast.Import):
                for alias in stmt.names:
                    assert "telemetry" not in alias.name
                    assert "endgame" not in alias.name
            elif isinstance(stmt, ast.ImportFrom):
                mod_name = stmt.module or ""
                assert "telemetry" not in mod_name
                assert "endgame" not in mod_name

        engine = BotEngine()
        assert not hasattr(engine, "telemetry_tracker")
        assert not hasattr(engine, "ring_buffer")
        assert not hasattr(engine, "episodic_memory")

    def test_farming_tasks_zero_endgame_imports(self) -> None:
        """Verifies through AST analysis that farming tasks have zero imports of telemetry or endgame."""
        for mod in (eza_farm, stage_farm, link_level_farm, box_scanner, challenge_task):
            source = inspect.getsource(mod)
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert "telemetry" not in alias.name
                        assert "endgame" not in alias.name
                elif isinstance(node, ast.ImportFrom):
                    mod_name = node.module or ""
                    assert "telemetry" not in mod_name
                    assert "endgame" not in mod_name

    def test_lazy_export_interface_on_ai_package(self) -> None:
        """Verifies that accessing endgame exports on dokkan_eza_link_farmer.ai works via __getattr__."""
        runner_cls = ai.EndgameRunner
        assert runner_cls is EndgameRunner

        ring_cls = ai.CombatRingBuffer
        assert ring_cls is CombatRingBuffer

        apply_fn = ai.apply_team_in_game
        assert callable(apply_fn)

        assert ai.endgame is not None

        ai_dir = dir(ai)
        for sym in ai._LAZY_ENDGAME_EXPORTS:
            assert sym in ai_dir, f"Expected {sym} to be present in dir(ai)"
            val = getattr(ai, sym)
            assert val is not None, f"Expected {sym} to resolve to non-None value"

        with pytest.raises(AttributeError):
            _ = ai.NonExistentAIComponent

    def test_concurrent_lazy_export_access(self) -> None:
        """Verifies thread-safe concurrent access to lazy exports on dokkan_eza_link_farmer.ai."""
        import concurrent.futures

        def load_symbol(sym_name: str):
            return getattr(ai, sym_name)

        symbols = [
            "EndgameRunner",
            "CombatRingBuffer",
            "endgame",
            "apply_team_in_game",
        ]
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(load_symbol, s) for s in symbols * 5]
            for f in concurrent.futures.as_completed(futures):
                res = f.result()
                assert res is not None

    def test_canonical_endgame_modules(self) -> None:
        """Verifies that endgame package and its canonical modules remain operational."""
        import dokkan_eza_link_farmer.ai.endgame as endgame
        from dokkan_eza_link_farmer.ai.endgame.runner import EndgameRunner as CanonicalRunner
        from dokkan_eza_link_farmer.ai.endgame.telemetry import (
            CombatRingBuffer as CanonicalRingBuffer,
        )

        assert CanonicalRunner is EndgameRunner
        assert CanonicalRingBuffer is CombatRingBuffer
        assert endgame.runner.EndgameRunner is EndgameRunner
        assert endgame.telemetry.CombatRingBuffer is CombatRingBuffer
        assert "runner" in endgame.__all__
        assert "telemetry" in endgame.__all__

    def test_start_ai_endgame_run_contract_and_alias(self) -> None:
        """Verifies start_ai_endgame_run public contract and on-demand initialization."""
        engine = BotEngine()
        assert hasattr(engine, "start_ai_endgame_run")
        assert engine.start_ai_endgame_run == engine.start_ai_endgame

        fake_stage = BossStage(
            stage_id=10101,
            event_id=101,
            event_name="Red Zone",
            stage_name="Stage 1",
            phases=[
                BossPhase(
                    phase_index=1,
                    element=1,
                    hp=1000000,
                )
            ],
        )

        dummy_card = make_card(101, "Goku", element=1)

        with patch("dokkan_eza_link_farmer.ai.endgame.runner.EndgameRunner.run") as mock_run:
            mock_run.return_value = EndgameResult(
                success=True,
                attempts=1,
                winning_team=[dummy_card] * 6,
                stage=fake_stage,
            )
            started = engine.start_ai_endgame_run(stage_identifier=fake_stage, dry_run=True)
            assert started is True
            assert engine.current_task is not None
            engine.stop_task()


# ==============================================================================
# 6. Discord Bot Optional Integration Isolation
# ==============================================================================


class TestDiscordBotIsolation:
    """Verifies that Discord Bot is treated as a secondary optional integration."""

    def test_bot_engine_init_does_not_attach_discord_listener(self) -> None:
        """Engine startup should never instantiate DiscordBotClient or attach discord listeners."""
        engine = BotEngine()
        assert len(engine.log_callbacks) == 0
        assert len(engine.run_callbacks) == 0

    def test_discord_callbacks_swallow_exceptions_safely(self) -> None:
        """No exception from discord background notification callbacks can crash automation."""
        pytest.importorskip("discord")
        from dokkan_eza_link_farmer.integrations.discord_bot import DiscordBotClient

        mock_engine = MagicMock()
        mock_engine.config = {"discord": {"allowed_user_ids": []}}

        bot = DiscordBotClient(mock_engine)
        bot._main_channel = MagicMock()
        bot._loop = MagicMock()
        bot._loop.is_running.side_effect = RuntimeError("Event loop is closed")

        bot._on_bot_log("Test Victory Completed!")
        bot._on_bot_run(5, 10)


# ==============================================================================
# 7. Boss Catalog Loading
# ==============================================================================


class TestBossCatalogLoading:
    """Verifies boss catalog JSON and helper functions."""

    def test_load_all_catalog_stages(self) -> None:
        stages = list_boss_stages()
        assert len(stages) >= 8

        stage_ids = {s.stage_id for s in stages}
        assert 10101 in stage_ids  # Broly
        assert 10102 in stage_ids  # Cell Max
        assert 10103 in stage_ids  # Fusion Zamasu
        assert 10104 in stage_ids  # Kid Buu
        assert 10105 in stage_ids  # Omega Shenron

        assert 20101 in stage_ids  # Beast Gohan
        assert 20102 in stage_ids  # Super Gogeta
        assert 20103 in stage_ids  # Evo Blue & UI Goku

    def test_get_boss_stage_by_slug_and_id(self) -> None:
        broly = get_boss_stage("rz_broly")
        assert broly.stage_id == 10101
        assert len(broly.phases) == 4
        assert broly.phases[-1].cancels_dodge is True
        assert broly.phases[2].has_aoe is True

        beast = get_boss_stage("smb_beast_gohan")
        assert beast.stage_id == 20101
        assert beast.phases[-1].cancels_dodge is True
        assert beast.phases[-1].locks_slots is True

    def test_get_boss_stage_not_found(self) -> None:
        with pytest.raises(KeyError) as exc_info:
            get_boss_stage("non_existent_stage_xyz")
        assert "not found in catalog" in str(exc_info.value)
