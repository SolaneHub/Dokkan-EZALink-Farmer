"""Tests for Milestone 2: Dokkan Endgame Damage Formula & Simulation Benchmarks.

Validates:
1. File Existence and Schema Conformance of `data/damage_simulation_benchmarks.json`.
2. Mathematical Order of Operations & DokkanConstraintSolver integration:
   Damage = floor(max(0, ((Enemy_ATK * Variance * Type_Mod) * (1 - DR%)) - Ally_DEF) * Guard_Reduction)
3. Status Categorization Thresholds (IMMUNE, SAFE, SURVIVES, VULNERABLE, LETHAL).
4. Strict Benchmark Disqualification Criteria:
   - LR Gogeta (1030481): LETHAL in Slot 1 (2.57M+ vs 2.5M boss, 3.72M+ vs 3.5M, 4.53M+ vs 4.2M),
     slot1_score = 0.0, viable = False. SAFE in Slot 2 (250k vs 2.5M boss), viable = True, slot2_score = 95.0.
   - Supreme Kai (1015201): LETHAL in Slot 1 (875k vs 2.5M boss, 1.27M+ vs 3.5M, 1.55M+ vs 4.2M),
     slot1_score = 0.0, viable = False. LETHAL in Slot 2/3 (2.57M+), viable = False.
5. Summary Metrics Consistency:
   - total_cards_benchmarked, slot1_viable_count, slot1_lethal_count, god_tank_count, slot2_specialist_count.
6. Pipeline Reproducibility.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from tools.generate_damage_simulation_benchmarks import (
    classify_damage_status,
    generate_damage_simulation_benchmarks,
)

from dokkan_eza_link_farmer.ai.solver import DokkanConstraintSolver

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BENCHMARKS_FILE = PROJECT_ROOT / "data" / "damage_simulation_benchmarks.json"
MATRIX_FILE = PROJECT_ROOT / "data" / "cards_tactical_matrix.json"


@pytest.fixture(scope="module")
def benchmark_data() -> dict[str, Any]:
    assert BENCHMARKS_FILE.exists(), f"Missing benchmarks file: {BENCHMARKS_FILE}"
    with open(BENCHMARKS_FILE, encoding="utf-8") as f:
        return json.load(f)


class TestBenchmarkSchemaAndMetadata:
    """Verifies schema structure, required fields, and metadata properties."""

    def test_top_level_keys_present(self, benchmark_data: dict[str, Any]) -> None:
        required_keys = {"metadata", "summary_metrics", "benchmarks"}
        assert required_keys.issubset(benchmark_data.keys())

    def test_metadata_fields(self, benchmark_data: dict[str, Any]) -> None:
        meta = benchmark_data["metadata"]
        assert meta["version"] == "1.0.0"
        assert meta["target_release"] == "10th_anniversary"
        assert "generated_at" in meta
        assert "formula_specification" in meta

        spec = meta["formula_specification"]
        assert "expression" in spec
        assert "order_of_operations" in spec
        assert isinstance(spec["order_of_operations"], list)
        assert len(spec["order_of_operations"]) >= 4

        assert "boss_benchmarks" in spec
        assert len(spec["boss_benchmarks"]) == 3
        boss_atks = {b["atk"] for b in spec["boss_benchmarks"]}
        assert boss_atks == {2_500_000, 3_500_000, 4_200_000}

        assert "status_classification" in spec
        status_map = spec["status_classification"]
        assert set(status_map.keys()) == {"LETHAL", "VULNERABLE", "SURVIVES", "SAFE", "IMMUNE"}

    def test_summary_metrics_consistency(self, benchmark_data: dict[str, Any]) -> None:
        summary = benchmark_data["summary_metrics"]
        benchmarks = benchmark_data["benchmarks"]

        total = summary["total_cards_benchmarked"]
        assert total == len(benchmarks)
        assert total == 354

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

    def test_card_record_schema(self, benchmark_data: dict[str, Any]) -> None:
        benchmarks = benchmark_data["benchmarks"]
        for card_id, rec in benchmarks.items():
            assert rec["card_id"] == int(card_id)
            assert isinstance(rec["name"], str)
            assert isinstance(rec["element_id"], int)
            assert isinstance(rec["element_name"], str)
            assert rec["class"] in ("Super", "Extreme")

            # Tags
            tags = rec["tags"]
            assert "guard_type" in tags
            assert "has_intro_cliff" in tags
            assert "dr_percent" in tags
            assert "dodge_percent" in tags

            # Stats
            stats = rec["stats"]
            assert stats["sot_def_slot1"] > 0
            assert stats["post_super_def_slot2"] > 0
            assert stats["post_super_def_slot3"] > 0

            # Slot evaluations
            evals = rec["slot_evaluations"]
            for slot_key in ("slot_1", "slot_2", "slot_3"):
                slot = evals[slot_key]
                assert "slot_score" in slot
                assert isinstance(slot["slot_score"], (int, float))
                assert "viable" in slot
                assert isinstance(slot["viable"], bool)
                assert slot["status"] in {"LETHAL", "VULNERABLE", "SURVIVES", "SAFE", "IMMUNE"}

                sims = slot["simulations"]
                for b_key in ("boss_2_5m", "boss_3_5m", "boss_4_2m"):
                    assert b_key in sims
                    b_sim = sims[b_key]
                    assert b_sim["enemy_atk"] in (2_500_000, 3_500_000, 4_200_000)
                    assert isinstance(b_sim["damage_taken"], int)
                    assert b_sim["damage_taken"] >= 0
                    assert b_sim["status"] in {"LETHAL", "VULNERABLE", "SURVIVES", "SAFE", "IMMUNE"}


class TestStatusClassificationLogic:
    """Validates the exact damage threshold boundaries."""

    def test_immune_threshold(self) -> None:
        assert classify_damage_status(0) == "IMMUNE"
        assert classify_damage_status(500) == "IMMUNE"
        assert classify_damage_status(1000) == "IMMUNE"

    def test_safe_threshold(self) -> None:
        assert classify_damage_status(1001) == "SAFE"
        assert classify_damage_status(100_000) == "SAFE"
        assert classify_damage_status(250_000) == "SAFE"

    def test_survives_threshold(self) -> None:
        assert classify_damage_status(250_001) == "SURVIVES"
        assert classify_damage_status(350_000) == "SURVIVES"
        assert classify_damage_status(499_999) == "SURVIVES"

    def test_vulnerable_threshold(self) -> None:
        assert classify_damage_status(500_000) == "VULNERABLE"
        assert classify_damage_status(600_000) == "VULNERABLE"
        assert classify_damage_status(699_999) == "VULNERABLE"

    def test_lethal_threshold(self) -> None:
        assert classify_damage_status(700_000) == "LETHAL"
        assert classify_damage_status(1_000_000) == "LETHAL"
        assert classify_damage_status(3_000_000) == "LETHAL"


class TestMathematicalOrderOfOperations:
    """Verifies that mathematical calculations strictly follow the Dokkan order of operations."""

    def test_neutral_no_dr_calculation(self) -> None:
        # 2.5M * 1.15 = 2,875,000 - 300,000 = 2,575,000 * 1.0 = 2,575,000
        dmg = DokkanConstraintSolver.calculate_damage_taken(
            enemy_atk=2_500_000,
            type_matchup=0,
            has_passive_guard=False,
            dr_pct=0,
            def_stat=300_000,
            is_super_vs_extreme=True,
            variance=1.0,
        )
        assert dmg == 2_575_000

    def test_naked_guard_calculation(self) -> None:
        # (2.5M * 0.8) = 2,000,000 - 250,000 = 1,750,000 * 0.5 = 875,000
        dmg = DokkanConstraintSolver.calculate_damage_taken(
            enemy_atk=2_500_000,
            type_matchup=0,
            has_passive_guard=True,
            dr_pct=0,
            def_stat=250_000,
            is_super_vs_extreme=True,
            variance=1.0,
        )
        assert dmg == 875_000

    def test_dr_compression_before_def_subtraction(self) -> None:
        # Enemy 3M, 50% DR, DEF 400k, Guard:
        # (3M * 0.8 * 0.5) = 1,200,000 - 400,000 = 800,000 * 0.5 = 400,000
        dmg = DokkanConstraintSolver.calculate_damage_taken(
            enemy_atk=3_000_000,
            type_matchup=0,
            has_passive_guard=True,
            dr_pct=50,
            def_stat=400_000,
            is_super_vs_extreme=True,
            variance=1.0,
        )
        assert dmg == 400_000


class TestRequiredBenchmarkTargets:
    """Strictly validates LR Gogeta (1030481) and Supreme Kai (1015201) criteria."""

    def test_lr_gogeta_1030481_benchmark_record(self, benchmark_data: dict[str, Any]) -> None:
        benchmarks = benchmark_data["benchmarks"]
        assert "1030481" in benchmarks, "LR Gogeta (1030481) missing from benchmark dataset"
        gogeta = benchmarks["1030481"]

        assert gogeta["card_id"] == 1030481
        assert gogeta["tags"]["guard_type"] == "slot_2_3_locked"
        assert gogeta["tags"]["has_intro_cliff"] is True
        assert gogeta["tags"]["cliff_turn"] == 3
        assert gogeta["tags"]["dr_percent"] == 0

        # Slot 1: Must be completely disqualified (LETHAL)
        s1 = gogeta["slot_evaluations"]["slot_1"]
        assert s1["slot_score"] == 0.0
        assert s1["viable"] is False
        assert s1["status"] == "LETHAL"
        assert "Fatal Slot 1 Trap" in s1["vulnerability_reason"]

        s1_sims = s1["simulations"]
        assert s1_sims["boss_2_5m"]["damage_taken"] == 2_575_000
        assert s1_sims["boss_2_5m"]["status"] == "LETHAL"
        assert s1_sims["boss_2_5m"]["effective_guard"] is False

        assert s1_sims["boss_3_5m"]["damage_taken"] == 3_724_999
        assert s1_sims["boss_3_5m"]["status"] == "LETHAL"

        assert s1_sims["boss_4_2m"]["damage_taken"] == 4_530_000
        assert s1_sims["boss_4_2m"]["status"] == "LETHAL"

        # Slot 2: Prime Slot 2 Specialist, active guard, SAFE against 2.5M
        s2 = gogeta["slot_evaluations"]["slot_2"]
        assert s2["viable"] is True
        assert s2["slot_score"] == 95.0
        assert s2["status"] == "SAFE"
        assert "Prime Slot 2 Specialist" in s2["tactical_role"]

        s2_sims = s2["simulations"]
        assert s2_sims["boss_2_5m"]["damage_taken"] == 250_000
        assert s2_sims["boss_2_5m"]["status"] == "SAFE"
        assert s2_sims["boss_2_5m"]["effective_guard"] is True

        assert s2_sims["boss_3_5m"]["damage_taken"] == 650_000
        assert s2_sims["boss_3_5m"]["status"] == "VULNERABLE"

        assert s2_sims["boss_4_2m"]["damage_taken"] == 930_000
        assert s2_sims["boss_4_2m"]["status"] == "LETHAL"

    def test_supreme_kai_1015201_benchmark_record(self, benchmark_data: dict[str, Any]) -> None:
        benchmarks = benchmark_data["benchmarks"]
        assert "1015201" in benchmarks, "Supreme Kai (1015201) missing from benchmark dataset"
        kai = benchmarks["1015201"]

        assert kai["card_id"] == 1015201
        assert kai["tags"]["guard_type"] == "slot_1_only"
        assert kai["tags"]["dr_percent"] == 0

        # Slot 1: Naked Guard Trap (LETHAL)
        s1 = kai["slot_evaluations"]["slot_1"]
        assert s1["slot_score"] == 0.0
        assert s1["viable"] is False
        assert s1["status"] == "LETHAL"
        assert "Naked Guard Trap" in s1["vulnerability_reason"]

        s1_sims = s1["simulations"]
        assert s1_sims["boss_2_5m"]["damage_taken"] == 875_000
        assert s1_sims["boss_2_5m"]["status"] == "LETHAL"
        assert s1_sims["boss_2_5m"]["effective_guard"] is True

        assert s1_sims["boss_3_5m"]["damage_taken"] == 1_275_000
        assert s1_sims["boss_3_5m"]["status"] == "LETHAL"

        assert s1_sims["boss_4_2m"]["damage_taken"] == 1_555_000
        assert s1_sims["boss_4_2m"]["status"] == "LETHAL"

        # Slot 2: Guard deactivates outside Slot 1 -> LETHAL
        s2 = kai["slot_evaluations"]["slot_2"]
        assert s2["viable"] is False
        assert s2["slot_score"] == 0.0
        assert s2["status"] == "LETHAL"

        s2_sims = s2["simulations"]
        assert s2_sims["boss_2_5m"]["damage_taken"] == 2_575_000
        assert s2_sims["boss_2_5m"]["status"] == "LETHAL"
        assert s2_sims["boss_2_5m"]["effective_guard"] is False


class TestPipelineReproducibility:
    """Verifies that executing the generator function reproduces identical data."""

    def test_pipeline_execution(self) -> None:
        data = generate_damage_simulation_benchmarks()
        assert len(data["benchmarks"]) == 354
        assert data["benchmarks"]["1030481"]["slot_evaluations"]["slot_1"]["status"] == "LETHAL"
        assert data["benchmarks"]["1015201"]["slot_evaluations"]["slot_1"]["status"] == "LETHAL"
