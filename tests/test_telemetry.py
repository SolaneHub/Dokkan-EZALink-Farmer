"""Comprehensive unit tests for Combat Telemetry, Credit Assignment, and Episodic Memory.

Covers the 12 core test cases specified in Explorer 3 Handoff Section 2.6:
1. test_turn_snapshot_recording
2. test_ring_buffer_fifo_capacity
3. test_direct_culprit_attribution
4. test_vulnerability_sharing_ambiguous
5. test_friend_leader_immunity_slot7
6. test_decision_tree_instant_retry_low_hp
7. test_consecutive_turn1_2_defeats_demotes_leader
8. test_consecutive_early_defeat_resets_on_turn3
9. test_surgical_replacement_max_death_penalty
10. test_orphan_partner_link_check_substitute
11. test_orphan_partner_pair_swap_fallback
12. test_ai_memory_json_serialization
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dokkan_eza_link_farmer.ai.endgame.telemetry import (
    CombatFrame,
    CombatRingBuffer,
    CulpritAttribution,
    EpisodicMemory,
    TurnSnapshot,
    attribute_culprit,
    create_failure_report,
)
from dokkan_eza_link_farmer.ai.models import (
    BossPhase,
    CardForm,
    DokkanCard,
    LeaderSkillSpec,
    PassiveTags,
    SATags,
)
from dokkan_eza_link_farmer.ai.solver import (
    DokkanConstraintSolver,
)


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
) -> DokkanCard:
    """Helper to synthesize fully valid DokkanCard fixtures for telemetry testing."""
    links_list = links or ["Super Saiyan", "Kamehameha", "Prepared for Battle"]
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
    )


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

    def test_ring_buffer_invalid_capacity(self) -> None:
        with pytest.raises(ValueError, match="capacity must be > 0"):
            CombatRingBuffer(capacity=0)


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
        # Enemy AoE attack hits without isolating a single slot
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
        # Boss is STR (3): PHY (4) has severe disadvantage if unshielded, while AGL (0) beats STR
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
        # Fragile PHY unit receives 0.60 share, others 0.20 each
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
        # 0 penalty assigned to player deck
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
        # Verify 0 death penalties were recorded for player cards
        penalties = memory.get_death_penalties(101)
        assert len(penalties) == 0


class TestEpisodicMemoryDecisionTree:
    """Tests the 3-tier post-defeat decision tree and persistence."""

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

        # Additional box cards
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
            boss_hp_percent=12.0,  # < 20%
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

        # Defeats on Turn 1 and Turn 2 -> early streak = 2
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

        # Defeat on Turn 4 (survived early game) -> streak resets to 0!
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

        # Seed death penalties: Card 1004 has 1.0, Card 1005 has 2.5
        stage_data = memory.get_stage_data(300)
        stage_data["card_death_penalties"] = {"1004": 1.0, "1005": 2.5}
        memory.save()

        # Turn 4 defeat with ambiguous blame across 1004, 1005, 1006
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
        # Unit 1005 has maximum death penalty (2.5 + 0.33 = 2.83) -> targeted for replacement
        assert 1005 in decision.replaced_card_ids
        assert 1004 not in decision.replaced_card_ids

    def test_orphan_partner_link_check_substitute(
        self, tmp_path: Path, test_team_and_box: tuple[list[DokkanCard], list[DokkanCard]]
    ) -> None:
        current_team, _ = test_team_and_box
        memory = EpisodicMemory(cache_path=tmp_path / "memory.json")

        # Main rotation: Slot 1 (Culprit C: 1002) & Slot 2 (Partner P: 1003)
        # Partner P has links: ["Super Saiyan", "Kamehameha", "Fusion", "Prepared for Battle"]
        c_culprit = current_team[1]
        p_partner = current_team[2]

        # Candidate 1: High defense, but shares only 1 link with P ("Super Saiyan") -> < 3 links!
        cand_low_link = make_card(
            3001,
            "Generic Tank (Low Synergy)",
            element=0,
            category_ids=[10],
            links=["Super Saiyan", "Shocking Speed", "Fierce Battle"],
            dr_pct=60,
        )

        # Candidate 2: Shares 4 links with P ("Super Saiyan", "Kamehameha", "Fusion", "Prepared for Battle")
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
        # Replaced culprit C, preserved partner P
        assert decision.replaced_card_ids == [c_culprit.id]
        # Forced candidate sharing >= 4 links with partner
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

        # No single candidate in box has >= 4 links with P (they only share <= 2 links)
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

        # But box HAS a pre-linked synergistic rotation pair (U1, U2) that share 4 links with each other!
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
        # Pair swap: replaces BOTH culprit and partner together!
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

        # Load fresh instance from file
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
