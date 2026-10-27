"""Unit tests validating pre-attack only defense mechanics (DR & Guard with Ki thresholds),
damage formula simulation for endgame normal attacks (Goten elimination), and transformation bridges.
"""

from __future__ import annotations

import pytest

from dokkan_eza_link_farmer.ai.card_models import (
    CardForm,
    DokkanCard,
    PassiveTags,
)
from dokkan_eza_link_farmer.ai.formatters import (
    format_team_summary_table,
    generate_deterministic_tactical_guide,
)
from dokkan_eza_link_farmer.ai.models import (
    BossPhase,
    BossStage,
    LeaderSkillSpec,
)
from dokkan_eza_link_farmer.ai.solver import (
    DokkanConstraintSolver,
)
from dokkan_eza_link_farmer.ai.synergy import (
    optimize_rotations_for_team,
)


@pytest.fixture
def ss3_goku_golden_fist() -> DokkanCard:
    """Card 1012721: SS3 Goku (Golden Fist).
    Passive: *Before attacking with 18 or more Ki* - Damage reduction rate 50% within the turn.
    """
    return DokkanCard(
        id=1012721,
        name="Super Saiyan 3 Goku (Golden Fist)",
        element=1,  # Super TEQ
        rarity=5,
        category_ids=[10, 20],
        categories=["Majin Buu Saga", "Pure Saiyans"],
        passive_skill=(
            "Ki +3 and ATK & DEF +150%; plus an additional ATK & DEF +50% when performing a Super Attack; "
            "*Before attacking with 18 or more Ki* - Damage reduction rate 50% within the turn"
        ),
        base_form=CardForm(
            form_id=1012721,
            form_index=0,
            form_name="SS3 Goku",
            element=1,
            passive_tags=PassiveTags(
                has_pre_attack_only_dr=True,
                pre_attack_dr_percent=50,
                pre_attack_dr_ki_req=18,
            ),
        ),
    )


@pytest.fixture
def goten_int() -> DokkanCard:
    """Card 1019461: Super Saiyan Goten (Kid).
    Passive: Reduces damage received by 50% (naked, no guard, ~200k DEF).
    """
    return DokkanCard(
        id=1019461,
        name="Super Saiyan Goten (Kid)",
        element=2,  # Super INT
        rarity=5,
        category_ids=[10],
        categories=["Majin Buu Saga"],
        passive_skill=(
            "ATK & DEF +150%; plus an additional ATK & DEF +50% when performing a Super Attack; "
            "reduces damage received by 50%"
        ),
        base_form=CardForm(
            form_id=1019461,
            form_index=0,
            form_name="Goten (Kid)",
            element=2,
            passive_tags=PassiveTags(
                dr_base_percent=50,
                has_guard=False,
            ),
        ),
    )


@pytest.fixture
def super_vegito_10th() -> DokkanCard:
    """Card 1030431: 10th Anniversary Goku & Vegeta (Angel) -> Super Vegito."""
    return DokkanCard(
        id=1030431,
        name="Super Saiyan Goku & Super Saiyan Vegeta (Angel)",
        element=1,  # Super TEQ
        rarity=5,
        category_ids=[10, 20],
        categories=["Majin Buu Saga", "Pure Saiyans"],
        passive_skill="Guards all attacks and reduces damage received by 50% for 3 turns from start of turn",
        base_form=CardForm(
            form_id=1030431,
            form_index=0,
            form_name="Goku & Vegeta (Angel)",
            element=1,
            passive_tags=PassiveTags(
                dr_base_percent=50,
                has_guard=True,
                slot1_viable=True,
            ),
        ),
        transformations=[
            CardForm(
                form_id=4030451,
                form_index=2,
                form_name="Super Vegito",
                element=1,
                min_turn=4,
                passive_tags=PassiveTags(
                    has_guard=True,
                    dr_base_percent=60,
                    permanent_dr_percent=60,
                    slot1_viable=True,
                ),
            )
        ],
    )


@pytest.fixture
def lethal_endgame_stage() -> BossStage:
    """Stage 17670015: Dokkan Ultimate Players' Choice Battle (Japanese Version).
    Final Phase (Majin Vegeta): 4.0M Normals, 10.0M Super Attack.
    """
    return BossStage(
        stage_id=17670015,
        event_id=1767,
        event_name="Dokkan Ultimate Players' Choice Battle",
        stage_name="Japanese Version",
        difficulty=10,
        phases=[
            BossPhase(
                phase_index=1,
                element=2,
                element_name="Extreme INT",
                atk=1_700_000,
                estimated_sa_damage=4_200_000,
            ),
            BossPhase(
                phase_index=2,
                element=1,
                element_name="Super TEQ",
                atk=3_300_000,
                estimated_sa_damage=8_200_000,
            ),
            BossPhase(
                phase_index=3,
                element=3,
                element_name="Extreme STR",
                atk=4_000_000,
                estimated_sa_damage=10_000_000,
            ),
        ],
    )


