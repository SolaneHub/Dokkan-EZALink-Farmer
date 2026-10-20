from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from dokkan_eza_link_farmer.ai.client import DokkanAIClient
from dokkan_eza_link_farmer.ai.models import (
    BossPhase,
    BossStage,
    CardForm,
    DokkanCard,
    LeaderSkillSpec,
    PassiveTags,
    SATags,
)
from dokkan_eza_link_farmer.ai.team_builder import CandidateEvaluation, TeamBuilder


class TestTeamBuilderStep1:
    """Rigorous unit test suite for Step 1: Algorithmic Solver + Ollama Advisor."""

    @pytest.fixture
    def sample_leader(self) -> DokkanCard:
        spec = LeaderSkillSpec(
            main_category_ids=[10, 20],  # Realm of Gods (10), Potara (20)
            extra_category_ids=[30],  # Future Saga (30) -> 200%
            base_boost_pct=170,
            extra_boost_pct=30,
        )
        return DokkanCard(
            id=1001,
            name="LR Vegito Blue",
            element=0,  # AGL
            rarity=5,
            category_ids=[10, 20, 30],
            leader_skill="Realm of Gods or Potara Ki +3, Stats +170%; plus extra +30% for Future Saga",
            leader_spec=spec,
            base_form=CardForm(
                form_id=1001,
                form_index=0,
                form_name="Vegito Blue (Base)",
                element=0,
                passive_tags=PassiveTags(slot1_viable=True, dr_base_percent=50, has_guard=True),
                sa_tags=SATags(stacks_def=True),
            ),
        )

    @pytest.fixture
    def slot1_tank(self) -> DokkanCard:
        return DokkanCard(
            id=1002,
            name="Beast Gohan",
            element=3,  # STR
            rarity=5,
            category_ids=[10],  # Under 170%
            base_form=CardForm(
                form_id=1002,
                form_index=0,
                form_name="Beast Gohan (Base)",
                element=3,
                passive_tags=PassiveTags(slot1_viable=True, dr_base_percent=60, has_guard=True),
                sa_tags=SATags(raise_def_turns=1),
            ),
        )

    @pytest.fixture
    def glass_cannon_dodge(self) -> DokkanCard:
        return DokkanCard(
            id=1003,
            name="MUI Goku",
            element=0,  # AGL
            rarity=5,
            category_ids=[10, 30],  # Under 200%
            base_form=CardForm(
                form_id=1003,
                form_index=0,
                form_name="MUI Goku (Base)",
                element=0,
                passive_tags=PassiveTags(
                    slot1_viable=False, dodge_chance_percent=70, dr_base_percent=0
                ),
                sa_tags=SATags(raise_def_turns=1),
            ),
        )

    @pytest.fixture
    def post_super_floater(self) -> DokkanCard:
        return DokkanCard(
            id=1004,
            name="SS3 Gotenks",
            element=4,  # PHY
            rarity=4,
            category_ids=[20],
            base_form=CardForm(
                form_id=1004,
                form_index=0,
                form_name="Gotenks (Base)",
                element=4,
                passive_tags=PassiveTags(slot1_viable=False, dr_base_percent=0, has_guard=False),
                sa_tags=SATags(raise_def_turns=1),
            ),
        )

    @pytest.fixture
    def transforming_late_game(self) -> DokkanCard:
        return DokkanCard(
            id=1005,
            name="TEQ Vegito",
            element=1,  # TEQ
            rarity=5,
            category_ids=[20, 30],  # 200%
            base_form=CardForm(
                form_id=1005,
                form_index=0,
                form_name="Goku & Vegeta (Base)",
                element=1,
                passive_tags=PassiveTags(slot1_viable=False, dr_base_percent=30),
                sa_tags=SATags(stacks_def=True),
            ),
            transformations=[
                CardForm(
                    form_id=4005,
                    form_index=1,
                    form_name="Super Vegito",
                    element=1,
                    passive_tags=PassiveTags(slot1_viable=True, dr_base_percent=50, has_guard=True),
                    sa_tags=SATags(stacks_def=True),
                    min_turn=4,
                )
            ],
        )

    def test_leader_skill_170_vs_200_coverage_scoring(
        self, sample_leader, glass_cannon_dodge, slot1_tank
    ):
        tb = TeamBuilder()
        ev_200 = tb.evaluate_card_against_boss(glass_cannon_dodge, sample_leader)
        assert ev_200.lead_boost_pct == 200.0
        assert "Full 200% Leader Skill coverage" in ev_200.counter_points

        ev_170 = tb.evaluate_card_against_boss(slot1_tank, sample_leader)
        assert ev_170.lead_boost_pct == 170.0
        assert "170% Leader Skill coverage" in ev_170.counter_points

    def test_base_form_slot1_viability_strictly_enforced(
        self, sample_leader, slot1_tank, transforming_late_game
    ):
        tb = TeamBuilder()
        ev_tank = tb.evaluate_card_against_boss(slot1_tank, sample_leader)
        assert ev_tank.base_slot1_viable is True
        assert any("Slot 1 viable" in cp for cp in ev_tank.counter_points)

        # Transforming card only gets slot 1 viable in turn 4+, so its BASE form is False
        ev_trans = tb.evaluate_card_against_boss(transforming_late_game, sample_leader)
        assert ev_trans.base_slot1_viable is False

    def test_cancels_dodge_gimmick_penalizes_dodge_units(self, sample_leader, glass_cannon_dodge):
        tb = TeamBuilder()
        boss_no_dodge = BossStage(
            stage_id=1,
            event_id=10,
            stage_name="Broly Phase 3",
            event_name="Red Zone Movie Bosses",
            difficulty=10,
            phases=[
                BossPhase(phase_index=1, element=0),
                BossPhase(phase_index=2, element=3, cancels_dodge=True),
            ],
        )
        ev = tb.evaluate_card_against_boss(
            glass_cannon_dodge, sample_leader, boss_stage=boss_no_dodge
        )
        assert any("Cancels Dodge" in pp for pp in ev.penalty_points)
        assert any("relies on dodge but lacks Guard/DR" in pp for pp in ev.penalty_points)

    def test_aoe_gimmick_penalizes_post_super_floaters(
        self, sample_leader, post_super_floater, slot1_tank
    ):
        tb = TeamBuilder()
        boss_aoe = BossStage(
            stage_id=2,
            event_id=11,
            stage_name="Omega Shenron",
            event_name="Shadow Dragons",
            difficulty=10,
            phases=[BossPhase(phase_index=1, element=3, has_aoe=True)],
        )
        ev_floater = tb.evaluate_card_against_boss(
            post_super_floater, sample_leader, boss_stage=boss_aoe
        )
        assert any("AoE Vulnerability" in pp for pp in ev_floater.penalty_points)

        ev_tank = tb.evaluate_card_against_boss(slot1_tank, sample_leader, boss_stage=boss_aoe)
        assert any("mitigates Boss AoE attacks" in cp for cp in ev_tank.counter_points)

    def test_select_best_team_guarantees_minimum_two_slot1_units(
        self,
        sample_leader,
        slot1_tank,
        glass_cannon_dodge,
        post_super_floater,
        transforming_late_game,
    ):
        # Create a 6th filler card with no slot 1 viability
        filler = DokkanCard(
            id=1006,
            name="Filler Support",
            element=2,
            category_ids=[10, 20],
            base_form=CardForm(
                form_id=1006,
                form_index=0,
                form_name="Support",
                element=2,
                passive_tags=PassiveTags(slot1_viable=False, has_support=True),
            ),
        )
        pool = [
            sample_leader,
            slot1_tank,
            glass_cannon_dodge,
            post_super_floater,
            transforming_late_game,
            filler,
        ]
        tb = TeamBuilder()
        team_rec, shortlist = tb.select_best_team_for_boss(pool, forced_leader=sample_leader)

        # Check total cards in team is 6
        assert len(team_rec.all_cards) == 6
        # Count base slot 1 viable units in team
        slot1_count = sum(
            1
            for c in team_rec.all_cards
            if (c.base_form and c.base_form.passive_tags and c.base_form.passive_tags.slot1_viable)
            or c.is_slot1_tank
        )
        assert slot1_count >= 2

    def test_ollama_advisor_tie_breaker_and_graceful_fallback(
        self, sample_leader, slot1_tank, glass_cannon_dodge
    ):
        tb = TeamBuilder()
        boss_stage = BossStage(
            stage_id=1,
            event_id=1,
            stage_name="Stage 1",
            event_name="Red Zone",
            difficulty=10,
            phases=[BossPhase(phase_index=1, element=3)],
        )
        candidates = [
            CandidateEvaluation(
                card=glass_cannon_dodge, score=85.0, lead_boost_pct=200.0, base_slot1_viable=False
            ),
            CandidateEvaluation(
                card=slot1_tank, score=82.0, lead_boost_pct=170.0, base_slot1_viable=True
            ),
        ]

        # 1. Test offline/unavailable fallback -> returns Candidate #1
        ai_client_offline = MagicMock(spec=DokkanAIClient)
        ai_client_offline.is_available.return_value = False
        chosen, reason = tb.consult_ollama_advisor(
            candidates, [sample_leader], boss_stage, ai_client=ai_client_offline
        )
        assert chosen.id == glass_cannon_dodge.id
        assert "Graceful Fallback" in reason

        # 2. Test active Ollama choosing candidate #2 (Beast Gohan) due to specific semantic reason
        ai_client_online = MagicMock(spec=DokkanAIClient)
        ai_client_online.is_available.return_value = True
        ai_client_online.chat_completion.return_value = (
            '{"selected_card_id": 1002, "reasoning": "Beast Gohan garantisce guardia assoluta e countera la fase STR"}',
            "Chain of Thought: Boss attacks heavily in Slot 1, Beast Gohan is necessary.",
        )
        chosen_ai, reason_ai = tb.consult_ollama_advisor(
            candidates, [sample_leader], boss_stage, ai_client=ai_client_online
        )
        assert chosen_ai.id == 1002
        assert "Beast Gohan garantisce guardia assoluta" in reason_ai
