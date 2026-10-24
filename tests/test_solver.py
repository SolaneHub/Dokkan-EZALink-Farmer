"""Comprehensive unit tests for DokkanConstraintSolver.

Covers:
- Leader skill filtering (170% and 200%, sub-elements)
- Team uniqueness (6 distinct cards, unique card.id)
- Same-name base form penalty (form_index: 0)
- Slot 1 viability constraint (>= 2 base slot 1 units in final team)
- Cyclic type wheel matrix (AGL > STR > PHY > INT > TEQ > AGL)
- Boss gimmick overrides:
  * cancels_dodge (neutralizes dodge, penalizes unshielded dodge glass cannons)
  * has_aoe (penalizes floaters lacking start-of-turn Guard/DR, rewards protected units)
  * locks_slots (boosts slot 1 viable units, penalizes fragile units)
  * type disadvantage mitigation (strongly mitigated if has_guard or DR >= 60%)
- Top-5 runner-up shortlist extraction
- Late-game scaling (transformations at Turn 4+ and permanent DEF stacking)
"""

from __future__ import annotations

from typing import Any

import pytest

from dokkan_eza_link_farmer.ai.mission_solver import MissionBatch
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
from dokkan_eza_link_farmer.ai.solver import (
    ELEMENT_ADVANTAGE,
    ELEMENT_DISADVANTAGE,
    SAME_NAME_BASE_PENALTY,
    CandidateEvaluation,
    DokkanConstraintSolver,
    get_base_form_name,
)
from dokkan_eza_link_farmer.ai.team_builder import format_team_summary_table
from dokkan_eza_link_farmer.integrations.dokkandb_client import DokkanDBClient


class TestTypeMatrix:
    """Validates the Dokkan Battle cyclic type effectiveness wheel."""

    def test_cyclic_type_advantage(self) -> None:
        solver = DokkanConstraintSolver()
        # AGL (0) beats STR (3)
        assert solver.check_type_matchup(0, 3) == 1
        # STR (3) beats PHY (4)
        assert solver.check_type_matchup(3, 4) == 1
        # PHY (4) beats INT (2)
        assert solver.check_type_matchup(4, 2) == 1
        # INT (2) beats TEQ (1)
        assert solver.check_type_matchup(2, 1) == 1
        # TEQ (1) beats AGL (0)
        assert solver.check_type_matchup(1, 0) == 1

    def test_cyclic_type_disadvantage(self) -> None:
        solver = DokkanConstraintSolver()
        # AGL (0) weak to TEQ (1)
        assert solver.check_type_matchup(0, 1) == -1
        # TEQ (1) weak to INT (2)
        assert solver.check_type_matchup(1, 2) == -1
        # INT (2) weak to PHY (4)
        assert solver.check_type_matchup(2, 4) == -1
        # PHY (4) weak to STR (3)
        assert solver.check_type_matchup(4, 3) == -1
        # STR (3) weak to AGL (0)
        assert solver.check_type_matchup(3, 0) == -1

    def test_neutral_type_matchups(self) -> None:
        solver = DokkanConstraintSolver()
        # Same type
        assert solver.check_type_matchup(0, 0) == 0
        assert solver.check_type_matchup(1, 1) == 0
        assert solver.check_type_matchup(2, 2) == 0
        assert solver.check_type_matchup(3, 3) == 0
        assert solver.check_type_matchup(4, 4) == 0

        # Non-adjacent neutral pairs
        assert solver.check_type_matchup(0, 4) == 0  # AGL vs PHY
        assert solver.check_type_matchup(4, 0) == 0  # PHY vs AGL
        assert solver.check_type_matchup(0, 2) == 0  # AGL vs INT
        assert solver.check_type_matchup(2, 0) == 0  # INT vs AGL
        assert solver.check_type_matchup(3, 2) == 0  # STR vs INT
        assert solver.check_type_matchup(2, 3) == 0  # INT vs STR
        assert solver.check_type_matchup(1, 3) == 0  # TEQ vs STR
        assert solver.check_type_matchup(3, 1) == 0  # STR vs TEQ

    def test_super_extreme_modulo_handling(self) -> None:
        solver = DokkanConstraintSolver()
        # Super AGL (10) vs Extreme STR (23) -> AGL beats STR
        assert solver.check_type_matchup(10, 23) == 1
        # Extreme STR (23) vs Super AGL (10) -> STR weak to AGL
        assert solver.check_type_matchup(23, 10) == -1
        # Super TEQ (11) vs Extreme AGL (20) -> TEQ beats AGL
        assert solver.check_type_matchup(11, 20) == 1

    def test_constants_completeness(self) -> None:
        for t in range(5):
            assert t in ELEMENT_ADVANTAGE
            assert t in ELEMENT_DISADVANTAGE
            # The type that t beats should be weak to t
            beaten = ELEMENT_ADVANTAGE[t]
            assert ELEMENT_DISADVANTAGE[beaten] == t


