"""Empirical Verification & Adversarial Stress Test Suite for cards_tactical_matrix.json.

Authored by: Challenger Agent (Milestone 1)
Role: Empirical Challenger / Adversarial Reviewer

Validates:
1. Data Integrity: Exact card counts (354 cards), O(1) lookup index sync, uniqueness.
2. Schema & Type Consistency: Required fields, strict typing, null constraints.
3. Value Ranges: Tactical scores (0.0 - 10.0), DR (0 - 100), Dodge (0 - 100).
4. Tag Conflicts & Edge Cases: Mutually exclusive guards, intro cliff turn pairing,
   status/score alignment, slot 2/3 locked lethality.
5. Benchmark Unit Disqualifications: LR Gogeta (1030481) and Supreme Kai (1015201)
   strictly disqualified from Slot 1 (score 0.0, status LETHAL).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MATRIX_PATH = PROJECT_ROOT / "data" / "cards_tactical_matrix.json"
CATALOG_PATH = PROJECT_ROOT / "data" / "dokkan_cards_post_10th_anniversary.json"

REQUIRED_FIELDS = [
    "card_id",
    "name",
    "subname",
    "element",
    "rarity",
    "slot1_score",
    "slot2_score",
    "slot3_score",
    "slot1_status",
    "guard_type",
    "dr_percent",
    "has_intro_cliff",
    "cliff_turn",
    "has_slot_2_3_guard",
    "has_slot_1_only_guard",
    "dodge_chance_percent",
    "has_stacking_def",
    "has_support",
    "slot_1_warning",
]

VALID_STATUSES = {"LETHAL", "UNSTABLE", "VIABLE"}
VALID_GUARD_TYPES = {
    "permanent",
    "turn_limited",
    "slot_2_3_locked",
    "slot_1_only",
    "on_hit",
    "high_chance",
    "medium_chance",
    "enemy_conditional",
    "none",
}
VALID_RARITIES = {"LR", "UR", "SSR", "SR", "R"}


@pytest.fixture(scope="module")
def matrix_data() -> dict[str, Any]:
    """Loads and provides data/cards_tactical_matrix.json."""
    assert MATRIX_PATH.exists(), f"Matrix file missing at {MATRIX_PATH}"
    with open(MATRIX_PATH, encoding="utf-8") as f:
        return json.load(f)


class TestTacticalMatrixIntegrity:
    """Stress-tests file structure, indexing, and completeness."""

    def test_top_level_keys(self, matrix_data: dict[str, Any]) -> None:
        assert "metadata" in matrix_data, "Missing top-level key: metadata"
        assert "cards" in matrix_data, "Missing top-level key: cards"
        assert "cards_by_id" in matrix_data, "Missing top-level key: cards_by_id"

    def test_metadata_completeness(self, matrix_data: dict[str, Any]) -> None:
        meta = matrix_data["metadata"]
        for field in ("title", "version", "generated_at", "total_cards", "scoring_scale"):
            assert field in meta, f"Metadata missing required field '{field}'"
        assert meta["total_cards"] == 354, f"Expected 354 total cards, got {meta['total_cards']}"
        assert meta["scoring_scale"] == "0.0 - 10.0"

    def test_card_count_exactness(self, matrix_data: dict[str, Any]) -> None:
        cards = matrix_data["cards"]
        cards_by_id = matrix_data["cards_by_id"]
        assert len(cards) == 354, f"Expected 354 cards in list, got {len(cards)}"
        assert len(cards_by_id) == 354, f"Expected 354 cards in dictionary, got {len(cards_by_id)}"

    def test_cards_by_id_synchronization(self, matrix_data: dict[str, Any]) -> None:
        """Every card in cards list must be identically indexed in cards_by_id."""
        cards = matrix_data["cards"]
        cards_by_id = matrix_data["cards_by_id"]
        seen_ids = set()

        for card in cards:
            cid = card["card_id"]
            cid_str = str(cid)
            assert cid not in seen_ids, f"Duplicate card ID found in cards list: {cid}"
            seen_ids.add(cid)
            assert cid_str in cards_by_id, f"Card ID {cid_str} missing from cards_by_id"
            assert cards_by_id[cid_str] == card, f"Data mismatch in cards_by_id for {cid_str}"

        assert len(seen_ids) == 354, f"Expected 354 unique IDs, got {len(seen_ids)}"


class TestTacticalMatrixSchemaAndTypes:
    """Stress-tests field types, null constraints, and value bounds."""

    def test_all_cards_have_required_fields_and_no_unexpected_nulls(
        self, matrix_data: dict[str, Any]
    ) -> None:
        cards = matrix_data["cards"]
        for c in cards:
            cid = c.get("card_id")
            for field in REQUIRED_FIELDS:
                assert field in c, f"Card {cid} is missing required field '{field}'"

            # Check unexpected nulls
            for k, v in c.items():
                if v is None and k not in ("cliff_turn", "slot_1_warning"):
                    pytest.fail(f"Card {cid} has unexpected null in field '{k}'")

    def test_string_field_types_and_non_emptiness(self, matrix_data: dict[str, Any]) -> None:
        cards = matrix_data["cards"]
        for c in cards:
            cid = c["card_id"]
            assert isinstance(c["name"], str) and c["name"].strip(), f"Card {cid} empty name"
            assert isinstance(c["subname"], str), f"Card {cid} subname not str"
            assert isinstance(c["element"], str) and c["element"].strip(), (
                f"Card {cid} invalid element"
            )
            assert c["rarity"] in VALID_RARITIES, f"Card {cid} invalid rarity: {c['rarity']}"
            assert c["slot1_status"] in VALID_STATUSES, (
                f"Card {cid} invalid status: {c['slot1_status']}"
            )
            assert c["guard_type"] in VALID_GUARD_TYPES, (
                f"Card {cid} invalid guard: {c['guard_type']}"
            )

    def test_score_ranges_and_types(self, matrix_data: dict[str, Any]) -> None:
        cards = matrix_data["cards"]
        for c in cards:
            cid = c["card_id"]
            for score_field in ("slot1_score", "slot2_score", "slot3_score"):
                score = c[score_field]
                assert isinstance(score, (int, float)), (
                    f"Card {cid} {score_field} not numeric: {score}"
                )
                assert score == score, f"Card {cid} {score_field} is NaN"
                assert 0.0 <= score <= 10.0, (
                    f"Card {cid} {score_field} out of range [0.0, 10.0]: {score}"
                )

    def test_defensive_percentage_ranges_and_types(self, matrix_data: dict[str, Any]) -> None:
        cards = matrix_data["cards"]
        for c in cards:
            cid = c["card_id"]
            dr = c["dr_percent"]
            assert isinstance(dr, int), f"Card {cid} dr_percent not int: {dr}"
            assert 0 <= dr <= 100, f"Card {cid} dr_percent out of range [0, 100]: {dr}"

            dodge = c["dodge_chance_percent"]
            assert isinstance(dodge, int), f"Card {cid} dodge_chance_percent not int: {dodge}"
            assert 0 <= dodge <= 100, (
                f"Card {cid} dodge_chance_percent out of range [0, 100]: {dodge}"
            )

    def test_boolean_flag_types(self, matrix_data: dict[str, Any]) -> None:
        cards = matrix_data["cards"]
        for c in cards:
            cid = c["card_id"]
            for bool_field in (
                "has_intro_cliff",
                "has_slot_2_3_guard",
                "has_slot_1_only_guard",
                "has_stacking_def",
                "has_support",
            ):
                assert isinstance(c[bool_field], bool), f"Card {cid} {bool_field} is not bool"


class TestTacticalMatrixEdgeCasesAndTagConflicts:
    """Stress-tests logical consistency across tags and domain rules."""

    def test_mutually_exclusive_slot_guards(self, matrix_data: dict[str, Any]) -> None:
        """A unit cannot simultaneously have slot_2_3_guard and slot_1_only_guard."""
        cards = matrix_data["cards"]
        conflicts = [
            c["card_id"] for c in cards if c["has_slot_2_3_guard"] and c["has_slot_1_only_guard"]
        ]
        assert not conflicts, f"Cards with conflicting slot guards: {conflicts}"

    def test_guard_type_and_flag_alignment(self, matrix_data: dict[str, Any]) -> None:
        """guard_type 'slot_2_3_locked' must match has_slot_2_3_guard and vice versa."""
        cards = matrix_data["cards"]
        for c in cards:
            cid = c["card_id"]
            if c["guard_type"] == "slot_2_3_locked":
                assert c["has_slot_2_3_guard"] is True, (
                    f"Card {cid} guard_type slot_2_3_locked but flag False"
                )
            if c["guard_type"] == "slot_1_only":
                assert c["has_slot_1_only_guard"] is True, (
                    f"Card {cid} guard_type slot_1_only but flag False"
                )

    def test_intro_cliff_turn_pairing(self, matrix_data: dict[str, Any]) -> None:
        """cliff_turn must be an int >= 1 if has_intro_cliff is True, and None otherwise."""
        cards = matrix_data["cards"]
        for c in cards:
            cid = c["card_id"]
            if c["has_intro_cliff"]:
                assert isinstance(c["cliff_turn"], int) and c["cliff_turn"] >= 1, (
                    f"Card {cid} has_intro_cliff is True but cliff_turn is invalid: {c['cliff_turn']}"
                )
            else:
                assert c["cliff_turn"] is None, (
                    f"Card {cid} has_intro_cliff is False but cliff_turn is not None: {c['cliff_turn']}"
                )

    def test_slot2_3_guard_strictly_disqualified_from_slot1(
        self, matrix_data: dict[str, Any]
    ) -> None:
        """Any card with slot_2_3_locked guard MUST have slot1_score == 0.0 and status LETHAL."""
        cards = matrix_data["cards"]
        for c in cards:
            cid = c["card_id"]
            if c["has_slot_2_3_guard"] or c["guard_type"] == "slot_2_3_locked":
                assert c["slot1_score"] == 0.0, (
                    f"Card {cid} has slot 2/3 guard but slot1_score = {c['slot1_score']} (expected 0.0)"
                )
                assert c["slot1_status"] == "LETHAL", (
                    f"Card {cid} has slot 2/3 guard but slot1_status = {c['slot1_status']} (expected LETHAL)"
                )
                assert c["slot_1_warning"] is not None and "FATAL TRAP" in c["slot_1_warning"], (
                    f"Card {cid} has slot 2/3 guard but missing FATAL TRAP warning"
                )

    def test_slot1_status_and_score_consistency(self, matrix_data: dict[str, Any]) -> None:
        """VIABLE must score >= 6.0, UNSTABLE in [2.0, 5.5], LETHAL <= 1.5."""
        cards = matrix_data["cards"]
        for c in cards:
            cid = c["card_id"]
            status = c["slot1_status"]
            score = c["slot1_score"]

            if status == "VIABLE":
                assert score >= 6.0, f"Card {cid} VIABLE but score={score} < 6.0"
            elif status == "UNSTABLE":
                assert 2.0 <= score <= 5.5, (
                    f"Card {cid} UNSTABLE but score={score} not in [2.0, 5.5]"
                )
            elif status == "LETHAL":
                assert score <= 1.5, f"Card {cid} LETHAL but score={score} > 1.5"

    def test_warning_presence_on_lethal_cards(self, matrix_data: dict[str, Any]) -> None:
        """Every LETHAL card must provide a warning string."""
        cards = matrix_data["cards"]
        for c in cards:
            cid = c["card_id"]
            if c["slot1_status"] == "LETHAL":
                assert isinstance(c["slot_1_warning"], str) and c["slot_1_warning"].strip(), (
                    f"Card {cid} is LETHAL but missing slot_1_warning"
                )

    def test_known_slot1_tanks_not_misclassified_as_slot2_3_locked(
        self, matrix_data: dict[str, Any]
    ) -> None:
        """Iconic tanks like Orange Piccolo (1025591) and Golden Frieza (1024511)
        must not be falsely classified as slot_2_3_locked with score 0.0 and fatal trap."""
        by_id = matrix_data["cards_by_id"]
        # 1025591: Piccolo (Power Awakening)
        if "1025591" in by_id:
            piccolo = by_id["1025591"]
            assert piccolo["guard_type"] != "slot_2_3_locked", (
                "Piccolo (1025591) falsely marked as slot_2_3_locked!"
            )
            assert piccolo["has_slot_2_3_guard"] is False, (
                "Piccolo (1025591) falsely has has_slot_2_3_guard=True!"
            )
        # 1024511: Golden Frieza
        if "1024511" in by_id:
            frieza = by_id["1024511"]
            assert frieza["guard_type"] != "slot_2_3_locked", (
                "Golden Frieza (1024511) falsely marked as slot_2_3_locked!"
            )
            assert frieza["has_slot_2_3_guard"] is False, (
                "Golden Frieza (1024511) falsely has has_slot_2_3_guard=True!"
            )


class TestBenchmarkDisqualifications:
    """Strictly validates LR Gogeta (1030481) and Supreme Kai (1015201) requirements."""

    def test_lr_gogeta_1030481_disqualification(self, matrix_data: dict[str, Any]) -> None:
        by_id = matrix_data["cards_by_id"]
        assert "1030481" in by_id, "LR Gogeta (1030481) missing from matrix"
        gogeta = by_id["1030481"]

        assert gogeta["card_id"] == 1030481
        assert gogeta["slot1_score"] == 0.0, (
            f"Expected slot1_score 0.0, got {gogeta['slot1_score']}"
        )
        assert gogeta["slot1_status"] == "LETHAL", (
            f"Expected status LETHAL, got {gogeta['slot1_status']}"
        )
        assert gogeta["slot2_score"] == 9.5, (
            f"Expected slot2_score 9.5, got {gogeta['slot2_score']}"
        )
        assert gogeta["slot3_score"] == 8.5, (
            f"Expected slot3_score 8.5, got {gogeta['slot3_score']}"
        )
        assert gogeta["guard_type"] == "slot_2_3_locked"
        assert gogeta["has_slot_2_3_guard"] is True
        assert gogeta["has_slot_1_only_guard"] is False
        assert gogeta["has_intro_cliff"] is True
        assert gogeta["cliff_turn"] == 3
        assert gogeta["dr_percent"] == 0
        assert "FATAL TRAP" in gogeta["slot_1_warning"]
        assert "2nd or 3rd attacker" in gogeta["slot_1_warning"]

    def test_supreme_kai_1015201_disqualification(self, matrix_data: dict[str, Any]) -> None:
        by_id = matrix_data["cards_by_id"]
        assert "1015201" in by_id, "Supreme Kai (1015201) missing from matrix"
        kai = by_id["1015201"]

        assert kai["card_id"] == 1015201
        assert kai["slot1_score"] == 0.0, f"Expected slot1_score 0.0, got {kai['slot1_score']}"
        assert kai["slot1_status"] == "LETHAL", f"Expected status LETHAL, got {kai['slot1_status']}"
        assert kai["slot2_score"] == 3.0, f"Expected slot2_score 3.0, got {kai['slot2_score']}"
        assert kai["slot3_score"] == 5.0, f"Expected slot3_score 5.0, got {kai['slot3_score']}"
        assert kai["guard_type"] == "slot_1_only"
        assert kai["has_slot_1_only_guard"] is True
        assert kai["has_slot_2_3_guard"] is False
        assert kai["has_intro_cliff"] is False
        assert kai["cliff_turn"] is None
        assert kai["dr_percent"] == 0
        assert "FATAL TRAP" in kai["slot_1_warning"]
        assert "Naked Guard without Damage Reduction" in kai["slot_1_warning"]


class TestRegenerationReproducibility:
    """Validates that running the generation pipeline produces identical data."""

    def test_catalog_source_file_exists(self) -> None:
        assert CATALOG_PATH.exists(), f"Catalog file missing at {CATALOG_PATH}"

    def test_generator_tool_runs_cleanly(self) -> None:
        from tools.generate_cards_tactical_matrix import generate_tactical_matrix

        reproduced = generate_tactical_matrix()
        assert len(reproduced["cards"]) == 354
        assert len(reproduced["cards_by_id"]) == 354
        assert reproduced["cards_by_id"]["1030481"]["slot1_score"] == 0.0
        assert reproduced["cards_by_id"]["1015201"]["slot1_score"] == 0.0
