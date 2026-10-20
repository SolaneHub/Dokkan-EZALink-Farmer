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

import pytest

from dokkan_eza_link_farmer.ai.models import (
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
            extra_category_ids=[30],      # Future Saga (30) -> 200%
            sub_elements_classes=[0],     # Super AGL fallback
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
            main_category_ids=[17, 85, 95],  # Pure Saiyans (17), Fused Fighters (85), Earth-Protecting Heroes (95)
            extra_category_ids=[10, 89],     # Potara (10), Earth-Bred Fighters (89)
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
            categories=["Majin Buu Saga", "Pure Saiyans", "Fused Fighters", "Earth-Protecting Heroes", "Potara", "Earth-Bred Fighters"],
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
            category_ids=[17, 89],  # Main Pure Saiyans (17) + Extra Earth-Bred Fighters (89) -> 220%
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
            DokkanCard(id=1012 + i, name=f"God {i}", category_ids=[10], categories=["Realm of Gods"])
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
        assert delta == 20.0
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
                passive_tags=PassiveTags(dodge_chance_percent=70, has_guard=False, dr_base_percent=0),
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
                passive_tags=PassiveTags(dodge_chance_percent=70, has_guard=True, dr_base_percent=40),
            ),
        )

        delta_unshielded, _, pen_unshielded = solver.evaluate_boss_gimmicks(unshielded_dodge, boss)
        delta_shielded, _, pen_shielded = solver.evaluate_boss_gimmicks(shielded_dodge, boss)

        # Unshielded receives dodge neutralization (-10.5) PLUS vulnerability penalty (-20) = -30.5
        assert delta_unshielded == pytest.approx(-30.5, abs=0.1)
        assert any("neutralized by Boss (Cancels Dodge)" in p for p in pen_unshielded)
        assert any("High vulnerability: relies on dodge but lacks Guard/DR" in p for p in pen_unshielded)

        # Shielded has dodge neutralized (-10.5) but does NOT suffer the extra -20 penalty
        assert delta_shielded == pytest.approx(-10.5, abs=0.1)
        assert not any("High vulnerability" in p for p in pen_shielded)

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
                passive_tags=PassiveTags(dodge_chance_percent=0, has_guard=False, dr_base_percent=0),
            ),
        )

        assert text_dodge_card.has_dodge is True
        assert text_dodge_card.base_form.passive_tags.dodge_chance_percent == 0

        delta, _, penalties = solver.evaluate_boss_gimmicks(text_dodge_card, boss)

        # Falls back to 100% dodge penalty (-15.0) plus high vulnerability (-20.0) = -35.0
        assert delta == pytest.approx(-35.0, abs=0.1)
        assert any("Dodge (100%) neutralized by Boss (Cancels Dodge)" in p for p in penalties)
        assert any("High vulnerability: relies on dodge but lacks Guard/DR" in p for p in penalties)

        # Also test auto-instantiated base form where passive_tags.dodge_chance_percent defaults to 0
        auto_card = DokkanCard(
            id=2100,
            name="Auto Form Dodge Unit",
            element=0,
            passive_skill="Great chance of evading enemy attacks",
        )
        delta_auto, _, pen_auto = solver.evaluate_boss_gimmicks(auto_card, boss)
        assert delta_auto == pytest.approx(-35.0, abs=0.1)
        assert any("Dodge (100%) neutralized by Boss (Cancels Dodge)" in p for p in pen_auto)
        assert any("High vulnerability: relies on dodge but lacks Guard/DR" in p for p in pen_auto)

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
            base_form=CardForm(form_id=3003, form_index=0, form_name="Vegito Blue (Base)", element=0),
        )
        candidate_diff = DokkanCard(
            id=3004,
            name="Super Gogeta",
            element=3,
            category_ids=[10],
            base_form=CardForm(form_id=3004, form_index=0, form_name="Super Gogeta (Base)", element=3),
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
        small_pool = [
            DokkanCard(id=i, name=f"Card {i}", category_ids=[10])
            for i in range(5)
        ]
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
        card = DokkanCard(id=999, name="Test Card", categories=["Pure Saiyans", "Hybrid Saiyans", "Goku's Family"])
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
