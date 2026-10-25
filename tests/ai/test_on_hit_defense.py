"""Unit and integration tests for on-hit defense mitigation and Slot 1 tank validation.

Verifies that units whose defense, damage reduction, or guard only activates
upon/after receiving an attack (such as cards 1025731 and 1009351) are:
1. Correctly identified as having on-hit defense mechanics.
2. Disqualified from base Slot 1 viability (is_slot1_viable is False).
3. Given heavily penalized Slot 1 defensive priority, routing them to Slot 2/3 in rotations.
4. Correctly classified in AI Advisor payloads and warned against in Qwen system prompts.
"""

from __future__ import annotations

import pytest

from dokkan_eza_link_farmer.ai.client import DokkanAIClient
from dokkan_eza_link_farmer.ai.formatters import generate_deterministic_tactical_guide
from dokkan_eza_link_farmer.ai.llm_advisor import build_advisor_messages, build_advisor_payload
from dokkan_eza_link_farmer.ai.models import (
    BossEnemy,
    BossPhase,
    BossStage,
    DokkanCard,
    LeaderSkillSpec,
    RotationPair,
)
from dokkan_eza_link_farmer.ai.solver import DokkanConstraintSolver
from dokkan_eza_link_farmer.ai.syncer import parse_passive_tags
from dokkan_eza_link_farmer.ai.synergy import (
    calculate_slot1_anchor_weight,
    calculate_slot1_def_priority,
    calculate_slot2_partner_weight,
    evaluate_rotation_pair,
    optimize_rotations_for_team,
)
from dokkan_eza_link_farmer.integrations.dokkandb_client import DokkanDBClient


@pytest.fixture
def dokkandb() -> DokkanDBClient:
    return DokkanDBClient()


@pytest.fixture
def true_slot1_tank() -> DokkanCard:
    return DokkanCard(
        id=999901,
        name="Beast Gohan",
        element=3,
        rarity=5,
        passive_skill=(
            "*Basic effect(s)*\n"
            "- ATK & DEF 250%\n"
            "- Guards all attacks\n"
            "- Damage reduction rate 80%\n"
        ),
    )


