"""Adversarial Challenge & Stress Test Suite for Dokkan Damage Simulation Benchmarks.

Authored by: Empirical Challenger Agent (Milestone 2)
Role: Empirical Challenger / Adversarial Critic & Specialist

Validates:
1. Exhaustive Mathematical Accuracy:
   - Verifies all 3,186 simulations (354 cards * 3 slots * 3 bosses) against DokkanConstraintSolver.
   - Validates monotonic damage growth across boss attack tiers (4.2M >= 3.5M >= 2.5M).
2. Threshold Boundary Stress Testing:
   - Validates boundary values for IMMUNE (<=1,000), SAFE (1,001 - 250,000),
     SURVIVES (250,001 - 499,999), VULNERABLE (500,000 - 699,999), LETHAL (>= 700,000).
   - Confirms risk hierarchy monotonicity: IMMUNE < SAFE < SURVIVES < VULNERABLE < LETHAL.
3. Benchmark Target Enforcements:
   - LR Gogeta (1030481): Strictly LETHAL in Slot 1 (score 0.0, unviable, 2.57M+ dmg vs 2.5M boss).
     Viable in Slot 2 (SAFE, score 95.0, 250k dmg).
   - Supreme Kai (1015201): Strictly LETHAL in Slot 1 (score 0.0, unviable, 875k dmg vs 2.5M boss).
     Strictly LETHAL in Slot 2 and Slot 3 (score 0.0, unviable, 2.57M+ dmg).
4. Global Slot 1 Invariants:
   - Zero tolerance: Any card taking >= 700,000 damage against 2.5M boss in Slot 1 must be LETHAL & unviable.
   - Any card with slot_score 0.0 must be unviable in Slot 1.
   - Viable Slot 1 cards must never be marked LETHAL.
5. Summary Metrics Consistency:
   - Exact mathematical tally across all 354 benchmark records.
6. Extreme Domain Edge Cases & Clamp Fuzzing:
   - Over-cap DR, negative DR, extreme ATK (10M+), DEF > ATK, 0 ATK, floor guard halving.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from tools.generate_damage_simulation_benchmarks import (
    BOSS_BENCHMARKS,
    classify_damage_status,
)

from dokkan_eza_link_farmer.ai.solver import DokkanConstraintSolver

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BENCHMARKS_FILE = PROJECT_ROOT / "data" / "damage_simulation_benchmarks.json"
MATRIX_FILE = PROJECT_ROOT / "data" / "cards_tactical_matrix.json"

STATUS_ORDER = {
    "IMMUNE": 0,
    "SAFE": 1,
    "SURVIVES": 2,
    "VULNERABLE": 3,
    "LETHAL": 4,
}


@pytest.fixture(scope="module")
def benchmark_data() -> dict[str, Any]:
    assert BENCHMARKS_FILE.exists(), f"Benchmark file not found: {BENCHMARKS_FILE}"
    with open(BENCHMARKS_FILE, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def matrix_data() -> dict[str, Any]:
    assert MATRIX_FILE.exists(), f"Tactical matrix file not found: {MATRIX_FILE}"
    with open(MATRIX_FILE, encoding="utf-8") as f:
        return json.load(f)


class TestThresholdBoundaryStress:
    """Stress tests exact boundary conditions for damage status classification."""

    @pytest.mark.parametrize(
        "damage,expected_status",
        [
            (-100, "IMMUNE"),
            (0, "IMMUNE"),
            (1, "IMMUNE"),
            (999, "IMMUNE"),
            (1_000, "IMMUNE"),
            (1_001, "SAFE"),
            (1_002, "SAFE"),
            (100_000, "SAFE"),
            (249_999, "SAFE"),
            (250_000, "SAFE"),
            (250_001, "SURVIVES"),
            (350_000, "SURVIVES"),
            (499_998, "SURVIVES"),
            (499_999, "SURVIVES"),
            (500_000, "VULNERABLE"),
            (500_001, "VULNERABLE"),
            (600_000, "VULNERABLE"),
            (699_999, "VULNERABLE"),
            (700_000, "LETHAL"),
            (700_001, "LETHAL"),
            (1_000_000, "LETHAL"),
            (10_000_000, "LETHAL"),
        ],
    )
    def test_exact_status_boundaries(self, damage: int, expected_status: str) -> None:
        assert classify_damage_status(damage) == expected_status

    def test_status_monotonicity_property(self) -> None:
        """Any increase in damage must never decrease the risk level."""
        sample_damages = [
            0,
            500,
            1000,
            1001,
            250000,
            250001,
            499999,
            500000,
            699999,
            700000,
            1500000,
        ]
        prev_rank = -1
        for d in sample_damages:
            status = classify_damage_status(d)
            rank = STATUS_ORDER[status]
            assert rank >= prev_rank, (
                f"Monotonicity violated at damage={d}: rank {rank} < {prev_rank}"
            )
            prev_rank = rank


class TestExhaustiveDatasetSimulationAccuracy:
    """Verifies all 3,186 individual simulation entries against DokkanConstraintSolver."""

    def test_all_simulations_reproducible_and_monotone(
        self, benchmark_data: dict[str, Any]
    ) -> None:
        benchmarks = benchmark_data["benchmarks"]
        assert len(benchmarks) == 354, f"Expected 354 cards, got {len(benchmarks)}"

        total_simulations_checked = 0

        for card_id, rec in benchmarks.items():
            card_class = rec["class"]
            is_super = card_class == "Super"
            stats = rec["stats"]
            evals = rec["slot_evaluations"]

            slot_def_map = {
                "slot_1": stats["sot_def_slot1"],
                "slot_2": stats["post_super_def_slot2"],
                "slot_3": stats["post_super_def_slot3"],
            }

            for slot_key, slot_def in slot_def_map.items():
                slot_eval = evals[slot_key]
                sims = slot_eval["simulations"]

                prev_damage = -1
                prev_status_rank = -1

                for boss in BOSS_BENCHMARKS:
                    boss_id = boss["id"]
                    boss_atk = boss["atk"]
                    assert boss_id in sims, f"Missing {boss_id} in {card_id} {slot_key}"
                    b_sim = sims[boss_id]

                    expected_dmg = DokkanConstraintSolver.calculate_damage_taken(
                        enemy_atk=boss_atk,
                        type_matchup=0,
                        has_passive_guard=b_sim["effective_guard"],
                        dr_pct=b_sim["effective_dr"],
                        def_stat=slot_def,
                        is_super_vs_extreme=is_super,
                        variance=1.0,
                    )

                    # Damage taken must match solver output exactly
                    assert b_sim["damage_taken"] == expected_dmg, (
                        f"Mismatch for card {card_id} in {slot_key} vs {boss_id}: "
                        f"recorded={b_sim['damage_taken']}, expected={expected_dmg}"
                    )

                    # Status classification must match damage taken
                    expected_status = classify_damage_status(expected_dmg)
                    assert b_sim["status"] == expected_status, (
                        f"Status mismatch for card {card_id} in {slot_key} vs {boss_id}: "
                        f"recorded={b_sim['status']}, expected={expected_status}"
                    )

                    # Boss tier scaling monotonicity
                    assert b_sim["damage_taken"] >= prev_damage, (
                        f"Damage not monotone for card {card_id} in {slot_key}: "
                        f"{b_sim['damage_taken']} < {prev_damage}"
                    )
                    curr_status_rank = STATUS_ORDER[b_sim["status"]]
                    assert curr_status_rank >= prev_status_rank, (
                        f"Status risk not monotone for card {card_id} in {slot_key}: "
                        f"{b_sim['status']} < rank {prev_status_rank}"
                    )

                    prev_damage = b_sim["damage_taken"]
                    prev_status_rank = curr_status_rank
                    total_simulations_checked += 1

        assert total_simulations_checked == 354 * 3 * 3, (
            f"Expected 3186 simulations, got {total_simulations_checked}"
        )


class TestAdversarialBenchmarkTargets:
    """Stress tests mandatory benchmark targets LR Gogeta (1030481) and Supreme Kai (1015201)."""

    def test_lr_gogeta_slot1_lethality_and_slot2_competence(
        self, benchmark_data: dict[str, Any]
    ) -> None:
        benchmarks = benchmark_data["benchmarks"]
        gogeta = benchmarks["1030481"]

        # Slot 1 must be strictly unviable and LETHAL
        s1 = gogeta["slot_evaluations"]["slot_1"]
        assert s1["slot_score"] == 0.0, f"Gogeta slot1_score must be 0.0, got {s1['slot_score']}"
        assert s1["viable"] is False, "Gogeta must be flagged not viable in Slot 1"
        assert s1["status"] == "LETHAL", f"Gogeta Slot 1 status must be LETHAL, got {s1['status']}"
        assert "Fatal Slot 1 Trap" in s1.get("vulnerability_reason", "")

        # Damage against 2.5M must exceed 2.5M HP threshold
        dmg_25m = s1["simulations"]["boss_2_5m"]["damage_taken"]
        assert dmg_25m == 2_575_000
        assert s1["simulations"]["boss_2_5m"]["effective_guard"] is False

        # Severe (3.5M) and Max (4.2M) scaling
        assert s1["simulations"]["boss_3_5m"]["damage_taken"] == 3_724_999
        assert s1["simulations"]["boss_4_2m"]["damage_taken"] == 4_530_000

        # Slot 2 must be viable, SAFE vs 2.5M, high tactical score
        s2 = gogeta["slot_evaluations"]["slot_2"]
        assert s2["viable"] is True
        assert s2["slot_score"] == 95.0
        assert s2["status"] == "SAFE"
        assert s2["simulations"]["boss_2_5m"]["damage_taken"] == 250_000
        assert s2["simulations"]["boss_2_5m"]["effective_guard"] is True

    def test_supreme_kai_naked_guard_trap_and_floater_death(
        self, benchmark_data: dict[str, Any]
    ) -> None:
        benchmarks = benchmark_data["benchmarks"]
        kai = benchmarks["1015201"]

        # Slot 1: Naked Guard Trap (guard active, but 0% DR and low DEF -> LETHAL)
        s1 = kai["slot_evaluations"]["slot_1"]
        assert s1["slot_score"] == 0.0, (
            f"Supreme Kai slot1_score must be 0.0, got {s1['slot_score']}"
        )
        assert s1["viable"] is False, "Supreme Kai must be unviable in Slot 1"
        assert s1["status"] == "LETHAL"
        assert "Naked Guard Trap" in s1.get("vulnerability_reason", "")

        # In Slot 1: Guard IS active, but damage is 875k, surpassing the 700k LETHAL threshold
        s1_sim = s1["simulations"]["boss_2_5m"]
        assert s1_sim["effective_guard"] is True
        assert s1_sim["damage_taken"] == 875_000
        assert s1_sim["status"] == "LETHAL"

        # Slot 2 & Slot 3: Guard completely turns off -> unmitigated lethal damage (2.57M+)
        s2 = kai["slot_evaluations"]["slot_2"]
        assert s2["viable"] is False
        assert s2["slot_score"] == 0.0
        assert s2["status"] == "LETHAL"
        assert s2["simulations"]["boss_2_5m"]["damage_taken"] == 2_575_000
        assert s2["simulations"]["boss_2_5m"]["effective_guard"] is False

        s3 = kai["slot_evaluations"]["slot_3"]
        assert s3["viable"] is False
        assert s3["slot_score"] == 0.0
        assert s3["status"] == "LETHAL"


class TestGlobalSlot1IntegrityAndInvariants:
    """Stress tests dataset-wide invariant rules on Slot 1 defense."""

    def test_no_lethal_card_marked_viable_in_slot1(self, benchmark_data: dict[str, Any]) -> None:
        """Every card that takes >= 700k damage from a 2.5M boss in Slot 1 MUST be LETHAL and unviable."""
        benchmarks = benchmark_data["benchmarks"]
        violating_cards = []

        for card_id, rec in benchmarks.items():
            s1 = rec["slot_evaluations"]["slot_1"]
            dmg_25m = s1["simulations"]["boss_2_5m"]["damage_taken"]

            if dmg_25m >= 700_000 and (
                s1["viable"] is not False or s1["status"] != "LETHAL" or s1["slot_score"] != 0.0
            ):
                violating_cards.append(
                    (
                        card_id,
                        rec["name"],
                        dmg_25m,
                        s1["viable"],
                        s1["status"],
                        s1["slot_score"],
                    )
                )

        assert len(violating_cards) == 0, (
            f"Found cards taking >= 700k not marked LETHAL/unviable: {violating_cards}"
        )

    def test_viable_slot1_cards_must_survive(self, benchmark_data: dict[str, Any]) -> None:
        """Cards marked viable in Slot 1 must have slot_score > 0 and baseline damage < 700k."""
        benchmarks = benchmark_data["benchmarks"]
        for card_id, rec in benchmarks.items():
            s1 = rec["slot_evaluations"]["slot_1"]
            if s1["viable"]:
                assert s1["slot_score"] > 0.0, (
                    f"Card {card_id} is viable in Slot 1 but has slot_score {s1['slot_score']}"
                )
                assert s1["status"] in ("IMMUNE", "SAFE", "SURVIVES", "VULNERABLE"), (
                    f"Card {card_id} is viable but has status {s1['status']}"
                )
                assert s1["simulations"]["boss_2_5m"]["damage_taken"] < 700_000


class TestSummaryMetricsConsistency:
    """Verifies summary metrics exactly match aggregated counts across all cards."""

    def test_summary_metrics_exact_tally(
        self, benchmark_data: dict[str, Any], matrix_data: dict[str, Any]
    ) -> None:
        summary = benchmark_data["summary_metrics"]
        benchmarks = benchmark_data["benchmarks"]
        matrix_cards = matrix_data["cards"]

        assert summary["total_cards_benchmarked"] == len(benchmarks)
        assert len(benchmarks) == len(matrix_cards)
        assert len(benchmarks) == 354

        # Cross-check card IDs
        matrix_ids = {str(c["card_id"]) for c in matrix_cards}
        benchmark_ids = set(benchmarks.keys())
        assert matrix_ids == benchmark_ids, (
            f"ID mismatch: diff={matrix_ids.symmetric_difference(benchmark_ids)}"
        )

        # Compute counts
        viable_s1 = sum(1 for c in benchmarks.values() if c["slot_evaluations"]["slot_1"]["viable"])
        lethal_s1 = sum(
            1 for c in benchmarks.values() if c["slot_evaluations"]["slot_1"]["status"] == "LETHAL"
        )
        god_tanks = sum(
            1
            for c in benchmarks.values()
            if c["slot_evaluations"]["slot_1"]["status"] in ("SAFE", "IMMUNE")
        )
        slot2_specs = sum(
            1
            for c in benchmarks.values()
            if c["slot_evaluations"]["slot_2"]["viable"]
            and not c["slot_evaluations"]["slot_1"]["viable"]
        )

        assert summary["slot1_viable_count"] == viable_s1
        assert summary["slot1_lethal_count"] == lethal_s1
        assert summary["god_tank_count"] == god_tanks
        assert summary["slot2_specialist_count"] == slot2_specs


class TestSolverExtremeEdgeCases:
    """Fuzzes and stress-tests DokkanConstraintSolver.calculate_damage_taken under extreme inputs."""

    def test_zero_attack_deals_zero_damage(self) -> None:
        dmg = DokkanConstraintSolver.calculate_damage_taken(
            enemy_atk=0, type_matchup=0, def_stat=100_000
        )
        assert dmg == 0

    def test_hundred_percent_dr_negates_all_damage(self) -> None:
        dmg = DokkanConstraintSolver.calculate_damage_taken(
            enemy_atk=10_000_000,
            type_matchup=-1,
            has_passive_guard=False,
            dr_pct=100,
            def_stat=0,
        )
        assert dmg == 0

    def test_dr_over_one_hundred_is_clamped(self) -> None:
        dmg = DokkanConstraintSolver.calculate_damage_taken(
            enemy_atk=10_000_000,
            type_matchup=-1,
            dr_pct=150,
            def_stat=0,
        )
        assert dmg == 0

    def test_negative_dr_is_clamped_to_zero(self) -> None:
        dmg_normal = DokkanConstraintSolver.calculate_damage_taken(
            enemy_atk=1_000_000,
            type_matchup=0,
            dr_pct=0,
            def_stat=100_000,
            is_super_vs_extreme=True,
        )
        dmg_neg = DokkanConstraintSolver.calculate_damage_taken(
            enemy_atk=1_000_000,
            type_matchup=0,
            dr_pct=-50,
            def_stat=100_000,
            is_super_vs_extreme=True,
        )
        assert dmg_neg == dmg_normal

    def test_def_exceeding_attack_yields_zero(self) -> None:
        dmg = DokkanConstraintSolver.calculate_damage_taken(
            enemy_atk=2_500_000,
            type_matchup=0,
            has_passive_guard=True,
            dr_pct=50,
            def_stat=2_000_000,  # Incoming attack after guard & DR is 1.0M, DEF is 2.0M
            is_super_vs_extreme=True,
        )
        assert dmg == 0

    def test_guard_halving_integer_truncation(self) -> None:
        # Damage after DEF = 1 -> floor(1 * 0.5) = 0
        dmg1 = DokkanConstraintSolver.calculate_damage_taken(
            enemy_atk=1,
            has_passive_guard=True,
            dr_pct=0,
            def_stat=0,
        )
        # 1 * 0.8 = 0.8 -> int(0.8 * 0.5) = int(0.4) = 0
        assert dmg1 == 0