class TestLeaderSkillFilter:
    """Validates O(1) set-based leader skill filtering (170%, 200%, 220%, sub-elements)."""

    @pytest.fixture
    def leader_card(self) -> DokkanCard:
        spec = LeaderSkillSpec(
            main_category_ids=[10, 20],  # Realm of Gods (10), Potara (20)
            extra_category_ids=[30],  # Future Saga (30) -> 200%
            sub_elements_classes=[0],  # Super AGL fallback
            base_boost_pct=170,
            extra_boost_pct=30,
            sub_boost_pct=150,
        )
        return DokkanCard(
            id=1001,
            name="LR Vegito Blue",
            element=0,
            category_ids=[10, 20, 30],
            categories=["Realm of Gods", "Potara", "Future Saga"],
            leader_skill="Realm of Gods or Potara +170%; Future Saga +30%; Super AGL +150%",
            leader_spec=spec,
        )

    @pytest.fixture
    def leader_card_220(self) -> DokkanCard:
        spec = LeaderSkillSpec(
            main_category_ids=[
                17,
                85,
                95,
            ],  # Pure Saiyans (17), Fused Fighters (85), Earth-Protecting Heroes (95)
            extra_category_ids=[10, 89],  # Potara (10), Earth-Bred Fighters (89)
            sub_elements_classes=[],
            base_boost_pct=170,
            extra_boost_pct=50,
            sub_boost_pct=0,
        )
        return DokkanCard(
            id=1030431,
            name="Super Saiyan Goku + Super Saiyan Vegeta (Angel)",
            element=11,
            category_ids=[9, 17, 85, 95, 10, 89],
            categories=[
                "Majin Buu Saga",
                "Pure Saiyans",
                "Fused Fighters",
                "Earth-Protecting Heroes",
                "Potara",
                "Earth-Bred Fighters",
            ],
            leader_skill="Pure Saiyans, Fused Fighters, Earth-Protecting Heroes +170%; Potara, Earth-Bred Fighters +50%",
            leader_spec=spec,
        )

    def test_200_percent_boost(self, leader_card: DokkanCard) -> None:
        solver = DokkanConstraintSolver()
        candidate = DokkanCard(
            id=1002,
            name="Zamasu",
            element=1,
            category_ids=[10, 30],  # Main (10) + Extra (30) -> 200%
            categories=["Realm of Gods", "Future Saga"],
        )
        is_cov, boost_pct, _ = candidate.is_covered_by_leader(leader_card)
        assert is_cov is True
        assert boost_pct == 200.0

        results = solver.filter_by_leader_skill([candidate], leader_card)
        assert len(results) == 1
        card, boost = results[0]
        assert card.id == 1002
        assert boost == 200.0

    def test_220_percent_boost(self, leader_card_220: DokkanCard) -> None:
        solver = DokkanConstraintSolver()
        candidate = DokkanCard(
            id=1024861,
            name="Super Saiyan Goku",
            element=11,
            category_ids=[
                17,
                89,
            ],  # Main Pure Saiyans (17) + Extra Earth-Bred Fighters (89) -> 220%
            categories=["Pure Saiyans", "Earth-Bred Fighters"],
        )
        is_cov, boost_pct, _ = candidate.is_covered_by_leader(leader_card_220)
        assert is_cov is True
        assert boost_pct == 220.0

        results = solver.filter_by_leader_skill([candidate], leader_card_220)
        assert len(results) == 1
        card, boost = results[0]
        assert card.id == 1024861
        assert boost == 220.0

    def test_170_percent_boost(self, leader_card: DokkanCard) -> None:
        solver = DokkanConstraintSolver()
        candidate = DokkanCard(
            id=1003,
            name="Kefla",
            element=3,
            category_ids=[20],  # Main (20) only -> 170%
            categories=["Potara"],
        )
        is_cov, boost_pct, _ = candidate.is_covered_by_leader(leader_card)
        assert is_cov is True
        assert boost_pct == 170.0

        results = solver.filter_by_leader_skill([candidate], leader_card)
        assert len(results) == 1
        card, boost = results[0]
        assert card.id == 1003
        assert boost == 170.0

    def test_extra_only_card_gives_zero_and_rejected_by_solver(
        self, leader_card: DokkanCard
    ) -> None:
        """A unit sharing only extra_category_ids without has_main must receive 0% and be rejected."""
        solver = DokkanConstraintSolver()
        candidate = DokkanCard(
            id=1006,
            name="Future Gohan (Extra Only)",
            element=3,  # STR (not sub-element AGL)
            category_ids=[30],  # Extra (30) ONLY, no Main (10 or 20)
            categories=["Future Saga"],
        )
        is_cov, boost_pct, msg = candidate.is_covered_by_leader(leader_card)
        assert is_cov is False
        assert boost_pct == 0.0

        results = solver.filter_by_leader_skill([candidate], leader_card)
        assert len(results) == 0

        ev = solver.evaluate_card(candidate, leader_card)
        assert ev.score <= -1000.0
        assert ev.lead_boost_pct == 0.0
        assert any("Zero shared categories" in p for p in ev.penalty_points)

    def test_sub_element_boost(self, leader_card: DokkanCard) -> None:
        solver = DokkanConstraintSolver()
        candidate = DokkanCard(
            id=1004,
            name="Super Saiyan Broly",
            element=0,  # AGL matches sub_elements_classes
            category_ids=[99],  # Unrelated category
        )
        results = solver.filter_by_leader_skill([candidate], leader_card, min_pct=150.0)
        assert len(results) == 1
        card, boost = results[0]
        assert card.id == 1004
        assert boost == 150.0

    def test_uncovered_card_filtered_out(self, leader_card: DokkanCard) -> None:
        solver = DokkanConstraintSolver()
        candidate = DokkanCard(
            id=1005,
            name="Cell (Max)",
            element=3,  # STR (not sub-element AGL)
            category_ids=[88, 99],  # No matching category
        )
        results = solver.filter_by_leader_skill([candidate], leader_card, min_pct=150.0)
        assert len(results) == 0

    def test_flat_200_percent_leader_no_extra_category(self) -> None:
        solver = DokkanConstraintSolver()
        flat_lead = DokkanCard(
            id=1010,
            name="Flat 200 Leader",
            category_ids=[10],
            categories=["Realm of Gods"],
            leader_spec=LeaderSkillSpec(
                main_category_ids=[10],
                extra_category_ids=[],
                base_boost_pct=200,
                extra_boost_pct=0,
            ),
        )
        cand = DokkanCard(
            id=1011,
            name="God Goku",
            category_ids=[10],
            categories=["Realm of Gods"],
        )
        is_cov, boost, _ = cand.is_covered_by_leader(flat_lead)
        assert is_cov is True
        assert boost == 200.0

        results = solver.filter_by_leader_skill([cand], flat_lead)
        assert len(results) == 1
        assert results[0][1] == 200.0

        team = [flat_lead, cand] + [
            DokkanCard(
                id=1012 + i, name=f"God {i}", category_ids=[10], categories=["Realm of Gods"]
            )
            for i in range(4)
        ]
        table = format_team_summary_table(team)
        assert "Extra: Nessuna" in table
        assert "200%" in table

    def test_regex_fallback_220_percent_boost(self) -> None:
        leader_no_spec = DokkanCard(
            id=1020,
            name="Pure Saiyan 220 Lead",
            leader_skill='"Pure Saiyans" Category Ki +3 and HP, ATK & DEF +170%, plus an additional HP, ATK & DEF +50% for characters who also belong to the "Earth-Bred Fighters" Category',
            categories=["Pure Saiyans", "Earth-Bred Fighters"],
        )
        full_220 = DokkanCard(
            id=1021,
            name="Full 220 Candidate",
            categories=["Pure Saiyans", "Earth-Bred Fighters"],
        )
        extra_only = DokkanCard(
            id=1022,
            name="Extra Only Candidate",
            categories=["Earth-Bred Fighters"],
        )

        is_cov, boost, _ = full_220.is_covered_by_leader(leader_no_spec)
        assert is_cov is True
        assert boost == 220.0

        is_cov_extra, boost_extra, _ = extra_only.is_covered_by_leader(leader_no_spec)
        assert is_cov_extra is False
        assert boost_extra == 0.0

    def test_extra_only_card_with_sub_element_fallback_rejected_by_solver(
        self, leader_card: DokkanCard
    ) -> None:
        solver = DokkanConstraintSolver()
        # Card has extra category [30] (Future Saga) and sub-element AGL (0), but NOT main [10, 20]
        candidate = DokkanCard(
            id=1030,
            name="AGL Future Sub-Element Only",
            element=0,  # AGL matches leader sub_elements_classes
            category_ids=[30],  # Extra category only
            categories=["Future Saga"],
        )
        # In models.py: receives sub-element boost (150%) since it lacks main
        is_cov, boost_pct, msg = candidate.is_covered_by_leader(leader_card)
        assert is_cov is True
        assert boost_pct == 150.0

        # In solver: rejected with default min_pct=170
        results = solver.filter_by_leader_skill([candidate], leader_card, min_pct=170.0)
        assert len(results) == 0

        # evaluate_card rejects because not has_main
        ev = solver.evaluate_card(candidate, leader_card)
        assert ev.score <= -1000.0
        assert ev.lead_boost_pct == 0.0