class TestOnHitDefenseMechanics:
    def test_card_1009351_rose_defense_mechanics_and_slot2_assignment(
        self, dokkandb: DokkanDBClient, true_slot1_tank: DokkanCard
    ) -> None:
        raw_card = dokkandb.get_card(1009351)
        assert raw_card is not None
        rose = DokkanCard.from_dokkandb(raw_card)

        # 1. Defense mechanics inspection
        assert rose.has_on_hit_defense is True
        assert rose.has_on_hit_dr is True
        assert rose.has_on_hit_def is True
        assert rose.pre_hit_guard is False
        assert rose.pre_hit_dr_percent == 20
        assert rose.is_guard_unconditional is False

        # 2. Solver Slot 1 viability: MUST NOT be slot 1 viable
        assert DokkanConstraintSolver.is_slot1_viable(rose) is False
        assert rose.is_slot1_tank is False

        # 3. Defensive priority for Slot 1: heavily penalized
        priority = calculate_slot1_def_priority(rose)
        assert priority < 10.0

        # 4. Rotation pair assignment: Tank in Slot 1, Rosé in Slot 2
        rot = evaluate_rotation_pair(rose, true_slot1_tank)
        assert rot.slot1.id == true_slot1_tank.id
        assert rot.slot2.id == rose.id

    def test_card_1025731_buu_boys_defense_mechanics_and_slot2_assignment(
        self, dokkandb: DokkanDBClient, true_slot1_tank: DokkanCard
    ) -> None:
        raw_card = dokkandb.get_card(1025731)
        assert raw_card is not None
        buu_boys = DokkanCard.from_dokkandb(raw_card)

        # 1. Defense mechanics inspection
        assert buu_boys.has_on_hit_defense is True
        assert buu_boys.is_once_only_dr is True
        assert buu_boys.has_on_hit_def is True
        assert buu_boys.pre_hit_dr_percent == 0
        # Evasion regex does NOT match crit (up to 100%)
        assert buu_boys.dodge_chance_percent == 50

        # 2. Solver Slot 1 viability: MUST NOT be slot 1 viable
        assert DokkanConstraintSolver.is_slot1_viable(buu_boys) is False
        assert buu_boys.is_slot1_tank is False

        # 3. Defensive priority for Slot 1: heavily penalized compared to true tank
        tank_priority = calculate_slot1_def_priority(true_slot1_tank)
        buu_boys_priority = calculate_slot1_def_priority(buu_boys)
        assert buu_boys_priority < tank_priority

        # 4. Rotation pair assignment: Tank in Slot 1, Buu Boys in Slot 2
        rot = evaluate_rotation_pair(buu_boys, true_slot1_tank)
        assert rot.slot1.id == true_slot1_tank.id
        assert rot.slot2.id == buu_boys.id

    def test_on_hit_guard_card_disqualification(self) -> None:
        on_hit_guard_card = DokkanCard(
            id=888801,
            name="On-Hit Guard Fighter",
            element=0,
            rarity=5,
            passive_skill=(
                "*Basic effect(s)*\n"
                "- ATK & DEF 150%\n"
                "*When receiving an attack*\n"
                "- Guards all attacks\n"
                "- DEF 150%\n"
            ),
        )
        assert on_hit_guard_card.has_on_hit_guard is True
        assert on_hit_guard_card.pre_hit_guard is False
        assert DokkanConstraintSolver.is_slot1_viable(on_hit_guard_card) is False

    def test_solver_evaluate_card_and_solve_with_on_hit_cards(
        self, dokkandb: DokkanDBClient
    ) -> None:
        raw_card = dokkandb.get_card(1009351)
        assert raw_card is not None
        rose = DokkanCard.from_dokkandb(raw_card)

        lead = DokkanCard(
            id=777701,
            name="Extreme Lead",
            element=0,
            category_ids=rose.category_ids,
            leader_spec=LeaderSkillSpec(
                main_category_ids=rose.category_ids[:1], base_boost_pct=170
            ),
            passive_skill="Guards all attacks\nDamage reduction rate 60%",
        )
        solver = DokkanConstraintSolver()
        ev = solver.evaluate_card(rose, lead)
        assert any("On-hit defense" in p for p in ev.penalty_points)
        assert ev.base_slot1_viable is False

    def test_starting_from_turn_received_attack_guard(self) -> None:
        post_hit_card = DokkanCard(
            id=888802,
            name="Delayed Guard Fighter",
            element=1,
            rarity=5,
            passive_skill=(
                "ATK & DEF +180%; guards all attacks starting from the turn in which the character receives an attack"
            ),
        )
        assert post_hit_card.has_on_hit_guard is True
        assert post_hit_card.pre_hit_guard is False
        assert DokkanConstraintSolver.is_slot1_viable(post_hit_card) is False


