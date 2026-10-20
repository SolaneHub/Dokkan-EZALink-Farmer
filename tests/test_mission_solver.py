from __future__ import annotations

import pytest
from dokkan_eza_link_farmer.ai.models import CardForm, DokkanCard, LeaderSkillSpec, PassiveTags
from dokkan_eza_link_farmer.ai.mission_solver import (
    ChallengeMission,
    MissionBatch,
    MissionBundler,
    MissionParser,
)
from dokkan_eza_link_farmer.ai.solver import DokkanConstraintSolver
from dokkan_eza_link_farmer.ai.team_builder import TeamBuilder


def make_card(
    cid: int,
    name: str,
    element: int,
    card_class: str = "Super",
    categories: list[str] | None = None,
    main_cats: list[int] | None = None,
    base_boost: float = 170.0,
    has_guard: bool = False,
    dr: int = 0,
    dodge: int = 0,
) -> DokkanCard:
    cats = categories or ["Time Travelers"]
    spec = None
    if main_cats:
        spec = LeaderSkillSpec(
            main_category_ids=main_cats,
            base_boost_pct=base_boost,
            extra_boost_pct=30.0,
        )
    return DokkanCard(
        id=cid,
        name=name,
        element=element,
        card_class=card_class,
        categories=cats,
        category_ids=[1, 2, 3] if main_cats else [1],
        leader_skill="Lead Boost" if spec else "",
        leader_spec=spec,
        base_form=CardForm(
            form_id=cid,
            form_index=0,
            form_name=name,
            element=element,
            passive_tags=PassiveTags(
                has_guard=has_guard,
                dr_base_percent=dr,
                dodge_chance_percent=dodge,
            ),
        ),
        passive_skill="Guards all attacks" if has_guard else "",
    )


class TestMissionParser:
    def test_parse_category_mission(self):
        raw = {
            "id": 101,
            "name": "Clear Stage 77 with 6 characters of the specified Category.",
            "description": 'Clear Stage 77 of the Challenge Event "Ultimate Red Zone" once with 6 "Time Travelers" Category characters on your team!\n* Friends do not count.',
        }
        mission = MissionParser.parse(raw)
        assert mission.id == 101
        assert mission.stage_num == 77
        assert mission.applicable_stages == [77]
        assert mission.categories == [(6, "Time Travelers")]
        assert not mission.rainbow_types
        assert mission.is_restricted

    def test_parse_at_least_category_mission(self):
        raw = {
            "id": 102,
            "name": "Clear Stage 78 with at least 5 characters of the specified Category.",
            "description": 'Clear Stage 78 of the Challenge Event "Ultimate Red Zone" once with at least 5 "Terrifying Conquerors" Category characters on your team!',
        }
        mission = MissionParser.parse(raw)
        assert mission.stage_num == 78
        assert mission.categories == [(5, "Terrifying Conquerors")]
        assert mission.is_restricted

    def test_parse_super_and_extreme_rainbow_missions(self):
        raw_super = {
            "id": 201,
            "name": "Clear Stage 79 once with a team that includes all five Super Types.",
            "description": "Clear Stage 79 with a Super AGL Type character, a Super TEQ Type character, a Super INT Type character, a Super STR Type character and a Super PHY Type character on your team!",
        }
        m_sup = MissionParser.parse(raw_super)
        assert m_sup.requires_all_super
        assert not m_sup.requires_all_extreme
        assert m_sup.rainbow_types

        raw_ext = {
            "id": 202,
            "name": "Clear Stage 79 once with a team that includes all five Extreme Types.",
            "description": "Clear Stage 79 with an Extreme AGL Type character, an Extreme TEQ Type character, an Extreme INT Type character, an Extreme STR Type character and an Extreme PHY Type character on your team!",
        }
        m_ext = MissionParser.parse(raw_ext)
        assert m_ext.requires_all_extreme
        assert not m_ext.requires_all_super
        assert m_ext.rainbow_types

    def test_parse_turns_and_no_items(self):
        raw = {
            "id": 301,
            "name": "Speedrun Challenge",
            "description": "Clear Stage 5 within 5 turns without using any support items!",
        }
        m = MissionParser.parse(raw)
        assert m.max_turns == 5
        assert m.no_items
        assert m.stage_num == 5