class TestBossGimmickOverrides:
    """Validates boss gimmick overrides: cancels_dodge, has_aoe, locks_slots, and guard/DR mitigation."""

    @pytest.fixture
    def solver(self) -> DokkanConstraintSolver:
        return DokkanConstraintSolver()

    def test_type_disadvantage_mitigated_by_guard(self, solver: DokkanConstraintSolver) -> None:
        # STR boss final phase
        boss = BossStage(
            stage_id=1,
            event_id=1,
            stage_name="Final Showdown",
            event_name="Red Zone",
            phases=[BossPhase(phase_index=1, element=3, element_name="STR")],
        )

        # PHY unit has type disadvantage against STR (STR beats PHY)
        phy_with_guard = DokkanCard(
            id=2001,
            name="PHY Guard Unit",
            element=4,  # PHY
            base_form=CardForm(
                form_id=2001,
                form_index=0,
                form_name="PHY Guard (Base)",
                element=4,
                passive_tags=PassiveTags(has_guard=True, dr_base_percent=0),
            ),
        )
        phy_without_guard = DokkanCard(
            id=2002,
            name="PHY Frail Unit",
            element=4,  # PHY
            base_form=CardForm(
                form_id=2002,
                form_index=0,
                form_name="PHY Frail (Base)",
                element=4,
                passive_tags=PassiveTags(has_guard=False, dr_base_percent=0),
            ),
        )

        delta_guard, counters_g, _ = solver.evaluate_boss_gimmicks(phy_with_guard, boss)
        delta_frail, _, penalties_f = solver.evaluate_boss_gimmicks(phy_without_guard, boss)

        # Guard strongly mitigates disadvantage to -5.0 instead of -25.0
        assert delta_guard == -5.0
        assert any("mitigated by Guard/DR" in c for c in counters_g)

        assert delta_frail == -25.0
        assert any("Severe Type Disadvantage" in p for p in penalties_f)

    def test_type_disadvantage_mitigated_by_high_dr(self, solver: DokkanConstraintSolver) -> None:
        # INT boss (INT beats TEQ)
        boss = BossStage(
            stage_id=1,
            event_id=1,
            stage_name="Showdown",
            event_name="Blue Zone",
            phases=[BossPhase(phase_index=1, element=2, element_name="INT")],
        )
        teq_with_60_dr = DokkanCard(
            id=2003,
            name="TEQ 60% DR Tank",
            element=1,  # TEQ weak to INT
            base_form=CardForm(
                form_id=2003,
                form_index=0,
                form_name="TEQ Tank",
                element=1,
                passive_tags=PassiveTags(has_guard=False, dr_base_percent=60),
            ),
        )
        delta, counters, _ = solver.evaluate_boss_gimmicks(teq_with_60_dr, boss)
        assert delta == -5.0
        assert any("mitigated by Guard/DR (60%)" in c for c in counters)

    def test_type_advantage_bonus(self, solver: DokkanConstraintSolver) -> None:
        # STR boss final phase
        boss = BossStage(
            stage_id=1,
            event_id=1,
            stage_name="Showdown",
            event_name="Red Zone",
            phases=[BossPhase(phase_index=1, element=3, element_name="STR")],
        )
        agl_unit = DokkanCard(
            id=2004,
            name="AGL Attacker",
            element=0,  # AGL beats STR
            base_form=CardForm(form_id=2004, form_index=0, form_name="AGL Attacker", element=0),
        )
        delta, counters, _ = solver.evaluate_boss_gimmicks(agl_unit, boss)
        assert delta == 5.0
        assert any("Type Advantage" in c for c in counters)

    def test_cancels_dodge_penalizes_unshielded_dodge(self, solver: DokkanConstraintSolver) -> None:
        boss = BossStage(
            stage_id=1,
            event_id=1,
            stage_name="Stage 1",
            event_name="Red Zone",
            phases=[BossPhase(phase_index=1, element=0, cancels_dodge=True)],
        )

        unshielded_dodge = DokkanCard(
            id=2005,
            name="Glass Cannon MUI",
            element=0,
            base_form=CardForm(
                form_id=2005,
                form_index=0,
                form_name="Glass Cannon",
                element=0,
                passive_tags=PassiveTags(
                    dodge_chance_percent=70, has_guard=False, dr_base_percent=0
                ),
            ),
        )
        shielded_dodge = DokkanCard(
            id=2006,
            name="Shielded Dodge Tank",
            element=0,
            base_form=CardForm(
                form_id=2006,
                form_index=0,
                form_name="Shielded Tank",
                element=0,
                passive_tags=PassiveTags(
                    dodge_chance_percent=70, has_guard=True, dr_base_percent=40
                ),
            ),
        )

        delta_unshielded, _, pen_unshielded = solver.evaluate_boss_gimmicks(unshielded_dodge, boss)
        delta_shielded, _, pen_shielded = solver.evaluate_boss_gimmicks(shielded_dodge, boss)

        # Unshielded receives severe glass cannon vulnerability penalty (-60.0)
        assert delta_unshielded == pytest.approx(-60.0, abs=0.1)
        assert any("neutralized by Boss (Cancels Dodge)" in p for p in pen_unshielded)
        assert any("Severe Glass Cannon Vulnerability" in p for p in pen_unshielded)

        # Shielded has dodge neutralized but does NOT suffer the extra -60.0 glass cannon penalty
        assert delta_shielded == pytest.approx(0.0, abs=0.1)
        assert not any("Severe Glass Cannon Vulnerability" in p for p in pen_shielded)

    def test_cancels_dodge_penalizes_passive_text_dodge_fallback(
        self, solver: DokkanConstraintSolver
    ) -> None:
        boss = BossStage(
            stage_id=1,
            event_id=1,
            stage_name="Stage 1",
            event_name="Red Zone",
            phases=[BossPhase(phase_index=1, element=0, cancels_dodge=True)],
        )

        # Card initialized with evasion in passive text but default dodge_chance_percent == 0
        text_dodge_card = DokkanCard(
            id=2099,
            name="Text Dodge Unit",
            element=0,
            passive_skill="Great chance of evading enemy attacks",
            base_form=CardForm(
                form_id=2099,
                form_index=0,
                form_name="Text Dodge Unit",
                element=0,
                passive_tags=PassiveTags(
                    dodge_chance_percent=0, has_guard=False, dr_base_percent=0
                ),
            ),
        )

        assert text_dodge_card.has_dodge is True
        assert (
            text_dodge_card.base_form is not None
            and text_dodge_card.base_form.passive_tags is not None
            and text_dodge_card.base_form.passive_tags.dodge_chance_percent == 0
        )

        delta, _, penalties = solver.evaluate_boss_gimmicks(text_dodge_card, boss)

        # Great chance parses to 70% and suffers severe glass cannon penalty (-60.0)
        assert delta == pytest.approx(-60.0, abs=0.1)
        assert any("Dodge (70%) neutralized by Boss (Cancels Dodge)" in p for p in penalties)
        assert any("Severe Glass Cannon Vulnerability" in p for p in penalties)

        # Also test auto-instantiated base form where passive_tags.dodge_chance_percent defaults to 0
        auto_card = DokkanCard(
            id=2100,
            name="Auto Form Dodge Unit",
            element=0,
            passive_skill="Great chance of evading enemy attacks",
        )
        delta_auto, _, pen_auto = solver.evaluate_boss_gimmicks(auto_card, boss)
        assert delta_auto == pytest.approx(-60.0, abs=0.1)
        assert any("Dodge (70%) neutralized by Boss (Cancels Dodge)" in p for p in pen_auto)
        assert any("Severe Glass Cannon Vulnerability" in p for p in pen_auto)

    def test_has_aoe_gimmick(self, solver: DokkanConstraintSolver) -> None:
        boss = BossStage(
            stage_id=1,
            event_id=1,
            stage_name="Stage 1",
            event_name="Red Zone Broly",
            phases=[BossPhase(phase_index=1, element=0, has_aoe=True)],
        )

        fragile_floater = DokkanCard(
            id=2007,
            name="Fragile Post-Super Attacker",
            element=0,
            base_form=CardForm(
                form_id=2007,
                form_index=0,
                form_name="Floater",
                element=0,
                passive_tags=PassiveTags(has_guard=False, dr_base_percent=0),
            ),
        )
        protected_unit = DokkanCard(
            id=2008,
            name="Start of Turn Tank",
            element=0,
            base_form=CardForm(
                form_id=2008,
                form_index=0,
                form_name="Tank",
                element=0,
                passive_tags=PassiveTags(has_guard=True, dr_base_percent=50),
            ),
        )

        delta_fragile, _, pen_fragile = solver.evaluate_boss_gimmicks(fragile_floater, boss)
        delta_protected, count_protected, _ = solver.evaluate_boss_gimmicks(protected_unit, boss)

        assert delta_fragile == -22.0
        assert any("AoE Vulnerability" in p for p in pen_fragile)

        assert delta_protected == 15.0
        assert any("Start-of-turn Guard/DR mitigates Boss AoE" in c for c in count_protected)

    def test_locks_slots_gimmick(self, solver: DokkanConstraintSolver) -> None:
        boss = BossStage(
            stage_id=1,
            event_id=1,
            stage_name="Stage 1",
            event_name="Red Zone Syn",
            phases=[BossPhase(phase_index=1, element=0, locks_slots=True)],
        )

        s1_unit = DokkanCard(
            id=2009,
            name="Slot 1 Anchor",
            element=0,
            base_form=CardForm(
                form_id=2009,
                form_index=0,
                form_name="Anchor",
                element=0,
                passive_tags=PassiveTags(slot1_viable=True, has_guard=True, dr_base_percent=50),
            ),
        )
        frail_unit = DokkanCard(
            id=2010,
            name="Frail Glass Unit",
            element=0,
            base_form=CardForm(
                form_id=2010,
                form_index=0,
                form_name="Frail",
                element=0,
                passive_tags=PassiveTags(slot1_viable=False, has_guard=False, dr_base_percent=0),
            ),
        )

        delta_s1, count_s1, _ = solver.evaluate_boss_gimmicks(s1_unit, boss)
        delta_frail, _, pen_frail = solver.evaluate_boss_gimmicks(frail_unit, boss)

        assert delta_s1 == 15.0
        assert any("Slot locking immunity" in c for c in count_s1)

        assert delta_frail == -15.0
        assert any("Slot Lock Vulnerability" in p for p in pen_frail)

    def test_solver_multi_battle_stacking_reset_penalty_and_turn1_bonus(
        self, solver: DokkanConstraintSolver
    ) -> None:
        stage = BossStage(
            stage_id=17280164,
            event_id=1728,
            stage_name="Pure Saiyans",
            event_name="Union Master",
            total_battles=3,
            phases=[
                BossPhase(
                    phase_index=1, battle_index=1, round_index=1, is_new_battle=True, element=21
                ),
                BossPhase(
                    phase_index=2, battle_index=2, round_index=1, is_new_battle=True, element=20
                ),
                BossPhase(
                    phase_index=3, battle_index=3, round_index=1, is_new_battle=True, element=10
                ),
                BossPhase(
                    phase_index=4, battle_index=3, round_index=2, is_new_battle=False, element=10
                ),
            ],
        )

        # Pure slow stacker without guard or DR
        stacker_card = DokkanCard(
            id=7001,
            name="Fragile Slow Stacker",
            element=1,  # TEQ
            super_attack="Raises DEF and causes supreme damage",
            passive_skill="ATK & DEF +100%",
        )
        assert stacker_card.has_stacking_def is True
        assert stacker_card.has_guard is False
        assert stacker_card.damage_reduction_percent == 0

        delta_s, _, pen_s = solver.evaluate_boss_gimmicks(stacker_card, stage)
        assert any("Stacking Reset Vulnerability" in p for p in pen_s)
        assert delta_s <= -15.0

        # Turn 1 Immediate Tank (Guard or 50% DR)
        tank_card = DokkanCard(
            id=7002,
            name="Turn 1 Solid Tank",
            element=1,  # TEQ
            passive_skill="Guards all attacks; reduces damage received by 50%",
        )
        assert tank_card.has_guard is True
        assert tank_card.damage_reduction_percent == 50

        delta_t, count_t, _ = solver.evaluate_boss_gimmicks(tank_card, stage)
        assert any("Multi-Battle Reliability" in c for c in count_t)
        assert delta_t >= 15.0

    def test_defensive_expiration_and_dodge_cancellation_awareness(
        self, solver: DokkanConstraintSolver
    ) -> None:
        stage = BossStage(
            stage_id=17280164,
            event_id=1728,
            stage_name="Pure Saiyans",
            event_name="Union Master",
            total_battles=3,
            phases=[
                BossPhase(
                    phase_index=1, battle_index=1, round_index=1, is_new_battle=True, element=21
                ),
                BossPhase(
                    phase_index=2, battle_index=2, round_index=1, is_new_battle=True, element=20
                ),
                BossPhase(
                    phase_index=3, battle_index=3, round_index=1, is_new_battle=True, element=10
                ),
                BossPhase(
                    phase_index=4,
                    battle_index=3,
                    round_index=2,
                    is_new_battle=False,
                    element=10,
                    cancels_dodge=True,
                ),
            ],
        )

        # Unit with intro guard (6 turns) and high dodge (70%) but no permanent guard/DR
        god_goku = DokkanCard(
            id=1034461,
            name="Super Saiyan God Goku",
            element=4,  # PHY
            passive_skill="Guards all attacks for 6 turns from start of turn; great chance of evading enemy attacks",
            categories=["Pure Saiyans"],
            category_ids=[17],
        )

        # 1. When evaluated against boss that cancels dodge in late phase:
        # Dodge is neutralized, guard expires in multi-battle stage -> NOT Slot 1 viable!
        assert solver.is_slot1_viable(god_goku, boss_stage=stage) is False

        # 2. Solver evaluates severe glass cannon / guard expiration penalties
        delta, _, penalties = solver.evaluate_boss_gimmicks(god_goku, stage)
        assert delta < 0.0
        assert any("Cancels Dodge" in p for p in penalties)
        assert any("Guard Expiration" in p for p in penalties)

    def test_multi_enemy_and_rainbow_phase_gimmicks(
        self, solver: DokkanConstraintSolver
    ) -> None:
        # Create a stage having a 5-enemy rainbow phase lacking ATK debuff immunity
        rainbow_enemies = [
            BossEnemy(card_id=901, name="Ginyu (AGL)", element=20, type_name="Extreme AGL"),
            BossEnemy(card_id=902, name="Guldo (TEQ)", element=21, type_name="Extreme TEQ"),
            BossEnemy(card_id=903, name="Jeice (INT)", element=22, type_name="Extreme INT"),
            BossEnemy(card_id=904, name="Burter (STR)", element=23, type_name="Extreme STR"),
            BossEnemy(card_id=905, name="Recoome (PHY)", element=24, type_name="Extreme PHY"),
        ]
        multi_rainbow_stage = BossStage(
            stage_id=999,
            event_id=99,
            stage_name="Ginyu Force SBR",
            event_name="Super Battle Road",
            phases=[
                BossPhase(
                    phase_index=1,
                    element=20,
                    bosses=rainbow_enemies,
                    nullifies_atk_down=False,
                )
            ],
        )

        assert multi_rainbow_stage.phases[0].enemy_count == 5
        assert multi_rainbow_stage.phases[0].is_multi_enemy is True
        assert multi_rainbow_stage.phases[0].is_rainbow is True

        # 1. AoE Specialist with Unconditional Guard
        aoe_guard_card = DokkanCard(
            id=8001,
            name="AoE Tank",
            element=1,
            super_attack="Causes colossal damage to all enemies",
            passive_skill="Guards all attacks",
        )
        assert aoe_guard_card.has_aoe is True
        assert aoe_guard_card.is_guard_unconditional is True

        delta_aoe, counters_aoe, _ = solver.evaluate_boss_gimmicks(aoe_guard_card, multi_rainbow_stage)
        # AoE (+25.0) + Omni-Guard (+15.0) = +40.0
        assert delta_aoe == pytest.approx(40.0)
        assert any("AoE Specialist" in c for c in counters_aoe)
        assert any("Omni-Guard/High-DR" in c for c in counters_aoe)

        # 2. Debuff Specialist with High DR (>= 50%)
        debuff_dr_card = DokkanCard(
            id=8002,
            name="Debuffer Tank",
            element=0,
            super_attack="Greatly lowers ATK and causes supreme damage",
            passive_skill="Reduces damage received by 60%",
        )
        assert debuff_dr_card.lowers_enemy_atk is True
        assert debuff_dr_card.damage_reduction_percent == 60

        delta_debuff, counters_debuff, _ = solver.evaluate_boss_gimmicks(debuff_dr_card, multi_rainbow_stage)
        # Debuff (+15.0) + High DR (+15.0) = +30.0
        assert delta_debuff == pytest.approx(30.0)
        assert any("Debuff Specialist" in c for c in counters_debuff)
        assert any("Omni-Guard/High-DR" in c for c in counters_debuff)

        # 3. Fragile Single-Target Unit (lacks Guard, DR < 50%, no AoE, no debuff)
        fragile_card = DokkanCard(
            id=8003,
            name="Fragile Glass Cannon",
            element=2,
            super_attack="Causes immense damage to enemy",
            passive_skill="ATK +150% and DEF +50%",
        )
        assert fragile_card.has_aoe is False
        assert fragile_card.lowers_enemy_atk is False
        assert fragile_card.is_guard_unconditional is False
        assert fragile_card.damage_reduction_percent < 50

        delta_fragile, _, penalties_fragile = solver.evaluate_boss_gimmicks(fragile_card, multi_rainbow_stage)
        # Penalty for Rainbow Phase Vulnerability (-15.0)
        assert delta_fragile == pytest.approx(-15.0)
        assert any("Rainbow Phase Vulnerability" in p for p in penalties_fragile)