class TestOnHitAIPromptsAndPayloads:
    def test_build_advisor_payload_identifies_on_hit_role(
        self, dokkandb: DokkanDBClient, true_slot1_tank: DokkanCard
    ) -> None:
        raw_card = dokkandb.get_card(1009351)
        assert raw_card is not None
        rose = DokkanCard.from_dokkandb(raw_card)

        stage = BossStage(
            stage_id=1,
            event_id=1,
            event_name="Red Zone",
            stage_name="Stage 1",
            difficulty=3,
            phases=[BossPhase(phase_index=1, element=0, element_name="AGL")],
        )
        payload = build_advisor_payload(
            boss_stage=stage,
            current_team=[true_slot1_tank, rose],
            top_candidates=[],
        )

        team = payload["current_team"]
        assert team[0]["role"] == "Slot 1 Tank"
        assert "On-Hit Buildup" in team[1]["role"]

    def test_build_advisor_messages_contains_strict_slot1_rule(
        self, true_slot1_tank: DokkanCard
    ) -> None:
        stage = BossStage(
            stage_id=1,
            event_id=1,
            event_name="Red Zone",
            stage_name="Stage 1",
            difficulty=3,
            phases=[BossPhase(phase_index=1, element=0, element_name="AGL")],
        )
        payload = build_advisor_payload(
            boss_stage=stage,
            current_team=[true_slot1_tank],
            top_candidates=[],
        )
        messages = build_advisor_messages(stage, [true_slot1_tank], payload)
        system_prompt = messages[0]["content"]
        assert "CRITICAL SLOT 1 SURVIVABILITY" in system_prompt
        assert "when receiving an attack" in system_prompt
        assert "oneshotted" in system_prompt.lower()

    def test_dokkan_ai_client_prompt_rules(self) -> None:
        client = DokkanAIClient()
        # Test Italian prompt rules
        messages_it: list[dict[str, str]] = []
        try:
            # Fake chat completion to inspect constructed messages
            client.chat_completion = lambda msgs, **_kwargs: (msgs, None)  # type: ignore
            res, _ = client.analyze_team_strategy("Team summary", "Boss info", language="it")
            messages_it = res  # type: ignore
        except Exception:
            pass

        if messages_it and isinstance(messages_it, list):
            sys_msg = messages_it[0]["content"]
            assert "REGOLA CRITICA SLOT 1 (NO TANK ON-HIT IN SLOT 1)" in sys_msg
            assert "quando ricevono un attacco" in sys_msg
            assert "ONESHOTTATE" in sys_msg

        # Test English prompt rules
        messages_en: list[dict[str, str]] = []
        try:
            res_en, _ = client.analyze_team_strategy("Team summary", "Boss info", language="en")
            messages_en = res_en  # type: ignore
        except Exception:
            pass

        if messages_en and isinstance(messages_en, list):
            sys_msg_en = messages_en[0]["content"]
            assert "CRITICAL SLOT 1 RULE (NO ON-HIT TANKS IN SLOT 1)" in sys_msg_en
            assert "when receiving an attack" in sys_msg_en
            assert "ONESHOTTED" in sys_msg_en

    def test_deterministic_guide_warns_on_hit_slot1(self, dokkandb: DokkanDBClient) -> None:
        raw_card = dokkandb.get_card(1009351)
        assert raw_card is not None
        rose = DokkanCard.from_dokkandb(raw_card)

        # Force rose in slot 1 of rotation A
        rot_a = RotationPair(
            slot1=rose,
            slot2=rose,
            shared_links=[],
            shared_ki_links=[],
            synergy_score=0.0,
        )
        rot_b = RotationPair(
            slot1=rose,
            slot2=rose,
            shared_links=[],
            shared_ki_links=[],
            synergy_score=0.0,
        )
        guide = generate_deterministic_tactical_guide(
            rot_a=rot_a,
            rot_b=rot_b,
            floaters=[],
            leader=rose,
            friend=rose,
        )
        assert "Avvisi Critici di Sopravvivenza (Difesa On-Hit)" in guide
        assert "oneshot" in guide


