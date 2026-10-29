"""Black-Box Integration Test Suite for Qwen LLM and TeamBuilder.

Validates the end-to-end team building pipeline:
Scanned Box Fixture -> DokkanConstraintSolver -> DokkanAIClient (Qwen) -> TeamRecommendation
without relying on internal regex parsers or private scoring heuristics.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests
from tests.harness.fake_dokkandb import FakeDokkanDBClient

from dokkan_eza_link_farmer.ai.client import DokkanAIClient
from dokkan_eza_link_farmer.ai.models import (
    AIConfig,
    BossPhase,
    BossStage,
    DokkanCard,
)
from dokkan_eza_link_farmer.ai.team_builder import TeamBuilder

FIXTURE_BOX_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "sample_user_box.json"


@pytest.fixture
def fake_dokkandb() -> FakeDokkanDBClient:
    """In-memory DokkanDB test harness preventing external network calls."""
    return FakeDokkanDBClient()


@pytest.fixture
def sample_user_box_cards(fake_dokkandb: FakeDokkanDBClient) -> list[DokkanCard]:
    """Loads the 20 realistic Dokkan cards from the realistic box fixture."""
    cards = TeamBuilder.load_user_box(str(FIXTURE_BOX_PATH), dokkandb=fake_dokkandb)
    assert len(cards) == 20, f"Expected 20 cards in fixture, got {len(cards)}"
    return cards


@pytest.fixture
def red_zone_two_phase_boss() -> BossStage:
    """Realistic Red Zone endgame boss stage with 2 phases: Phase 1 AGL, Phase 2 STR."""
    return BossStage(
        stage_id=9901,
        event_id=901,
        event_name="Red Zone: Supreme Battle",
        stage_name="Stage 1: Multi-Phase Gauntlet",
        difficulty=10,
        phases=[
            BossPhase(phase_index=1, element=0, element_name="AGL"),
            BossPhase(phase_index=2, element=3, element_name="STR", cancels_dodge=True),
        ],
    )


class TestRealisticBoxFixtureContract:
    """R1: Realistic Box Fixture verification."""

    def test_sample_user_box_structure_and_categories(
        self, sample_user_box_cards: list[DokkanCard]
    ) -> None:
        """Verifies that the realistic box fixture contains 20 cards with required categories and rarities."""
        assert len(sample_user_box_cards) == 20

        # Verify presence of both UR (rarity 4) and LR (rarity 5) cards
        lr_cards = [c for c in sample_user_box_cards if c.is_lr]
        ur_cards = [c for c in sample_user_box_cards if not c.is_lr]
        assert len(lr_cards) >= 5, f"Expected at least 5 LRs, found {len(lr_cards)}"
        assert len(ur_cards) >= 10, f"Expected at least 10 URs, found {len(ur_cards)}"

        # Verify key Dokkan categories are represented in the box
        all_categories = {cat for c in sample_user_box_cards for cat in c.categories}
        assert "Pure Saiyans" in all_categories
        assert "Super Heroes" in all_categories
        assert "Movie Bosses" in all_categories

        # Verify all cards have complete public attributes
        for card in sample_user_box_cards:
            assert card.id > 0
            assert len(card.name) > 0
            assert card.element >= 0
            assert len(card.categories) > 0
            assert len(card.links) > 0


class TestQwenTeamBuilderBlackBox:
    """R2: Black-box integration tests for TeamBuilder + DokkanAIClient (Qwen)."""

    def test_qwen_teambuilder_online_end_to_end_and_payload_contracts(
        self,
        sample_user_box_cards: list[DokkanCard],
        red_zone_two_phase_boss: BossStage,
        fake_dokkandb: FakeDokkanDBClient,
    ) -> None:
        """End-to-end integration test with simulated Qwen HTTP response:

        1. Instantiates TeamBuilder with DokkanAIClient.
        2. Verifies prompt payload contains candidates, Slot 1 tanks, and link synergies.
        3. Validates resulting TeamRecommendation contracts (1 Leader, 2 Rot A, 2 Rot B, floaters).
        """
        captured_http_requests: list[dict[str, Any]] = []
        chosen_id: int | None = None

        def mock_requests_post(url: str, *_args: Any, **kwargs: Any) -> MagicMock:
            nonlocal chosen_id
            payload = kwargs.get("json", {})
            captured_http_requests.append({"url": url, "payload": payload})

            # Determine response based on prompt contents
            messages = payload.get("messages", [])
            last_message_content = messages[-1].get("content", "") if messages else ""

            mock_response = MagicMock(spec=requests.Response)
            mock_response.status_code = 200
            mock_response.raise_for_status.return_value = None

            if "TOP 5 CANDIDATES" in last_message_content:
                # Find the candidate IDs passed to Qwen
                candidate_ids = [
                    int(cid) for cid in re.findall(r'"card_id":\s*(\d+)', last_message_content)
                ]
                # Pick candidate #2 if multiple candidates exist to verify non-default incorporation
                chosen_id = (
                    candidate_ids[1]
                    if len(candidate_ids) > 1
                    else (candidate_ids[0] if candidate_ids else 10013)
                )
                # Return Qwen's structured JSON recommendation
                mock_response.json.return_value = {
                    "message": {
                        "content": json.dumps(
                            {
                                "selected_card_id": chosen_id,
                                "reasoning": "Ottima sinergia difensiva, link condivisi e alta efficacia tattica contro il boss.",
                            }
                        )
                    }
                }
            else:
                # Response for analyze_team_strategy
                mock_response.json.return_value = {
                    "message": {
                        "content": (
                            "- **Rotazione A**: Mantieni Slot 1 con Guardia attiva per assorbire i colpi iniziali.\n"
                            "- **Rotazione B**: Gestisci lo Slot 2 per lanciare la Super Attack e caricare i bonus difensivi.\n"
                            "- **Oggetti di Supporto**: Utilizza Whis al Turno 3 contro il Super Attack letale della Fase 2."
                        )
                    }
                }
            return mock_response

        def mock_requests_get(*_args: Any, **_kwargs: Any) -> MagicMock:
            mock_response = MagicMock(spec=requests.Response)
            mock_response.status_code = 200
            return mock_response

        # Configure AI client pointing to local Qwen endpoint
        ai_config = AIConfig(
            enabled=True,
            base_url="http://localhost:11434/v1",
            model_name="qwen3.5:4b",
        )
        ai_client = DokkanAIClient(config=ai_config)

        with (
            patch("requests.post", side_effect=mock_requests_post),
            patch("requests.get", side_effect=mock_requests_get),
        ):
            team_builder = TeamBuilder(dokkandb=fake_dokkandb, ai_client=ai_client)
            team_rec, _shortlist = team_builder.select_best_team_for_boss(
                candidate_pool=sample_user_box_cards,
                boss_stage=red_zone_two_phase_boss,
                use_ai_advisor=True,
                generate_tactics=True,
            )

        # ---------------------------------------------------------------------
        # 1. PAYLOAD CONTRACT VERIFICATION (Black-Box Communication Contract)
        # ---------------------------------------------------------------------
        assert len(captured_http_requests) >= 2, (
            "Expected both candidate recommendation and tactical strategy calls to Qwen"
        )

        advisor_call = captured_http_requests[0]
        advisor_payload = advisor_call["payload"]
        messages = advisor_payload.get("messages", [])
        assert len(messages) >= 2, "Payload must contain system and user messages"

        system_prompt = messages[0]["content"]
        assert len(system_prompt) > 0
        user_prompt = messages[1]["content"]

        # A. Verify candidates from user box are present in prompt payload
        assert "=== TOP 5 CANDIDATES PRE-FILTERED BY SOLVER ===" in user_prompt
        candidate_ids_in_prompt = [int(m) for m in re.findall(r'"card_id":\s*(\d+)', user_prompt)]
        assert len(candidate_ids_in_prompt) >= 3, (
            f"Prompt payload must contain at least 3 candidate cards from box, found {len(candidate_ids_in_prompt)}"
        )
        box_ids = {c.id for c in sample_user_box_cards}
        for cid in candidate_ids_in_prompt:
            assert cid in box_ids, f"Candidate {cid} in prompt must originate from user box"

        # B. Verify Slot 1 tanks are explicitly identified in payload
        # (Visible either in the current team roster roles or in candidate slot tags)
        has_slot1_tank_in_team = "Slot 1 Tank" in user_prompt
        has_slot1_tag_in_candidates = (
            "SLOT_1_SAFE" in user_prompt
            or "base_slot1_viable" in user_prompt
            or "slot1_score" in user_prompt
        )
        assert has_slot1_tank_in_team or has_slot1_tag_in_candidates, (
            "Payload must contain identified Slot 1 tank information"
        )

        # C. Verify link synergies and rotation roles in tactical payload
        tactics_call = captured_http_requests[1]
        tactics_messages = tactics_call["payload"].get("messages", [])
        assert len(tactics_messages) >= 2, "Tactical payload must contain system and user messages"
        tactics_system_prompt = tactics_messages[0]["content"]
        tactics_user_prompt = tactics_messages[1]["content"]

        assert (
            "LINK" in tactics_system_prompt.upper() or "SINERGIA" in tactics_system_prompt.upper()
        ), "Tactical system prompt must contain link skill instructions"
        assert "(Link:" in tactics_user_prompt, (
            "Tactical user payload must contain link synergies between rotation partners"
        )
        assert "Rotazione A" in tactics_user_prompt, "Tactical user payload must detail Rotation A"
        assert "Rotazione B" in tactics_user_prompt, "Tactical user payload must detail Rotation B"

        # ---------------------------------------------------------------------
        # 2. TEAM RECOMMENDATION CONTRACT VERIFICATION
        # ---------------------------------------------------------------------
        # Exactly 1 valid Leader
        assert team_rec.leader is not None
        assert team_rec.leader.id in {card.id for card in team_rec.all_cards}

        # Exactly 1 compatible Friend Leader
        assert team_rec.friend_leader is not None

        # Exactly 2 cards in Rotation A
        assert team_rec.rotation_a is not None
        assert team_rec.rotation_a.slot1 is not None
        assert team_rec.rotation_a.slot2 is not None
        assert team_rec.rotation_a.slot1.id != team_rec.rotation_a.slot2.id

        # Exactly 2 cards in Rotation B
        assert team_rec.rotation_b is not None
        assert team_rec.rotation_b.slot1 is not None
        assert team_rec.rotation_b.slot2 is not None
        assert team_rec.rotation_b.slot1.id != team_rec.rotation_b.slot2.id

        # Distinct cards in rotations
        rot_cards = {
            team_rec.rotation_a.slot1.id,
            team_rec.rotation_a.slot2.id,
            team_rec.rotation_b.slot1.id,
            team_rec.rotation_b.slot2.id,
        }
        # At least 3 distinct cards across the 4 rotation slots
        assert len(rot_cards) >= 3

        # Exactly 3 floaters
        assert len(team_rec.floaters) == 3

        # Full combat roster consists of 7 units (6 titular + 1 friend leader)
        combat_roster = [
            team_rec.rotation_a.slot1,
            team_rec.rotation_a.slot2,
            team_rec.rotation_b.slot1,
            team_rec.rotation_b.slot2,
            *team_rec.floaters,
        ]
        assert len(combat_roster) == 7

        # Exactly 6 titular cards and Qwen recommendation incorporated
        assert len(team_rec.all_cards) == 6
        assert len({c.id for c in team_rec.all_cards}) == 6
        assert chosen_id in {c.id for c in team_rec.all_cards}, (
            f"Expected Qwen-selected candidate {chosen_id} to be present in final team"
        )

        # Coverage by Leader Skill: all team members and floaters must receive boost >= 150%
        for member in team_rec.all_cards:
            is_covered, boost_pct, _info = member.is_covered_by_leader(team_rec.leader)
            assert is_covered is True, (
                f"Card {member.name} ({member.id}) must be covered by Leader {team_rec.leader.name}"
            )
            assert boost_pct >= 150.0, (
                f"Card {member.name} coverage boost ({boost_pct}%) must be at least 150%"
            )

        for floater in team_rec.floaters:
            is_covered, boost_pct, _info = floater.is_covered_by_leader(team_rec.leader)
            assert is_covered is True, (
                f"Floater {floater.name} ({floater.id}) must be covered by Leader {team_rec.leader.name}"
            )
            assert boost_pct >= 150.0

        # Slot 1 defensive aptitude in both rotations (guard, damage reduction, or slot 1 tank viability)
        for rot, name in [(team_rec.rotation_a, "Rotation A"), (team_rec.rotation_b, "Rotation B")]:
            s1 = rot.slot1
            has_defensive_aptitude = (
                s1.has_guard
                or s1.damage_reduction_percent > 0
                or s1.has_damage_reduction
                or s1.is_slot1_tank
            )
            assert has_defensive_aptitude, (
                f"{name} Slot 1 unit {s1.name} must have defensive aptitude"
            )

        # AI reasoning and tactical analysis are captured from Qwen responses
        assert team_rec.ai_reasoning is not None
        assert len(team_rec.ai_reasoning) > 0
        assert team_rec.tactical_analysis is not None
        assert "Rotazione A" in team_rec.tactical_analysis
        assert "Whis" in team_rec.tactical_analysis

    def test_qwen_teambuilder_markdown_code_block_response(
        self,
        sample_user_box_cards: list[DokkanCard],
        red_zone_two_phase_boss: BossStage,
        fake_dokkandb: FakeDokkanDBClient,
    ) -> None:
        """Verifies parsing resilience when Qwen returns JSON wrapped inside Markdown code blocks."""

        chosen_id: int | None = None

        def mock_markdown_post(_url: str, *_args: Any, **kwargs: Any) -> MagicMock:
            nonlocal chosen_id
            payload = kwargs.get("json", {})
            messages = payload.get("messages", [])
            last_content = messages[-1].get("content", "") if messages else ""

            mock_response = MagicMock(spec=requests.Response)
            mock_response.status_code = 200
            mock_response.raise_for_status.return_value = None

            if "TOP 5 CANDIDATES" in last_content:
                candidate_ids = [
                    int(cid) for cid in re.findall(r'"card_id":\s*(\d+)', last_content)
                ]
                chosen_id = (
                    candidate_ids[1]
                    if len(candidate_ids) > 1
                    else (candidate_ids[0] if candidate_ids else 10013)
                )
                # Markdown-wrapped JSON response from Qwen
                wrapped_content = (
                    "Certamente! Ecco la mia raccomandazione per il completamento del team:\n\n"
                    "```json\n"
                    "{\n"
                    f'  "selected_card_id": {chosen_id},\n'
                    '  "reasoning": "Scelta eccellente: ottima sinergia con il leader e guard garantita."\n'
                    "}\n"
                    "```\n"
                    "Buona fortuna con la sfida!"
                )
                mock_response.json.return_value = {"message": {"content": wrapped_content}}
            else:
                mock_response.json.return_value = {
                    "message": {
                        "content": "- Rotazione A: Slot 1 protetto\n- Rotazione B: Danni costanti"
                    }
                }
            return mock_response

        def mock_online_get(*_args: Any, **_kwargs: Any) -> MagicMock:
            mock_response = MagicMock(spec=requests.Response)
            mock_response.status_code = 200
            return mock_response

        ai_config = AIConfig(
            enabled=True,
            base_url="http://localhost:11434/v1",
            model_name="qwen3.5:4b",
        )
        ai_client = DokkanAIClient(config=ai_config)

        with (
            patch("requests.post", side_effect=mock_markdown_post),
            patch("requests.get", side_effect=mock_online_get),
        ):
            team_builder = TeamBuilder(dokkandb=fake_dokkandb, ai_client=ai_client)
            team_rec, _shortlist = team_builder.select_best_team_for_boss(
                candidate_pool=sample_user_box_cards,
                boss_stage=red_zone_two_phase_boss,
                use_ai_advisor=True,
            )

        assert len(team_rec.all_cards) == 6
        assert len(team_rec.floaters) == 3
        assert chosen_id in {c.id for c in team_rec.all_cards}
        assert "Scelta eccellente" in (team_rec.ai_reasoning or "")

    def test_qwen_teambuilder_offline_fallback_deterministic(
        self,
        sample_user_box_cards: list[DokkanCard],
        red_zone_two_phase_boss: BossStage,
        fake_dokkandb: FakeDokkanDBClient,
    ) -> None:
        """Verifies deterministic fallback when local LLM server is offline or unreachable."""
        ai_config = AIConfig(
            enabled=True,
            base_url="http://localhost:11434/v1",
            model_name="qwen3.5:4b",
        )
        ai_client = DokkanAIClient(config=ai_config)

        # Simulate offline server: requests.get fails with ConnectionError
        with (
            patch(
                "requests.get",
                side_effect=requests.exceptions.ConnectionError("Server offline"),
            ),
            patch("requests.post") as mock_post,
        ):
            team_builder = TeamBuilder(dokkandb=fake_dokkandb, ai_client=ai_client)
            team_rec, _shortlist = team_builder.select_best_team_for_boss(
                candidate_pool=sample_user_box_cards,
                boss_stage=red_zone_two_phase_boss,
                use_ai_advisor=True,
            )

            # No chat completion requests should be made if server is offline
            mock_post.assert_not_called()

        # Contract assertions for offline recommendation
        assert len(team_rec.all_cards) == 6
        assert len(team_rec.floaters) == 3
        assert team_rec.leader is not None
        assert team_rec.friend_leader is not None
        assert team_rec.rotation_a.slot1 is not None
        assert team_rec.rotation_b.slot1 is not None

        # Verify all cards receive leader skill coverage
        for card in team_rec.all_cards:
            is_covered, boost, _ = card.is_covered_by_leader(team_rec.leader)
            assert is_covered is True
            assert boost >= 150.0

        # Reasoning indicates offline fallback
        assert "Offline" in (team_rec.ai_reasoning or "") or "Fallback" in (
            team_rec.ai_reasoning or ""
        )

    def test_qwen_teambuilder_timeout_fallback(
        self,
        sample_user_box_cards: list[DokkanCard],
        red_zone_two_phase_boss: BossStage,
        fake_dokkandb: FakeDokkanDBClient,
    ) -> None:
        """Verifies zero-crash fallback when Qwen call times out (>75s)."""

        def mock_timeout_post(*_args: Any, **_kwargs: Any) -> MagicMock:
            raise requests.exceptions.Timeout("Ollama inference timed out after 75.0s")

        def mock_online_get(*_args: Any, **_kwargs: Any) -> MagicMock:
            mock_resp = MagicMock(spec=requests.Response)
            mock_resp.status_code = 200
            return mock_resp

        ai_config = AIConfig(
            enabled=True,
            base_url="http://localhost:11434/v1",
            model_name="qwen3.5:4b",
        )
        ai_client = DokkanAIClient(config=ai_config)

        with (
            patch("requests.post", side_effect=mock_timeout_post),
            patch("requests.get", side_effect=mock_online_get),
        ):
            team_builder = TeamBuilder(dokkandb=fake_dokkandb, ai_client=ai_client)
            team_rec, _shortlist = team_builder.select_best_team_for_boss(
                candidate_pool=sample_user_box_cards,
                boss_stage=red_zone_two_phase_boss,
                use_ai_advisor=True,
            )

        # Verified graceful degradation
        assert len(team_rec.all_cards) == 6
        assert len(team_rec.floaters) == 3
        assert team_rec.leader is not None
        assert "Timeout" in (team_rec.ai_reasoning or "")

    def test_qwen_teambuilder_malformed_json_fallback(
        self,
        sample_user_box_cards: list[DokkanCard],
        red_zone_two_phase_boss: BossStage,
        fake_dokkandb: FakeDokkanDBClient,
    ) -> None:
        """Verifies deterministic fallback to Candidate #1 when Qwen returns unparseable or non-JSON chatter."""

        def mock_malformed_post(*_args: Any, **_kwargs: Any) -> MagicMock:
            mock_resp = MagicMock(spec=requests.Response)
            mock_resp.status_code = 200
            mock_resp.raise_for_status.return_value = None
            mock_resp.json.return_value = {
                "message": {
                    "content": "Mi dispiace, non posso fornire una risposta strutturata in questo momento."
                }
            }
            return mock_resp

        def mock_online_get(*_args: Any, **_kwargs: Any) -> MagicMock:
            mock_resp = MagicMock(spec=requests.Response)
            mock_resp.status_code = 200
            return mock_resp

        ai_config = AIConfig(
            enabled=True,
            base_url="http://localhost:11434/v1",
            model_name="qwen3.5:4b",
        )
        ai_client = DokkanAIClient(config=ai_config)

        with (
            patch("requests.post", side_effect=mock_malformed_post),
            patch("requests.get", side_effect=mock_online_get),
        ):
            team_builder = TeamBuilder(dokkandb=fake_dokkandb, ai_client=ai_client)
            team_rec, _shortlist = team_builder.select_best_team_for_boss(
                candidate_pool=sample_user_box_cards,
                boss_stage=red_zone_two_phase_boss,
                use_ai_advisor=True,
            )

        assert len(team_rec.all_cards) == 6
        assert len(team_rec.floaters) == 3
        assert team_rec.leader is not None
        assert "Malformed Response Fallback" in (team_rec.ai_reasoning or "")

    def test_qwen_teambuilder_null_or_none_card_id_fallback(
        self,
        sample_user_box_cards: list[DokkanCard],
        red_zone_two_phase_boss: BossStage,
        fake_dokkandb: FakeDokkanDBClient,
    ) -> None:
        """Verifies zero-crash fallback when Qwen outputs null as selected_card_id."""

        def mock_null_id_post(*_args: Any, **_kwargs: Any) -> MagicMock:
            mock_resp = MagicMock(spec=requests.Response)
            mock_resp.status_code = 200
            mock_resp.raise_for_status.return_value = None
            mock_resp.json.return_value = {
                "message": {
                    "content": json.dumps(
                        {
                            "selected_card_id": None,
                            "reasoning": "Nessuna unita soddisfa pienamente i requisiti.",
                        }
                    )
                }
            }
            return mock_resp

        def mock_online_get(*_args: Any, **_kwargs: Any) -> MagicMock:
            mock_resp = MagicMock(spec=requests.Response)
            mock_resp.status_code = 200
            return mock_resp

        ai_config = AIConfig(
            enabled=True,
            base_url="http://localhost:11434/v1",
            model_name="qwen3.5:4b",
        )
        ai_client = DokkanAIClient(config=ai_config)

        with (
            patch("requests.post", side_effect=mock_null_id_post),
            patch("requests.get", side_effect=mock_online_get),
        ):
            team_builder = TeamBuilder(dokkandb=fake_dokkandb, ai_client=ai_client)
            team_rec, _shortlist = team_builder.select_best_team_for_boss(
                candidate_pool=sample_user_box_cards,
                boss_stage=red_zone_two_phase_boss,
                use_ai_advisor=True,
            )

        assert len(team_rec.all_cards) == 6
        assert len(team_rec.floaters) == 3
        assert team_rec.leader is not None
        assert "Malformed Response Fallback" in (team_rec.ai_reasoning or "")

    def test_qwen_teambuilder_empty_json_response_fallback(
        self,
        sample_user_box_cards: list[DokkanCard],
        red_zone_two_phase_boss: BossStage,
        fake_dokkandb: FakeDokkanDBClient,
    ) -> None:
        """Verifies zero-crash fallback when Qwen returns an empty JSON object '{}'."""

        def mock_empty_json_post(*_args: Any, **_kwargs: Any) -> MagicMock:
            mock_resp = MagicMock(spec=requests.Response)
            mock_resp.status_code = 200
            mock_resp.raise_for_status.return_value = None
            mock_resp.json.return_value = {"message": {"content": "{}"}}
            return mock_resp

        def mock_online_get(*_args: Any, **_kwargs: Any) -> MagicMock:
            mock_resp = MagicMock(spec=requests.Response)
            mock_resp.status_code = 200
            return mock_resp

        ai_config = AIConfig(
            enabled=True,
            base_url="http://localhost:11434/v1",
            model_name="qwen3.5:4b",
        )
        ai_client = DokkanAIClient(config=ai_config)

        with (
            patch("requests.post", side_effect=mock_empty_json_post),
            patch("requests.get", side_effect=mock_online_get),
        ):
            team_builder = TeamBuilder(dokkandb=fake_dokkandb, ai_client=ai_client)
            team_rec, _shortlist = team_builder.select_best_team_for_boss(
                candidate_pool=sample_user_box_cards,
                boss_stage=red_zone_two_phase_boss,
                use_ai_advisor=True,
            )

        assert len(team_rec.all_cards) == 6
        assert len(team_rec.floaters) == 3
        assert team_rec.leader is not None
        assert "Malformed Response Fallback" in (team_rec.ai_reasoning or "")

    def test_qwen_teambuilder_hallucinated_id_fallback(
        self,
        sample_user_box_cards: list[DokkanCard],
        red_zone_two_phase_boss: BossStage,
        fake_dokkandb: FakeDokkanDBClient,
    ) -> None:
        """Verifies graceful degradation when Qwen hallucinates a card ID outside the pre-filtered shortlist."""

        def mock_hallucinated_post(*_args: Any, **_kwargs: Any) -> MagicMock:
            mock_resp = MagicMock(spec=requests.Response)
            mock_resp.status_code = 200
            mock_resp.raise_for_status.return_value = None
            mock_resp.json.return_value = {
                "message": {
                    "content": json.dumps(
                        {
                            "selected_card_id": 999999,
                            "reasoning": "Unita leggendaria inventata per vincere facilmente.",
                        }
                    )
                }
            }
            return mock_resp

        def mock_online_get(*_args: Any, **_kwargs: Any) -> MagicMock:
            mock_resp = MagicMock(spec=requests.Response)
            mock_resp.status_code = 200
            return mock_resp

        ai_config = AIConfig(
            enabled=True,
            base_url="http://localhost:11434/v1",
            model_name="qwen3.5:4b",
        )
        ai_client = DokkanAIClient(config=ai_config)

        with (
            patch("requests.post", side_effect=mock_hallucinated_post),
            patch("requests.get", side_effect=mock_online_get),
        ):
            team_builder = TeamBuilder(dokkandb=fake_dokkandb, ai_client=ai_client)
            team_rec, _shortlist = team_builder.select_best_team_for_boss(
                candidate_pool=sample_user_box_cards,
                boss_stage=red_zone_two_phase_boss,
                use_ai_advisor=True,
            )

        assert len(team_rec.all_cards) == 6
        assert len(team_rec.floaters) == 3
        assert team_rec.leader is not None
        assert "Invalid / Hallucinated ID Fallback" in (team_rec.ai_reasoning or "")

    def test_qwen_teambuilder_http_error_fallback(
        self,
        sample_user_box_cards: list[DokkanCard],
        red_zone_two_phase_boss: BossStage,
        fake_dokkandb: FakeDokkanDBClient,
    ) -> None:
        """Verifies zero-crash degradation when the LLM server returns an HTTP 500 error."""

        def mock_500_post(*_args: Any, **_kwargs: Any) -> MagicMock:
            mock_resp = MagicMock(spec=requests.Response)
            mock_resp.status_code = 500
            mock_resp.text = "Internal Server Error"
            http_err = requests.exceptions.HTTPError(response=mock_resp)
            mock_resp.raise_for_status.side_effect = http_err
            return mock_resp

        def mock_online_get(*_args: Any, **_kwargs: Any) -> MagicMock:
            mock_resp = MagicMock(spec=requests.Response)
            mock_resp.status_code = 200
            return mock_resp

        ai_config = AIConfig(
            enabled=True,
            base_url="http://localhost:11434/v1",
            model_name="qwen3.5:4b",
        )
        ai_client = DokkanAIClient(config=ai_config)

        with (
            patch("requests.post", side_effect=mock_500_post),
            patch("requests.get", side_effect=mock_online_get),
        ):
            team_builder = TeamBuilder(dokkandb=fake_dokkandb, ai_client=ai_client)
            team_rec, _shortlist = team_builder.select_best_team_for_boss(
                candidate_pool=sample_user_box_cards,
                boss_stage=red_zone_two_phase_boss,
                use_ai_advisor=True,
            )

        assert len(team_rec.all_cards) == 6
        assert len(team_rec.floaters) == 3
        assert team_rec.leader is not None
        assert "Offline / Graceful Fallback" in (team_rec.ai_reasoning or "")

    def test_qwen_teambuilder_http_404_model_not_found_fallback(
        self,
        sample_user_box_cards: list[DokkanCard],
        red_zone_two_phase_boss: BossStage,
        fake_dokkandb: FakeDokkanDBClient,
    ) -> None:
        """Verifies zero-crash fallback when LLM server returns HTTP 404 (model not found)."""

        def mock_404_post(*_args: Any, **_kwargs: Any) -> MagicMock:
            mock_resp = MagicMock(spec=requests.Response)
            mock_resp.status_code = 404
            mock_resp.text = '{"error": "model \'qwen3.5:4b\' not found"}'
            http_err = requests.exceptions.HTTPError(response=mock_resp)
            mock_resp.raise_for_status.side_effect = http_err
            return mock_resp

        def mock_online_get(*_args: Any, **_kwargs: Any) -> MagicMock:
            mock_resp = MagicMock(spec=requests.Response)
            mock_resp.status_code = 200
            return mock_resp

        ai_config = AIConfig(
            enabled=True,
            base_url="http://localhost:11434/v1",
            model_name="qwen3.5:4b",
        )
        ai_client = DokkanAIClient(config=ai_config)

        with (
            patch("requests.post", side_effect=mock_404_post),
            patch("requests.get", side_effect=mock_online_get),
        ):
            team_builder = TeamBuilder(dokkandb=fake_dokkandb, ai_client=ai_client)
            team_rec, _shortlist = team_builder.select_best_team_for_boss(
                candidate_pool=sample_user_box_cards,
                boss_stage=red_zone_two_phase_boss,
                use_ai_advisor=True,
            )

        assert len(team_rec.all_cards) == 6
        assert len(team_rec.floaters) == 3
        assert team_rec.leader is not None
        assert "Offline / Graceful Fallback" in (team_rec.ai_reasoning or "")

    def test_qwen_teambuilder_openai_compatible_response(
        self,
        sample_user_box_cards: list[DokkanCard],
        red_zone_two_phase_boss: BossStage,
        fake_dokkandb: FakeDokkanDBClient,
    ) -> None:
        """Verifies compatibility with OpenAI endpoint schema: choices[0].message.content."""

        def mock_openai_post(_url: str, *_args: Any, **kwargs: Any) -> MagicMock:
            payload = kwargs.get("json", {})
            messages = payload.get("messages", [])
            last_content = messages[-1].get("content", "") if messages else ""

            mock_response = MagicMock(spec=requests.Response)
            mock_response.status_code = 200
            mock_response.raise_for_status.return_value = None

            if "TOP 5 CANDIDATES" in last_content:
                candidate_ids = [
                    int(cid) for cid in re.findall(r'"card_id":\s*(\d+)', last_content)
                ]
                chosen_id = candidate_ids[0] if candidate_ids else 10013
                openai_payload = {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "selected_card_id": chosen_id,
                                        "reasoning": "Validato tramite endpoint OpenAI-compatible.",
                                    }
                                )
                            }
                        }
                    ]
                }
                mock_response.json.return_value = openai_payload
            else:
                mock_response.json.return_value = {
                    "choices": [
                        {
                            "message": {
                                "content": "- Rotazione A: Slot 1 protetto\n- Rotazione B: Danni costanti"
                            }
                        }
                    ]
                }
            return mock_response

        def mock_online_get(*_args: Any, **_kwargs: Any) -> MagicMock:
            mock_resp = MagicMock(spec=requests.Response)
            mock_resp.status_code = 200
            return mock_resp

        # Non-Ollama base_url triggers OpenAI-compatible path
        ai_config = AIConfig(
            enabled=True,
            base_url="http://localhost:8000/v1",
            model_name="qwen-openai-compat",
        )
        ai_client = DokkanAIClient(config=ai_config)

        with (
            patch("requests.post", side_effect=mock_openai_post),
            patch("requests.get", side_effect=mock_online_get),
        ):
            team_builder = TeamBuilder(dokkandb=fake_dokkandb, ai_client=ai_client)
            team_rec, _shortlist = team_builder.select_best_team_for_boss(
                candidate_pool=sample_user_box_cards,
                boss_stage=red_zone_two_phase_boss,
                use_ai_advisor=True,
            )

        assert len(team_rec.all_cards) == 6
        assert len(team_rec.floaters) == 3
        assert "OpenAI-compatible" in (team_rec.ai_reasoning or "")

    def test_qwen_teambuilder_string_card_id_response(
        self,
        sample_user_box_cards: list[DokkanCard],
        red_zone_two_phase_boss: BossStage,
        fake_dokkandb: FakeDokkanDBClient,
    ) -> None:
        """Verifies ingestion resilience when Qwen outputs card ID as string ("10007") instead of int."""

        def mock_string_id_post(*_args: Any, **_kwargs: Any) -> MagicMock:
            mock_resp = MagicMock(spec=requests.Response)
            mock_resp.status_code = 200
            mock_resp.raise_for_status.return_value = None
            mock_resp.json.return_value = {
                "message": {
                    "content": json.dumps(
                        {
                            "selected_card_id": "10007",
                            "reasoning": "Selezionato SS Trunks tramite ID in formato stringa.",
                        }
                    )
                }
            }
            return mock_resp

        def mock_online_get(*_args: Any, **_kwargs: Any) -> MagicMock:
            mock_resp = MagicMock(spec=requests.Response)
            mock_resp.status_code = 200
            return mock_resp

        ai_config = AIConfig(
            enabled=True,
            base_url="http://localhost:11434/v1",
            model_name="qwen3.5:4b",
        )
        ai_client = DokkanAIClient(config=ai_config)

        with (
            patch("requests.post", side_effect=mock_string_id_post),
            patch("requests.get", side_effect=mock_online_get),
        ):
            team_builder = TeamBuilder(dokkandb=fake_dokkandb, ai_client=ai_client)
            team_rec, _shortlist = team_builder.select_best_team_for_boss(
                candidate_pool=sample_user_box_cards,
                boss_stage=red_zone_two_phase_boss,
                use_ai_advisor=True,
            )

        assert 10007 in {c.id for c in team_rec.all_cards}
        assert len(team_rec.all_cards) == 6
        assert len(team_rec.floaters) == 3

    def test_qwen_teambuilder_duplicate_team_member_selection_fallback(
        self,
        sample_user_box_cards: list[DokkanCard],
        red_zone_two_phase_boss: BossStage,
        fake_dokkandb: FakeDokkanDBClient,
    ) -> None:
        """Verifies rejection and graceful fallback when Qwen selects a card already locked on the team."""

        def mock_dup_post(*_args: Any, **_kwargs: Any) -> MagicMock:
            mock_resp = MagicMock(spec=requests.Response)
            mock_resp.status_code = 200
            mock_resp.raise_for_status.return_value = None
            # Return Orange Piccolo (10012) who is already the team leader
            mock_resp.json.return_value = {
                "message": {
                    "content": json.dumps(
                        {
                            "selected_card_id": 10012,
                            "reasoning": "Tentativo di clonare il leader già presente nel team.",
                        }
                    )
                }
            }
            return mock_resp

        def mock_online_get(*_args: Any, **_kwargs: Any) -> MagicMock:
            mock_resp = MagicMock(spec=requests.Response)
            mock_resp.status_code = 200
            return mock_resp

        ai_config = AIConfig(
            enabled=True,
            base_url="http://localhost:11434/v1",
            model_name="qwen3.5:4b",
        )
        ai_client = DokkanAIClient(config=ai_config)

        with (
            patch("requests.post", side_effect=mock_dup_post),
            patch("requests.get", side_effect=mock_online_get),
        ):
            team_builder = TeamBuilder(dokkandb=fake_dokkandb, ai_client=ai_client)
            team_rec, _shortlist = team_builder.select_best_team_for_boss(
                candidate_pool=sample_user_box_cards,
                boss_stage=red_zone_two_phase_boss,
                use_ai_advisor=True,
            )

        assert len(team_rec.all_cards) == 6
        assert len({c.id for c in team_rec.all_cards}) == 6
        assert "Invalid / Hallucinated ID Fallback" in (team_rec.ai_reasoning or "")

    def test_qwen_teambuilder_pool_boundary_conditions(
        self,
        sample_user_box_cards: list[DokkanCard],
        red_zone_two_phase_boss: BossStage,
        fake_dokkandb: FakeDokkanDBClient,
    ) -> None:
        """Verifies boundary conditions:

        1. Exact 6 valid cards in candidate pool forms valid team.
        2. Fewer than 6 cards raises ValueError.
        3. Forced leader with insufficient eligible sub-units raises ValueError.
        """
        tb = TeamBuilder(dokkandb=fake_dokkandb)

        # 1. Exact 6 cards that form a valid Pure Saiyans team
        pure_saiyans_6 = [c for c in sample_user_box_cards if 17 in c.category_ids][:6]
        assert len(pure_saiyans_6) == 6
        rec_6, shortlist_6 = tb.select_best_team_for_boss(
            candidate_pool=pure_saiyans_6,
            boss_stage=red_zone_two_phase_boss,
            use_ai_advisor=False,
        )
        assert len(rec_6.all_cards) == 6
        assert len(shortlist_6) == 0

        # 2. Fewer than 6 cards raises ValueError
        with pytest.raises(ValueError, match="Need at least 6 cards"):
            tb.select_best_team_for_boss(
                candidate_pool=sample_user_box_cards[:5],
                boss_stage=red_zone_two_phase_boss,
            )

        # 3. Forced leader with insufficient matching sub-units raises ValueError
        ps_lead = next(c for c in sample_user_box_cards if c.id == 10002)
        non_ps_cards = [c for c in sample_user_box_cards if 17 not in c.category_ids][:6]
        insufficient_pool = [ps_lead] + non_ps_cards
        with pytest.raises(ValueError, match="cannot form a valid team"):
            tb.select_best_team_for_boss(
                candidate_pool=insufficient_pool,
                boss_stage=red_zone_two_phase_boss,
                forced_leader=ps_lead,
                use_ai_advisor=False,
            )

    @pytest.mark.slow
    def test_qwen_teambuilder_live_inference_if_available(
        self,
        sample_user_box_cards: list[DokkanCard],
        red_zone_two_phase_boss: BossStage,
        fake_dokkandb: FakeDokkanDBClient,
    ) -> None:
        """Verifies live end-to-end inference against local Ollama daemon if running on host hardware."""
        ai_config = AIConfig(
            enabled=True,
            base_url="http://localhost:11434/v1",
            model_name="qwen3.5:4b",
        )
        ai_client = DokkanAIClient(config=ai_config)

        if not ai_client.is_available():
            pytest.skip(
                "Local Ollama daemon not running or not responding at http://localhost:11434"
            )

        models = ai_client.list_available_models()
        target_model = next((m for m in models if "qwen" in m.lower()), None)
        if not target_model:
            pytest.skip("No Qwen model installed on local Ollama server")

        ai_client.config.model_name = target_model

        team_builder = TeamBuilder(dokkandb=fake_dokkandb, ai_client=ai_client)
        team_rec, shortlist = team_builder.select_best_team_for_boss(
            candidate_pool=sample_user_box_cards,
            boss_stage=red_zone_two_phase_boss,
            use_ai_advisor=True,
            generate_tactics=False,
        )

        assert len(team_rec.all_cards) == 6
        assert len(team_rec.floaters) == 3
        assert team_rec.leader is not None
        assert team_rec.friend_leader is not None
        assert team_rec.ai_reasoning is not None
        assert len(team_rec.ai_reasoning) > 10
        assert "Qwen Advisor" in team_rec.ai_reasoning

        # Leader coverage holds for all cards
        for card in team_rec.all_cards:
            is_covered, boost, _ = card.is_covered_by_leader(team_rec.leader)
            assert is_covered is True
            assert boost >= 150.0

    def test_qwen_teambuilder_archetype_thematic_teams(
        self,
        sample_user_box_cards: list[DokkanCard],
        red_zone_two_phase_boss: BossStage,
        fake_dokkandb: FakeDokkanDBClient,
    ) -> None:
        """Verifies team building with specific thematic archetypes from the realistic box:

        1. Pure Saiyans team (forced leader: Super Saiyan God Goku).
        2. Movie Bosses team (forced leader: Cell Max).
        3. Super Heroes team (forced leader: Beast Gohan).
        """
        # Test 1: Pure Saiyans Archetype
        ps_leader = next(c for c in sample_user_box_cards if c.id == 10001)
        team_builder = TeamBuilder(dokkandb=fake_dokkandb)
        ps_team, _ = team_builder.select_best_team_for_boss(
            candidate_pool=sample_user_box_cards,
            boss_stage=red_zone_two_phase_boss,
            forced_leader=ps_leader,
            use_ai_advisor=False,
        )

        assert ps_team.leader.id == 10001
        assert len(ps_team.all_cards) == 6
        assert len(ps_team.floaters) == 3
        for card in ps_team.all_cards:
            covered, boost, _ = card.is_covered_by_leader(ps_team.leader)
            assert covered is True, f"Card {card.name} not covered by Pure Saiyans lead"
            assert boost >= 150.0

        # Test 2: Movie Bosses Archetype
        mb_leader = next(c for c in sample_user_box_cards if c.id == 10015)
        mb_team, _ = team_builder.select_best_team_for_boss(
            candidate_pool=sample_user_box_cards,
            boss_stage=red_zone_two_phase_boss,
            forced_leader=mb_leader,
            use_ai_advisor=False,
        )

        assert mb_team.leader.id == 10015
        assert len(mb_team.all_cards) == 6
        assert len(mb_team.floaters) == 3
        for card in mb_team.all_cards:
            covered, boost, _ = card.is_covered_by_leader(mb_team.leader)
            assert covered is True, f"Card {card.name} not covered by Movie Bosses lead"
            assert boost >= 150.0

        # Test 3: Super Heroes Archetype
        sh_leader = next(c for c in sample_user_box_cards if c.id == 10009)
        sh_team, _ = team_builder.select_best_team_for_boss(
            candidate_pool=sample_user_box_cards,
            boss_stage=red_zone_two_phase_boss,
            forced_leader=sh_leader,
            use_ai_advisor=False,
        )

        assert sh_team.leader.id == 10009
        assert len(sh_team.all_cards) == 6
        assert len(sh_team.floaters) == 3
        for card in sh_team.all_cards:
            covered, boost, _ = card.is_covered_by_leader(sh_team.leader)
            assert covered is True, f"Card {card.name} not covered by Super Heroes lead"
            assert boost >= 150.0

    def test_qwen_teambuilder_archetypes_with_qwen_advisor(
        self,
        sample_user_box_cards: list[DokkanCard],
        red_zone_two_phase_boss: BossStage,
        fake_dokkandb: FakeDokkanDBClient,
    ) -> None:
        """Verifies end-to-end Qwen advisor candidate selection on all 3 core archetypes:

        1. Pure Saiyans (forced leader: Super Saiyan God Goku 10001).
        2. Movie Bosses (forced leader: Cell Max 10015).
        3. Super Heroes (forced leader: Beast Gohan 10009).
        """
        archetype_configs = [
            (10001, "Pure Saiyans"),
            (10015, "Movie Bosses"),
            (10009, "Super Heroes"),
        ]

        for leader_id, archetype_name in archetype_configs:
            captured_candidates: list[int] = []
            chosen_candidate_id: int | None = None

            def mock_archetype_post(
                _url: str,
                *_args: Any,
                arch_name: str = archetype_name,
                **kwargs: Any,
            ) -> MagicMock:
                nonlocal chosen_candidate_id, captured_candidates
                payload = kwargs.get("json", {})
                messages = payload.get("messages", [])
                last_content = messages[-1].get("content", "") if messages else ""

                mock_response = MagicMock(spec=requests.Response)
                mock_response.status_code = 200
                mock_response.raise_for_status.return_value = None

                if "TOP 5 CANDIDATES" in last_content:
                    candidate_ids = [
                        int(cid) for cid in re.findall(r'"card_id":\s*(\d+)', last_content)
                    ]
                    captured_candidates = candidate_ids
                    # Pick candidate #2 if available, else #1
                    chosen_candidate_id = (
                        candidate_ids[1] if len(candidate_ids) > 1 else candidate_ids[0]
                    )
                    mock_response.json.return_value = {
                        "message": {
                            "content": json.dumps(
                                {
                                    "selected_card_id": chosen_candidate_id,
                                    "reasoning": f"Consiglio per archetipo {arch_name}.",
                                }
                            )
                        }
                    }
                else:
                    mock_response.json.return_value = {
                        "message": {
                            "content": f"- Rotazione A: Focus difensivo per {arch_name}\n- Rotazione B: Danni"
                        }
                    }
                return mock_response

            def mock_online_get(*_args: Any, **_kwargs: Any) -> MagicMock:
                mock_resp = MagicMock(spec=requests.Response)
                mock_resp.status_code = 200
                return mock_resp

            ai_config = AIConfig(
                enabled=True,
                base_url="http://localhost:11434/v1",
                model_name="qwen3.5:4b",
            )
            ai_client = DokkanAIClient(config=ai_config)

            forced_lead = next(c for c in sample_user_box_cards if c.id == leader_id)

            with (
                patch("requests.post", side_effect=mock_archetype_post),
                patch("requests.get", side_effect=mock_online_get),
            ):
                tb = TeamBuilder(dokkandb=fake_dokkandb, ai_client=ai_client)
                team_rec, _ = tb.select_best_team_for_boss(
                    candidate_pool=sample_user_box_cards,
                    boss_stage=red_zone_two_phase_boss,
                    forced_leader=forced_lead,
                    use_ai_advisor=True,
                )

            # Contract verifications for this archetype
            assert len(captured_candidates) >= 2, (
                f"Archetype {archetype_name} must present at least 2 candidates to Qwen, got {len(captured_candidates)}"
            )
            assert chosen_candidate_id in {c.id for c in team_rec.all_cards}, (
                f"Archetype {archetype_name} must incorporate chosen card {chosen_candidate_id}"
            )
            assert team_rec.leader.id == leader_id
            assert len(team_rec.all_cards) == 6
            assert len(team_rec.floaters) == 3
            assert team_rec.rotation_a.slot1 is not None
            assert team_rec.rotation_b.slot1 is not None

            for member in team_rec.all_cards:
                covered, boost, _ = member.is_covered_by_leader(team_rec.leader)
                assert covered is True, (
                    f"Member {member.name} must be covered by {archetype_name} leader"
                )
                assert boost >= 150.0