class TestSameNameBaseFormPenalty:
    """Validates the mathematical same-name penalty for base form (form_index: 0)."""

    def test_same_name_penalty_applied(self) -> None:
        solver = DokkanConstraintSolver()
        leader = DokkanCard(
            id=3001,
            name="LR Beast Gohan",
            element=3,
            category_ids=[10],
            leader_spec=LeaderSkillSpec(main_category_ids=[10], base_boost_pct=170),
            base_form=CardForm(form_id=3001, form_index=0, form_name="Beast Gohan", element=3),
        )
        # Duplicate base form name
        candidate_same_name = DokkanCard(
            id=3002,
            name="UR Beast Gohan",
            element=3,
            category_ids=[10],
            base_form=CardForm(form_id=3002, form_index=0, form_name="Beast Gohan", element=3),
        )

        # Evaluated alone vs evaluated with team containing the base form
        ev_solo = solver.evaluate_card(candidate_same_name, leader, selected_team=[])
        ev_team = solver.evaluate_card(candidate_same_name, leader, selected_team=[leader])

        # Team evaluation should have penalty subtracted
        assert ev_team.score == round(ev_solo.score - SAME_NAME_BASE_PENALTY, 2)
        assert any("Same-Name Base Form Penalty" in p for p in ev_team.penalty_points)

    def test_different_names_no_penalty(self) -> None:
        solver = DokkanConstraintSolver()
        leader = DokkanCard(
            id=3003,
            name="LR Vegito Blue",
            element=0,
            category_ids=[10],
            leader_spec=LeaderSkillSpec(main_category_ids=[10], base_boost_pct=170),
            base_form=CardForm(
                form_id=3003, form_index=0, form_name="Vegito Blue (Base)", element=0
            ),
        )
        candidate_diff = DokkanCard(
            id=3004,
            name="Super Gogeta",
            element=3,
            category_ids=[10],
            base_form=CardForm(
                form_id=3004, form_index=0, form_name="Super Gogeta (Base)", element=3
            ),
        )
        ev = solver.evaluate_card(candidate_diff, leader, selected_team=[leader])
        assert not any("Same-Name Base Form Penalty" in p for p in ev.penalty_points)

    def test_get_base_form_name_normalizer(self) -> None:
        card1 = DokkanCard(
            id=3005,
            name="Super Saiyan Goku",
            base_form=CardForm(form_name="Super Saiyan Goku (Base)", form_index=0),
        )
        card2 = DokkanCard(
            id=3006,
            name="Super Saiyan Goku",
            base_form=CardForm(form_name="super saiyan goku", form_index=0),
        )
        assert get_base_form_name(card1) == "super saiyan goku"
        assert get_base_form_name(card2) == "super saiyan goku"
        assert get_base_form_name(card1) == get_base_form_name(card2)


