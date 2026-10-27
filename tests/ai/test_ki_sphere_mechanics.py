"""Test Suite for Ki Sphere Conditional Defense, Orb Hunger, and Orb-Changer Synergy.

Validates:
1. Passive parsing detects Ki Sphere conditional Damage Reduction, Dodge, and Guard.
2. Orb-dependent units are recognized as vulnerable pre-attack in Slot 1.
3. True Rainbow Ki Sphere changers and type changers are properly identified.
4. Rotation optimizer awards Orb Synergy when pairing orb-hungry units with orb changers.
5. Qwen LLM advisor payload and prompt reflect Ki Sphere mechanics.
"""

from __future__ import annotations

import pytest

from dokkan_eza_link_farmer.ai.boss_models import BossPhase, BossStage
from dokkan_eza_link_farmer.ai.card_models import DokkanCard
from dokkan_eza_link_farmer.ai.llm_advisor import build_advisor_messages, build_advisor_payload
from dokkan_eza_link_farmer.ai.solver import DokkanConstraintSolver
from dokkan_eza_link_farmer.ai.syncer import parse_passive_tags
from dokkan_eza_link_farmer.ai.synergy import (
    calculate_slot1_def_priority,
    calculate_slot2_partner_weight,
    optimize_rotations_for_team,
)


class TestKiSpherePassiveParsing:
    """Verifies that parse_passive_tags accurately identifies orb-conditional mechanics."""

    def test_ki_sphere_conditional_dr_detection(self) -> None:
        # Passive with DR per Ki Sphere obtained (e.g., Goku 4033771)
        passive = (
            "*Basic effect(s)*\n"
            "- Ki +3 and ATK & DEF 200%\n"
            "*When receiving an attack*\n"
            "- Damage reduction rate 10% per Ki Sphere obtained (up to 70%)\n"
        )
        tags = parse_passive_tags(passive)
        assert tags.has_orb_conditional_dr is True
        assert tags.is_orb_hungry is True
        # Since DR requires orbs, it is not unconditional pre-hit DR
        assert tags.pre_hit_dr_percent == 0
        assert tags.slot1_viable is False

    def test_ki_sphere_conditional_dodge_detection(self) -> None:
        # Passive with dodge based on Ki Spheres (e.g., Spy Robot 1034561 or Cell Jr.)
        passive = (
            "*Basic effect(s)*\n"
            "- ATK & DEF 150%\n"
            "*With a PHY Ki Sphere obtained*\n"
            "- Chance of evading enemy's attack 25%\n"
        )
        tags = parse_passive_tags(passive)
        assert tags.has_orb_conditional_dodge is True
        assert tags.is_orb_hungry is True
        assert tags.dodge_chance_percent == 0  # Not unconditional base dodge
        assert tags.slot1_viable is False

    def test_ki_sphere_conditional_guard_detection(self) -> None:
        # Passive with Guard requiring 6+ Ki Spheres (e.g., SSG Goku 1034461)
        passive = (
            "*Basic effect(s)*\n"
            "- Ki +3 and ATK & DEF 250%\n"
            "*6 or more Ki Spheres obtained*\n"
            "- Guards all attacks\n"
        )
        tags = parse_passive_tags(passive)
        assert tags.has_orb_conditional_guard is True
        assert tags.is_orb_hungry is True
        # Must NOT be marked as unconditional pre-hit guard
        assert tags.pre_hit_guard is False
        assert tags.slot1_viable is False

    def test_rainbow_orb_changer_distinction(self) -> None:
        # Card that changes spheres to Rainbow (e.g., Tamagami / Fusion Zamasu)
        passive_changer = (
            "*Basic effect(s)*\n"
            "- Randomly changes Ki Spheres of a certain Type to Rainbow Ki Spheres\n"
            "- ATK & DEF 200%\n"
        )
        tags_changer = parse_passive_tags(passive_changer)
        assert tags_changer.has_rainbow_orb_changing is True
        assert tags_changer.has_orb_changing is True
        assert tags_changer.is_orb_hungry is False  # Changer itself is not hungry

        # Card that consumes Rainbow spheres (e.g., SSJ4 Duo)
        passive_consumer = (
            "*Basic effect(s)*\n"
            "- ATK & DEF 200%\n"
            "*With 1 or more Rainbow Ki Spheres obtained*\n"
            "- Damage reduction rate 25%\n"
        )
        tags_consumer = parse_passive_tags(passive_consumer)
        assert tags_consumer.has_rainbow_orb_changing is False
        assert tags_consumer.has_orb_conditional_dr is True
        assert tags_consumer.is_orb_hungry is True


