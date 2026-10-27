"""Tests for Dokkan tactical dictionary integration into Qwen team generator.

Validates:
1. Automatic mapping of passive tags: unconditional guard, intro/turn-limited guard,
   and slot 2/3 restricted guard.
2. Intro shield timeline tracking and downgrade mechanics for long fights.
3. Qwen advisor payload enrichment with slot 1 penalties and guard ontology metadata.
4. Unit test validation ensuring LR Gogeta (1030481) and Supreme Kai (1015201) are
   strictly barred from Slot 1 assignment.
"""

from __future__ import annotations

import pytest

from dokkan_eza_link_farmer.ai.card_models import DokkanCard, LeaderSkillSpec
from dokkan_eza_link_farmer.ai.llm_advisor import (
    build_advisor_messages,
    build_advisor_payload,
)
from dokkan_eza_link_farmer.ai.models import BossPhase, BossStage
from dokkan_eza_link_farmer.ai.solver import DokkanConstraintSolver
from dokkan_eza_link_farmer.ai.synergy import (
    calculate_slot1_def_priority,
    calculate_slot2_partner_weight,
    optimize_rotations_for_team,
)


class TestTacticalDictionaryIntegration:
    """Verifies that tactical dictionary rules are accurately enforced across solver, synergy, and LLM advisor."""

    @pytest.fixture
    def hard_boss_stage(self) -> BossStage:
        """High-difficulty Red Zone stage with lethal pre-attack Super Attacks (>= 2.5M)."""
        return BossStage(
            stage_id=9999,
            event_id=99,
            event_name="Supreme Magnificent Battle",
            stage_name="Final Battle",
            phases=[
                BossPhase(
                    phase_index=1, element=0, element_name="AGL", estimated_sa_damage=1_500_000
                ),
                BossPhase(
                    phase_index=2, element=1, element_name="TEQ", estimated_sa_damage=2_000_000
                ),
                BossPhase(
                    phase_index=3, element=3, element_name="STR", estimated_sa_damage=3_200_000
                ),
            ],
        )

    @pytest.fixture
    def lr_gogeta_card(self) -> DokkanCard:
        """LR Super Saiyan Vegeta (Angel) & Super Saiyan Goku (Angel) (ID: 1030481)."""
        return DokkanCard(
            id=1030481,
            name="Super Saiyan Vegeta (Angel) + Super Saiyan Goku (Angel)",
            subname="Unprecedented Miracle",
            element=10,  # Super AGL
            category_ids=[1, 2, 3],
            passive_skill=(
                "*Basic effect(s)*\n"
                "- Ki +5 and ATK & DEF 200%\n"
                "*For 3 turns from the character's entry turn*\n"
                "- DEF 300%\n"
                "- Guards all attacks\n"
                "*When attacking*\n"
                "- ATK 200%\n"
                "- DEF 100%\n"
                "*As the 2nd or 3rd attacker in a turn*\n"
                "- Guards all attacks\n"
                "- Launches an additional attack that has a great chance of becoming a Super Attack\n"
            ),
        )

    @pytest.fixture
    def supreme_kai_card(self) -> DokkanCard:
        """Supreme Kai (ID: 1015201) with 'as the 1st attacker in a turn' guard."""
        return DokkanCard(
            id=1015201,
            name="Supreme Kai",
            subname="Watchers of the Cosmos",
            element=12,  # Super TEQ
            category_ids=[1, 4],
            passive_skill=(
                "Super Class allies' Ki +1 and ATK & DEF 20%; "
                "Guards all attacks as the 1st attacker in a turn; "
                "recovers 15% HP at the end of turn after receiving an attack"
            ),
        )

    @pytest.fixture
    def beast_gohan_card(self) -> DokkanCard:
        """True Slot 1 God Tank with unconditional permanent guard and high DR."""
        return DokkanCard(
            id=1028301,
            name="Ultimate Gohan",
            element=13,  # Super STR
            category_ids=[1, 2],
            passive_skill=(
                "*Basic effect(s)*\n"
                "- Ki +3 and ATK & DEF 250%\n"
                "- Guards all attacks\n"
                "- Reduces damage received by 50%\n"
            ),
        )

    def test_passive_tag_mapping_guard_types(
        self, lr_gogeta_card: DokkanCard, supreme_kai_card: DokkanCard, beast_gohan_card: DokkanCard
    ) -> None:
        """Step 1: Check passive tag identification for unconditional, intro, and slot 2/3 lock."""
        # Beast Gohan: Unconditional Guard
        assert beast_gohan_card.has_guard is True
        assert beast_gohan_card.is_guard_unconditional is True
        assert beast_gohan_card.is_guard_permanent is True
        assert beast_gohan_card.has_slot_2_3_guard is False
        assert beast_gohan_card.has_slot_1_only_guard is False

        # LR Gogeta: Intro Guard (3 turns) + Slot 2/3 locked guard
        assert lr_gogeta_card.has_guard is True
        assert lr_gogeta_card.has_slot_2_3_guard is True
        assert lr_gogeta_card.is_guard_unconditional is False
        assert lr_gogeta_card.guard_turns_limit == 3
        # Once intro expires or when evaluated outside entry, guard is conditional on slot 2/3
        assert lr_gogeta_card.is_guard_permanent is False

        # Supreme Kai: Slot 1 only guard
        assert supreme_kai_card.has_guard is True
        assert supreme_kai_card.has_slot_1_only_guard is True
        assert supreme_kai_card.has_slot_2_3_guard is False
        assert supreme_kai_card.is_guard_unconditional is False

    def test_slot1_disqualification_for_lr_gogeta(
        self, lr_gogeta_card: DokkanCard, hard_boss_stage: BossStage
    ) -> None:
        """Step 2 & 4: LR Gogeta (1030481) must NEVER be viable as Slot 1 tank."""
        # Generic check without boss
        assert DokkanConstraintSolver.is_slot1_viable(lr_gogeta_card, boss_stage=None) is False

        # Check against high-power endgame stage
        assert (
            DokkanConstraintSolver.is_slot1_viable(lr_gogeta_card, boss_stage=hard_boss_stage)
            is False
        )

        # Solver gimmick evaluation should register slot 2/3 guard warning
        solver = DokkanConstraintSolver()
        leader = DokkanCard(
            id=1,
            name="Leader",
            element=10,
            category_ids=[1, 2, 3],
            leader_spec=LeaderSkillSpec(main_category_ids=[1, 2, 3], base_boost_pct=170),
        )
        ev = solver.evaluate_card(lr_gogeta_card, leader, boss_stage=hard_boss_stage)
        assert ev.base_slot1_viable is False
        assert any("Slot 2/3 Restricted Guard" in p for p in ev.penalty_points)

    def test_slot1_disqualification_for_supreme_kai(
        self, supreme_kai_card: DokkanCard, hard_boss_stage: BossStage
    ) -> None:
        """Step 4: Supreme Kai (1015201) must be disqualified from Slot 1 against hard bosses."""
        # Supreme Kai has naked slot-1 only guard (0% DR, low base DEF)
        assert (
            DokkanConstraintSolver.is_slot1_viable(supreme_kai_card, boss_stage=hard_boss_stage)
            is False
        )

    def test_rotation_optimizer_assigns_gogeta_to_slot_2_not_slot_1(
        self, lr_gogeta_card: DokkanCard, beast_gohan_card: DokkanCard, hard_boss_stage: BossStage
    ) -> None:
        """Step 2: Ensure rotation optimizer places Gogeta in Slot 2 paired with a true Slot 1 tank."""
        slot1_tank_2 = DokkanCard(
            id=102,
            name="Tank Two",
            element=10,
            category_ids=[1, 2],
            passive_skill="Guards all attacks; reduces damage received by 60%",
        )
        partner_2 = DokkanCard(
            id=103,
            name="Partner Two",
            element=10,
            category_ids=[1, 2],
            passive_skill="Ki +3 and ATK & DEF 200%; launches additional Super Attack",
        )
        floater_1 = DokkanCard(
            id=104,
            name="Support Floater 1",
            element=10,
            category_ids=[1, 2],
            passive_skill="All allies' Ki +3 and DEF +50%; high chance of evading",
        )
        floater_2 = DokkanCard(
            id=105,
            name="Support Floater 2",
            element=10,
            category_ids=[1, 2],
            passive_skill="All allies' Ki +3 and DEF +40%",
        )

        team = [beast_gohan_card, lr_gogeta_card, slot1_tank_2, partner_2, floater_1, floater_2]
        rot_a, rot_b, floaters = optimize_rotations_for_team(team, boss_stage=hard_boss_stage)

        # LR Gogeta must not be in Slot 1 of either rotation pair
        assert rot_a.slot1.id != 1030481
        assert rot_b.slot1.id != 1030481

        # Slot 2 partner priority for Gogeta should be high
        weight_s2 = calculate_slot2_partner_weight(lr_gogeta_card, boss_stage=hard_boss_stage)
        assert weight_s2 >= 18.0

        # Slot 1 defense priority should be heavily penalized for Gogeta
        priority_s1 = calculate_slot1_def_priority(lr_gogeta_card, boss_stage=hard_boss_stage)
        priority_beast = calculate_slot1_def_priority(beast_gohan_card, boss_stage=hard_boss_stage)
        assert priority_s1 < priority_beast

    def test_llm_advisor_payload_enrichment_and_prompt_penalties(
        self, lr_gogeta_card: DokkanCard, hard_boss_stage: BossStage
    ) -> None:
        """Step 3: Enrich Qwen prompt payload with Slot 1 penalties and tactical metadata."""
        solver = DokkanConstraintSolver()
        leader = DokkanCard(
            id=1,
            name="Leader",
            element=10,
            category_ids=[1, 2, 3],
            leader_spec=LeaderSkillSpec(main_category_ids=[1, 2, 3], base_boost_pct=170),
        )
        ev_gogeta = solver.evaluate_card(lr_gogeta_card, leader, boss_stage=hard_boss_stage)

        payload = build_advisor_payload(
            boss_stage=hard_boss_stage,
            current_team=[leader],
            top_candidates=[ev_gogeta],
        )

        cand_data = payload["top_5_candidates"][0]
        assert cand_data["tactical_guard_type"] == "slot_2_3_locked"
        assert cand_data["has_slot_2_3_guard"] is True
        assert cand_data["slot_1_penalty"] is not None
        assert "Slot 2/3 restricted guard" in cand_data["slot_1_penalty"]

        messages = build_advisor_messages(hard_boss_stage, [leader], payload)
        system_content = messages[0]["content"]

        assert "has_slot_2_3_guard" in system_content
        assert "CRITICAL INTRO CLIFF EFFECT" in system_content
        assert "1030481" in system_content or "Slot 2/3 conditional guard" in system_content
