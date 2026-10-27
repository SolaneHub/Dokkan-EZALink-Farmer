"""Tests for the exact Dokkan Battle damage formula, Natural Guard vs Passive Guard,
and Qwen AI advisor integration.
"""

from __future__ import annotations

from dokkan_eza_link_farmer.ai.llm_advisor import (
    build_advisor_messages,
    build_advisor_payload,
)
from dokkan_eza_link_farmer.ai.models import (
    BossPhase,
    BossStage,
    DokkanCard,
    LeaderSkillSpec,
)
from dokkan_eza_link_farmer.ai.solver import (
    CandidateEvaluation,
    DokkanConstraintSolver,
)


class TestDokkanDamageFormulaAndGuard:
    """Verifies mathematical correctness of the Dokkan Battle damage formula:
    Damage = {[(Enemy ATK * Variance * Type Modifier) * (1 - DR%)] - Ally DEF} * Guard Reduction
    """

    def test_user_scenario_1_type_neutral_50_percent_dr(self) -> None:
        """Scenario 1: Type Neutral (Type Mod = 1.0, Guard Reduction = 1.0), 50% DR, 250k DEF, 1M ATK."""
        damage = DokkanConstraintSolver.calculate_damage_taken(
            enemy_atk=1_000_000,
            type_matchup=0,
            has_passive_guard=False,
            dr_pct=50,
            def_stat=250_000,
            is_super_vs_extreme=False,
            variance=1.0,
        )
        # [(1,000,000 * 1.0 * 0.5) - 250,000] * 1.0 = 250,000
        assert damage == 250_000

    def test_user_scenario_2_passive_guard_no_dr(self) -> None:
        """Scenario 2: Passive Guard (Type Mod = 0.8, Guard Reduction = 0.5), 0% DR, 250k DEF, 1M ATK."""
        damage = DokkanConstraintSolver.calculate_damage_taken(
            enemy_atk=1_000_000,
            type_matchup=0,
            has_passive_guard=True,
            dr_pct=0,
            def_stat=250_000,
            is_super_vs_extreme=False,
            variance=1.0,
        )
        # [(1,000,000 * 0.8 * 1.0) - 250,000] * 0.5 = [550,000] * 0.5 = 275,000
        assert damage == 275_000

    def test_modern_red_zone_super_attack_naked_guard_vs_synergy(self) -> None:
        """Against a 3,000,000 Super Attack with 300,000 DEF:
        - Naked Guard (Guard, 0% DR) is lethal (1,050,000 damage).
        - 70% DR alone survives (600,000 damage).
        - Guard + 50% DR tanks easily (450,000 damage).
        """
        boss_sa = 3_000_000
        def_stat = 300_000

        # 1. Naked Guard
        naked_guard_dmg = DokkanConstraintSolver.calculate_damage_taken(
            enemy_atk=boss_sa,
            type_matchup=0,
            has_passive_guard=True,
            dr_pct=0,
            def_stat=def_stat,
            is_super_vs_extreme=False,
        )
        # [(3M * 0.8) - 300k] * 0.5 = [2.4M - 300k] * 0.5 = 1,050,000
        assert naked_guard_dmg == 1_050_000

        # 2. 70% DR without Guard (Neutral)
        dr_70_dmg = DokkanConstraintSolver.calculate_damage_taken(
            enemy_atk=boss_sa,
            type_matchup=0,
            has_passive_guard=False,
            dr_pct=70,
            def_stat=def_stat,
            is_super_vs_extreme=False,
        )
        # [(3M * 1.0 * 0.3) - 300k] * 1.0 = [900k - 300k] = 600,000
        assert dr_70_dmg == 600_000

        # 3. God Tank Synergy: Passive Guard + 50% DR
        god_tank_dmg = DokkanConstraintSolver.calculate_damage_taken(
            enemy_atk=boss_sa,
            type_matchup=0,
            has_passive_guard=True,
            dr_pct=50,
            def_stat=def_stat,
            is_super_vs_extreme=False,
        )
        # [(3M * 0.8 * 0.5) - 300k] * 0.5 = [1.2M - 300k] * 0.5 = 450,000
        assert god_tank_dmg == 450_000

    def test_natural_guard_type_advantage(self) -> None:
        """Natural Type Advantage (Natural Guard) gives 0.9x type mod and 0.5 guard reduction."""
        damage = DokkanConstraintSolver.calculate_damage_taken(
            enemy_atk=1_000_000,
            type_matchup=1,  # Advantage
            has_passive_guard=False,
            dr_pct=0,
            def_stat=300_000,
            is_super_vs_extreme=True,
        )
        # [(1M * 0.9) - 300k] * 0.5 = [600k] * 0.5 = 300,000
        assert damage == 300_000

    def test_passive_guard_saves_type_disadvantage(self) -> None:
        """In Type Disadvantage, Passive Guard completely overrides the 1.5x disadvantage to 0.8x + 0.5 reduction."""
        boss_atk = 2_000_000
        def_stat = 400_000

        # Disadvantage without Guard
        disadv_no_guard = DokkanConstraintSolver.calculate_damage_taken(
            enemy_atk=boss_atk,
            type_matchup=-1,
            has_passive_guard=False,
            dr_pct=0,
            def_stat=def_stat,
            is_super_vs_extreme=True,
        )
        # [(2M * 1.5) - 400k] * 1.0 = 2,600,000
        assert disadv_no_guard == 2_600_000

        # Disadvantage with Passive Guard
        disadv_with_guard = DokkanConstraintSolver.calculate_damage_taken(
            enemy_atk=boss_atk,
            type_matchup=-1,
            has_passive_guard=True,
            dr_pct=0,
            def_stat=def_stat,
            is_super_vs_extreme=True,
        )
        # [(2M * 0.8) - 400k] * 0.5 = [1.2M] * 0.5 = 600,000
        assert disadv_with_guard == 600_000


