"""Pytest test suite converted from scripts/verify_phase3_teambuilder.py."""

from __future__ import annotations

import tempfile

from dokkan_eza_link_farmer.ai.models import (
    BossPhase,
    BossStage,
    CardForm,
    DokkanCard,
    LeaderSkillSpec,
    PassiveTags,
    SATags,
)
from dokkan_eza_link_farmer.ai.solver import DokkanConstraintSolver
from dokkan_eza_link_farmer.ai.telemetry import (
    CulpritAttribution,
    EpisodicMemory,
    TurnSnapshot,
)
from dokkan_eza_link_farmer.automation.team_formation import apply_team_in_game


def make_card(
    card_id: int,
    name: str,
    element: int = 0,
    category_ids: list[int] | None = None,
    leader_spec: LeaderSkillSpec | None = None,
    slot1_viable: bool = False,
    dr_pct: int = 0,
    has_guard: bool = False,
    dodge_pct: int = 0,
    stacks_def: bool = False,
    links: list[str] | None = None,
) -> DokkanCard:
    cats = category_ids or [10]
    card_links = links or ["Super Saiyan", "Prepared for Battle", "Fierce Battle"]
    return DokkanCard(
        id=card_id,
        name=name,
        element=element,
        rarity=5,
        category_ids=cats,
        links=card_links,
        leader_spec=leader_spec,
        base_form=CardForm(
            form_id=card_id,
            form_index=0,
            form_name=f"{name} (Base)",
            element=element,
            passive_tags=PassiveTags(
                slot1_viable=slot1_viable,
                dr_base_percent=dr_pct,
                has_guard=has_guard,
                dodge_chance_percent=dodge_pct,
            ),
            sa_tags=SATags(stacks_def=stacks_def),
        ),
    )


def test_scenario_a_instant_retry():
    """Scenario A: Boss HP < 20% in Final Phase triggers InstantRetry without modifying team."""
    with tempfile.TemporaryDirectory() as tmpdir:
        memory = EpisodicMemory(cache_path=f"{tmpdir}/ai_memory.json")

        stage_broly = BossStage(
            stage_id=1001,
            event_id=10,
            stage_name="Broly",
            event_name="Red Zone Movie Bosses",
            phases=[
                BossPhase(phase_index=1, element=1, element_name="TEQ"),
                BossPhase(phase_index=2, element=3, element_name="STR"),
                BossPhase(phase_index=3, element=0, element_name="AGL", cancels_dodge=True),
            ],
        )

        team = [make_card(1000 + i, f"Member {i}", element=i % 5) for i in range(1, 7)]

        snapshot = TurnSnapshot(
            turn_number=6,
            boss_phase_index=3,
            boss_element=0,
            boss_element_name="AGL",
            boss_hp_percent=14.5,
            player_hp_percent=0.0,
            active_rotation=[team[0], team[1], team[2]],
        )

        attribution = CulpritAttribution(
            direct_culprit_id=team[1].id,
            direct_culprit_slot=2,
            is_friend_leader=False,
            is_ambiguous=False,
            vulnerability_shares={team[1].id: 1.0},
        )

        decision = memory.evaluate_post_defeat(
            stage_id=1001,
            snapshot=snapshot,
            attribution=attribution,
            current_team=team,
            user_box=team,
            boss_stage=stage_broly,
            is_final_phase=True,
        )

        assert decision.action == "InstantRetry"
        assert len(decision.replaced_card_ids) == 0
        assert [c.id for c in decision.team] == [c.id for c in team]


