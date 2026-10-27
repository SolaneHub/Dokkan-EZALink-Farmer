"""
Unit tests validating that:
1. Units with raw 50% DR (no guard) or 70% Dodge (no guard/DR) like Goten INT or LR Vegito INT
   are strictly DISQUALIFIED from Slot 1 in Endgame stages with lethal Super Attacks (>= 1.8M - 10M+).
2. The solver strictly forbids bringing duplicate characters with the exact same base form name.
"""

import pytest

from dokkan_eza_link_farmer.ai.boss_models import BossPhase, BossStage
from dokkan_eza_link_farmer.ai.card_models import CardForm, DokkanCard, LeaderSkillSpec
from dokkan_eza_link_farmer.ai.solver import DokkanConstraintSolver
from dokkan_eza_link_farmer.ai.syncer import parse_passive_tags


class TestSlot1LethalBossDisqualification:
    @pytest.fixture
    def lethal_boss_stage(self) -> BossStage:
        """3-phase Endgame Boss (Dokkan Ultimate Players' Choice Battle)."""
        return BossStage(
            stage_id=17670015,
            event_id=1767,
            stage_name="Japanese Version",
            event_name="Dokkan Ultimate Players' Choice Battle",
            phases=[
                BossPhase(phase_index=1, element=22, atk=1700000, estimated_sa_damage=4200000),
                BossPhase(phase_index=2, element=11, atk=3300000, estimated_sa_damage=8200000),
                BossPhase(phase_index=3, element=23, atk=4000000, estimated_sa_damage=10400000),
            ],
        )

    def test_goten_int_rejected_from_slot1_against_lethal_boss(self, lethal_boss_stage: BossStage):
        """Goten INT has 50% DR but NO Guard and NO Dodge. Against 8.2M TEQ Super he takes 5M damage -> DISQUALIFIED."""
        goten_passive = "*Basic effect(s)*\n- ATK & DEF 180%\n- Reduces damage received by 50%\n"
        goten = DokkanCard(
            id=1021941,
            name="Super Saiyan Goten (Kid)",
            element=12,  # Super INT
            categories=["Majin Buu Saga", "Hybrid Saiyans"],
            passive_skill=goten_passive,
            base_form=CardForm(
                form_index=0,
                form_name="Super Saiyan Goten (Kid)",
                passive_tags=parse_passive_tags(goten_passive),
            ),
        )

        assert DokkanConstraintSolver.is_slot1_viable(goten, boss_stage=lethal_boss_stage) is False

    def test_goku_and_vegeta_int_rejected_from_slot1_against_lethal_boss(
        self, lethal_boss_stage: BossStage
    ):
        """LR INT Vegito has 70% Dodge but 0% DR and NO Guard. Missing 1 dodge = 10M damage -> DISQUALIFIED."""
        vegito_passive = (
            "*Basic effect(s)*\n- ATK & DEF 300%\n- Great chance of evading enemy's attack\n"
        )
        vegito = DokkanCard(
            id=1012901,
            name="Super Saiyan Goku & Super Saiyan Vegeta",
            element=12,  # Super INT
            categories=["Majin Buu Saga", "Pure Saiyans"],
            passive_skill=vegito_passive,
            base_form=CardForm(
                form_index=0,
                form_name="Super Saiyan Goku & Super Saiyan Vegeta",
                passive_tags=parse_passive_tags(vegito_passive),
            ),
        )

        assert DokkanConstraintSolver.is_slot1_viable(vegito, boss_stage=lethal_boss_stage) is False

    def test_solver_strictly_prevents_duplicate_same_name_characters(
        self, lethal_boss_stage: BossStage
    ):
        """Verifies solver never includes two cards with the exact same base form name in the 6-man team."""
        leader = DokkanCard(
            id=1033061,
            name="Majin Vegeta + Super Saiyan 2 Goku (Angel)",
            element=23,
            categories=["Majin Buu Saga"],
            category_ids=[1],
            leader_spec=LeaderSkillSpec(
                main_category_ids=[1], base_boost_pct=170, extra_boost_pct=30
            ),
            base_form=CardForm(
                form_index=0,
                form_name="Majin Vegeta",
                passive_tags=parse_passive_tags(
                    "*Basic effect(s)*\n- Damage reduction rate 18%\n- Guards all attacks\n"
                ),
            ),
        )
        card_copy1 = DokkanCard(
            id=1012901,
            name="Super Saiyan Goku & Super Saiyan Vegeta",
            element=12,
            categories=["Majin Buu Saga"],
            category_ids=[1],
            base_form=CardForm(
                form_index=0,
                form_name="Super Saiyan Goku & Super Saiyan Vegeta",
                passive_tags=parse_passive_tags("*Basic effect(s)*\n- ATK 300%\n"),
            ),
        )
        card_copy2 = DokkanCard(
            id=1034761,  # Different ID, same character name
            name="Super Saiyan Goku & Super Saiyan Vegeta",
            element=12,
            categories=["Majin Buu Saga"],
            category_ids=[1],
            base_form=CardForm(
                form_index=0,
                form_name="Super Saiyan Goku & Super Saiyan Vegeta",
                passive_tags=parse_passive_tags("*Basic effect(s)*\n- ATK 300%\n"),
            ),
        )
        other_cards = [
            DokkanCard(
                id=2001,
                name="Gohan A",
                element=11,
                categories=["Majin Buu Saga"],
                category_ids=[1],
                base_form=CardForm(
                    form_index=0,
                    form_name="Gohan A",
                    passive_tags=parse_passive_tags(
                        "*Basic effect(s)*\n- Guards all attacks\n- Damage reduction rate 50%\n"
                    ),
                ),
            ),
            DokkanCard(
                id=2002,
                name="Gohan B",
                element=12,
                categories=["Majin Buu Saga"],
                category_ids=[1],
                base_form=CardForm(
                    form_index=0,
                    form_name="Gohan B",
                    passive_tags=parse_passive_tags(
                        "*Basic effect(s)*\n- Guards all attacks\n- Damage reduction rate 50%\n"
                    ),
                ),
            ),
            DokkanCard(
                id=2003,
                name="Buu A",
                element=21,
                categories=["Majin Buu Saga"],
                category_ids=[1],
                base_form=CardForm(
                    form_index=0,
                    form_name="Buu A",
                    passive_tags=parse_passive_tags(
                        "*Basic effect(s)*\n- Guards all attacks\n- Damage reduction rate 50%\n"
                    ),
                ),
            ),
            DokkanCard(
                id=2004,
                name="Buu B",
                element=22,
                categories=["Majin Buu Saga"],
                category_ids=[1],
                base_form=CardForm(
                    form_index=0,
                    form_name="Buu B",
                    passive_tags=parse_passive_tags(
                        "*Basic effect(s)*\n- Guards all attacks\n- Damage reduction rate 50%\n"
                    ),
                ),
            ),
        ]

        pool = [leader, card_copy1, card_copy2] + other_cards
        solver = DokkanConstraintSolver()
        res = solver.solve(pool, boss_stage=lethal_boss_stage, forced_leader=leader)

        team_names = [c.name for c in res.team_cards]
        assert team_names.count("Super Saiyan Goku & Super Saiyan Vegeta") <= 1, (
            "Duplicate character name detected on team!"
        )