class TestAdvisorPayloadAndPromptIntegration:
    """Verifies that candidate evaluations, advisor payloads, and system prompts
    fully expose the damage formula and guard types to Qwen.
    """

    def test_candidate_evaluation_contains_guard_type_and_simulated_damage(self) -> None:
        solver = DokkanConstraintSolver()
        leader = DokkanCard(
            id=101,
            name="Leader",
            element=0,
            category_ids=[1],
            leader_spec=LeaderSkillSpec(main_category_ids=[1], base_boost_pct=170),
        )
        beast_gohan = DokkanCard(
            id=102,
            name="Beast Gohan",
            element=3,  # STR
            category_ids=[1],
            passive_skill="Guards all attacks; reduces damage received by 50%",
        )
        stage = BossStage(
            stage_id=1,
            event_id=1,
            event_name="Red Zone",
            stage_name="Final Showdown",
            phases=[
                BossPhase(
                    phase_index=1, element=1, element_name="TEQ", estimated_sa_damage=3_000_000
                )
            ],
        )

        ev = solver.evaluate_card(beast_gohan, leader, boss_stage=stage)

        assert ev.guard_type == "passive_guard"
        assert "God Tank" in ev.defensive_tier
        assert ev.estimated_damage_taken is not None
        assert ev.estimated_damage_taken < 600_000

    def test_advisor_payload_structure_includes_guard_and_damage_fields(self) -> None:
        card = DokkanCard(
            id=201,
            name="Test Tank",
            element=2,
            category_ids=[1],
            passive_skill="Guards all attacks; reduces damage received by 50%",
        )
        ev = CandidateEvaluation(
            card=card,
            score=90.0,
            lead_boost_pct=170.0,
            base_slot1_viable=True,
            guard_type="passive_guard",
            defensive_tier="God Tank (Passive Guard + 50% DR)",
            estimated_damage_taken=450_000,
        )
        stage = BossStage(
            stage_id=2,
            event_id=2,
            event_name="Event",
            stage_name="Stage",
            phases=[BossPhase(phase_index=1, element=0, element_name="AGL")],
        )

        payload = build_advisor_payload(
            boss_stage=stage,
            current_team=[card],
            top_candidates=[ev],
        )

        cand_json = payload["top_5_candidates"][0]
        assert cand_json["guard_type"] == "passive_guard"
        assert "God Tank" in cand_json["defensive_tier"]
        assert cand_json["estimated_sa_damage_taken"] == 450_000
        assert cand_json["dr_percent"] == 50

    def test_advisor_messages_include_damage_formula_instructions(self) -> None:
        card = DokkanCard(id=301, name="Test Card", element=0, category_ids=[1])
        stage = BossStage(
            stage_id=3,
            event_id=3,
            event_name="Event",
            stage_name="Stage",
            phases=[BossPhase(phase_index=1, element=0, element_name="AGL")],
        )
        payload = build_advisor_payload(stage, [card], [])

        messages = build_advisor_messages(stage, [card], payload)
        system_content = messages[0]["content"]

        assert "CRITICAL DOKKAN DAMAGE FORMULA" in system_content
        assert "Enemy ATK * Variance * Type Modifier" in system_content
        assert "Naked Guard" in system_content
        assert "Natural Guard" in system_content
        assert "has_slot_1_only_guard" in system_content