def test_scenario_b_surgical_replacement():
    """Scenario B: Surgical replacement of floater at STR Phase with AGL/Guard tank."""
    with tempfile.TemporaryDirectory() as tmpdir:
        memory = EpisodicMemory(cache_path=f"{tmpdir}/ai_memory.json")

        stage_omega = BossStage(
            stage_id=2001,
            event_id=20,
            stage_name="Omega Shenron",
            event_name="Red Zone GT Bosses",
            phases=[
                BossPhase(phase_index=1, element=4, element_name="PHY"),
                BossPhase(phase_index=2, element=3, element_name="STR"),
            ],
        )

        lead_spec = LeaderSkillSpec(
            main_category_ids=[10],
            extra_category_ids=[20],
            base_boost_pct=170.0,
            extra_boost_pct=30.0,
        )

        c_lead = make_card(
            1001,
            "LR Vegito Leader",
            element=0,
            category_ids=[10, 20],
            leader_spec=lead_spec,
            slot1_viable=True,
        )
        c_gohan = make_card(
            1002,
            "Beast Gohan",
            element=3,
            category_ids=[10, 20],
            slot1_viable=True,
            dr_pct=80,
            has_guard=True,
        )
        c_teq = make_card(
            1003, "TEQ Vegito", element=1, category_ids=[10, 20], dr_pct=50, has_guard=True
        )
        c_gotenks = make_card(
            1004, "PHY Gotenks", element=4, category_ids=[10], dr_pct=0, has_guard=False
        )
        c_sub5 = make_card(1005, "Hero 5", element=2, category_ids=[10], dr_pct=40)
        c_sub6 = make_card(1006, "Hero 6", element=0, category_ids=[10], dr_pct=40)

        current_team = [c_lead, c_gohan, c_teq, c_gotenks, c_sub5, c_sub6]
        c_frieza = make_card(
            1007, "AGL Golden Frieza", element=0, category_ids=[10], dr_pct=90, has_guard=False
        )
        user_box = list(current_team) + [c_frieza]

        snapshot = TurnSnapshot(
            turn_number=4,
            boss_phase_index=2,
            boss_element=3,
            boss_element_name="STR",
            boss_hp_percent=62.0,
            player_hp_percent=0.0,
            active_rotation=[c_lead, c_gohan, c_gotenks],
        )

        attribution = CulpritAttribution(
            direct_culprit_id=1004,
            direct_culprit_slot=3,
            is_friend_leader=False,
            is_ambiguous=False,
            vulnerability_shares={1004: 1.0},
        )

        solver = DokkanConstraintSolver()
        decision = memory.evaluate_post_defeat(
            stage_id=2001,
            snapshot=snapshot,
            attribution=attribution,
            current_team=current_team,
            user_box=user_box,
            solver=solver,
            boss_stage=stage_omega,
            is_final_phase=False,
        )

        assert decision.action == "SurgicalReplace"
        assert 1004 in decision.replaced_card_ids
        assert 1007 in decision.new_card_ids

        new_card = next(c for c in decision.team if c.id == 1007)
        assert (
            new_card.element == 0 or new_card.has_guard or new_card.damage_reduction_percent >= 60
        )

        is_cov, boost_pct, _ = new_card.is_covered_by_leader(c_lead)
        assert is_cov and boost_pct >= 170.0


def test_scenario_c_cancels_dodge():
    """Scenario C: Boss with cancels_dodge discards pure dodge candidates."""
    stage_broly3 = BossStage(
        stage_id=1001,
        event_id=10,
        stage_name="Broly",
        event_name="Red Zone Movie Bosses",
        phases=[
            BossPhase(phase_index=1, element=0, element_name="AGL", cancels_dodge=True),
        ],
    )

    lead_spec = LeaderSkillSpec(
        main_category_ids=[10],
        base_boost_pct=170.0,
    )

    leader = make_card(
        3000, "Leader Unit", element=0, category_ids=[10], leader_spec=lead_spec, slot1_viable=True
    )
    slot1_tank = make_card(
        3001,
        "Slot 1 Tank",
        element=3,
        category_ids=[10],
        slot1_viable=True,
        has_guard=True,
        dr_pct=50,
    )
    mui_goku = make_card(
        3002,
        "MUI Goku",
        element=0,
        category_ids=[10],
        slot1_viable=False,
        dr_pct=0,
        has_guard=False,
        dodge_pct=70,
    )
    golden_frieza = make_card(
        3003,
        "Golden Frieza",
        element=0,
        category_ids=[10],
        slot1_viable=False,
        dr_pct=90,
        has_guard=False,
        dodge_pct=0,
    )
    subs = [
        make_card(3004, "Sub A", element=1, category_ids=[10], dr_pct=40),
        make_card(3005, "Sub B", element=2, category_ids=[10], dr_pct=40),
        make_card(3006, "Sub C", element=1, category_ids=[10], dr_pct=40),
    ]

    solver = DokkanConstraintSolver()
    ev_mui = solver.evaluate_card(mui_goku, leader, boss_stage=stage_broly3)
    ev_frieza = solver.evaluate_card(golden_frieza, leader, boss_stage=stage_broly3)

    assert any("neutralized by Boss (Cancels Dodge)" in p for p in ev_mui.penalty_points)
    assert ev_frieza.score > ev_mui.score

    pool = [leader, slot1_tank, mui_goku, golden_frieza] + subs
    result = solver.solve(pool, boss_stage=stage_broly3, forced_leader=leader)

    team_ids = {c.id for c in result.team_cards}
    assert 3003 in team_ids
    assert 3002 not in team_ids

    formation_ok = apply_team_in_game(None, None, None, result.team_cards, dry_run=True)
    assert formation_ok is True