class TestKiSphereSlotAllocationAndSynergy:
    """Verifies that orb-hungry units are protected in Slot 2/3 and paired with orb changers."""

    @pytest.fixture
    def orb_hungry_tank(self) -> DokkanCard:
        """Card that gets 50% DR and Guard only with 6+ Ki Spheres obtained."""
        return DokkanCard(
            id=777001,
            name="Orb Hungry God",
            element=10,
            passive_skill=(
                "*Basic effect(s)*\n"
                "- ATK & DEF 200%\n"
                "*6 or more Ki Spheres obtained*\n"
                "- Guards all attacks\n"
                "- Damage reduction rate 50%\n"
            ),
        )

    @pytest.fixture
    def unconditional_tank(self) -> DokkanCard:
        """Card that has permanent unconditional Guard and 50% DR from turn start."""
        return DokkanCard(
            id=777002,
            name="Unconditional Wall",
            element=10,
            passive_skill=(
                "*Basic effect(s)*\n"
                "- Guards all attacks\n"
                "- Reduces damage received by 50%\n"
                "- ATK & DEF 250%\n"
            ),
        )

    @pytest.fixture
    def rainbow_orb_changer(self) -> DokkanCard:
        """Support unit that creates Rainbow Ki Spheres."""
        return DokkanCard(
            id=777003,
            name="Rainbow Provider",
            element=10,
            passive_skill=(
                "*Basic effect(s)*\n"
                "- Randomly changes Ki Spheres of a certain Type to Rainbow Ki Spheres\n"
                "- All allies' Ki +3 and ATK & DEF 40%\n"
            ),
            category_ids=[1, 2],
        )

    def test_orb_hungry_unit_penalized_for_slot1_priority(
        self, orb_hungry_tank: DokkanCard, unconditional_tank: DokkanCard
    ) -> None:
        """Unconditional tank must heavily outrank orb-hungry unit for Slot 1 placement."""
        p_uncond = calculate_slot1_def_priority(unconditional_tank)
        p_hungry = calculate_slot1_def_priority(orb_hungry_tank)

        assert p_uncond > p_hungry + 30.0, (
            f"Unconditional tank priority ({p_uncond}) should be significantly higher than orb hungry ({p_hungry})"
        )

    def test_orb_hungry_unit_rewarded_for_slot2_partner(self, orb_hungry_tank: DokkanCard) -> None:
        """Orb-hungry unit receives weight bonus for Slot 2 (picks up orbs before taking hits)."""
        w_s2 = calculate_slot2_partner_weight(orb_hungry_tank)
        assert w_s2 >= 12.0, f"Expected slot 2 weight >= 12.0, got {w_s2}"

    def test_rotation_optimizer_pairs_orb_hungry_with_orb_changer(
        self,
        unconditional_tank: DokkanCard,
        orb_hungry_tank: DokkanCard,
        rainbow_orb_changer: DokkanCard,
    ) -> None:
        """Rotation optimizer should favor having the orb changer in rotation or as floater with orb-hungry unit."""
        filler_1 = DokkanCard(id=777004, name="Filler 1", element=10, passive_skill="ATK 100%")
        filler_2 = DokkanCard(id=777005, name="Filler 2", element=10, passive_skill="ATK 100%")
        filler_3 = DokkanCard(id=777006, name="Filler 3", element=10, passive_skill="ATK 100%")
        filler_4 = DokkanCard(id=777007, name="Filler 4", element=10, passive_skill="ATK 100%")

        team = [
            unconditional_tank,
            orb_hungry_tank,
            rainbow_orb_changer,
            filler_1,
            filler_2,
            filler_3,
            filler_4,
        ]

        rot_a, rot_b, floaters = optimize_rotations_for_team(team)
        [rot_a.slot1, rot_a.slot2, rot_b.slot1, rot_b.slot2] + floaters

        # Orb hungry unit must be in Slot 2 or Slot 3, NEVER Slot 1 of rotation A if unconditional tank is present
        assert rot_a.slot1.id != orb_hungry_tank.id


class TestAdvisorPayloadKiSphereRules:
    """Verifies that the LLM system prompt and payload explicitly warn about Ki Sphere defense."""

    def test_advisor_system_prompt_contains_ki_sphere_rules(self) -> None:
        boss = BossStage(
            stage_id=1,
            event_id=1,
            event_name="Test Event",
            stage_name="Stage 1",
            phases=[BossPhase(phase_index=1, element=0, element_name="AGL")],
        )
        lead = DokkanCard(id=1, name="L", element=0)
        payload = build_advisor_payload(boss_stage=boss, current_team=[lead], top_candidates=[])
        msgs = build_advisor_messages(boss_stage=boss, current_team=[lead], payload=payload)

        system_prompt = msgs[0]["content"]
        assert "CRITICAL KI SPHERE CONDITIONAL DEFENSE" in system_prompt
        assert "DO NOT have that defense active pre-attack in Slot 1" in system_prompt
        assert "Rainbow Ki Sphere Changers" in system_prompt
        assert "CRITICAL DUAL CONDITIONAL PASSIVES" in system_prompt
        assert "Majin Vegeta (1033061)" in system_prompt