class TestMissionBundler:
    def test_compatibility_super_vs_extreme(self):
        m_sup = ChallengeMission(id=1, name="All Super", description="", requires_all_super=True)
        m_ext = ChallengeMission(id=2, name="All Extreme", description="", requires_all_extreme=True)
        assert not MissionBundler.are_compatible(m_sup, m_ext)

    def test_create_batch_from_selection(self):
        m1 = ChallengeMission(id=1, name="6x Time Travelers", description="", categories=[(6, "Time Travelers")])
        m2 = ChallengeMission(id=2, name="No Items", description="", no_items=True)
        batch = MissionBundler.create_batch_from_selection([m1, m2])
        assert batch.required_categories == [(6, "Time Travelers")]
        assert batch.requires_no_items
        assert "Time Travelers" in batch.summary
        assert "No Support Items" in batch.summary

    def test_matches_team_verification(self):
        cards = [
            make_card(1, "Lead", 10, card_class="Super", categories=["Time Travelers"]),
            make_card(2, "Sub1", 11, card_class="Super", categories=["Time Travelers"]),
            make_card(3, "Sub2", 12, card_class="Super", categories=["Time Travelers"]),
            make_card(4, "Sub3", 13, card_class="Super", categories=["Time Travelers"]),
            make_card(5, "Sub4", 14, card_class="Super", categories=["Time Travelers"]),
            make_card(6, "Sub5", 10, card_class="Super", categories=["Pure Saiyans"]),  # Missing TT
        ]
        batch = MissionBatch(missions=[], required_categories=[(6, "Time Travelers")])
        passed, reasons = batch.matches_team(cards)
        assert not passed
        assert any("5/6" in r for r in reasons)


class TestSolverMissionIntegration:
    def test_solve_with_6x_category_mission(self):
        solver = DokkanConstraintSolver()
        # Pool with mix of Time Travelers and others
        pool = [
            make_card(1, "Lead TT", 10, categories=["Time Travelers"], main_cats=[1], has_guard=True),
            make_card(2, "TT 1", 11, categories=["Time Travelers"], has_guard=True),
            make_card(3, "TT 2", 12, categories=["Time Travelers"], dr=50),
            make_card(4, "TT 3", 13, categories=["Time Travelers"]),
            make_card(5, "TT 4", 14, categories=["Time Travelers"]),
            make_card(6, "TT 5", 10, categories=["Time Travelers"]),
            make_card(7, "Non TT 1", 11, categories=["Pure Saiyans"]),
            make_card(8, "Non TT 2", 12, categories=["Pure Saiyans"]),
        ]
        batch = MissionBatch(missions=[], required_categories=[(6, "Time Travelers")])
        res = solver.solve(pool, mission_batch=batch)
        assert len(res.team_cards) == 6
        for c in res.team_cards:
            assert "Time Travelers" in c.categories

    def test_solve_with_rainbow_mission(self):
        solver = DokkanConstraintSolver()
        # Elements: 10 (AGL), 11 (TEQ), 12 (INT), 13 (STR), 14 (PHY)
        pool = [
            make_card(1, "Lead AGL", 10, categories=["Pure Saiyans"], main_cats=[1], has_guard=True),
            make_card(2, "Sub TEQ", 11, categories=["Pure Saiyans"], has_guard=True),
            make_card(3, "Sub INT", 12, categories=["Pure Saiyans"]),
            make_card(4, "Sub STR", 13, categories=["Pure Saiyans"]),
            make_card(5, "Sub PHY", 14, categories=["Pure Saiyans"]),
            make_card(6, "Sub Extra AGL", 10, categories=["Pure Saiyans"]),
        ]
        batch = MissionBatch(missions=[], requires_rainbow=True)
        res = solver.solve(pool, mission_batch=batch)
        team_types = {c.element % 10 for c in res.team_cards}
        assert team_types == {0, 1, 2, 3, 4}


class TestTeamBuilderMissionIntegration:
    def test_team_builder_attaches_mission_summary(self):
        builder = TeamBuilder()
        pool = [
            make_card(1, "Lead TT", 10, categories=["Time Travelers"], main_cats=[1], has_guard=True),
            make_card(2, "TT 1", 11, categories=["Time Travelers"], has_guard=True),
            make_card(3, "TT 2", 12, categories=["Time Travelers"], dr=50),
            make_card(4, "TT 3", 13, categories=["Time Travelers"]),
            make_card(5, "TT 4", 14, categories=["Time Travelers"]),
            make_card(6, "TT 5", 10, categories=["Time Travelers"]),
        ]
        m = ChallengeMission(id=77, name="Clear with TT", description="", categories=[(6, "Time Travelers")])
        batch = MissionBatch(missions=[m], required_categories=[(6, "Time Travelers")])

        rec, _ = builder.select_best_team_for_boss(
            candidate_pool=pool,
            generate_tactics=False,
            mission_batch=batch,
        )
        assert rec.mission_summary is not None
        assert "Time Travelers" in rec.mission_summary
        assert len(rec.target_missions) == 1