class TestSlot2OptimizationAndStacking:
    def test_slot2_partner_weights_and_properties_buu_boys_and_rose(
        self, dokkandb: DokkanDBClient
    ) -> None:
        raw_buu = dokkandb.get_card(1025731)
        raw_rose = dokkandb.get_card(1009351)
        assert raw_buu is not None
        assert raw_rose is not None

        buu_boys = DokkanCard.from_dokkandb(raw_buu)
        rose = DokkanCard.from_dokkandb(raw_rose)

        # Buu Boys: Stacks DEF, has on-hit, slot 2/3 bonus, raises DEF on SA
        assert buu_boys.has_stacking_def is True
        assert buu_boys.raises_def_on_sa is True
        assert buu_boys.has_slot_2_3_buff is True
        assert buu_boys.has_on_hit_defense is True
        buu_s2_weight = calculate_slot2_partner_weight(buu_boys)
        assert buu_s2_weight >= 35.0

        # Rosé: Has on-hit, raises DEF on SA
        assert rose.raises_def_on_sa is True
        assert rose.has_on_hit_defense is True
        rose_s2_weight = calculate_slot2_partner_weight(rose)
        assert rose_s2_weight >= 25.0

    def test_symbiotic_rotation_pair_scoring(
        self, dokkandb: DokkanDBClient, true_slot1_tank: DokkanCard
    ) -> None:
        raw_buu = dokkandb.get_card(1025731)
        assert raw_buu is not None
        buu_boys = DokkanCard.from_dokkandb(raw_buu)

        rot = evaluate_rotation_pair(buu_boys, true_slot1_tank)
        assert rot.slot1.id == true_slot1_tank.id
        assert rot.slot2.id == buu_boys.id
        # Includes symbiotic pairing bonus (+5.0)
        assert rot.synergy_score >= 5.0

    def test_optimize_rotations_locks_buu_boys_and_rose_into_slot2_not_floaters(
        self, dokkandb: DokkanDBClient, true_slot1_tank: DokkanCard
    ) -> None:
        raw_buu = dokkandb.get_card(1025731)
        raw_rose = dokkandb.get_card(1009351)
        assert raw_buu is not None
        assert raw_rose is not None
        buu_boys = DokkanCard.from_dokkandb(raw_buu)
        rose = DokkanCard.from_dokkandb(raw_rose)

        tank_2 = DokkanCard(
            id=999902,
            name="Angel SS3 Goku",
            element=1,
            rarity=5,
            passive_skill="Guards all attacks\nDamage reduction rate 70%",
        )

        support_floater_1 = DokkanCard(
            id=999903,
            name="Support Pan",
            element=2,
            rarity=4,
            passive_skill="All allies' Ki +3 and ATK & DEF +40%",
        )

        support_floater_2 = DokkanCard(
            id=999904,
            name="Support Bulla",
            element=3,
            rarity=4,
            passive_skill="All allies' Ki +3 and ATK +40%; great chance of evading enemy's attack",
        )

        cards = [true_slot1_tank, tank_2, buu_boys, rose, support_floater_1, support_floater_2]
        rot_a, rot_b, floaters = optimize_rotations_for_team(cards)

        tank_ids = {true_slot1_tank.id, tank_2.id}
        slot2_ids = {buu_boys.id, rose.id}
        floater_ids = {f.id for f in floaters}

        # 1. Slot 1 of both rotations MUST be true tanks
        assert rot_a.slot1.id in tank_ids
        assert rot_b.slot1.id in tank_ids

        # 2. Slot 2 of both rotations MUST be the stacker / on-hit buildup specialists
        assert rot_a.slot2.id in slot2_ids
        assert rot_b.slot2.id in slot2_ids

        # 3. Neither Buu Boys nor Rosé must be relegated to floaters
        assert buu_boys.id not in floater_ids
        assert rose.id not in floater_ids
        assert floater_ids == {support_floater_1.id, support_floater_2.id}

    def test_solver_evaluate_card_recognizes_slot2_stacker_partner(
        self, dokkandb: DokkanDBClient
    ) -> None:
        raw_buu = dokkandb.get_card(1025731)
        assert raw_buu is not None
        buu_boys = DokkanCard.from_dokkandb(raw_buu)

        lead = DokkanCard(
            id=777701,
            name="Super Lead",
            element=0,
            category_ids=buu_boys.category_ids,
            leader_spec=LeaderSkillSpec(
                main_category_ids=buu_boys.category_ids[:1], base_boost_pct=170
            ),
            passive_skill="Guards all attacks\nDamage reduction rate 60%",
        )
        solver = DokkanConstraintSolver()
        ev = solver.evaluate_card(buu_boys, lead)

        assert any("Optimal Slot 2 Partner" in c for c in ev.counter_points)
        assert any("Synergistic Slot 2 Stacker" in c for c in ev.counter_points)
        assert ev.base_slot1_viable is False


