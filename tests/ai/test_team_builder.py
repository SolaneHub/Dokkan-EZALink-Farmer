"""Unit and integration tests for Dokkan AI TeamBuilder and Ollama AI Advisor.

Covers:
- Top-5 candidate shortlist generation and scoring.
- Payload structure sent to AI client (BossStage, FailureReport, 5 team members, 5 candidates).
- Explicit mocks for Zero-Crash Graceful Degradation:
  1) Server offline -> fallback to Candidate #1.
  2) Timeout (> 75s) -> fallback to Candidate #1.
  3) Invalid / hallucinated ID outside shortlist -> fallback to Candidate #1.
  4) Valid JSON response -> selecting the advisor's recommended candidate.
  5) Malformed response -> fallback to Candidate #1.
  6) AI Advisor disabled in settings -> fallback to Candidate #1.
- Integration tests for full team recommendation with DokkanConstraintSolver and AI Advisor.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
import requests

from dokkan_eza_link_farmer.ai.client import DokkanAIClient
from dokkan_eza_link_farmer.ai.models import (
    AIConfig,
    BossPhase,
    BossStage,
    CardForm,
    DokkanCard,
    FailureReport,
    LeaderSkillSpec,
    PassiveTags,
    SATags,
)
from dokkan_eza_link_farmer.ai.team_builder import (
    CandidateEvaluation,
    TeamBuilder,
)


@pytest.fixture
def sample_leader_200() -> DokkanCard:
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
        links=["Super Saiyan", "Prepared for Battle", "Fierce Battle", "Over in a Flash"],
    )


@pytest.fixture
def candidate_pool_sample(sample_leader_200: DokkanCard) -> list[DokkanCard]:
    cards = [sample_leader_200]
    # Unit 2: Beast Gohan (Slot 1 tank, 170%)
    cards.append(
        DokkanCard(
            id=1002,
            name="Beast Gohan",
            element=3,  # STR
            rarity=5,
            category_ids=[10],
            base_form=CardForm(
                form_id=1002,
                form_index=0,
                form_name="Beast Gohan (Base)",
                element=3,
                passive_tags=PassiveTags(slot1_viable=True, dr_base_percent=60, has_guard=True),
                sa_tags=SATags(raise_def_turns=1),
            ),
            passive_skill="Guards all attacks; reduces damage received by 60% for 3 turns",
            super_attack="Causes colossal damage and raises DEF for 1 turn",
            links=["Prepared for Battle", "Fierce Battle"],
        )
    )
    # Unit 3: MUI Goku (Dodge glass cannon, 200%)
    cards.append(
        DokkanCard(
            id=1003,
            name="MUI Goku",
            element=0,  # AGL
            rarity=5,
            category_ids=[10, 30],
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
            passive_skill="Great chance of evading enemy attacks (including Super Attack)",
            super_attack="Causes colossal damage and raises ATK & DEF for 1 turn",
            links=["Over in a Flash", "Prepared for Battle", "Fierce Battle"],
        )
    )
    # Unit 4: TEQ Vegito (Transforming, DEF stacker, 200%)
    cards.append(
        DokkanCard(
            id=1004,
            name="TEQ Vegito",
            element=1,  # TEQ
            rarity=5,
            category_ids=[20, 30],
            base_form=CardForm(
                form_id=1004,
                form_index=0,
                form_name="Goku & Vegeta (Base)",
                element=1,
                passive_tags=PassiveTags(slot1_viable=False, dr_base_percent=30),
                sa_tags=SATags(stacks_def=True),
            ),
            transformations=[
                CardForm(
                    form_id=4004,
                    form_index=1,
                    form_name="Super Vegito",
                    element=1,
                    passive_tags=PassiveTags(slot1_viable=True, dr_base_percent=50, has_guard=True),
                    sa_tags=SATags(stacks_def=True),
                    min_turn=4,
                )
            ],
            passive_skill="Reduces damage received by 30%; transforms into Super Vegito starting from Turn 4",
            super_attack="Raises ATK & DEF and causes colossal damage",
            links=["Super Saiyan", "Prepared for Battle", "Fierce Battle"],
        )
    )
    # Unit 5: SS3 Gotenks (PHY floater, 170%)
    cards.append(
        DokkanCard(
            id=1005,
            name="SS3 Gotenks",
            element=4,  # PHY
            rarity=4,
            category_ids=[20],
            base_form=CardForm(
                form_id=1005,
                form_index=0,
                form_name="Gotenks (Base)",
                element=4,
                passive_tags=PassiveTags(slot1_viable=False, dr_base_percent=0, has_guard=False),
                sa_tags=SATags(raise_def_turns=1),
            ),
            passive_skill="ATK +150% and DEF +100% when performing a Super Attack",
            super_attack="Causes supreme damage and raises DEF for 1 turn",
            links=["Super Saiyan", "Over in a Flash", "Fierce Battle"],
        )
    )
    # Unit 6: INT SSGSS Vegeta (170%, slot 1 viable)
    cards.append(
        DokkanCard(
            id=1006,
            name="SSGSS Vegeta",
            element=2,  # INT
            rarity=5,
            category_ids=[10],
            base_form=CardForm(
                form_id=1006,
                form_index=0,
                form_name="SSGSS Vegeta (Base)",
                element=2,
                passive_tags=PassiveTags(slot1_viable=True, dr_base_percent=50, has_guard=True),
                sa_tags=SATags(stacks_def=True),
            ),
            passive_skill="Guards all attacks; reduces damage received by 50%",
            super_attack="Raises DEF and causes immense damage",
            links=["Super Saiyan", "Prepared for Battle", "Warrior Gods"],
        )
    )
    # Unit 7: Support Whis (200%, healing & dodge)
    cards.append(
        DokkanCard(
            id=1007,
            name="Whis",
            element=0,  # AGL
            rarity=4,
            category_ids=[10, 30],
            base_form=CardForm(
                form_id=1007,
                form_index=0,
                form_name="Whis (Base)",
                element=0,
                passive_tags=PassiveTags(
                    slot1_viable=False, has_support=True, dodge_chance_percent=50
                ),
                sa_tags=SATags(raise_def_turns=1),
            ),
            passive_skill="Super Class allies Ki +2 and ATK & DEF +40%; high chance of evading enemy attacks",
            super_attack="Causes supreme damage and raises DEF for 1 turn",
            links=["Shocking Speed"],
        )
    )
    # Unit 8: Piccolo (170%, massive DR)
    cards.append(
        DokkanCard(
            id=1008,
            name="Piccolo",
            element=1,  # TEQ
            rarity=5,
            category_ids=[10],
            base_form=CardForm(
                form_id=1008,
                form_index=0,
                form_name="Piccolo (Base)",
                element=1,
                passive_tags=PassiveTags(slot1_viable=True, dr_base_percent=50, has_guard=False),
                sa_tags=SATags(raise_def_turns=1),
            ),
            passive_skill="Reduces damage received by 50%; guards all attacks when HP is 50% or more",
            super_attack="Causes colossal damage and greatly raises DEF for 1 turn",
            links=["Shocking Speed", "Fierce Battle"],
        )
    )
    return cards


@pytest.fixture
def sample_boss_stage() -> BossStage:
    return BossStage(
        stage_id=101,
        event_id=10,
        event_name="Red Zone: Movie Bosses",
        stage_name="Stage 8: Broly",
        difficulty=10,
        phases=[
            BossPhase(phase_index=1, element=0, element_name="AGL"),
            BossPhase(phase_index=2, element=1, element_name="TEQ", has_aoe=True),
            BossPhase(
                phase_index=3, element=3, element_name="STR", cancels_dodge=True, locks_slots=True
            ),
        ],
    )


class TestShortlistGenerationAndScoring:
    """Verifies that TeamBuilder correctly produces and ranks the Top-5 shortlist."""

    def test_top_5_shortlist_generation_and_ordering(
        self,
        sample_leader_200: DokkanCard,
        candidate_pool_sample: list[DokkanCard],
        sample_boss_stage: BossStage,
    ) -> None:
        tb = TeamBuilder()
        shortlist = tb.get_top_candidates(
            candidate_pool=candidate_pool_sample,
            leader=sample_leader_200,
            boss_stage=sample_boss_stage,
            top_k=5,
        )

        assert len(shortlist) <= 5
        assert len(shortlist) > 0

        # Verify ordering is strictly descending by score
        scores = [ev.score for ev in shortlist]
        assert scores == sorted(scores, reverse=True)

        # Leader must NOT be in the shortlist
        assert not any(ev.card.id == sample_leader_200.id for ev in shortlist)

        # Verify each candidate has complete evaluation metadata
        for ev in shortlist:
            assert isinstance(ev, CandidateEvaluation)
            assert ev.score != 0.0
            assert ev.lead_boost_pct >= 150.0
            assert isinstance(ev.base_slot1_viable, bool)
            assert isinstance(ev.counter_points, list)
            assert isinstance(ev.penalty_points, list)

    def test_shortlist_excludes_specified_ids(
        self,
        sample_leader_200: DokkanCard,
        candidate_pool_sample: list[DokkanCard],
        sample_boss_stage: BossStage,
    ) -> None:
        tb = TeamBuilder()
        excluded = {1002, 1003}
        shortlist = tb.get_top_candidates(
            candidate_pool=candidate_pool_sample,
            leader=sample_leader_200,
            boss_stage=sample_boss_stage,
            top_k=5,
            exclude_ids=excluded,
        )
        for ev in shortlist:
            assert ev.card.id not in excluded
            assert ev.card.id != sample_leader_200.id


class TestAdvisorPayloadStructure:
    """Verifies the compact JSON payload delivered to the Ollama AI client."""

    def test_payload_structure_without_failure_report(
        self,
        sample_leader_200: DokkanCard,
        candidate_pool_sample: list[DokkanCard],
        sample_boss_stage: BossStage,
    ) -> None:
        tb = TeamBuilder()
        current_team = candidate_pool_sample[:5]
        candidates = tb.get_top_candidates(
            candidate_pool=candidate_pool_sample,
            leader=sample_leader_200,
            boss_stage=sample_boss_stage,
            top_k=5,
        )

        payload = TeamBuilder.build_advisor_payload(
            boss_stage=sample_boss_stage,
            current_team=current_team,
            top_candidates=candidates,
            failure_report=None,
        )

        # 1. Root structure
        assert "boss_stage" in payload
        assert "failure_report" in payload
        assert payload["failure_report"] is None
        assert "current_team" in payload
        assert "top_5_candidates" in payload

        # 2. Boss Stage Details
        bs = payload["boss_stage"]
        assert bs["event_name"] == sample_boss_stage.event_name
        assert bs["stage_name"] == sample_boss_stage.stage_name
        assert bs["difficulty"] == sample_boss_stage.difficulty
        assert len(bs["phases"]) == len(sample_boss_stage.phases)
        assert bs["phases"][2]["cancels_dodge"] is True
        assert bs["phases"][2]["locks_slots"] is True

        # 3. Current Team
        team_members = payload["current_team"]
        assert len(team_members) == 5
        for m in team_members:
            assert "card_id" in m
            assert "name" in m
            assert "element" in m
            assert "role" in m

        # 4. Top 5 Candidates
        top_cands = payload["top_5_candidates"]
        assert len(top_cands) <= 5
        for i, c in enumerate(top_cands):
            assert c["rank"] == i + 1
            assert "card_id" in c
            assert "name" in c
            assert "element" in c
            assert "leader_coverage_pct" in c
            assert "base_slot1_viable" in c
            assert "solver_score" in c
            assert "passive_skill" in c
            assert "super_attack" in c
            assert "counter_points" in c
            assert "penalty_points" in c

    def test_payload_structure_with_failure_report(
        self,
        sample_leader_200: DokkanCard,
        candidate_pool_sample: list[DokkanCard],
        sample_boss_stage: BossStage,
    ) -> None:
        tb = TeamBuilder()
        current_team = candidate_pool_sample[:5]
        candidates = tb.get_top_candidates(
            candidate_pool=candidate_pool_sample,
            leader=sample_leader_200,
            boss_stage=sample_boss_stage,
            top_k=5,
        )

        report = FailureReport(
            defeat_turn=3,
            phase_index=3,
            boss_element=3,
            boss_hp_percent=14.5,
            culprit_card_id=1005,
            classification="DirectCulprit",
            reason="Took 620,000 Super Attack damage in Slot 3 against STR Phase",
        )

        payload = TeamBuilder.build_advisor_payload(
            boss_stage=sample_boss_stage,
            current_team=current_team,
            top_candidates=candidates,
            failure_report=report,
        )

        assert payload["failure_report"] is not None
        fr = payload["failure_report"]
        assert fr["defeat_turn"] == 3
        assert fr["phase_index"] == 3
        assert fr["boss_hp_percent"] == 14.5
        assert fr["culprit_card_id"] == 1005
        assert fr["classification"] == "DirectCulprit"
        assert fr["reason"] == "Took 620,000 Super Attack damage in Slot 3 against STR Phase"


class TestGracefulDegradation:
    """Verifies strict zero-crash graceful degradation across all failure modes."""

    def test_server_offline_fallback_to_candidate_1(
        self, candidate_pool_sample: list[DokkanCard], sample_boss_stage: BossStage
    ) -> None:
        tb = TeamBuilder()
        cands = [
            CandidateEvaluation(
                card=candidate_pool_sample[1],
                score=95.0,
                lead_boost_pct=170.0,
                base_slot1_viable=True,
            ),
            CandidateEvaluation(
                card=candidate_pool_sample[2],
                score=90.0,
                lead_boost_pct=200.0,
                base_slot1_viable=False,
            ),
        ]

        mock_client = MagicMock(spec=DokkanAIClient)
        mock_client.is_available.return_value = False

        chosen, reason = tb.consult_ollama_advisor(
            top_candidates=cands,
            current_team=candidate_pool_sample[:5],
            boss_stage=sample_boss_stage,
            ai_client=mock_client,
        )

        assert chosen.id == cands[0].card.id
        assert "Offline / Graceful Fallback" in reason
        mock_client.chat_completion.assert_not_called()

    def test_timeout_fallback_to_candidate_1(
        self, candidate_pool_sample: list[DokkanCard], sample_boss_stage: BossStage
    ) -> None:
        tb = TeamBuilder()
        cands = [
            CandidateEvaluation(
                card=candidate_pool_sample[1],
                score=95.0,
                lead_boost_pct=170.0,
                base_slot1_viable=True,
            ),
            CandidateEvaluation(
                card=candidate_pool_sample[2],
                score=90.0,
                lead_boost_pct=200.0,
                base_slot1_viable=False,
            ),
        ]

        mock_client = MagicMock(spec=DokkanAIClient)
        mock_client.is_available.return_value = True
        mock_client.chat_completion.side_effect = requests.exceptions.Timeout(
            "HTTP request to Ollama timed out (> 75s)"
        )

        chosen, reason = tb.consult_ollama_advisor(
            top_candidates=cands,
            current_team=candidate_pool_sample[:5],
            boss_stage=sample_boss_stage,
            ai_client=mock_client,
        )

        assert chosen.id == cands[0].card.id
        assert "Ollama Timeout Fallback (>75s)" in reason

    def test_timeout_error_fallback_to_candidate_1(
        self, candidate_pool_sample: list[DokkanCard], sample_boss_stage: BossStage
    ) -> None:
        tb = TeamBuilder()
        cands = [
            CandidateEvaluation(
                card=candidate_pool_sample[1],
                score=95.0,
                lead_boost_pct=170.0,
                base_slot1_viable=True,
            ),
            CandidateEvaluation(
                card=candidate_pool_sample[2],
                score=90.0,
                lead_boost_pct=200.0,
                base_slot1_viable=False,
            ),
        ]

        mock_client = MagicMock(spec=DokkanAIClient)
        mock_client.is_available.return_value = True
        mock_client.chat_completion.side_effect = TimeoutError("Connection timed out after 75s")

        chosen, reason = tb.consult_ollama_advisor(
            top_candidates=cands,
            current_team=candidate_pool_sample[:5],
            boss_stage=sample_boss_stage,
            ai_client=mock_client,
        )

        assert chosen.id == cands[0].card.id
        assert "Ollama Timeout Fallback (>75s)" in reason

    def test_hallucinated_id_outside_shortlist_fallback_to_candidate_1(
        self, candidate_pool_sample: list[DokkanCard], sample_boss_stage: BossStage
    ) -> None:
        tb = TeamBuilder()
        cands = [
            CandidateEvaluation(
                card=candidate_pool_sample[1],
                score=95.0,
                lead_boost_pct=170.0,
                base_slot1_viable=True,
            ),
            CandidateEvaluation(
                card=candidate_pool_sample[2],
                score=90.0,
                lead_boost_pct=200.0,
                base_slot1_viable=False,
            ),
        ]

        mock_client = MagicMock(spec=DokkanAIClient)
        mock_client.is_available.return_value = True
        # Model hallucinated ID 999999 not present in cands
        mock_client.chat_completion.return_value = (
            json.dumps(
                {"selected_card_id": 999999, "reasoning": "Scelgo questo personaggio inventato"}
            ),
            "Chain of Thought",
        )

        chosen, reason = tb.consult_ollama_advisor(
            top_candidates=cands,
            current_team=candidate_pool_sample[:5],
            boss_stage=sample_boss_stage,
            ai_client=mock_client,
        )

        assert chosen.id == cands[0].card.id
        assert "Invalid / Hallucinated ID Fallback" in reason

    def test_valid_json_response_selects_advisor_candidate(
        self, candidate_pool_sample: list[DokkanCard], sample_boss_stage: BossStage
    ) -> None:
        tb = TeamBuilder()
        cands = [
            CandidateEvaluation(
                card=candidate_pool_sample[1],
                score=95.0,
                lead_boost_pct=170.0,
                base_slot1_viable=True,
            ),
            CandidateEvaluation(
                card=candidate_pool_sample[2],
                score=90.0,
                lead_boost_pct=200.0,
                base_slot1_viable=False,
            ),
        ]

        mock_client = MagicMock(spec=DokkanAIClient)
        mock_client.is_available.return_value = True
        mock_client.chat_completion.return_value = (
            json.dumps(
                {
                    "selected_card_id": candidate_pool_sample[2].id,
                    "reasoning": "MUI Goku fornisce schivata critica e chiude il boss rapidamente",
                }
            ),
            "CoT: Valutazione schivate",
        )

        chosen, reason = tb.consult_ollama_advisor(
            top_candidates=cands,
            current_team=candidate_pool_sample[:5],
            boss_stage=sample_boss_stage,
            ai_client=mock_client,
        )

        assert chosen.id == candidate_pool_sample[2].id
        assert "MUI Goku fornisce schivata critica" in reason
        assert "Qwen Advisor:" in reason

    def test_malformed_json_fallback_to_candidate_1(
        self, candidate_pool_sample: list[DokkanCard], sample_boss_stage: BossStage
    ) -> None:
        tb = TeamBuilder()
        cands = [
            CandidateEvaluation(
                card=candidate_pool_sample[1],
                score=95.0,
                lead_boost_pct=170.0,
                base_slot1_viable=True,
            ),
            CandidateEvaluation(
                card=candidate_pool_sample[2],
                score=90.0,
                lead_boost_pct=200.0,
                base_slot1_viable=False,
            ),
        ]

        mock_client = MagicMock(spec=DokkanAIClient)
        mock_client.is_available.return_value = True
        # Model returned broken text
        mock_client.chat_completion.return_value = (
            "Ecco la mia risposta: non ho un JSON valido da darti {id: broken",
            None,
        )

        chosen, reason = tb.consult_ollama_advisor(
            top_candidates=cands,
            current_team=candidate_pool_sample[:5],
            boss_stage=sample_boss_stage,
            ai_client=mock_client,
        )

        assert chosen.id == cands[0].card.id
        assert "Malformed Response Fallback" in reason

    def test_ai_advisor_disabled_in_config_fallback_to_candidate_1(
        self, candidate_pool_sample: list[DokkanCard], sample_boss_stage: BossStage
    ) -> None:
        tb = TeamBuilder()
        cands = [
            CandidateEvaluation(
                card=candidate_pool_sample[1],
                score=95.0,
                lead_boost_pct=170.0,
                base_slot1_viable=True,
            ),
            CandidateEvaluation(
                card=candidate_pool_sample[2],
                score=90.0,
                lead_boost_pct=200.0,
                base_slot1_viable=False,
            ),
        ]

        mock_client = MagicMock(spec=DokkanAIClient)
        mock_client.config = AIConfig(enabled=False)

        chosen, reason = tb.consult_ollama_advisor(
            top_candidates=cands,
            current_team=candidate_pool_sample[:5],
            boss_stage=sample_boss_stage,
            ai_client=mock_client,
        )

        assert chosen.id == cands[0].card.id
        assert "AI Advisor Disabled in Settings" in reason
        mock_client.is_available.assert_not_called()
        mock_client.chat_completion.assert_not_called()


class TestFullTeamRecommendationIntegration:
    """End-to-end integration tests combining DokkanConstraintSolver and Ollama Advisor."""

    def test_full_team_recommendation_with_advisor_tie_break(
        self,
        sample_leader_200: DokkanCard,
        candidate_pool_sample: list[DokkanCard],
        sample_boss_stage: BossStage,
    ) -> None:
        mock_client = MagicMock(spec=DokkanAIClient)
        mock_client.config = AIConfig(enabled=True)
        mock_client.is_available.return_value = True

        # Advisor suggests candidate with ID 1007 (Whis)
        mock_client.chat_completion.return_value = (
            json.dumps(
                {
                    "selected_card_id": 1007,
                    "reasoning": "Whis garantisce supporto Ki +2 e ATK/DEF +40% a tutto il team",
                }
            ),
            "CoT: Support and dodge needed for Broly",
        )
        mock_client.analyze_team_strategy.return_value = (
            "Tactical guide for Broly",
            "Reasoning for rotations and items",
        )

        tb = TeamBuilder(ai_client=mock_client)
        team_rec, shortlist = tb.select_best_team_for_boss(
            candidate_pool=candidate_pool_sample,
            boss_stage=sample_boss_stage,
            forced_leader=sample_leader_200,
            use_ai_advisor=True,
        )

        # 1. Exactly 6 cards
        assert len(team_rec.all_cards) == 6
        assert len({c.id for c in team_rec.all_cards}) == 6
        assert team_rec.leader.id == sample_leader_200.id

        # 2. Rotations A and B defined (with 7-unit combat team including Friend Leader, 3 floaters)
        assert team_rec.rotation_a is not None
        assert team_rec.rotation_b is not None
        assert len(team_rec.floaters) == 3

        # 3. Two-phase survival constraint (>= 2 slot 1 viable)
        slot1_count = sum(
            1
            for c in team_rec.all_cards
            if (c.base_form and c.base_form.passive_tags and c.base_form.passive_tags.slot1_viable)
            or c.is_slot1_tank
        )
        assert slot1_count >= 2

        # 4. AI Advisor candidate integrated
        assert any(c.id == 1007 for c in team_rec.all_cards)
        assert team_rec.ai_reasoning is not None
        assert "Whis garantisce supporto" in team_rec.ai_reasoning

        # 5. Shortlist contains runner-ups excluding team cards
        team_ids = {c.id for c in team_rec.all_cards}
        for ev in shortlist:
            assert ev.card.id not in team_ids

    def test_full_team_recommendation_with_offline_advisor_falls_back(
        self,
        sample_leader_200: DokkanCard,
        candidate_pool_sample: list[DokkanCard],
        sample_boss_stage: BossStage,
    ) -> None:
        mock_client = MagicMock(spec=DokkanAIClient)
        mock_client.config = AIConfig(enabled=True)
        mock_client.is_available.return_value = False

        tb = TeamBuilder(ai_client=mock_client)
        team_rec, shortlist = tb.select_best_team_for_boss(
            candidate_pool=candidate_pool_sample,
            boss_stage=sample_boss_stage,
            forced_leader=sample_leader_200,
            use_ai_advisor=True,
        )

        assert len(team_rec.all_cards) == 6
        assert len(shortlist) > 0
        assert team_rec.ai_reasoning is not None
        assert "Offline / Graceful Fallback" in team_rec.ai_reasoning


class TestTeamBuilderUserBoxAndTableFormatting:
    """Verifies user box loading, multiline name sanitization, and category resolution."""

    def test_load_user_box_parses_serialized_cards(self, tmp_path) -> None:
        box_file = tmp_path / "test_user_box.json"
        card_data = {
            "cards": [
                {
                    "id": 1030431,
                    "name": "Super Saiyan Goku + Super Saiyan Vegeta (Angel)",
                    "subname": "Incomparable Radiance",
                    "element": 11,
                    "element_name": "Super TEQ",
                    "category_ids": [17, 85, 95],
                    "categories": ["Pure Saiyans", "Fused Fighters", "Earth-Protecting Heroes"],
                    "leader_spec": {
                        "main_category_ids": [17, 85, 95],
                        "extra_category_ids": [10, 89],
                        "base_boost_pct": 170,
                        "extra_boost_pct": 50,
                    },
                }
            ]
        }
        box_file.write_text(json.dumps(card_data), encoding="utf-8")

        loaded = TeamBuilder.load_user_box(str(box_file))
        assert len(loaded) == 1
        card = loaded[0]
        assert card.id == 1030431
        assert card.name == "Super Saiyan Goku + Super Saiyan Vegeta (Angel)"
        assert card.leader_spec is not None
        assert card.leader_spec.extra_boost_pct == 50

    def test_format_team_summary_table_removes_embedded_newlines(self) -> None:
        from dokkan_eza_link_farmer.ai.team_builder import format_team_summary_table

        card_with_newline = DokkanCard(
            id=1022381,
            name="Super Saiyan God Goku &\nSuper Saiyan God Vegeta",
            subname="Divine Warriors\nwith Infinite Power",
            element_name="Super TEQ",
            category_ids=[17],
            categories=["Pure Saiyans"],
        )
        lead = DokkanCard(
            id=1030431,
            name="Leader",
            element_name="Super TEQ",
            category_ids=[17],
            categories=["Pure Saiyans"],
            leader_spec=LeaderSkillSpec(main_category_ids=[17], base_boost_pct=170),
        )
        team = [lead, card_with_newline] + [
            DokkanCard(
                id=8000 + i, name=f"Filler {i}", category_ids=[17], categories=["Pure Saiyans"]
            )
            for i in range(4)
        ]

        table = format_team_summary_table(team)
        # Every slot row must be on a single physical line (no literal newline in the name column)
        assert (
            "Super Saiyan God Goku & Super Saiyan God Vegeta (Divine Warriors with Infinite Power)"
            in table
        )
        assert "&\n" not in table

    def test_resolve_category_name_fallback_to_global_catalog(self) -> None:
        from dokkan_eza_link_farmer.ai.team_builder import _resolve_category_name

        # Card has category ID 95 but empty categories list
        card = DokkanCard(id=9999, name="Blank Cats", category_ids=[95], categories=[])
        leader = DokkanCard(id=9998, name="Blank Lead", category_ids=[], categories=[])

        resolved = _resolve_category_name(95, card, leader)
        # If dokkandb_categories.json exists on system, it resolves to 'Earth-Protecting Heroes', otherwise '95'
        assert resolved in ("Earth-Protecting Heroes", "95")

    def test_dokkan_card_type_colors_and_rich_formatting(self) -> None:
        from rich.text import Text

        from dokkan_eza_link_farmer.ai.team_builder import render_team_summary_table_rich

        agl_card = DokkanCard(id=1, name="Goku", element=10, element_name="Super AGL")
        teq_card = DokkanCard(id=2, name="Vegeta", element=11, element_name="Super TEQ")
        int_card = DokkanCard(id=3, name="Trunks", element=22, element_name="Extreme INT")
        str_card = DokkanCard(id=4, name="Broly", element=23, element_name="Extreme STR")
        phy_card = DokkanCard(id=5, name="Gogeta", element=14, element_name="Super PHY")
        extra_card = DokkanCard(id=6, name="Piccolo", element=11, element_name="Super TEQ")

        assert agl_card.element_color == "bold cyan"
        assert teq_card.element_color == "bold green"
        assert int_card.element_color == "bold magenta"
        assert str_card.element_color == "bold red"
        assert phy_card.element_color == "bold yellow"

        assert agl_card.type_tag == "AGL"
        assert "[bold cyan]" in agl_card.dokkan_colored_name

        rich_txt = agl_card.rich_formatted_name()
        assert isinstance(rich_txt, Text)
        assert rich_txt.style == "bold cyan"
        assert "[Super AGL] Goku" in rich_txt.plain

        team = [agl_card, teq_card, int_card, str_card, phy_card, extra_card]
        rich_table = render_team_summary_table_rich(team)
        assert rich_table is not None
        assert len(rich_table.rows) == 6

    def test_consult_ollama_advisor_reasoning_fallback_and_markdown(
        self, candidate_pool_sample: list[DokkanCard], sample_boss_stage: BossStage
    ) -> None:
        tb = TeamBuilder()
        cands = [
            CandidateEvaluation(
                card=candidate_pool_sample[1],
                score=95.0,
                lead_boost_pct=170.0,
                base_slot1_viable=True,
            ),
            CandidateEvaluation(
                card=candidate_pool_sample[2],
                score=90.0,
                lead_boost_pct=200.0,
                base_slot1_viable=False,
            ),
        ]

        mock_client = MagicMock(spec=DokkanAIClient)
        mock_client.is_available.return_value = True

        # Case 1: Markdown code block in content
        mock_client.chat_completion.return_value = (
            f'```json\n{{"selected_card_id": {cands[1].card.id}, "confidence": 0.9, "reasoning": "Best guard"}}\n```',
            "Thought process here",
        )
        chosen, reason = tb.consult_ollama_advisor(
            top_candidates=cands,
            current_team=candidate_pool_sample[:5],
            boss_stage=sample_boss_stage,
            ai_client=mock_client,
        )
        assert chosen.id == cands[1].card.id
        assert "Best guard" in reason

        # Case 2: Content empty (DeepSeek-R1 token truncation), JSON present in reasoning
        mock_client.chat_completion.return_value = (
            "",
            f'I think the best card is: {{"selected_card_id": {cands[1].card.id}, "confidence": 0.85, "reasoning": "Extracted from reasoning"}}',
        )
        chosen2, reason2 = tb.consult_ollama_advisor(
            top_candidates=cands,
            current_team=candidate_pool_sample[:5],
            boss_stage=sample_boss_stage,
            ai_client=mock_client,
        )
        assert chosen2.id == cands[1].card.id
        assert "Extracted from reasoning" in reason2

    def test_select_best_team_for_boss_generate_tactics_false(
        self, candidate_pool_sample: list[DokkanCard], sample_boss_stage: BossStage
    ) -> None:
        mock_client = MagicMock(spec=DokkanAIClient)
        mock_client.is_available.return_value = True
        mock_client.chat_completion.return_value = (
            f'{{"selected_card_id": {candidate_pool_sample[5].id}, "confidence": 0.9, "reasoning": "Solid floater"}}',
            None,
        )

        tb = TeamBuilder(ai_client=mock_client)
        rec, _ = tb.select_best_team_for_boss(
            candidate_pool=candidate_pool_sample,
            boss_stage=sample_boss_stage,
            generate_tactics=False,
        )
        assert len(rec.all_cards) == 6
        # analyze_team_strategy must NOT be called when generate_tactics=False
        mock_client.analyze_team_strategy.assert_not_called()
        assert "Piano Tattico Deterministico" in rec.tactical_analysis

    def test_build_advisor_payload_with_mission_batch(
        self,
        sample_leader_200: DokkanCard,
        candidate_pool_sample: list[DokkanCard],
        sample_boss_stage: BossStage,
    ) -> None:
        tb = TeamBuilder()
        from dokkan_eza_link_farmer.ai.mission_solver import ChallengeMission, MissionBatch

        batch = MissionBatch(
            missions=[
                ChallengeMission(
                    id=1,
                    name="Clear with 3 Movie Heroes",
                    description="Clear stage with 3 or more Movie Heroes",
                    categories=[(3, "Movie Heroes")],
                )
            ],
            required_categories=[(3, "Movie Heroes")],
            requires_rainbow=True,
            requires_all_super=True,
        )

        candidates = tb.get_top_candidates(
            candidate_pool=candidate_pool_sample,
            leader=sample_leader_200,
            boss_stage=sample_boss_stage,
            top_k=5,
        )

        payload = TeamBuilder.build_advisor_payload(
            boss_stage=sample_boss_stage,
            current_team=candidate_pool_sample[:5],
            top_candidates=candidates,
            mission_batch=batch,
        )

        assert "mission_batch" in payload
        mb = payload["mission_batch"]
        assert mb["requires_rainbow"] is True
        assert mb["requires_all_super"] is True
        assert len(mb["required_categories"]) == 1
        assert mb["required_categories"][0]["category"] == "Movie Heroes"
        assert mb["required_categories"][0]["count"] == 3

    def test_select_best_team_for_boss_filters_candidates_for_mission_deficit(
        self,
        candidate_pool_sample: list[DokkanCard],
        sample_boss_stage: BossStage,
    ) -> None:
        from dokkan_eza_link_farmer.ai.mission_solver import ChallengeMission, MissionBatch

        mock_client = MagicMock(spec=DokkanAIClient)
        mock_client.is_available.return_value = True

        # Ensure cards in candidate_pool_sample have string categories populated:
        # 1001, 1002, 1004 have "Realm of Gods"
        # 1003, 1005 have "Fusion"
        # 1006, 1007, 1008 do not have "Realm of Gods"
        pool = []
        for c in candidate_pool_sample:
            new_c = DokkanCard(
                id=c.id,
                name=c.name,
                element=c.element,
                element_name=c.element_name,
                rarity=c.rarity,
                category_ids=list(c.category_ids),
                categories=["Realm of Gods"] if c.id in (1001, 1002, 1004) else ["Pure Saiyans"],
                leader_skill=c.leader_skill,
                leader_spec=c.leader_spec,
                base_form=c.base_form,
                transformations=c.transformations,
                links=list(c.links),
            )
            pool.append(new_c)

        def fake_chat_completion(messages, **_kwargs):
            user_msg = next(m["content"] for m in messages if m["role"] == "user")
            system_msg = next(m["content"] for m in messages if m["role"] == "system")
            assert "CRITICAL MANDATORY REQUIREMENT" in system_msg
            assert "ACTIVE MISSION CONSTRAINTS" in user_msg

            # 1004 has Realm of Gods
            return (
                json.dumps({"selected_card_id": 1004, "reasoning": "Fits mission Realm of Gods"}),
                None,
            )

        mock_client.chat_completion.side_effect = fake_chat_completion

        batch = MissionBatch(
            missions=[
                ChallengeMission(
                    id=1,
                    name="Clear with Realm of Gods",
                    description="Clear stage with Realm of Gods",
                    categories=[(3, "Realm of Gods")],
                )
            ],
            required_categories=[(3, "Realm of Gods")],
        )

        tb = TeamBuilder(ai_client=mock_client)
        rec, _ = tb.select_best_team_for_boss(
            candidate_pool=pool,
            boss_stage=sample_boss_stage,
            forced_leader=pool[0],
            mission_batch=batch,
            use_ai_advisor=True,
            generate_tactics=False,
        )

        # Team must satisfy mission (at least 3 Realm of Gods cards)
        passed, reasons = batch.matches_team(rec.all_cards)
        assert passed, f"Team failed mission: {reasons}"
        assert any(c.id == 1004 for c in rec.all_cards)


class TestFriendLeaderAndRotationConsistency:
    """Tests for friend leader selection hierarchy, fallback and rotation consistency."""

    def test_identical_card_highest_priority(self, sample_leader_200: DokkanCard):
        tb = TeamBuilder()
        identical_friend = DokkanCard(
            id=sample_leader_200.id,
            name=sample_leader_200.name,
            leader_skill=sample_leader_200.leader_skill,
            leader_spec=sample_leader_200.leader_spec,
            category_ids=list(sample_leader_200.category_ids),
            categories=list(sample_leader_200.categories),
        )
        another_cand = DokkanCard(
            id=9999,
            name="Another Compatible Lead",
            leader_skill=sample_leader_200.leader_skill,
            leader_spec=sample_leader_200.leader_spec,
            category_ids=list(sample_leader_200.category_ids),
            categories=list(sample_leader_200.categories),
        )

        team = [sample_leader_200] + [
            DokkanCard(
                id=2000 + i,
                name=f"Sub {i}",
                category_ids=[10, 20],
                categories=["Realm of Gods"],
            )
            for i in range(5)
        ]

        # Put another_cand first to ensure priority is by id match, not pool position
        selected = tb.select_best_friend_leader(team, [another_cand, identical_friend])
        assert selected.id == sample_leader_200.id
        assert getattr(selected, "is_friend_leader", False) is True

    def test_fallback_to_exact_copy_of_leader_when_pool_incompatible_or_empty(
        self, sample_leader_200: DokkanCard
    ):
        tb = TeamBuilder()
        incompatible_cand = DokkanCard(
            id=8888,
            name="Incompatible Unit",
            leader_skill="Namekians Ki +3, Stats +170%",
            leader_spec=LeaderSkillSpec(main_category_ids=[999], base_boost_pct=170),
            category_ids=[999],
            categories=["Namekians"],
        )

        team = [sample_leader_200] + [
            DokkanCard(
                id=2000 + i,
                name=f"Sub {i}",
                category_ids=[10, 20],
                categories=["Realm of Gods"],
            )
            for i in range(5)
        ]

        # 1. Incompatible pool -> fallback to copy of leader
        friend_incompat = tb.select_best_friend_leader(team, [incompatible_cand])
        assert friend_incompat.id == sample_leader_200.id
        assert getattr(friend_incompat, "is_friend_leader", False) is True

        # 2. Empty candidate pool -> fallback to copy of leader
        friend_empty = tb.select_best_friend_leader(team, [])
        assert friend_empty.id == sample_leader_200.id
        assert getattr(friend_empty, "is_friend_leader", False) is True

    def test_compatible_candidate_selection_when_covering_five_members(
        self, sample_leader_200: DokkanCard
    ):
        tb = TeamBuilder()
        compatible_cand = DokkanCard(
            id=7777,
            name="Compatible Different Unit",
            leader_skill="Realm of Gods Ki +3, Stats +170%",
            leader_spec=LeaderSkillSpec(main_category_ids=[10], base_boost_pct=170),
            category_ids=[10],
            categories=["Realm of Gods"],
        )

        team = [sample_leader_200] + [
            DokkanCard(
                id=2000 + i,
                name=f"Sub {i}",
                category_ids=[10],
                categories=["Realm of Gods"],
            )
            for i in range(5)
        ]

        selected = tb.select_best_friend_leader(team, [compatible_cand])
        assert selected.id == 7777
        assert getattr(selected, "is_friend_leader", False) is True

    def test_rotation_labeling_and_friend_leader_consistency(self, sample_leader_200: DokkanCard):
        tb = TeamBuilder()
        team = [sample_leader_200] + [
            DokkanCard(
                id=3000 + i,
                name=f"Sub {i}",
                category_ids=[10, 20, 30],
                categories=["Realm of Gods", "Future Saga"],
                links=["Super Saiyan", "Prepared for Battle"],
                base_form=CardForm(
                    form_id=3000 + i,
                    passive_tags=PassiveTags(slot1_viable=True, dr_base_percent=50, has_guard=True),
                ),
            )
            for i in range(5)
        ]

        # Friend with lower boost (170% without extra 30% Future Saga)
        friend_lower_boost = DokkanCard(
            id=4001,
            name="Friend Lower Boost",
            leader_skill="Realm of Gods Ki +3, Stats +170%",
            leader_spec=LeaderSkillSpec(main_category_ids=[10], base_boost_pct=170),
            category_ids=[10],
            categories=["Realm of Gods"],
            links=["Super Saiyan", "Prepared for Battle"],
        )

        rec = tb.build_team_plan(team, friend_leader=friend_lower_boost, generate_tactics=False)
        assert getattr(rec.friend_leader, "is_friend_leader", False) is True
        assert rec.friend_leader.id == 4001

        # Summary text must include [Friend Leader] and [Leader] badges
        summary = rec.tactical_analysis
        assert "[Friend Leader]" in summary
        assert "[Leader]" in summary

        # Check that floaters contain friend or friend is labeled properly
        floater_ids = [f.id for f in rec.floaters]
        # Since friend gets only 170% while all subs get 200%, friend should not displace the 200% core starters
        assert 4001 in floater_ids

    def test_friend_leader_does_not_displace_core_starter_even_with_high_synergy_links(
        self, sample_leader_200: DokkanCard
    ):
        """Friend leader with top-tier link synergy but inferior boost (<200%) should be floated."""
        tb = TeamBuilder()
        # Subs have 200% boost and standard links
        team = [sample_leader_200] + [
            DokkanCard(
                id=5000 + i,
                name=f"Sub {i}",
                category_ids=[10, 20],  # 200% under sample_leader_200
                categories=["Realm of Gods", "Future Saga"],
                links=["Super Saiyan", "Prepared for Battle", "Fierce Battle"],
                base_form=CardForm(
                    form_id=5000 + i,
                    passive_tags=PassiveTags(slot1_viable=True, dr_base_percent=40, has_guard=True),
                ),
            )
            for i in range(5)
        ]

        # Friend only has 170% boost (lacks Future Saga), but shares ALL 7 links with Sub 0
        friend_high_links_low_boost = DokkanCard(
            id=6001,
            name="Friend High Synergy Low Boost",
            leader_skill="Realm of Gods Ki +3, Stats +170%",
            leader_spec=LeaderSkillSpec(main_category_ids=[10], base_boost_pct=170),
            category_ids=[10],  # only 170%
            categories=["Realm of Gods"],
            links=[
                "Super Saiyan",
                "Prepared for Battle",
                "Fierce Battle",
                "Warrior Gods",
                "Godly Power",
            ],
            base_form=CardForm(
                form_id=6001,
                passive_tags=PassiveTags(slot1_viable=True, dr_base_percent=40, has_guard=True),
            ),
        )

        rec = tb.build_team_plan(
            team, friend_leader=friend_high_links_low_boost, generate_tactics=False
        )
        assert getattr(rec.friend_leader, "is_friend_leader", False) is True
        assert rec.friend_leader.id in [f.id for f in rec.floaters]
        assert "[Friend Leader]" in rec.tactical_analysis


class TestMultiEnemyAdvisorAndBriefing:
    """Verifies multi-enemy telemetry formatting across Qwen Advisor, Tactical Briefing, and Rich CLI."""

    @pytest.fixture
    def multi_enemy_boss_stage(self) -> BossStage:
        from dokkan_eza_link_farmer.ai.models import BossEnemy

        minions = [
            BossEnemy(
                card_id=901,
                name="Cell Jr. (AGL)",
                element=0,
                type_name="AGL",
                hp=31_000_000,
                atk=400_000,
                actions_per_turn=1,
            ),
            BossEnemy(
                card_id=902,
                name="Cell Jr. (TEQ)",
                element=1,
                type_name="TEQ",
                hp=31_000_000,
                atk=400_000,
                actions_per_turn=1,
            ),
            BossEnemy(
                card_id=903,
                name="Cell Jr. (INT)",
                element=2,
                type_name="INT",
                hp=31_000_000,
                atk=400_000,
                actions_per_turn=1,
            ),
            BossEnemy(
                card_id=904,
                name="Cell Jr. (STR)",
                element=3,
                type_name="STR",
                hp=31_000_000,
                atk=400_000,
                actions_per_turn=1,
            ),
            BossEnemy(
                card_id=905,
                name="Cell Jr. (PHY)",
                element=4,
                type_name="PHY",
                hp=31_000_000,
                atk=400_000,
                actions_per_turn=1,
            ),
        ]
        phase1 = BossPhase(
            phase_index=1,
            battle_index=1,
            round_index=1,
            bosses=minions,
            hp=155_000_000,
            atk=400_000,
            actions_per_turn=5,
        )
        phase2 = BossPhase(
            phase_index=2,
            battle_index=1,
            round_index=2,
            bosses=[
                BossEnemy(
                    card_id=999,
                    name="Perfect Cell",
                    element=1,
                    type_name="TEQ",
                    hp=80_000_000,
                    atk=850_000,
                    actions_per_turn=8,
                )
            ],
            hp=80_000_000,
            atk=850_000,
            actions_per_turn=8,
            cancels_dodge=True,
        )
        return BossStage(
            stage_id=500,
            event_id=50,
            event_name="Battlefield Clash",
            stage_name="Stage 3: Cell Games",
            difficulty=10,
            phases=[phase1, phase2],
        )

    def test_build_advisor_payload_multi_enemy_fields(
        self,
        candidate_pool_sample: list[DokkanCard],
        multi_enemy_boss_stage: BossStage,
    ) -> None:
        tb = TeamBuilder()
        cands = [
            CandidateEvaluation(
                card=candidate_pool_sample[1],
                score=90.0,
                lead_boost_pct=170.0,
                base_slot1_viable=True,
            )
        ]
        payload = tb.build_advisor_payload(
            boss_stage=multi_enemy_boss_stage,
            current_team=candidate_pool_sample[:5],
            top_candidates=cands,
        )
        phases = payload["boss_stage"]["phases"]
        assert len(phases) == 2

        # Phase 1: Multi-enemy Rainbow
        p1 = phases[0]
        assert p1["enemy_count"] == 5
        assert p1["is_multi_enemy"] is True
        assert p1["is_rainbow"] is True
        assert "enemies" in p1
        assert len(p1["enemies"]) == 5
        assert p1["enemies"][0]["name"] == "Cell Jr. (AGL)"
        assert p1["enemies"][0]["element"] == "AGL"
        assert p1["enemies"][0]["hp"] == 31_000_000
        assert p1["enemies"][0]["atk"] == 400_000

        # Phase 2: Single enemy
        p2 = phases[1]
        assert p2["enemy_count"] == 1
        assert p2["is_multi_enemy"] is False
        assert p2["is_rainbow"] is False
        assert "enemies" not in p2

    def test_consult_ollama_advisor_multi_enemy_prompt(
        self,
        candidate_pool_sample: list[DokkanCard],
        multi_enemy_boss_stage: BossStage,
    ) -> None:
        tb = TeamBuilder()
        cands = [
            CandidateEvaluation(
                card=candidate_pool_sample[1],
                score=90.0,
                lead_boost_pct=170.0,
                base_slot1_viable=True,
            )
        ]
        mock_client = MagicMock(spec=DokkanAIClient)
        mock_client.is_available.return_value = True
        mock_client.chat_completion.return_value = (
            f'{{"selected_card_id": {cands[0].card.id}, "reasoning": "Eccellente AoE"}}',
            "Thought",
        )

        chosen, reason = tb.consult_ollama_advisor(
            top_candidates=cands,
            current_team=candidate_pool_sample[:5],
            boss_stage=multi_enemy_boss_stage,
            ai_client=mock_client,
        )

        # Inspect messages passed to chat_completion
        call_args = mock_client.chat_completion.call_args[0][0]
        system_content = next(m["content"] for m in call_args if m["role"] == "system")
        user_content = next(m["content"] for m in call_args if m["role"] == "user")

        assert (
            "When multi-enemy phases are present, strongly prioritize AoE attackers"
            in system_content
        )
        assert "unconditional Guard that protect against rainbow attacks" in system_content
        assert (
            "CRITICAL MANDATORY REQUIREMENT: You MUST evaluate unit survivability and effectiveness across ALL battles and ALL phases of the stage"
            in system_content
        )
        assert (
            "A candidate that is strong against the final boss but has severe type disadvantage or dies in Phase 1"
            in system_content
        )
        assert (
            "Phase 1: Rainbow (5 Enemies: All 5 Types) - Total HP: 155M, Actions: 5/turn"
            in user_content
        )

    def test_format_stage_tactical_briefing_multi_enemy(
        self,
        multi_enemy_boss_stage: BossStage,
    ) -> None:
        from dokkan_eza_link_farmer.ai.team_builder import format_stage_tactical_briefing

        # Italian briefing
        briefing_it = format_stage_tactical_briefing(multi_enemy_boss_stage, language="it")
        assert "👥 5 Nemici [Rainbow (5 Enemies: All 5 Types)]" in briefing_it
        assert "**Cell Jr. (AGL)** [AGL]: HP 31M, ATK 400k" in briefing_it
        assert "💡 CONSIGLIO TATTICO: La fase contiene 5 nemici simultanei." in briefing_it
        assert (
            "Personaggi con Super Attacchi AoE o con Guardia incondizionata eccellono qui"
            in briefing_it
        )

        # English briefing
        briefing_en = format_stage_tactical_briefing(multi_enemy_boss_stage, language="en")
        assert "👥 5 Enemies [Rainbow (5 Enemies: All 5 Types)]" in briefing_en
        assert "**Cell Jr. (AGL)** [AGL]: HP 31M, ATK 400k" in briefing_en
        assert "💡 TACTICAL ADVICE: Phase contains 5 simultaneous enemies." in briefing_en

    def test_render_stage_intel_rich_multi_enemy(
        self,
        multi_enemy_boss_stage: BossStage,
    ) -> None:
        from dokkan_eza_link_farmer.ai.team_builder import render_stage_intel_rich

        panel = render_stage_intel_rich(multi_enemy_boss_stage)
        assert panel is not None
        # Extract table from panel
        table = panel.renderable
        rows = list(table.rows)
        assert len(rows) == 2

        # Check column 1 (Boss Nemico / Boss Enemy) for phase 1
        p1_boss_text = table.columns[1]._cells[0]
        plain_text = p1_boss_text.plain if hasattr(p1_boss_text, "plain") else str(p1_boss_text)
        assert (
            "👥 5 Nemici (Rainbow (5 Enemies: All 5 Types))" in plain_text
            or "👥 5 Enemies (Rainbow (5 Enemies: All 5 Types))" in plain_text
        )
        assert "• [AGL] Cell Jr. (AGL)" in plain_text
        assert "• [STR] Cell Jr. (STR)" in plain_text