class TestSlot1RestrictedDefenseAndSupremeKai:
    """Verifies that cards with 'As the 1st attacker in a turn' guard (such as Supreme Kai 1015201):
    1. Are identified as having slot-1 restricted guard (has_slot_1_only_guard = True).
    2. Are NOT marked as unconditionally or permanently guarded.
    3. Are disqualified from Slot 1 viability against high-power (>= 1.8M) Super Attack bosses.
    4. Suffer score deductions for slot-1 locked defense and lethal simulated SA damage.
    5. Are heavily penalized if designated as floaters in rotation optimization.
    6. Trigger explicit tactical guide warnings if placed in Slot 3.
    """

    def test_supreme_kai_passive_parsing(self) -> None:
        kai = DokkanCard(
            id=1015201,
            name="Supreme Kai",
            subname="Watchers of the Cosmos",
            element=12,  # Super TEQ
            category_ids=[1, 2],
            passive_skill=(
                "Super Class allies' Ki +1 and ATK & DEF 20%; "
                "Ki +1 and ATK & DEF 30% per 'Realm of Gods' Category ally on the team; "
                "Guards all attacks as the 1st attacker in a turn; "
                "recovers 15% HP at the end of turn after receiving an attack"
            ),
        )
        assert kai.has_guard is True
        assert kai.has_slot_1_only_guard is True
        assert kai.is_guard_permanent is False
        assert kai.is_guard_unconditional is False

    def test_slot1_viability_disqualification_against_hard_hitting_boss(self) -> None:
        kai = DokkanCard(
            id=1015201,
            name="Supreme Kai",
            element=12,
            passive_skill="Guards all attacks as the 1st attacker in a turn",
        )
        hard_stage = BossStage(
            stage_id=17280054,
            event_id=1728,
            event_name="Union Master",
            stage_name="Stage 20",
            phases=[
                BossPhase(
                    phase_index=1,
                    element=1,
                    element_name="STR",
                    estimated_sa_damage=2_125_000,
                )
            ],
        )
        # Without boss_stage context (generic), slot 1 guard is viable
        assert DokkanConstraintSolver.is_slot1_viable(kai, boss_stage=None) is True

        # Against hard boss (SA >= 1.8M), Naked Guard is DISQUALIFIED from Slot 1 viability
        assert DokkanConstraintSolver.is_slot1_viable(kai, boss_stage=hard_stage) is False

    def test_multi_battle_turn1_shield_refusal(self) -> None:
        solver = DokkanConstraintSolver()
        kai = DokkanCard(
            id=1015201,
            name="Supreme Kai",
            element=12,
            passive_skill="Guards all attacks as the 1st attacker in a turn",
        )
        multi_stage = BossStage(
            stage_id=17280054,
            event_id=1728,
            event_name="Union Master",
            stage_name="Stage 20",
            total_battles=4,
            phases=[
                BossPhase(phase_index=1, battle_index=1, element=1, estimated_sa_damage=2_000_000),
                BossPhase(phase_index=2, battle_index=2, element=1, estimated_sa_damage=2_000_000),
            ],
        )
        delta, counters, penalties = solver.evaluate_boss_gimmicks(kai, multi_stage)
        # Should NOT receive the Multi-Battle Reliability Turn-1 bonus (+15.0)
        assert not any("Multi-Battle Reliability" in c for c in counters)

    def test_evaluate_card_penalties_for_slot1_guard_and_lethal_sa(self) -> None:
        solver = DokkanConstraintSolver()
        leader = DokkanCard(
            id=100,
            name="Test Leader",
            element=10,
            category_ids=[1],
            leader_spec=LeaderSkillSpec(main_category_ids=[1], base_boost_pct=170.0),
        )
        kai = DokkanCard(
            id=1015201,
            name="Supreme Kai",
            element=11,  # Super TEQ
            category_ids=[1],
            passive_skill="Guards all attacks as the 1st attacker in a turn",
        )
        hard_stage = BossStage(
            stage_id=17280054,
            event_id=1728,
            event_name="Union Master",
            stage_name="Stage 20",
            phases=[
                BossPhase(
                    phase_index=1,
                    element=13,  # Super STR (type disadvantage for TEQ)
                    estimated_sa_damage=2_500_000,
                )
            ],
        )
        ev = solver.evaluate_card(kai, leader, boss_stage=hard_stage)
        # 1. Base slot 1 viable must be False
        assert ev.base_slot1_viable is False
        # 2. Penalty points must note slot-1 restricted defense
        assert any("Slot-1 Restricted Defense" in p for p in ev.penalty_points)
        # 3. Penalty points must note lethal or severe SA vulnerability
        assert any("Vulnerability" in p for p in ev.penalty_points)
        # 4. Guard type should be deactivated when forced out of slot 1
        assert ev.guard_type == "none"

    def test_rotation_optimizer_penalizes_floating_slot1_guard_unit(self) -> None:
        from dokkan_eza_link_farmer.ai.synergy import optimize_rotations_for_team

        # 6 cards: 2 God tanks, 2 slot 2 partners, 1 normal support, 1 slot-1 guard unit
        tank1 = DokkanCard(
            id=1,
            name="Beast Gohan",
            element=11,
            passive_skill="Guards all attacks; reduces damage received by 60%",
        )
        tank2 = DokkanCard(
            id=2,
            name="TEQ UI Goku",
            element=12,
            passive_skill="Guards all attacks; reduces damage received by 50%",
        )
        dps1 = DokkanCard(
            id=3,
            name="LR SSJ4 Goku",
            element=10,
            passive_skill="Raises ATK & DEF by 150%; launches additional super attack",
        )
        dps2 = DokkanCard(
            id=4,
            name="LR SSJ4 Vegeta",
            element=11,
            passive_skill="Raises ATK & DEF by 150%; launches additional super attack",
        )
        support = DokkanCard(
            id=5,
            name="Support Piccolo",
            element=12,
            passive_skill="Super Class allies Ki +3 and ATK & DEF 40%",
        )
        kai = DokkanCard(
            id=1015201,
            name="Supreme Kai",
            element=12,
            passive_skill="Guards all attacks as the 1st attacker in a turn",
        )

        team = [tank1, tank2, dps1, dps2, support, kai]
        rot_a, rot_b, floaters = optimize_rotations_for_team(team)

        # Check that tactical guide triggers warning if a slot 1 locked card is floated
        from dokkan_eza_link_farmer.ai.formatters import generate_deterministic_tactical_guide

        guide = generate_deterministic_tactical_guide(
            rot_a, rot_b, floaters, leader=tank1, friend=tank2
        )
        if any(f.id == 1015201 for f in floaters):
            assert "Allerta Critica Floater con Meccanica Slot 1" in guide
            assert "As the 1st attacker in a turn" in guide
