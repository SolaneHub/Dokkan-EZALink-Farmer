"""Black-box contract tests for modular synergy and LLM advisor architecture.

Validates that:
- ai/synergy.py functions are pure, deterministic, and compute link and rotation synergy correctly.
- ai/llm_advisor.py correctly strips <think> tags, parses JSON responses, and executes zero-grade fallback.
- TeamBuilder delegates to synergy and llm_advisor with identical public contract behavior for:
  calculate_link_synergy, build_team, and recommend_candidate.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from dokkan_eza_link_farmer.ai.client import DokkanAIClient
from dokkan_eza_link_farmer.ai.llm_advisor import (
    consult_ollama_advisor,
    parse_advisor_response,
    strip_think_tags,
)
from dokkan_eza_link_farmer.ai.models import (
    BossPhase,
    BossStage,
    CardForm,
    DokkanCard,
    LeaderSkillSpec,
    PassiveTags,
    RotationPair,
    SATags,
    TeamRecommendation,
)
from dokkan_eza_link_farmer.ai.solver import CandidateEvaluation
from dokkan_eza_link_farmer.ai.synergy import (
    calculate_link_synergy,
    check_type_matchup,
    evaluate_rotation_pair,
    optimize_rotations_for_team,
)
from dokkan_eza_link_farmer.ai.team_builder import TeamBuilder


@pytest.fixture
def sample_cards() -> list[DokkanCard]:
    spec = LeaderSkillSpec(
        main_category_ids=[17],
        base_boost_pct=170.0,
        extra_boost_pct=30.0,
    )
    c1 = DokkanCard(
        id=101,
        name="Goku",
        element=10,
        leader_skill="Pure Saiyans Ki +3, Stats +170%",
        leader_spec=spec,
        links=["Super Saiyan", "Prepared for Battle", "Fierce Battle"],
        categories=["Pure Saiyans"],
        category_ids=[17],
        base_form=CardForm(
            form_id=101,
            form_name="Goku",
            element=10,
            passive_tags=PassiveTags(slot1_viable=True, has_guard=True, dr_base_percent=50),
            sa_tags=SATags(stacks_def=True),
        ),
    )
    c2 = DokkanCard(
        id=102,
        name="Vegeta",
        element=11,
        links=["Super Saiyan", "Prepared for Battle", "Royal Lineage"],
        categories=["Pure Saiyans"],
        category_ids=[17],
        base_form=CardForm(
            form_id=102,
            form_name="Vegeta",
            element=11,
            passive_tags=PassiveTags(slot1_viable=False, dr_base_percent=30),
            sa_tags=SATags(raise_def_turns=1),
        ),
    )
    c3 = DokkanCard(
        id=103,
        name="Gohan",
        element=12,
        links=["Super Saiyan", "Fierce Battle"],
        categories=["Pure Saiyans"],
        category_ids=[17],
    )
    c4 = DokkanCard(
        id=104,
        name="Trunks",
        element=13,
        links=["Super Saiyan", "Prepared for Battle"],
        categories=["Pure Saiyans"],
        category_ids=[17],
    )
    c5 = DokkanCard(
        id=105,
        name="Piccolo",
        element=14,
        links=["Fierce Battle"],
        categories=["Pure Saiyans"],
        category_ids=[17],
    )
    c6 = DokkanCard(
        id=106,
        name="Krillin",
        element=10,
        links=["Fierce Battle"],
        categories=["Pure Saiyans"],
        category_ids=[17],
    )
    return [c1, c2, c3, c4, c5, c6]


class TestSynergyPureEngine:
    def test_calculate_link_synergy_pure_and_deterministic(
        self, sample_cards: list[DokkanCard]
    ) -> None:
        c1, c2 = sample_cards[0], sample_cards[1]
        score1, shared1, ki1 = calculate_link_synergy(c1, c2)
        score2, shared2, ki2 = calculate_link_synergy(c1, c2)

        assert score1 == score2
        assert shared1 == shared2 == ["Prepared for Battle", "Super Saiyan"]
        assert ki1 == ki2 == ["Prepared for Battle"]
        assert score1 > 0.0

    def test_same_card_or_same_name_returns_zero(self, sample_cards: list[DokkanCard]) -> None:
        c1 = sample_cards[0]
        c1_clone = DokkanCard(id=999, name="Goku", element=10)
        assert calculate_link_synergy(c1, c1) == (0.0, [], [])
        assert calculate_link_synergy(c1, c1_clone) == (0.0, [], [])

    def test_evaluate_rotation_pair_places_tank_in_slot1(
        self, sample_cards: list[DokkanCard]
    ) -> None:
        c1, c2 = sample_cards[0], sample_cards[1]
        rot = evaluate_rotation_pair(c2, c1)
        assert isinstance(rot, RotationPair)
        assert rot.slot1.id == c1.id
        assert rot.slot2.id == c2.id
        assert rot.synergy_score > 0.0

    def test_optimize_rotations_for_team(self, sample_cards: list[DokkanCard]) -> None:
        rot_a, rot_b, floaters = optimize_rotations_for_team(sample_cards)
        assert isinstance(rot_a, RotationPair)
        assert isinstance(rot_b, RotationPair)
        assert len(floaters) == 2
        rot_ids = {rot_a.slot1.id, rot_a.slot2.id, rot_b.slot1.id, rot_b.slot2.id}
        floater_ids = {f.id for f in floaters}
        assert rot_ids.isdisjoint(floater_ids)
        assert len(rot_ids | floater_ids) == 6

    def test_check_type_matchup(self) -> None:
        assert check_type_matchup(0, 3) == 1  # AGL vs STR
        assert check_type_matchup(0, 1) == -1  # AGL vs TEQ
        assert check_type_matchup(0, 0) == 0  # AGL vs AGL


class TestLLMAdvisorModular:
    def test_strip_think_tags(self) -> None:
        raw = '<think>\nThinking about Goku...\n</think>{"selected_card_id": 101}'
        assert strip_think_tags(raw) == '{"selected_card_id": 101}'

        unclosed = "<think>Still thinking..."
        assert strip_think_tags(unclosed) == ""

        plain = '{"selected_card_id": 101}'
        assert strip_think_tags(plain) == plain

    def test_strip_think_tags_case_insensitive_and_nested(self) -> None:
        # Uppercase and mixed case
        assert (
            strip_think_tags('<Think>reasoning</Think>{"selected_card_id": 101}')
            == '{"selected_card_id": 101}'
        )
        assert (
            strip_think_tags('<THINK>all caps</THINK>{"selected_card_id": 101}')
            == '{"selected_card_id": 101}'
        )
        assert (
            strip_think_tags('<tHink>mixed</tHink>{"selected_card_id": 101}')
            == '{"selected_card_id": 101}'
        )

        # Nested think tags
        nested = '<think>outer <think>inner</think> remaining</think>{"selected_card_id": 101}'
        assert strip_think_tags(nested) == '{"selected_card_id": 101}'

        # Think tag with attributes or whitespace
        with_attrs = "<think class='analysis' id='1'>analysis</think>{\"selected_card_id\": 101}"
        assert strip_think_tags(with_attrs) == '{"selected_card_id": 101}'

        # Stray closing tags
        stray = 'prefix </think>{"selected_card_id": 101}'
        assert strip_think_tags(stray) == 'prefix {"selected_card_id": 101}'

    def test_parse_advisor_response_valid_and_markdown(
        self, sample_cards: list[DokkanCard]
    ) -> None:
        cands = [
            CandidateEvaluation(card=c, lead_boost_pct=170.0, score=10.0, base_slot1_viable=False)
            for c in sample_cards[:3]
        ]
        # JSON inside markdown code block
        markdown_resp = '```json\n{"selected_card_id": 102, "reasoning": "Best link partner"}\n```'
        res = parse_advisor_response(markdown_resp, None, cands)
        assert res is not None
        assert res[0] == 102
        assert "Best link partner" in res[1]

        # Unknown ID outside shortlist returns None
        hallucinated = '{"selected_card_id": 9999, "reasoning": "hallucinated"}'
        assert parse_advisor_response(hallucinated, None, cands) is None

    def test_parse_advisor_response_multi_json_resilience(
        self, sample_cards: list[DokkanCard]
    ) -> None:
        cands = [
            CandidateEvaluation(card=c, lead_boost_pct=170.0, score=10.0, base_slot1_viable=False)
            for c in sample_cards[:3]
        ]
        # Multiple JSON objects in text (e.g., example + chosen)
        multi = (
            'Here is a discarded card: {"card_id": 101, "note": "rejected"}. '
            'Optimal pick: {"selected_card_id": 102, "reasoning": "Best partner"}'
        )
        res = parse_advisor_response(multi, None, cands)
        assert res is not None
        assert res[0] == 102
        assert res[1] == "Best partner"

        # Case-insensitive Think tag with braces in reasoning
        with_think_braces = (
            "<Think>Candidate {101} is suboptimal</Think>"
            '{"selected_card_id": 102, "reasoning": "Superior stats"}'
        )
        res2 = parse_advisor_response(with_think_braces, None, cands)
        assert res2 is not None
        assert res2[0] == 102
        assert res2[1] == "Superior stats"

    def test_parse_advisor_response_truncated_json_and_token_boundaries(
        self, sample_cards: list[DokkanCard]
    ) -> None:
        c10 = DokkanCard(id=10, name="Old Card", element=10)
        cands = [
            CandidateEvaluation(card=c10, lead_boost_pct=170.0, score=5.0, base_slot1_viable=False),
            CandidateEvaluation(
                card=sample_cards[1], lead_boost_pct=170.0, score=10.0, base_slot1_viable=False
            ),
        ]
        # 1. Truncated unclosed JSON
        truncated = '{"selected_card_id": 102, "reasoning": "Ottima difesa contro Broly'
        res = parse_advisor_response(truncated, None, cands)
        assert res is not None
        assert res[0] == 102
        assert "Ottima difesa contro Broly" in res[1]

        # 2. Token boundary: "10M HP" should not match candidate ID 10 over candidate ID 102
        plain_text = "Il boss ha 10M HP e 50k ATK. Raccomando card 102 per la vittoria."
        res2 = parse_advisor_response(plain_text, None, cands)
        assert res2 is not None
        assert res2[0] == 102

    def test_synergy_none_links_and_same_name_safety(self, sample_cards: list[DokkanCard]) -> None:
        c_none1 = DokkanCard(id=201, name="Mock Goku", element=0, links=None)  # type: ignore
        c_none2 = DokkanCard(id=202, name="Mock Vegeta", element=1, links=None)  # type: ignore
        score, shared, ki = calculate_link_synergy(c_none1, c_none2)
        assert score == 0.0
        assert shared == []
        assert ki == []

        # Same name unit link score with leader is 0.0
        from dokkan_eza_link_farmer.ai.synergy import rate_sub_unit

        lead = sample_cards[0]
        sub_same_name = DokkanCard(
            id=302,
            name="Goku",
            element=10,
            category_ids=[17],
            links=["Super Saiyan", "Prepared for Battle"],
        )
        sub_diff_name = DokkanCard(
            id=303,
            name="Vegeta",
            element=10,
            category_ids=[17],
            links=["Super Saiyan", "Prepared for Battle"],
        )
        rate_same = rate_sub_unit(sub_same_name, lead)
        rate_diff = rate_sub_unit(sub_diff_name, lead)
        assert rate_diff > rate_same

    def test_consult_ollama_advisor_zero_crash_fallback(
        self, sample_cards: list[DokkanCard]
    ) -> None:
        cands = [
            CandidateEvaluation(card=c, lead_boost_pct=170.0, score=10.0, base_slot1_viable=False)
            for c in sample_cards[:3]
        ]
        boss = BossStage(
            stage_id=1,
            event_id=1,
            stage_name="Test Boss",
            event_name="Test Event",
            phases=[BossPhase(phase_index=1, hp=1000000)],
        )

        # Offline client fallback
        mock_client = MagicMock(spec=DokkanAIClient)
        mock_client.is_available.return_value = False
        card, reason = consult_ollama_advisor(
            top_candidates=cands,
            current_team=sample_cards[:5],
            boss_stage=boss,
            ai_client=mock_client,
        )
        assert card.id == cands[0].card.id
        assert "Offline / Graceful Fallback" in reason


class TestTeamBuilderDelegationContracts:
    def test_team_builder_delegates_calculate_link_synergy(
        self, sample_cards: list[DokkanCard]
    ) -> None:
        c1, c2 = sample_cards[0], sample_cards[1]
        score_tb, shared_tb, ki_tb = TeamBuilder.calculate_link_synergy(c1, c2)
        score_syn, shared_syn, ki_syn = calculate_link_synergy(c1, c2)
        assert score_tb == score_syn
        assert shared_tb == shared_syn
        assert ki_tb == ki_syn

    def test_team_builder_recommend_candidate_contract(
        self, sample_cards: list[DokkanCard]
    ) -> None:
        cands = [
            CandidateEvaluation(card=c, lead_boost_pct=170.0, score=10.0, base_slot1_viable=False)
            for c in sample_cards[:3]
        ]
        boss = BossStage(
            stage_id=1,
            event_id=1,
            stage_name="Test Boss",
            event_name="Test Event",
            phases=[BossPhase(phase_index=1, hp=1000000)],
        )
        # 1. Instance call
        tb = TeamBuilder()
        card, reason = tb.recommend_candidate(
            top_candidates=cands,
            current_team=sample_cards[:5],
            boss_stage=boss,
        )
        assert card.id == cands[0].card.id

        # 2. Module re-export call
        from dokkan_eza_link_farmer.ai.team_builder import (
            recommend_candidate as tb_recommend_candidate,
        )

        card_mod, _ = tb_recommend_candidate(
            top_candidates=cands,
            current_team=sample_cards[:5],
            boss_stage=boss,
        )
        assert card_mod.id == cands[0].card.id

    def test_team_builder_build_team_contract(self, sample_cards: list[DokkanCard]) -> None:
        boss = BossStage(
            stage_id=1,
            event_id=1,
            stage_name="Test Boss",
            event_name="Test Event",
            phases=[BossPhase(phase_index=1, hp=1000000)],
        )
        tb = TeamBuilder()
        rec, shortlist = tb.build_team(
            candidate_pool=sample_cards,
            boss_stage=boss,
            generate_tactics=False,
            use_ai_advisor=False,
        )
        assert isinstance(rec, TeamRecommendation)
        assert len(rec.all_cards) == 6
        assert isinstance(shortlist, list)

        # Module-level convenience build_team call
        from dokkan_eza_link_farmer.ai.team_builder import build_team as tb_build_team

        rec_mod, shortlist_mod = tb_build_team(
            candidate_pool=sample_cards,
            boss_stage=boss,
            generate_tactics=False,
            use_ai_advisor=False,
        )
        assert isinstance(rec_mod, TeamRecommendation)
        assert len(rec_mod.all_cards) == 6
        assert isinstance(shortlist_mod, list)


class TestSynergyAndAdvisorAdversarialHardening:
    def test_parse_advisor_response_alternative_keys_and_nested_json(
        self, sample_cards: list[DokkanCard]
    ) -> None:
        cands = [
            CandidateEvaluation(card=c, lead_boost_pct=170.0, score=10.0, base_slot1_viable=False)
            for c in sample_cards[:3]
        ]
        # 1. Alternative key "choice"
        res_choice = parse_advisor_response('{"choice": 102, "reasoning": "Ottimo"}', None, cands)
        assert res_choice is not None
        assert res_choice[0] == 102
        assert "Ottimo" in res_choice[1]

        # 2. Nested JSON: {"decision": {"selected_card_id": 102}}
        res_nested = parse_advisor_response(
            '{"decision": {"selected_card_id": 102}, "reasoning": "Decision made"}', None, cands
        )
        assert res_nested is not None
        assert res_nested[0] == 102

        # 3. Message containing card token inside valid JSON
        res_msg = parse_advisor_response(
            '{"status": "ok", "message": "Raccomando card 102 per vincere"}', None, cands
        )
        assert res_msg is not None
        assert res_msg[0] == 102

    def test_evaluate_rotation_pair_symmetric_tiebreaking_between_lrs(self) -> None:
        # Two LRs with identical defense priority (0.0), but different kit power
        lr_low_kit = DokkanCard(id=501, name="LR Low", rarity=5, element=0)
        lr_high_kit = DokkanCard(id=502, name="LR High", rarity=5, element=1)
        # Mock kit power
        lr_low_kit.evaluate_kit_power = lambda: (50.0, {})  # type: ignore
        lr_high_kit.evaluate_kit_power = lambda: (200.0, {})  # type: ignore

        # Symmetrical test: order of arguments should NOT change who is Slot 1
        rot1 = evaluate_rotation_pair(lr_low_kit, lr_high_kit)
        rot2 = evaluate_rotation_pair(lr_high_kit, lr_low_kit)

        assert rot1.slot1.id == 502
        assert rot1.slot2.id == 501
        assert rot2.slot1.id == 502
        assert rot2.slot2.id == 501

    def test_from_dict_accepts_already_hydrated_instances(
        self, sample_cards: list[DokkanCard]
    ) -> None:
        card = sample_cards[0]
        # DokkanCard.from_dict on existing DokkanCard
        rehydrated = DokkanCard.from_dict(card)
        assert rehydrated is card

        # RotationPair.from_dict on existing RotationPair
        rot = RotationPair(
            slot1=sample_cards[0],
            slot2=sample_cards[1],
            shared_links=["Fierce Battle"],
            shared_ki_links=[],
            synergy_score=5.0,
        )
        rehydrated_rot = RotationPair.from_dict(rot)
        assert rehydrated_rot is rot

        # RotationPair.from_dict with already hydrated slot1 and slot2 objects inside dictionary
        mixed_dict = {
            "slot1": sample_cards[0],
            "slot2": sample_cards[1],
            "shared_links": ["Fierce Battle"],
            "shared_ki_links": [],
            "synergy_score": 5.0,
        }
        rehydrated_mixed = RotationPair.from_dict(mixed_dict)
        assert rehydrated_mixed.slot1.id == sample_cards[0].id
        assert rehydrated_mixed.slot2.id == sample_cards[1].id

    def test_none_and_empty_name_safety(self) -> None:
        c_none_name1 = DokkanCard(id=601, name="", element=0)
        c_none_name2 = DokkanCard(id=602, name="", element=1)
        # Should not falsely trigger same-name rule if both have empty names
        score, _, _ = calculate_link_synergy(c_none_name1, c_none_name2)
        assert isinstance(score, float)