class TestLateGameScaling:
    """Validates late game scaling for Turn 4+ transformations and permanent DEF stacking."""

    def test_permanent_def_stacking_bonus(self) -> None:
        solver = DokkanConstraintSolver()
        leader = DokkanCard(
            id=4001,
            name="Leader",
            category_ids=[10],
            leader_spec=LeaderSkillSpec(main_category_ids=[10], base_boost_pct=170),
        )
        stacker = DokkanCard(
            id=4002,
            name="DEF Stacker",
            category_ids=[10],
            base_form=CardForm(
                form_id=4002,
                form_index=0,
                form_name="Stacker",
                sa_tags=SATags(stacks_def=True),
            ),
        )
        non_stacker = DokkanCard(
            id=4003,
            name="Non Stacker",
            category_ids=[10],
            base_form=CardForm(
                form_id=4003,
                form_index=0,
                form_name="Non Stacker",
                sa_tags=SATags(stacks_def=False),
            ),
        )

        ev_stack = solver.evaluate_card(stacker, leader)
        ev_non = solver.evaluate_card(non_stacker, leader)

        assert ev_stack.score > ev_non.score
        assert any("Permanent DEF stacking" in c for c in ev_stack.counter_points)

    def test_late_game_transformation_scaling(self) -> None:
        solver = DokkanConstraintSolver()
        leader = DokkanCard(
            id=4004,
            name="Leader",
            category_ids=[10],
            leader_spec=LeaderSkillSpec(main_category_ids=[10], base_boost_pct=170),
        )
        transforming_card = DokkanCard(
            id=4005,
            name="Transforming Warrior",
            category_ids=[10],
            base_form=CardForm(form_id=4005, form_index=0, form_name="Base Form", min_turn=1),
            transformations=[
                CardForm(
                    form_id=40051,
                    form_index=1,
                    form_name="Final Ascended State",
                    min_turn=4,
                    passive_tags=PassiveTags(has_guard=True, dr_base_percent=50, has_revive=True),
                    sa_tags=SATags(stacks_def=True),
                )
            ],
        )

        ev = solver.evaluate_card(transforming_card, leader)
        assert any("Final Ascended State" in c and "Turn 4+" in c for c in ev.counter_points)