def test_ss3_goku_pre_attack_only_parsing_and_slot1_disqualification(
    ss3_goku_golden_fist: DokkanCard,
    lethal_endgame_stage: BossStage,
) -> None:
    """Verifies SS3 Goku's pre-attack DR is parsed with Ki 18 threshold and disqualified from Slot 1."""
    def_mech = ss3_goku_golden_fist._parse_defense_mechanics()
    assert def_mech["has_pre_attack_only_dr"] is True
    assert def_mech["pre_attack_dr"] == 50
    assert ss3_goku_golden_fist.pre_attack_dr_percent == 50
    assert ss3_goku_golden_fist.pre_attack_dr_ki_req == 18
    assert def_mech["is_dr_permanent"] is False

    solver = DokkanConstraintSolver()
    # Pre-attack only without persistent Guard cannot be Slot 1 in endgame
    is_s1 = solver.is_slot1_viable(ss3_goku_golden_fist, boss_stage=lethal_endgame_stage)
    assert is_s1 is False


def test_ss3_goku_formatting_and_tactical_warning(
    ss3_goku_golden_fist: DokkanCard,
    super_vegito_10th: DokkanCard,
    goten_int: DokkanCard,
    lethal_endgame_stage: BossStage,
) -> None:
    """Verifies that format_team_summary_table displays 'DR 50% (Pre-Atk 18+ Ki)' and warning is generated."""
    table_str = format_team_summary_table([ss3_goku_golden_fist])
    assert "DR 50% (Pre-Atk 18+ Ki)" in table_str
    assert "DR 50% (Perm)" not in table_str

    # Build a 6-card team including SS3 Goku to generate the deterministic tactical guide
    team = [
        super_vegito_10th,
        ss3_goku_golden_fist,
        goten_int,
        DokkanCard(id=2001, name="Filler 1", element=0),
        DokkanCard(id=2002, name="Filler 2", element=0),
        DokkanCard(id=2003, name="Filler 3", element=0),
    ]
    rot_a, rot_b, floaters = optimize_rotations_for_team(team, boss_stage=lethal_endgame_stage)
    guide = generate_deterministic_tactical_guide(
        rot_a,
        rot_b,
        floaters,
        leader=super_vegito_10th,
        friend=super_vegito_10th,
        boss_stage=lethal_endgame_stage,
    )
    assert "Allerta Critica Difesa Pre-Attacco" in guide
    assert "si attiva SOLO prima di attaccare con 18+ Ki" in guide
    assert "la riduzione CESSA (0% DR)" in guide


def test_goten_elimination_via_lethal_normal_attack_vulnerability(
    goten_int: DokkanCard,
    lethal_endgame_stage: BossStage,
) -> None:
    """Verifies Goten INT (50% DR naked) receives lethal normal attack penalty against 4M normals."""
    leader = DokkanCard(
        id=9001,
        name="Buu Saga Lead",
        element=0,
        category_ids=[10],
        categories=["Majin Buu Saga"],
        leader_spec=LeaderSkillSpec(main_category_ids=[10], base_boost_pct=170),
    )
    solver = DokkanConstraintSolver()
    ev = solver.evaluate_card(goten_int, leader=leader, boss_stage=lethal_endgame_stage)

    # 4.0M normal attack * 1.15 * 0.5 - 200k DEF = 2.0M damage per normal!
    assert any("Lethal Normal Attack Vulnerability" in p for p in ev.penalty_points)
    assert any("Lethal SA Vulnerability" in p for p in ev.penalty_points)
    assert ev.score < 0.0


def test_super_vegito_transformation_bridge_bonus(
    super_vegito_10th: DokkanCard,
    lethal_endgame_stage: BossStage,
) -> None:
    """Verifies 10th Anniv Super Vegito is rewarded for Turn 4 transformation bridge."""
    solver = DokkanConstraintSolver()
    gimmick_score, counter_points, penalty_points = solver.evaluate_boss_gimmicks(
        super_vegito_10th, lethal_endgame_stage
    )

    # Intro DR expires turn 3, but Turn 4 Super Vegito transforms seamlessly
    assert any("Transformation Bridge" in cp for cp in counter_points)
    assert not any("Intro Buff Expiration Vulnerability" in pp for pp in penalty_points)
    assert gimmick_score >= 0.0