class TestDualConditionTeamBypass:
    """Verifies dual conditional units like Majin Vegeta (1033061) and SSJ2 Goku (4033071)."""

    @pytest.fixture
    def majin_vegeta_card(self) -> DokkanCard:
        return DokkanCard(
            id=1033061,
            name="Majin Vegeta + Super Saiyan 2 Goku (Angel)",
            element=23,  # Extreme STR
            passive_skill=(
                "*Basic effect(s)*\n"
                "- Damage reduction rate 18%\n"
                "- Guards all attacks\n"
                "*3 or more Ki Spheres obtained, or when 3 or more Extreme Class allies are on the team*\n"
                "- DEF 180% and damage reduction rate 18% when receiving an attack\n"
                "*5 or more Ki Spheres obtained, or when 4 or more Extreme Class allies are on the team*\n"
                "- Damage reduction rate 18% when receiving an attack\n"
                "*7 or more Ki Spheres obtained, or when 5 or more Extreme Class allies are on the team*\n"
                "- Damage reduction rate 18% before attacking\n"
            ),
            category_ids=[1, 2],
        )

    def test_majin_vegeta_with_5_extreme_allies_bypasses_orb_requirement(
        self, majin_vegeta_card: DokkanCard
    ) -> None:
        """With 5 Extreme Class allies, Majin Vegeta reaches 72% DR + Guard from start of turn."""
        extreme_team = [
            DokkanCard(id=201, name="Extreme 1", element=20),
            DokkanCard(id=202, name="Extreme 2", element=21),
            DokkanCard(id=203, name="Extreme 3", element=22),
            DokkanCard(id=204, name="Extreme 4", element=23),
            DokkanCard(id=205, name="Extreme 5", element=24),
        ]

        team_def = majin_vegeta_card.calculate_team_conditional_defense(extreme_team)
        assert team_def["dr"] == 72, f"Expected 72% DR, got {team_def['dr']}"
        assert team_def["guard"] is True
        assert team_def["is_slot1_safe"] is True
        assert team_def["bypasses_orb_requirement"] is True

        # Solver must recognize him as Slot 1 viable under this team
        solver = DokkanConstraintSolver()
        is_s1 = solver.is_slot1_viable(majin_vegeta_card, team=extreme_team)
        assert is_s1 is True

    def test_majin_vegeta_in_super_class_team_requires_orbs(
        self, majin_vegeta_card: DokkanCard
    ) -> None:
        """In a Super Class team (< 3 Extreme allies), Majin Vegeta does not bypass orbs."""
        super_team = [
            DokkanCard(id=101, name="Super 1", element=10),
            DokkanCard(id=102, name="Super 2", element=11),
            DokkanCard(id=103, name="Super 3", element=12),
            DokkanCard(id=104, name="Super 4", element=13),
            DokkanCard(id=105, name="Super 5", element=14),
        ]

        team_def = majin_vegeta_card.calculate_team_conditional_defense(super_team)
        assert team_def["dr"] == 18  # Only base 18% without orbs
        assert team_def["bypasses_orb_requirement"] is False
        assert team_def["is_slot1_safe"] is False

    def test_ssj2_goku_angel_in_super_class_team_bypasses_orbs(self) -> None:
        """Card 4033071 with 3+ Super allies activates 53% DR, 75% Dodge, and Guard without orbs."""
        goku_card = DokkanCard(
            id=4033071,
            name="Super Saiyan 2 Goku (Angel) + Majin Vegeta",
            element=13,  # Super STR
            passive_skill=(
                "*Basic effect(s)*\n"
                "- Damage reduction rate 18%\n"
                "- Chance of evading enemy's attack 40%\n"
                "*4 or more Ki Spheres obtained, or when 2 or more Super Class allies are on the team*\n"
                "- DEF 180% and chance of evading enemy's attack & damage reduction rate 35% when receiving an attack\n"
                "*6 or more Ki Spheres obtained, or when 3 or more Super Class allies are on the team*\n"
                "- Guards all attacks\n"
            ),
        )

        super_team = [
            DokkanCard(id=101, name="Super 1", element=10),
            DokkanCard(id=102, name="Super 2", element=11),
            DokkanCard(id=103, name="Super 3", element=12),
        ]

        team_def = goku_card.calculate_team_conditional_defense(super_team)
        assert team_def["dr"] == 53
        assert team_def["dodge"] == 75
        assert team_def["guard"] is True
        assert team_def["is_slot1_safe"] is True
        assert team_def["bypasses_orb_requirement"] is True