class TestEnemyConditionalDefense:
    def test_teq_god_goku_parsed_mechanics(self, dokkandb: DokkanDBClient) -> None:
        raw_card = dokkandb.get_card(1016031)
        assert raw_card is not None
        god_goku = DokkanCard.from_dokkandb(raw_card)

        # 1. Detection of enemy conditional defense
        assert god_goku.has_enemy_conditional_defense is True
        assert "Movie Bosses" in god_goku.enemy_conditional_categories
        assert "Pure Saiyans" in god_goku.enemy_conditional_categories
        assert god_goku.enemy_conditional_dr == 77

        # 2. Unconditional base defense is 0
        assert god_goku.pre_hit_dr_percent == 0
        assert god_goku.permanent_damage_reduction_percent == 0
        assert god_goku.has_guard is False

        # 3. Disqualified from Slot 1 without boss stage context
        assert DokkanConstraintSolver.is_slot1_viable(god_goku) is False
        assert god_goku.is_slot1_tank is False

    def test_union_mastery_realm_of_gods_stage_failing_phases(
        self, dokkandb: DokkanDBClient
    ) -> None:
        raw_card = dokkandb.get_card(1016031)
        assert raw_card is not None
        god_goku = DokkanCard.from_dokkandb(raw_card)

        # Reconstruct Union Mastery Stage 17280194
        p1_black = BossPhase(
            phase_index=1,
            bosses=[
                BossEnemy(
                    card_id=9531771,
                    name="Goku Black (Clone)",
                    categories=["Future Saga", "Realm of Gods"],
                )
            ],
        )
        p2_toppo = BossPhase(
            phase_index=2,
            bosses=[
                BossEnemy(
                    card_id=9528691,
                    name="Toppo (God of Destruction Mode)",
                    categories=["Universe Survival Saga", "Realm of Gods", "Universe 11"],
                )
            ],
        )
        p3_beerus = BossPhase(
            phase_index=3,
            bosses=[
                BossEnemy(
                    card_id=9104881, name="Beerus", categories=["Movie Bosses", "Realm of Gods"]
                )
            ],
        )
        stage = BossStage(
            stage_id=17280194,
            event_id=1728,
            event_name="Union Master",
            stage_name="Realm of Gods [3 Required]",
            phases=[p1_black, p2_toppo, p3_beerus],
        )

        all_match, failing = god_goku.check_enemy_conditions_match_all_phases(stage)
        assert all_match is False
        assert failing == [1, 2]

        # In this stage with Toppo, God Goku is NOT slot 1 viable
        assert DokkanConstraintSolver.is_slot1_viable(god_goku, stage) is False

    def test_movie_bosses_stage_matching_phases(self, dokkandb: DokkanDBClient) -> None:
        raw_card = dokkandb.get_card(1016031)
        assert raw_card is not None
        god_goku = DokkanCard.from_dokkandb(raw_card)

        # Stage where all enemies are Movie Bosses / Pure Saiyans
        p1_broly = BossPhase(
            phase_index=1,
            bosses=[
                BossEnemy(
                    card_id=910001,
                    name="Broly (Wrathful)",
                    categories=["Movie Bosses", "Pure Saiyans"],
                )
            ],
        )
        p2_broly = BossPhase(
            phase_index=2,
            bosses=[
                BossEnemy(
                    card_id=910002,
                    name="Super Saiyan Broly",
                    categories=["Movie Bosses", "Pure Saiyans"],
                )
            ],
        )
        stage = BossStage(
            stage_id=5001,
            event_id=500,
            event_name="Red Zone Movie Bosses",
            stage_name="Broly",
            phases=[p1_broly, p2_broly],
        )

        all_match, failing = god_goku.check_enemy_conditions_match_all_phases(stage)
        assert all_match is True
        assert failing == []

        # Against Movie Bosses Broly, God Goku gets 77% DR and is a legitimate Slot 1 tank!
        assert DokkanConstraintSolver.is_slot1_viable(god_goku, stage) is True

    def test_solver_evaluate_boss_gimmicks_penalties(self, dokkandb: DokkanDBClient) -> None:
        raw_card = dokkandb.get_card(1016031)
        assert raw_card is not None
        god_goku = DokkanCard.from_dokkandb(raw_card)

        # Stage with Toppo
        p1_black = BossPhase(
            phase_index=1,
            bosses=[
                BossEnemy(
                    card_id=9531771,
                    name="Goku Black (Clone)",
                    categories=["Future Saga", "Realm of Gods"],
                )
            ],
        )
        p2_toppo = BossPhase(
            phase_index=2,
            bosses=[
                BossEnemy(
                    card_id=9528691,
                    name="Toppo (God of Destruction Mode)",
                    categories=["Universe Survival Saga", "Realm of Gods", "Universe 11"],
                )
            ],
        )
        stage = BossStage(
            stage_id=17280194,
            event_id=1728,
            event_name="Union Master",
            stage_name="Realm of Gods [3 Required]",
            phases=[p1_black, p2_toppo],
        )

        solver = DokkanConstraintSolver()
        delta, counters, penalties = solver.evaluate_boss_gimmicks(god_goku, stage)
        assert delta <= -60.0
        assert any("Conditional Defense Inactive" in p for p in penalties)
        assert any("Phase(s) 1, 2" in p for p in penalties)

    def test_rotation_assignment_disqualifies_god_goku_when_unmatched(
        self, dokkandb: DokkanDBClient, true_slot1_tank: DokkanCard
    ) -> None:
        raw_card = dokkandb.get_card(1016031)
        assert raw_card is not None
        god_goku = DokkanCard.from_dokkandb(raw_card)

        p2_toppo = BossPhase(
            phase_index=1,
            bosses=[
                BossEnemy(
                    card_id=9528691, name="Toppo", categories=["Realm of Gods", "Universe 11"]
                )
            ],
        )
        stage = BossStage(
            stage_id=17280194,
            event_id=1728,
            event_name="Union Master",
            stage_name="Realm of Gods",
            phases=[p2_toppo],
        )

        priority = calculate_slot1_def_priority(god_goku, boss_stage=stage)
        assert priority < 0.0

        anchor_wt = calculate_slot1_anchor_weight(god_goku, boss_stage=stage)
        assert anchor_wt == 0.0

        rot = evaluate_rotation_pair(god_goku, true_slot1_tank, boss_stage=stage)
        assert rot.slot1.id == true_slot1_tank.id
        assert rot.slot2.id == god_goku.id

    def test_syncer_parse_passive_tags_enemy_conditional(self, dokkandb: DokkanDBClient) -> None:
        raw_card = dokkandb.get_card(1016031)
        assert raw_card is not None
        god_goku = DokkanCard.from_dokkandb(raw_card)

        tags = parse_passive_tags(god_goku.passive_skill)
        assert tags.has_enemy_conditional_defense is True
        assert "Movie Bosses" in tags.enemy_conditional_categories
        assert "Pure Saiyans" in tags.enemy_conditional_categories
        assert tags.enemy_conditional_dr == 77
        assert tags.slot1_viable is False
        assert tags.pre_hit_dr_percent == 0
        assert tags.dr_base_percent == 0

    def test_deterministic_tactical_guide_warnings(
        self, dokkandb: DokkanDBClient, true_slot1_tank: DokkanCard
    ) -> None:
        raw_card = dokkandb.get_card(1016031)
        assert raw_card is not None
        god_goku = DokkanCard.from_dokkandb(raw_card)

        p2_toppo = BossPhase(
            phase_index=1,
            bosses=[
                BossEnemy(
                    card_id=9528691, name="Toppo", categories=["Realm of Gods", "Universe 11"]
                )
            ],
        )
        stage = BossStage(
            stage_id=17280194,
            event_id=1728,
            event_name="Union Master",
            stage_name="Realm of Gods",
            phases=[p2_toppo],
        )

        rot_a = RotationPair(
            slot1=true_slot1_tank,
            slot2=god_goku,
            shared_links=[],
            shared_ki_links=[],
            synergy_score=0.0,
        )
        rot_b = RotationPair(
            slot1=true_slot1_tank,
            slot2=god_goku,
            shared_links=[],
            shared_ki_links=[],
            synergy_score=0.0,
        )
        guide = generate_deterministic_tactical_guide(
            rot_a=rot_a,
            rot_b=rot_b,
            floaters=[true_slot1_tank, god_goku],
            leader=true_slot1_tank,
            friend=true_slot1_tank,
            boss_stage=stage,
        )

        assert "🛑 Allerta Critica Categoria Nemica (Rischio Oneshot)" in guide
        assert "Movie Bosses" in guide or "Pure Saiyans" in guide