class TestFullSolverIntegration:
    """Validates complete solve() constraints: uniqueness, slot 1 count, shortlist generation."""

    @pytest.fixture
    def full_pool(self) -> list[DokkanCard]:
        spec = LeaderSkillSpec(
            main_category_ids=[10],
            extra_category_ids=[20],
            base_boost_pct=170,
            extra_boost_pct=30,
        )
        cards: list[DokkanCard] = []

        # Card 1: Prime Leader (Slot 1 tank, 200% lead)
        cards.append(
            DokkanCard(
                id=5001,
                name="Prime Leader",
                element=0,
                rarity=5,
                category_ids=[10, 20],
                leader_spec=spec,
                base_form=CardForm(
                    form_id=5001,
                    form_index=0,
                    form_name="Prime Leader (Base)",
                    element=0,
                    passive_tags=PassiveTags(slot1_viable=True, has_guard=True, dr_base_percent=50),
                    sa_tags=SATags(stacks_def=True),
                ),
            )
        )

        # Card 2: Second Slot 1 Tank
        cards.append(
            DokkanCard(
                id=5002,
                name="Second Slot 1 Tank",
                element=3,
                rarity=5,
                category_ids=[10, 20],
                leader_spec=spec,
                base_form=CardForm(
                    form_id=5002,
                    form_index=0,
                    form_name="Slot 1 Tank (Base)",
                    element=3,
                    passive_tags=PassiveTags(slot1_viable=True, has_guard=True, dr_base_percent=60),
                ),
            )
        )

        # Card 3: Third Slot 1 Tank
        cards.append(
            DokkanCard(
                id=5003,
                name="Third Slot 1 Tank",
                element=1,
                rarity=4,
                category_ids=[10],
                base_form=CardForm(
                    form_id=5003,
                    form_index=0,
                    form_name="Third Tank (Base)",
                    element=1,
                    passive_tags=PassiveTags(slot1_viable=True, has_guard=True, dr_base_percent=40),
                ),
            )
        )

        # Cards 4-10: Sub-units (Floaters / Damage dealers)
        for i in range(4, 11):
            cards.append(
                DokkanCard(
                    id=5000 + i,
                    name=f"Sub Unit {i}",
                    element=i % 5,
                    rarity=4,
                    category_ids=[10, 20] if i % 2 == 0 else [10],
                    base_form=CardForm(
                        form_id=5000 + i,
                        form_index=0,
                        form_name=f"Sub Unit {i} (Base)",
                        element=i % 5,
                        passive_tags=PassiveTags(slot1_viable=False, dr_base_percent=20),
                        sa_tags=SATags(raise_def_turns=1),
                    ),
                )
            )

        return cards

    def test_solve_produces_six_distinct_cards(self, full_pool: list[DokkanCard]) -> None:
        solver = DokkanConstraintSolver()
        result = solver.solve(full_pool)

        # Must have exactly 6 cards
        assert len(result.team_cards) == 6
        # Must all be unique
        unique_ids = {c.id for c in result.team_cards}
        assert len(unique_ids) == 6
        assert result.leader.id == result.team_cards[0].id

    def test_solve_enforces_slot1_survival_constraint(self, full_pool: list[DokkanCard]) -> None:
        solver = DokkanConstraintSolver()
        result = solver.solve(full_pool)

        # Hard constraint: >= 2 base slot 1 viable units
        assert result.base_slot1_count >= 2
        actual_s1 = sum(1 for c in result.team_cards if solver.is_slot1_viable(c))
        assert actual_s1 == result.base_slot1_count
        assert actual_s1 >= 2

    def test_shortlist_extraction_top_5(self, full_pool: list[DokkanCard]) -> None:
        solver = DokkanConstraintSolver()
        result = solver.solve(full_pool)

        # Shortlist has at most 5 runner-ups
        assert len(result.shortlist) <= 5
        assert len(result.shortlist) > 0

        # Shortlist cards MUST NOT be in the main team
        team_ids = {c.id for c in result.team_cards}
        for cand in result.shortlist:
            assert cand.card.id not in team_ids

        # Shortlist must be sorted descending by score
        scores = [c.score for c in result.shortlist]
        assert scores == sorted(scores, reverse=True)

    def test_forced_leader_option(self, full_pool: list[DokkanCard]) -> None:
        solver = DokkanConstraintSolver()
        forced = full_pool[1]  # Card 5002
        result = solver.solve(full_pool, forced_leader=forced)

        assert result.leader.id == forced.id
        assert result.team_cards[0].id == forced.id
        assert len(result.team_cards) == 6

    def test_pool_too_small_raises_error(self) -> None:
        solver = DokkanConstraintSolver()
        small_pool = [DokkanCard(id=i, name=f"Card {i}", category_ids=[10]) for i in range(5)]
        with pytest.raises(ValueError, match="Need at least 6 distinct cards"):
            solver.solve(small_pool)

    def test_duplicate_cards_in_pool_deduplicated(self, full_pool: list[DokkanCard]) -> None:
        solver = DokkanConstraintSolver()
        # Add duplicate card with identical ID
        dup_pool = list(full_pool) + [full_pool[0]]
        result = solver.solve(dup_pool)
        assert len(result.team_cards) == 6
        assert len({c.id for c in result.team_cards}) == 6

    def test_zero_shared_categories_rejected(self, full_pool: list[DokkanCard]) -> None:
        solver = DokkanConstraintSolver()
        leader = full_pool[0]
        unrelated = DokkanCard(
            id=9999,
            name="Unrelated Fighter",
            category_ids=[999],  # Does not match leader main category [10]
        )
        ev = solver.evaluate_card(unrelated, leader)
        assert ev.score == -1000.0
        assert any("Zero shared categories" in p for p in ev.penalty_points)

    def test_insufficient_leader_boost_rejected(self) -> None:
        solver = DokkanConstraintSolver()
        leader = DokkanCard(
            id=1001,
            name="Weak Leader",
            category_ids=[10],
            leader_spec=LeaderSkillSpec(main_category_ids=[10], base_boost_pct=130),
        )
        sub = DokkanCard(id=1002, name="Sub", category_ids=[10])
        ev = solver.evaluate_card(sub, leader)
        assert ev.score == -1000.0

    def test_forced_leader_without_leader_spec_raises(self) -> None:
        solver = DokkanConstraintSolver()
        pool = [DokkanCard(id=i, name=f"Card {i}", category_ids=[10]) for i in range(1, 8)]
        invalid_lead = pool[0]
        invalid_lead.leader_spec = None
        invalid_lead.leader_skill = ""
        with pytest.raises(ValueError, match="no valid category leader skill"):
            solver.solve(pool, forced_leader=invalid_lead)

    def test_leader_selection_maximizes_200_percent_members(self) -> None:
        solver = DokkanConstraintSolver()
        # Leader A: 170% flat, no extra category (all 5 subs get 170%)
        lead_a = DokkanCard(
            id=6001,
            name="Flat 170 Lead",
            category_ids=[10],
            categories=["Realm of Gods"],
            leader_spec=LeaderSkillSpec(main_category_ids=[10], base_boost_pct=170),
        )
        # Leader B: 170% base + 50% extra (total 220%), has 5 subs with both main & extra
        lead_b = DokkanCard(
            id=1030431,
            name="Super Saiyan Goku + Super Saiyan Vegeta (Angel)",
            category_ids=[17, 89],
            categories=["Pure Saiyans", "Earth-Bred Fighters"],
            leader_spec=LeaderSkillSpec(
                main_category_ids=[17],
                extra_category_ids=[89],
                base_boost_pct=170,
                extra_boost_pct=50,
            ),
        )
        subs = [
            DokkanCard(
                id=6100 + i,
                name=f"Unit {i}",
                category_ids=[10, 17, 89],
                categories=["Realm of Gods", "Pure Saiyans", "Earth-Bred Fighters"],
            )
            for i in range(1, 7)
        ]
        pool = [lead_a, lead_b] + subs
        result = solver.solve(pool)
        assert result.leader.id == 1030431

    def test_format_team_summary_table_main_and_extra_categories(self) -> None:
        leader = DokkanCard(
            id=1030431,
            name="Super Saiyan Goku + Super Saiyan Vegeta (Angel)",
            element_name="Super TEQ",
            category_ids=[17, 85, 95, 10, 89],
            categories=[
                "Pure Saiyans",
                "Fused Fighters",
                "Earth-Protecting Heroes",
                "Potara",
                "Earth-Bred Fighters",
            ],
            leader_spec=LeaderSkillSpec(
                main_category_ids=[17, 85, 95],
                extra_category_ids=[10, 89],
                base_boost_pct=170,
                extra_boost_pct=50,
            ),
        )
        full_220_card = DokkanCard(
            id=1024861,
            name="Super Saiyan Goku",
            element_name="Super TEQ",
            category_ids=[17, 89],
            categories=["Pure Saiyans", "Earth-Bred Fighters"],
        )
        only_170_card = DokkanCard(
            id=1022381,
            name="Super Saiyan God Goku & Vegeta",
            element_name="Super TEQ",
            category_ids=[17],
            categories=["Pure Saiyans"],
        )
        team = [leader, full_220_card, only_170_card] + [
            DokkanCard(
                id=7000 + i,
                name=f"Filler {i}",
                element_name="Super TEQ",
                category_ids=[17],
                categories=["Pure Saiyans"],
            )
            for i in range(3)
        ]
        table = format_team_summary_table(team)
        assert "Main: [Pure Saiyans] | Extra: [Earth-Bred Fighters]" in table
        assert "Extra: Nessuna" in table

    def test_candidate_evaluation_reasoning_property(self) -> None:
        card = DokkanCard(
            id=999, name="Test Card", categories=["Pure Saiyans", "Hybrid Saiyans", "Goku's Family"]
        )
        # Case 1: counter_points populated
        eval1 = CandidateEvaluation(
            card=card,
            score=95.0,
            lead_boost_pct=200.0,
            base_slot1_viable=True,
            counter_points=["Guard against all attacks", "High DR 50%"],
        )
        assert eval1.reasoning == "Guard against all attacks; High DR 50%"

        # Case 2: base_slot1_viable without counter_points
        eval2 = CandidateEvaluation(
            card=card,
            score=80.0,
            lead_boost_pct=170.0,
            base_slot1_viable=True,
        )
        assert eval2.reasoning == "Slot 1 Tank viable"

        # Case 3: fallback to categories
        eval3 = CandidateEvaluation(
            card=card,
            score=70.0,
            lead_boost_pct=170.0,
            base_slot1_viable=False,
        )
        assert eval3.reasoning == "Pure Saiyans, Hybrid Saiyans, Goku's Family"

    def test_tiered_leader_search_hierarchy(self) -> None:
        solver = DokkanConstraintSolver()
        # Lead Tier 1 (220%): Realm of Gods (id=10) + RoG extra (+50%)
        lead_t1 = DokkanCard(
            id=8001,
            name="Tier 1 Lead (220%)",
            category_ids=[10],
            categories=["Realm of Gods"],
            leader_spec=LeaderSkillSpec(
                main_category_ids=[10],
                extra_category_ids=[10],
                base_boost_pct=170,
                extra_boost_pct=50,
            ),
        )
        # Lead Tier 2 (200%): Pure Saiyans (id=17) + PS extra (+30%)
        lead_t2 = DokkanCard(
            id=8002,
            name="Tier 2 Lead (200%)",
            category_ids=[17],
            categories=["Pure Saiyans"],
            leader_spec=LeaderSkillSpec(
                main_category_ids=[17],
                extra_category_ids=[17],
                base_boost_pct=170,
                extra_boost_pct=30,
            ),
        )
        # 5 subs compatible with both Realm of Gods (10) and Pure Saiyans (17)
        subs = [
            DokkanCard(
                id=8100 + i,
                name=f"Dual Sub {i}",
                category_ids=[10, 17],
                categories=["Realm of Gods", "Pure Saiyans"],
            )
            for i in range(1, 6)
        ]
        # Even if Lead T2 has favorable kit or type advantage, T1 MUST be chosen
        boss = BossStage(
            stage_id=1,
            event_id=1,
            stage_name="Stage",
            event_name="Event",
            phases=[BossPhase(phase_index=1, element=3)],  # STR
        )
        lead_t2.element = 0  # AGL (type advantage vs STR)
        lead_t1.element = 1  # TEQ (neutral/disadvantage)

        res = solver.solve([lead_t1, lead_t2] + subs, boss_stage=boss)
        assert res.leader.id == 8001

    def test_tiered_leader_search_fallback_when_tier_has_insufficient_subs(self) -> None:
        solver = DokkanConstraintSolver()
        # Lead Tier 1 (220%) has only 2 compatible subs
        lead_t1 = DokkanCard(
            id=8003,
            name="Tier 1 Lead (220%)",
            category_ids=[99],
            categories=["Universe 6"],
            leader_spec=LeaderSkillSpec(
                main_category_ids=[99],
                base_boost_pct=170,
                extra_boost_pct=50,
            ),
        )
        # Lead Tier 2 (200%) has 5 compatible subs
        lead_t2 = DokkanCard(
            id=8004,
            name="Tier 2 Lead (200%)",
            category_ids=[17],
            categories=["Pure Saiyans"],
            leader_spec=LeaderSkillSpec(
                main_category_ids=[17],
                base_boost_pct=170,
                extra_boost_pct=30,
            ),
        )
        subs_t1 = [
            DokkanCard(id=8201, name="U6 Sub 1", category_ids=[99], categories=["Universe 6"]),
            DokkanCard(id=8202, name="U6 Sub 2", category_ids=[99], categories=["Universe 6"]),
        ]
        subs_t2 = [
            DokkanCard(id=8300 + i, name=f"PS Sub {i}", category_ids=[17], categories=["Pure Saiyans"])
            for i in range(1, 6)
        ]
        res = solver.solve([lead_t1, lead_t2] + subs_t1 + subs_t2)
        assert res.leader.id == 8004

    def test_tiered_leader_mission_category_priority_within_tier(self) -> None:
        from dokkan_eza_link_farmer.ai.mission_solver import MissionBatch

        solver = DokkanConstraintSolver()
        # Both leaders in Tier 2 (200%)
        # Lead 1: Pure Saiyans (17)
        lead_ps = DokkanCard(
            id=8005,
            name="PS 200 Lead",
            category_ids=[17],
            categories=["Pure Saiyans"],
            leader_spec=LeaderSkillSpec(
                main_category_ids=[17],
                base_boost_pct=170,
                extra_boost_pct=30,
            ),
        )
        # Lead 2: Hybrid Saiyans (18)
        lead_hs = DokkanCard(
            id=8006,
            name="HS 200 Lead",
            category_ids=[18],
            categories=["Hybrid Saiyans"],
            leader_spec=LeaderSkillSpec(
                main_category_ids=[18],
                base_boost_pct=170,
                extra_boost_pct=30,
            ),
        )
        subs = [
            DokkanCard(
                id=8400 + i,
                name=f"Dual Sub {i}",
                category_ids=[17, 18],
                categories=["Pure Saiyans", "Hybrid Saiyans"],
            )
            for i in range(1, 6)
        ]
        # Mission requires Hybrid Saiyans
        mission_batch = MissionBatch(
            missions=[],
            required_categories=[(3, "Hybrid Saiyans")],
        )
        res = solver.solve([lead_ps, lead_hs] + subs, mission_batch=mission_batch)
        assert res.leader.id == 8006

    def test_tiered_leader_mission_main_vs_extra_vs_personal_fallback(self) -> None:
        from dokkan_eza_link_farmer.ai.mission_solver import MissionBatch

        solver = DokkanConstraintSolver()
        # Lead 1: Covers "Realm of Gods" (ID 22) in main_category_ids
        lead_main = DokkanCard(
            id=9001,
            name="Main Lead RoG",
            category_ids=[22],
            categories=["Realm of Gods"],
            leader_spec=LeaderSkillSpec(
                main_category_ids=[22],
                base_boost_pct=170,
                extra_boost_pct=30,
            ),
        )
        # Lead 2: Covers "Realm of Gods" (ID 22) only in extra_category_ids
        lead_extra = DokkanCard(
            id=9002,
            name="Extra Lead RoG",
            category_ids=[17, 22],
            categories=["Pure Saiyans", "Realm of Gods"],
            leader_spec=LeaderSkillSpec(
                main_category_ids=[17],
                extra_category_ids=[22],
                base_boost_pct=170,
                extra_boost_pct=30,
            ),
        )
        # Lead 3: Has "Realm of Gods" only in personal categories (c.categories), leader skill is Pure Saiyans only
        lead_personal = DokkanCard(
            id=9003,
            name="Personal Lead RoG",
            category_ids=[17, 22],
            categories=["Pure Saiyans", "Realm of Gods"],
            leader_spec=LeaderSkillSpec(
                main_category_ids=[17],
                base_boost_pct=170,
                extra_boost_pct=30,
            ),
        )
        subs = [
            DokkanCard(
                id=9100 + i,
                name=f"Sub {i}",
                category_ids=[17, 22],
                categories=["Pure Saiyans", "Realm of Gods"],
            )
            for i in range(1, 6)
        ]
        # 1. When main vs extra are present, main takes precedence
        mb = MissionBatch(missions=[], required_categories=[(3, "Realm of Gods")])
        res1 = solver.solve([lead_main, lead_extra, lead_personal] + subs, mission_batch=mb)
        assert res1.leader.id == 9001

        # 2. When only extra and personal are present, extra takes precedence over personal
        res2 = solver.solve([lead_extra, lead_personal] + subs, mission_batch=mb)
        assert res2.leader.id == 9002

        # 3. Fallback: when NO leader in tier has the category in leader skill, fallback on personal category
        # Mission requires niche category "Golden Warriors" which none of the leader specs cover
        for c in [lead_personal] + subs:
            c.categories.append("Golden Warriors")
        mb_niche = MissionBatch(missions=[], required_categories=[(3, "Golden Warriors")])
        res3 = solver.solve([lead_personal, lead_extra] + subs, mission_batch=mb_niche)
        # lead_personal has Golden Warriors in personal categories, while lead_extra does not
        assert res3.leader.id == 9003

    def test_card_1030431_no_arbitrary_priority_over_other_categories(self) -> None:
        solver = DokkanConstraintSolver()
        # Card 1030431 in Tier 2 (200%) vs Rival in Tier 2 (200%) with higher kit/type advantage
        card_1030431 = DokkanCard(
            id=1030431,
            name="Super Saiyan Goku + Super Saiyan Vegeta (Angel)",
            category_ids=[17],
            categories=["Pure Saiyans"],
            leader_spec=LeaderSkillSpec(
                main_category_ids=[17],
                base_boost_pct=170,
                extra_boost_pct=30,
            ),
        )
        rival_lead = DokkanCard(
            id=99999,
            name="Rival Leader",
            category_ids=[17],
            categories=["Pure Saiyans"],
            leader_spec=LeaderSkillSpec(
                main_category_ids=[17],
                base_boost_pct=170,
                extra_boost_pct=30,
            ),
        )
        subs = [
            DokkanCard(id=8500 + i, name=f"Sub {i}", category_ids=[17], categories=["Pure Saiyans"])
            for i in range(1, 6)
        ]
        boss = BossStage(
            stage_id=1,
            event_id=1,
            stage_name="Stage",
            event_name="Event",
            phases=[BossPhase(phase_index=1, element=3)],  # STR
        )
        card_1030431.element = 1  # TEQ (disadvantage)
        rival_lead.element = 0    # AGL (advantage)

        res = solver.solve([card_1030431, rival_lead] + subs, boss_stage=boss)
        # Rival lead has type advantage (+10.0 score) and 1030431 no longer gets +25.0 free bonus
        assert res.leader.id == 99999

    def test_parse_category_leader_payloads(self) -> None:
        client = DokkanDBClient()

        # 1. Efficacy 82 with 220% boost and extra 30% boost, ki 5
        item_220 = {
            "id": 1034201,
            "name": "Super Saiyan 3 Goku",
            "leader_skills": [
                {
                    "efficacy_type": 5,
                    "efficacy_values": "[3,0,0]",
                    "sub_target_types": [{"target_value": 9}],
                },
                {
                    "efficacy_type": 82,
                    "efficacy_values": '"[31,220,0]"',
                    "sub_target_types": [{"target_value": 9}],
                },
                {
                    "efficacy_type": 82,
                    "efficacy_values": "[64,30,0]",
                    "sub_target_types": [{"target_value": 9}],
                },
            ],
        }
        parsed_220 = client.parse_category_leader(item_220, category_id=9)
        assert parsed_220["card_id"] == 1034201
        assert parsed_220["base_boost_pct"] == 220.0
        assert parsed_220["extra_boost_pct"] == 30.0
        assert parsed_220["total_boost_pct"] == 250.0
        assert parsed_220["hp_stat_pct"] == 220.0
        assert parsed_220["ki"] == 3
        assert parsed_220["is_main_leader"] is True
        assert parsed_220["is_extra_leader"] is True

        # 2. Efficacy 104 with [200, 170, 170] and ki 83
        item_104 = {
            "id": 1034151,
            "name": "Buu (Kid)",
            "leader_skills": [
                {
                    "efficacy_type": 83,
                    "efficacy_values": "[31,4,0]",
                    "sub_target_types": [{"target_value": 9}],
                },
                {
                    "efficacy_type": 104,
                    "efficacy_values": "[200,170,170]",
                    "sub_target_types": [{"target_value": 9}],
                },
            ],
        }
        parsed_104 = client.parse_category_leader(item_104, category_id=9)
        assert parsed_104["card_id"] == 1034151
        assert parsed_104["base_boost_pct"] == 170.0
        assert parsed_104["hp_stat_pct"] == 200.0
        assert parsed_104["ki"] == 4
        assert parsed_104["is_main_leader"] is True
        assert parsed_104["is_extra_leader"] is False

    def test_solver_integration_dokkandb_category_leaders(self) -> None:
        from tests.harness.fake_dokkandb import FakeDokkanDBClient

        fake_dokkan = FakeDokkanDBClient()
        fake_dokkan.categories.append({"id": 9, "name": "Majin Buu Saga"})
        fake_dokkan.get_category_leaders = lambda _cat_id, **_kwargs: [  # type: ignore
            {
                "id": 1034201,
                "name": "Super Saiyan 3 Goku",
                "leader_skills": [
                    {
                        "efficacy_type": 5,
                        "efficacy_values": "[3,0,0]",
                        "sub_target_types": [{"target_value": 9}],
                    },
                    {
                        "efficacy_type": 82,
                        "efficacy_values": "[31,220,0]",
                        "sub_target_types": [{"target_value": 9}],
                    },
                ],
            },
            {
                "id": 1020000,
                "name": "Old 170 Leader",
                "leader_skills": [
                    {
                        "efficacy_type": 5,
                        "efficacy_values": "[3,0,0]",
                        "sub_target_types": [{"target_value": 9}],
                    },
                    {
                        "efficacy_type": 82,
                        "efficacy_values": "[31,170,0]",
                        "sub_target_types": [{"target_value": 9}],
                    },
                ],
            },
        ]

        solver = DokkanConstraintSolver(dokkandb=fake_dokkan)

        lead_220 = DokkanCard(
            id=1034201,
            name="Super Saiyan 3 Goku",
            category_ids=[9],
            categories=["Majin Buu Saga"],
            leader_spec=LeaderSkillSpec(main_category_ids=[9], base_boost_pct=170),  # Will be enriched to 220%
        )
        lead_170 = DokkanCard(
            id=1020000,
            name="Old 170 Leader",
            category_ids=[9],
            categories=["Majin Buu Saga"],
            leader_spec=LeaderSkillSpec(main_category_ids=[9], base_boost_pct=170),
        )
        subs = [
            DokkanCard(id=5500 + i, name=f"Sub {i}", category_ids=[9], categories=["Majin Buu Saga"])
            for i in range(1, 6)
        ]

        mb = MissionBatch(missions=[], required_categories=[(6, "Majin Buu Saga")])
        res = solver.solve([lead_170, lead_220] + subs, mission_batch=mb)

        # SS3 Goku ID 1034201 should be enriched to 220%, chosen as Tier 1 leader over 170% leader
        assert res.leader.id == 1034201
        assert res.leader.leader_spec is not None and res.leader.leader_spec.base_boost_pct == 220.0


    def test_solver_multi_category_official_leader_isolation(self) -> None:
        from tests.harness.fake_dokkandb import FakeDokkanDBClient

        fake_dokkan = FakeDokkanDBClient()
        fake_dokkan.categories.append({"id": 8, "name": "Cat A"})
        fake_dokkan.categories.append({"id": 19, "name": "Cat B"})

        def fake_get_category_leaders(cat_id: int, **_kwargs: Any) -> list[dict[str, Any]]:
            if cat_id == 8:
                return [
                    {
                        "id": 1,
                        "name": "Card 1 Leader A",
                        "leader_skills": [
                            {
                                "efficacy_type": 5,
                                "efficacy_values": "[3,0,0]",
                                "sub_target_types": [{"target_value": 8}],
                            },
                            {
                                "efficacy_type": 82,
                                "efficacy_values": "[31,170,0]",
                                "sub_target_types": [{"target_value": 8}],
                            },
                        ],
                    }
                ]
            if cat_id == 19:
                return [
                    {
                        "id": 2,
                        "name": "Card 2 Leader B",
                        "leader_skills": [
                            {
                                "efficacy_type": 5,
                                "efficacy_values": "[3,0,0]",
                                "sub_target_types": [{"target_value": 19}],
                            },
                            {
                                "efficacy_type": 82,
                                "efficacy_values": "[31,170,0]",
                                "sub_target_types": [{"target_value": 19}],
                            },
                        ],
                    }
                ]
            return []

        fake_dokkan.get_category_leaders = fake_get_category_leaders  # type: ignore

        solver = DokkanConstraintSolver(dokkandb=fake_dokkan)

        card1 = DokkanCard(
            id=1,
            name="Card 1 Leader A",
            category_ids=[8, 19],
            categories=["Cat A", "Cat B"],
        )
        card2 = DokkanCard(
            id=2,
            name="Card 2 Leader B",
            category_ids=[8, 19],
            categories=["Cat A", "Cat B"],
        )
        subs = [
            DokkanCard(
                id=100 + i,
                name=f"Sub {i}",
                category_ids=[8, 19],
                categories=["Cat A", "Cat B"],
            )
            for i in range(1, 6)
        ]

        mb = MissionBatch(
            missions=[],
            required_categories=[(3, "Cat A"), (3, "Cat B")],
        )

        _res = solver.solve([card1, card2] + subs, mission_batch=mb)

        assert card1.leader_spec is not None
        assert card1.leader_spec.main_category_ids == [8]
        assert 19 not in card1.leader_spec.main_category_ids

        assert card2.leader_spec is not None
        assert card2.leader_spec.main_category_ids == [19]
        assert 8 not in card2.leader_spec.main_category_ids


