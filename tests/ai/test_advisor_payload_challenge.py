"""Empirical Adversarial Challenge & Stress Test Suite for LLM Advisor Payload (Milestone 3 / Requirement R3).

Authored by: Empirical Challenger Agent (Milestone 3)
Role: Empirical Challenger / Adversarial Critic & Specialist

Validates:
1. Schema & Serialization Completeness:
   - All 20 legacy candidate keys preserved.
   - All 7 new tactical keys properly serialized (slot1_score, slot2_score, slot3_score,
     has_intro_cliff, cliff_turn, slot1_status, damage_simulations).
2. Absolute Benchmark Disqualification:
   - LR Gogeta (1030481): slot1_score == 0.0, slot1_status == "LETHAL", fatal slot_1_penalty.
   - Supreme Kai (1015201): slot1_score == 0.0, slot1_status == "LETHAL", fatal slot_1_penalty.
   - Resistant to kit deception attacks (base_slot1_viable=True, is_slot1_tank=True, etc.).
   - Resistant to cache loss / empty JSON files.
3. Damage Simulations Dictionary Consistency:
   - All 3 boss thresholds ("2.5M", "3.5M", "4.2M") present and strictly typed.
   - Exact benchmark damages for LR Gogeta (2.575M, 3.725M, 4.530M) and Supreme Kai (875k, 1.275M, 1.555M).
   - Monotonicity (4.2M dmg >= 3.5M dmg >= 2.5M dmg) and survival invariant (survived == status != "LETHAL").
   - Mathematical fallback order of operations for cards outside the benchmark dataset.
4. Robustness Under Extreme & Malformed Inputs:
   - Empty candidate lists, empty teams, empty boss phases, None/missing fields, unknown card IDs.
5. Exhaustive Dataset Ingestion:
   - Validates payload construction for all 354 catalog units without exception.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from dokkan_eza_link_farmer.ai.boss_models import BossPhase, BossStage
from dokkan_eza_link_farmer.ai.card_models import DokkanCard, LeaderSkillSpec
from dokkan_eza_link_farmer.ai.llm_advisor import (
    build_advisor_messages,
    build_advisor_payload,
    load_cards_tactical_matrix,
)
from dokkan_eza_link_farmer.ai.solver import CandidateEvaluation

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MATRIX_FILE = PROJECT_ROOT / "data" / "cards_tactical_matrix.json"
BENCHMARKS_FILE = PROJECT_ROOT / "data" / "damage_simulation_benchmarks.json"

REQUIRED_CANDIDATE_KEYS = {
    # 20 Pre-existing legacy keys
    "rank",
    "card_id",
    "name",
    "element",
    "leader_coverage_pct",
    "base_slot1_viable",
    "solver_score",
    "passive_skill",
    "super_attack",
    "counter_points",
    "penalty_points",
    "guard_type",
    "tactical_guard_type",
    "defensive_tier",
    "estimated_sa_damage_taken",
    "dr_percent",
    "has_slot_1_only_guard",
    "has_slot_2_3_guard",
    "intro_turns",
    "slot_1_penalty",
    # 7 New tactical keys (R3)
    "slot1_score",
    "slot2_score",
    "slot3_score",
    "has_intro_cliff",
    "cliff_turn",
    "slot1_status",
    "slot_restrictions",
    "damage_simulations",
}

DAMAGE_THRESHOLDS = ("2.5M", "3.5M", "4.2M")


@pytest.fixture(scope="module")
def sample_stage() -> BossStage:
    return BossStage(
        stage_id=999,
        event_id=99,
        event_name="Supreme Battle Spectacle",
        stage_name="Stage 10 (Goku & Frieza)",
        difficulty=3,
        phases=[
            BossPhase(phase_index=1, element=1, element_name="AGL", estimated_sa_damage=2_500_000),
            BossPhase(phase_index=2, element=2, element_name="TEQ", estimated_sa_damage=3_500_000),
            BossPhase(phase_index=3, element=3, element_name="INT", estimated_sa_damage=4_200_000),
        ],
    )


@pytest.fixture(scope="module")
def sample_team() -> list[DokkanCard]:
    return [
        DokkanCard(
            id=4034771,
            name="Super Vegito",
            element=12,
            category_ids=[1, 2],
            leader_spec=LeaderSkillSpec(main_category_ids=[1, 2], base_boost_pct=170.0),
        )
    ]


class TestAdvisorPayloadSchemaAndKeyPreservation:
    """Validates structural integrity and key completeness of build_advisor_payload."""

    def test_all_27_candidate_keys_present_and_typed(
        self, sample_stage: BossStage, sample_team: list[DokkanCard]
    ) -> None:
        """Every candidate dictionary must contain all 20 legacy + 7 new tactical keys."""
        cand_card = DokkanCard(
            id=1030481,
            name="Super Saiyan Vegeta (Angel) & Super Saiyan Goku (Angel)",
            element=10,
            passive_skill="Guards all attacks as 2nd or 3rd attacker in a turn",
        )
        cand_eval = CandidateEvaluation(
            card=cand_card,
            score=95.0,
            lead_boost_pct=170.0,
            base_slot1_viable=False,
            guard_type="slot_2_3_locked",
        )

        payload = build_advisor_payload(
            boss_stage=sample_stage,
            current_team=sample_team,
            top_candidates=[cand_eval],
        )

        candidates = payload.get("top_5_candidates", [])
        assert len(candidates) == 1
        cand_dict = candidates[0]

        missing = REQUIRED_CANDIDATE_KEYS - set(cand_dict.keys())
        assert not missing, f"Missing required keys in candidate payload: {missing}"

        # Type checks
        assert isinstance(cand_dict["rank"], int)
        assert isinstance(cand_dict["card_id"], int)
        assert isinstance(cand_dict["name"], str)
        assert isinstance(cand_dict["slot1_score"], (int, float))
        assert isinstance(cand_dict["slot2_score"], (int, float))
        assert isinstance(cand_dict["slot3_score"], (int, float))
        assert isinstance(cand_dict["has_intro_cliff"], bool)
        assert cand_dict["cliff_turn"] is None or isinstance(cand_dict["cliff_turn"], int)
        assert cand_dict["slot1_status"] in ("LETHAL", "SURVIVED", "VIABLE")
        assert isinstance(cand_dict["damage_simulations"], dict)

        for th in DAMAGE_THRESHOLDS:
            assert th in cand_dict["damage_simulations"]
            sim = cand_dict["damage_simulations"][th]
            assert isinstance(sim.get("damage_taken"), int)
            assert isinstance(sim.get("status"), str)
            assert isinstance(sim.get("survived"), bool)


class TestMandatoryBenchmarkDisqualifications:
    """Stress tests mandatory benchmark targets LR Gogeta (1030481) and Supreme Kai (1015201)."""

    def test_lr_gogeta_1030481_slot1_disqualification(
        self, sample_stage: BossStage, sample_team: list[DokkanCard]
    ) -> None:
        """LR Gogeta (1030481) must strictly receive slot1_score: 0.0, LETHAL, and fatal penalty."""
        gogeta = DokkanCard(
            id=1030481,
            name="Super Saiyan Vegeta (Angel) & Super Saiyan Goku (Angel)",
            element=10,
            passive_skill="*As the 2nd or 3rd attacker in a turn*\n- Guards all attacks",
        )
        cand_eval = CandidateEvaluation(
            card=gogeta,
            score=95.0,
            lead_boost_pct=170.0,
            base_slot1_viable=False,
            guard_type="slot_2_3_locked",
        )

        payload = build_advisor_payload(
            boss_stage=sample_stage,
            current_team=sample_team,
            top_candidates=[cand_eval],
        )

        cand = payload["top_5_candidates"][0]
        assert cand["card_id"] == 1030481
        assert cand["slot1_score"] == 0.0
        assert cand["slot1_status"] == "LETHAL"
        assert cand["slot_1_penalty"] is not None
        assert "-45.0" in cand["slot_1_penalty"] or "-50.0" in cand["slot_1_penalty"]
        assert "do NOT place in Slot 1" in cand["slot_1_penalty"]
        assert cand["has_intro_cliff"] is True
        assert cand["cliff_turn"] == 3

    def test_supreme_kai_1015201_slot1_disqualification(
        self, sample_stage: BossStage, sample_team: list[DokkanCard]
    ) -> None:
        """Supreme Kai (1015201) must strictly receive slot1_score: 0.0, LETHAL, and fatal penalty."""
        kai = DokkanCard(
            id=1015201,
            name="Supreme Kai",
            element=11,
            passive_skill="Guards all attacks as the 1st attacker in a turn",
        )
        cand_eval = CandidateEvaluation(
            card=kai,
            score=45.0,
            lead_boost_pct=170.0,
            base_slot1_viable=False,
            guard_type="slot_1_only",
        )

        payload = build_advisor_payload(
            boss_stage=sample_stage,
            current_team=sample_team,
            top_candidates=[cand_eval],
        )

        cand = payload["top_5_candidates"][0]
        assert cand["card_id"] == 1015201
        assert cand["slot1_score"] == 0.0
        assert cand["slot1_status"] == "LETHAL"
        assert cand["slot_1_penalty"] is not None
        assert "-45.0" in cand["slot_1_penalty"] or "-50.0" in cand["slot_1_penalty"]
        assert "do NOT place in Slot 1" in cand["slot_1_penalty"]

    @pytest.mark.parametrize(
        "deceptive_attr,deceptive_val",
        [
            ("base_slot1_viable", True),
            ("guard_type", "unconditional"),
            ("score", 999.0),
        ],
    )
    def test_lr_gogeta_immune_to_candidate_evaluation_deception(
        self,
        sample_stage: BossStage,
        sample_team: list[DokkanCard],
        deceptive_attr: str,
        deceptive_val: Any,
    ) -> None:
        """Even if CandidateEvaluation is deceptively manipulated, LR Gogeta MUST remain LETHAL in Slot 1."""
        gogeta = DokkanCard(
            id=1030481,
            name="Super Saiyan Vegeta (Angel) & Super Saiyan Goku (Angel)",
            element=10,
        )
        eval_kwargs: dict[str, Any] = {
            "card": gogeta,
            "score": 90.0,
            "lead_boost_pct": 200.0,
            "base_slot1_viable": False,
        }
        eval_kwargs[deceptive_attr] = deceptive_val
        cand_eval = CandidateEvaluation(**eval_kwargs)

        payload = build_advisor_payload(
            boss_stage=sample_stage,
            current_team=sample_team,
            top_candidates=[cand_eval],
        )

        cand = payload["top_5_candidates"][0]
        assert cand["slot1_score"] == 0.0, (
            f"Deception with {deceptive_attr}={deceptive_val} allowed non-zero slot1_score!"
        )
        assert cand["slot1_status"] == "LETHAL"
        assert cand["slot_1_penalty"] is not None

    @pytest.mark.parametrize(
        "deceptive_attr,deceptive_val",
        [
            ("base_slot1_viable", True),
            ("guard_type", "unconditional"),
            ("score", 999.0),
        ],
    )
    def test_supreme_kai_immune_to_candidate_evaluation_deception(
        self,
        sample_stage: BossStage,
        sample_team: list[DokkanCard],
        deceptive_attr: str,
        deceptive_val: Any,
    ) -> None:
        """Even if CandidateEvaluation is deceptively manipulated, Supreme Kai MUST remain LETHAL in Slot 1."""
        kai = DokkanCard(
            id=1015201,
            name="Supreme Kai",
            element=11,
        )
        eval_kwargs: dict[str, Any] = {
            "card": kai,
            "score": 80.0,
            "lead_boost_pct": 200.0,
            "base_slot1_viable": False,
        }
        eval_kwargs[deceptive_attr] = deceptive_val
        cand_eval = CandidateEvaluation(**eval_kwargs)

        payload = build_advisor_payload(
            boss_stage=sample_stage,
            current_team=sample_team,
            top_candidates=[cand_eval],
        )

        cand = payload["top_5_candidates"][0]
        assert cand["slot1_score"] == 0.0, (
            f"Deception with {deceptive_attr}={deceptive_val} allowed non-zero slot1_score!"
        )
        assert cand["slot1_status"] == "LETHAL"
        assert cand["slot_1_penalty"] is not None

    def test_cache_loss_resilience_for_benchmark_cards(
        self, sample_stage: BossStage, sample_team: list[DokkanCard]
    ) -> None:
        """If data files are completely missing or return empty dicts, fallback branch still enforces disqualification."""
        gogeta = DokkanCard(id=1030481, name="Gogeta", element=10)
        kai = DokkanCard(id=1015201, name="Kai", element=11)
        ev_g = CandidateEvaluation(
            card=gogeta, score=50.0, lead_boost_pct=170.0, base_slot1_viable=True
        )
        ev_k = CandidateEvaluation(
            card=kai, score=50.0, lead_boost_pct=170.0, base_slot1_viable=True
        )

        with (
            patch(
                "dokkan_eza_link_farmer.ai.llm_advisor.load_cards_tactical_matrix", return_value={}
            ),
            patch(
                "dokkan_eza_link_farmer.ai.llm_advisor.load_damage_simulation_benchmarks",
                return_value={},
            ),
        ):
            payload = build_advisor_payload(
                boss_stage=sample_stage,
                current_team=sample_team,
                top_candidates=[ev_g, ev_k],
            )

            candidates = payload["top_5_candidates"]
            g_dict = next(c for c in candidates if c["card_id"] == 1030481)
            k_dict = next(c for c in candidates if c["card_id"] == 1015201)

            assert g_dict["slot1_score"] == 0.0
            assert g_dict["slot1_status"] == "LETHAL"
            assert "-45.0" in g_dict["slot_1_penalty"] or "-50.0" in g_dict["slot_1_penalty"]
            assert g_dict["damage_simulations"]["2.5M"]["damage_taken"] == 2575000

            assert k_dict["slot1_score"] == 0.0
            assert k_dict["slot1_status"] == "LETHAL"
            assert "-45.0" in k_dict["slot_1_penalty"] or "-50.0" in k_dict["slot_1_penalty"]
            assert k_dict["damage_simulations"]["2.5M"]["damage_taken"] == 875000


class TestDamageSimulationsDictionaryAndCalculations:
    """Validates structure, accuracy, and monotonicity of damage simulations."""

    def test_lr_gogeta_exact_damage_values(
        self, sample_stage: BossStage, sample_team: list[DokkanCard]
    ) -> None:
        """LR Gogeta takes exact unmitigated damages: 2,575,000 / 3,724,999 / 4,530,000."""
        gogeta = DokkanCard(id=1030481, name="LR Gogeta", element=10)
        ev = CandidateEvaluation(
            card=gogeta, score=90.0, lead_boost_pct=170.0, base_slot1_viable=False
        )

        payload = build_advisor_payload(
            boss_stage=sample_stage, current_team=sample_team, top_candidates=[ev]
        )
        sims = payload["top_5_candidates"][0]["damage_simulations"]

        assert sims["2.5M"]["damage_taken"] == 2575000
        assert sims["2.5M"]["status"] == "LETHAL"
        assert sims["2.5M"]["survived"] is False

        assert sims["3.5M"]["damage_taken"] == 3724999
        assert sims["3.5M"]["status"] == "LETHAL"
        assert sims["3.5M"]["survived"] is False

        assert sims["4.2M"]["damage_taken"] == 4530000
        assert sims["4.2M"]["status"] == "LETHAL"
        assert sims["4.2M"]["survived"] is False

    def test_supreme_kai_exact_damage_values(
        self, sample_stage: BossStage, sample_team: list[DokkanCard]
    ) -> None:
        """Supreme Kai takes exact naked guard damages: 875,000 / 1,275,000 / 1,555,000."""
        kai = DokkanCard(id=1015201, name="Supreme Kai", element=11)
        ev = CandidateEvaluation(
            card=kai, score=40.0, lead_boost_pct=170.0, base_slot1_viable=False
        )

        payload = build_advisor_payload(
            boss_stage=sample_stage, current_team=sample_team, top_candidates=[ev]
        )
        sims = payload["top_5_candidates"][0]["damage_simulations"]

        assert sims["2.5M"]["damage_taken"] == 875000
        assert sims["2.5M"]["status"] == "LETHAL"
        assert sims["2.5M"]["survived"] is False

        assert sims["3.5M"]["damage_taken"] == 1275000
        assert sims["3.5M"]["status"] == "LETHAL"
        assert sims["3.5M"]["survived"] is False

        assert sims["4.2M"]["damage_taken"] == 1555000
        assert sims["4.2M"]["status"] == "LETHAL"
        assert sims["4.2M"]["survived"] is False

    def test_monotonicity_and_survival_invariants(
        self, sample_stage: BossStage, sample_team: list[DokkanCard]
    ) -> None:
        """Across any candidate, damage taken must grow monotonically with boss attack, and survived == (status != LETHAL)."""
        card_tank = DokkanCard(
            id=4034771,
            name="Super Vegito",
            element=12,
            passive_skill="Guards all attacks; reduces damage received by 65%",
        )
        card_fragile = DokkanCard(
            id=9999991,
            name="Glass Cannon",
            element=10,
            passive_skill="ATK +300%",
        )
        ev_tank = CandidateEvaluation(
            card=card_tank, score=98.0, lead_boost_pct=200.0, base_slot1_viable=True
        )
        ev_fragile = CandidateEvaluation(
            card=card_fragile, score=30.0, lead_boost_pct=170.0, base_slot1_viable=False
        )

        payload = build_advisor_payload(
            boss_stage=sample_stage, current_team=sample_team, top_candidates=[ev_tank, ev_fragile]
        )

        for cand in payload["top_5_candidates"]:
            sims = cand["damage_simulations"]
            d_25 = sims["2.5M"]["damage_taken"]
            d_35 = sims["3.5M"]["damage_taken"]
            d_42 = sims["4.2M"]["damage_taken"]

            assert d_42 >= d_35 >= d_25, (
                f"Damage is not monotonic for {cand['name']}: {d_25} -> {d_35} -> {d_42}"
            )

            for th in DAMAGE_THRESHOLDS:
                s = sims[th]
                expected_survived = s["status"] != "LETHAL"
                assert s["survived"] is expected_survived, (
                    f"Invariant violated: status={s['status']} but survived={s['survived']}"
                )

    def test_dokkan_order_of_operations_mathematical_fallback(
        self, sample_stage: BossStage, sample_team: list[DokkanCard]
    ) -> None:
        """Fallback math: Damage Taken = {[(Enemy ATK * Type Mod) * (1 - DR%)] - Ally DEF} * Guard Reduction."""
        # Custom card not present in benchmarks
        custom_card = DokkanCard(
            id=8888888,
            name="Synthetic Unit",
            element=10,
            passive_skill="Guards all attacks; reduces damage received by 50%",
        )
        custom_card.defense = 300000
        ev = CandidateEvaluation(
            card=custom_card, score=85.0, lead_boost_pct=170.0, base_slot1_viable=True
        )

        payload = build_advisor_payload(
            boss_stage=sample_stage, current_team=sample_team, top_candidates=[ev]
        )
        sims = payload["top_5_candidates"][0]["damage_simulations"]

        # Expected calculation for 2.5M:
        # type_mod = 0.8 (guard), dr = 0.5
        # dmg_before_def = 2_500_000 * 0.8 * 0.5 = 1_000_000
        # dmg_after_def = 1_000_000 - 300_000 = 700_000
        # calc_dmg = int(700_000 * 0.5) = 350_000
        assert sims["2.5M"]["damage_taken"] == 350000
        assert sims["2.5M"]["status"] == "SURVIVES"
        assert sims["2.5M"]["survived"] is True


class TestExtremeAdversarialInputsAndGracefulDegradation:
    """Stress tests candidate evaluation and payload builder under boundary and hostile inputs."""

    def test_empty_candidates_list(
        self, sample_stage: BossStage, sample_team: list[DokkanCard]
    ) -> None:
        """Empty top_candidates list returns empty top_5_candidates list gracefully."""
        payload = build_advisor_payload(
            boss_stage=sample_stage, current_team=sample_team, top_candidates=[]
        )
        assert payload["top_5_candidates"] == []

    def test_candidate_list_truncation(
        self, sample_stage: BossStage, sample_team: list[DokkanCard]
    ) -> None:
        """Top candidates list with 12 items is strictly truncated to 5 items."""
        cards = [
            CandidateEvaluation(
                card=DokkanCard(id=2000 + i, name=f"Card {i}", element=10),
                score=100.0 - i,
                lead_boost_pct=170.0,
                base_slot1_viable=False,
            )
            for i in range(12)
        ]
        payload = build_advisor_payload(
            boss_stage=sample_stage, current_team=sample_team, top_candidates=cards
        )
        assert len(payload["top_5_candidates"]) == 5
        assert [c["rank"] for c in payload["top_5_candidates"]] == [1, 2, 3, 4, 5]
        assert [c["card_id"] for c in payload["top_5_candidates"]] == [2000, 2001, 2002, 2003, 2004]

    def test_empty_team_and_empty_boss_phases(self) -> None:
        """Payload handles empty current_team and empty boss phases without crashing."""
        empty_stage = BossStage(
            stage_id=1, event_id=1, event_name="", stage_name="", difficulty=1, phases=[]
        )
        payload = build_advisor_payload(boss_stage=empty_stage, current_team=[], top_candidates=[])

        assert payload["boss_stage"]["phases"] == []
        assert payload["current_team"] == []
        assert payload["top_5_candidates"] == []

    def test_card_with_none_and_missing_attributes(
        self, sample_stage: BossStage, sample_team: list[DokkanCard]
    ) -> None:
        """Candidate evaluation with None skills and missing optional fields completes safely."""
        card = DokkanCard(
            id=7777777,
            name="Minimal Card",
            element=10,
        )
        card.passive_skill = ""
        card.super_attack = ""
        cand_eval = CandidateEvaluation(
            card=card,
            score=50.0,
            lead_boost_pct=170.0,
            base_slot1_viable=False,
        )

        payload = build_advisor_payload(
            boss_stage=sample_stage,
            current_team=sample_team,
            top_candidates=[cand_eval],
        )

        cand = payload["top_5_candidates"][0]
        assert cand["passive_skill"] == ""
        assert cand["super_attack"] == ""
        assert cand["card_id"] == 7777777


class TestPromptAndAdvisorMessagesHardening:
    """Verifies that build_advisor_messages generates robust prompt rules forbidding slot1 traps."""

    def test_system_prompt_rules_and_forbidding_instructions(
        self, sample_stage: BossStage, sample_team: list[DokkanCard]
    ) -> None:
        """System prompt must explicitly mention benchmarks (2.5M, 3.5M, 4.2M) and forbid 1030481/1015201 in Slot 1."""
        payload: dict[str, Any] = {
            "top_5_candidates": [
                {
                    "rank": 1,
                    "card_id": 1030481,
                    "name": "Super Saiyan Vegeta (Angel) & Super Saiyan Goku (Angel)",
                    "slot1_score": 0.0,
                    "slot1_status": "LETHAL",
                    "damage_simulations": {
                        "2.5M": {"damage_taken": 2575000, "status": "LETHAL"},
                        "3.5M": {"damage_taken": 3724999, "status": "LETHAL"},
                        "4.2M": {"damage_taken": 4530000, "status": "LETHAL"},
                    },
                }
            ]
        }
        messages = build_advisor_messages(
            boss_stage=sample_stage,
            current_team=sample_team,
            payload=payload,
        )

        assert len(messages) == 2
        sys_msg = messages[0]["content"]
        user_msg = messages[1]["content"]

        # Benchmark rules in system prompt
        assert "CRITICAL POST-10TH ANNIVERSARY TACTICAL MATRIX & DAMAGE BENCHMARKS" in sys_msg
        assert "2.5M, 3.5M, 4.2M SA" in sys_msg
        assert "1030481" in sys_msg
        assert "1015201" in sys_msg
        assert "MUST NEVER be selected or advised for Slot 1" in sys_msg
        assert "slot1_score == 0.0 or slot1_status == 'LETHAL'" in sys_msg

        # User message embeds serialized JSON
        assert "top_5_candidates" not in user_msg  # Embeds array directly
        assert "1030481" in user_msg


class TestExhaustiveCatalogPayloadGeneration:
    """Tests payload generation across all 354 post-10th anniversary cards to guarantee zero exceptions."""

    def test_all_catalog_cards_can_be_evaluated_in_payload(
        self, sample_stage: BossStage, sample_team: list[DokkanCard]
    ) -> None:
        """Iterates through all 354 cards from cards_tactical_matrix.json and ensures robust payload construction."""
        matrix = load_cards_tactical_matrix()
        assert matrix and "cards" in matrix, "Tactical matrix not loaded"

        cards_list = matrix["cards"]
        assert len(cards_list) >= 350, f"Expected ~354 cards, got {len(cards_list)}"

        for _i, card_info in enumerate(cards_list):
            card_id = int(card_info["card_id"])
            card = DokkanCard(
                id=card_id,
                name=card_info.get("name", f"Card {card_id}"),
                element=10,
            )
            cand_eval = CandidateEvaluation(
                card=card,
                score=float(card_info.get("slot2_score", 5.0)),
                lead_boost_pct=170.0,
                base_slot1_viable=bool(card_info.get("slot1_score", 0.0) >= 5.0),
                guard_type=card_info.get("guard_type", "none"),
            )

            payload = build_advisor_payload(
                boss_stage=sample_stage,
                current_team=sample_team,
                top_candidates=[cand_eval],
            )

            c_dict = payload["top_5_candidates"][0]
            assert c_dict["card_id"] == card_id
            assert REQUIRED_CANDIDATE_KEYS.issubset(c_dict.keys())
            assert c_dict["slot1_status"] in ("LETHAL", "SURVIVED", "VIABLE")
            assert isinstance(c_dict["damage_simulations"], dict)

            # Specific check for LR Gogeta and Supreme Kai during catalog sweep
            if card_id == 1030481:
                assert c_dict["slot1_score"] == 0.0
                assert c_dict["slot1_status"] == "LETHAL"
                assert "-45.0" in c_dict["slot_1_penalty"]
            elif card_id == 1015201:
                assert c_dict["slot1_score"] == 0.0
                assert c_dict["slot1_status"] == "LETHAL"
                assert "-50.0" in c_dict["slot_1_penalty"]


class TestRotationDisqualificationAndPayloadSerializability:
    """Verifies that lethal Slot 1 candidates are kept out of rotation Slot 1 and payload is strictly JSON-serializable."""

    def test_full_payload_json_serializability(
        self, sample_stage: BossStage, sample_team: list[DokkanCard]
    ) -> None:
        """The entire payload dictionary must be valid JSON without custom objects or NaN."""
        gogeta = DokkanCard(id=1030481, name="Gogeta", element=10)
        kai = DokkanCard(id=1015201, name="Kai", element=11)
        ev_g = CandidateEvaluation(
            card=gogeta, score=95.0, lead_boost_pct=170.0, base_slot1_viable=False
        )
        ev_k = CandidateEvaluation(
            card=kai, score=45.0, lead_boost_pct=170.0, base_slot1_viable=False
        )

        payload = build_advisor_payload(
            boss_stage=sample_stage,
            current_team=sample_team,
            top_candidates=[ev_g, ev_k],
        )

        serialized = json.dumps(payload, ensure_ascii=False)
        assert isinstance(serialized, str)
        deserialized = json.loads(serialized)
        assert deserialized["boss_stage"]["event_name"] == sample_stage.event_name
        assert len(deserialized["top_5_candidates"]) == 2

    def test_rotation_optimizer_strictly_excludes_gogeta_and_kai_from_slot_1(
        self, sample_stage: BossStage
    ) -> None:
        """When forming team rotations, neither Gogeta nor Supreme Kai can displace true Slot 1 tanks."""
        from dokkan_eza_link_farmer.ai.synergy import optimize_rotations_for_team

        beast_gohan = DokkanCard(
            id=1028441,
            name="Beast Gohan",
            element=13,
            passive_skill="Guards all attacks; reduces damage received by 50%",
        )
        super_vegito = DokkanCard(
            id=4034771,
            name="Super Vegito",
            element=12,
            passive_skill="Guards all attacks; reduces damage received by 65%",
        )
        gogeta = DokkanCard(
            id=1030481,
            name="LR Gogeta",
            element=10,
            passive_skill="*As the 2nd or 3rd attacker in a turn*\n- Guards all attacks",
        )
        kai = DokkanCard(
            id=1015201,
            name="Supreme Kai",
            element=11,
            passive_skill="Guards all attacks as the 1st attacker in a turn",
        )
        floater1 = DokkanCard(id=101, name="Floater 1", element=10)
        floater2 = DokkanCard(id=102, name="Floater 2", element=10)

        team = [beast_gohan, super_vegito, gogeta, kai, floater1, floater2]
        rot_a, rot_b, floaters = optimize_rotations_for_team(team, boss_stage=sample_stage)

        slot1_ids = {rot_a.slot1.id, rot_b.slot1.id}
        assert 1030481 not in slot1_ids, (
            "LR Gogeta (1030481) was mistakenly placed in Slot 1 of a main rotation!"
        )
        assert 1015201 not in slot1_ids, (
            "Supreme Kai (1015201) was mistakenly placed in Slot 1 of a main rotation!"
        )
