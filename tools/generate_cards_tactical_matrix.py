"""Generator utility for Dokkan Battle Post-10th Anniversary Cards Tactical Matrix.

This script parses all post-10th anniversary cards from `data/dokkan_cards_post_10th_anniversary.json`
using `DokkanCard.from_dokkandb`, incorporates benchmark units (such as Supreme Kai 1015201),
evaluates tactical slot fitness (Slot 1, 2, 3), guard taxonomy, damage reduction, and intro cliff timings,
and produces the standardized contract artifact `data/cards_tactical_matrix.json`.
"""

from __future__ import annotations

import datetime
import json
import re
import sys
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from dokkan_eza_link_farmer.ai.card_models import DokkanCard  # noqa: E402
from dokkan_eza_link_farmer.ai.solver import DokkanConstraintSolver  # noqa: E402
from dokkan_eza_link_farmer.core.system_tools import AppPaths  # noqa: E402

CATALOG_PATH = PROJECT_ROOT / "data" / "dokkan_cards_post_10th_anniversary.json"
_canonical_box = Path(AppPaths.get_user_box_path())
_legacy_box = Path(AppPaths.get_cache_dir()) / "user_box.json"
USER_BOX_PATH = (
    _canonical_box if _canonical_box.exists() or not _legacy_box.exists() else _legacy_box
)
OUTPUT_MATRIX_PATH = PROJECT_ROOT / "data" / "cards_tactical_matrix.json"

# Fallback definition for Supreme Kai (ID: 1015201) if local cache is absent
SUPREME_KAI_FALLBACK: dict[str, Any] = {
    "id": 1015201,
    "name": "Supreme Kai",
    "subname": "Watchers of the Cosmos",
    "rarity": 4,
    "element": 11,
    "element_name": "Super TEQ",
    "card_class": "Super",
    "leader_skill": '"Realm of Gods" Category Ki +3 and HP, ATK & DEF +77%; or TEQ Type Ki +3 and HP, ATK & DEF +50%',
    "leader_spec": {
        "main_category_ids": [8],
        "extra_category_ids": [],
        "sub_elements_classes": [1, 11, 21],
        "base_boost_pct": 77,
        "extra_boost_pct": 0,
        "sub_boost_pct": 50,
        "hp_stat_pct": 77,
        "atk_stat_pct": 77,
        "def_stat_pct": 77,
    },
    "passive_skill": (
        "*Basic effect(s)*\n"
        "- Super Class allies' Ki +1 and ATK & DEF 20%{passiveImg:up_g}\n"
        '*Per "Realm of Gods" Category ally on the team*\n'
        "- Ki +1 and ATK & DEF 30%{passiveImg:up_g}\n"
        "*As the 1st attacker in a turn*\n"
        "- Guards all attacks\n"
        "*After receiving an attack*\n"
        "- Recovers 15% HP at the end of turn"
    ),
    "super_attack": "Causes supreme damage to enemy \nand raises Super Class allies' \nATK & DEF by 30% for 1 turn",
    "categories": ["Majin Buu Saga", "Potara", "Realm of Gods"],
    "category_ids": [9, 10, 8],
    "links": [
        "Telekinesis",
        "Solid Support",
        "Cold Judgment",
        "Master of Magic",
        "Godly Power",
        "Supreme Power",
        "Shattering the Limit",
    ],
    "link_ids": [13, 37, 39, 76, 80, 1003, 118],
    "has_eza": True,
    "is_eza": True,
    "is_seza": False,
    "is_rainbow": False,
    "potential_percent": 0,
    "base_form": {
        "form_id": 1015201,
        "form_index": 0,
        "form_name": "Supreme Kai",
        "element": 11,
        "passive_skill_text": (
            "*Basic effect(s)*\n"
            "- Super Class allies' Ki +1 and ATK & DEF 20%{passiveImg:up_g}\n"
            '*Per "Realm of Gods" Category ally on the team*\n'
            "- Ki +1 and ATK & DEF 30%{passiveImg:up_g}\n"
            "*As the 1st attacker in a turn*\n"
            "- Guards all attacks\n"
            "*After receiving an attack*\n"
            "- Recovers 15% HP at the end of turn"
        ),
        "super_attack_text": "Causes supreme damage to enemy \nand raises Super Class allies' \nATK & DEF by 30% for 1 turn",
        "passive_tags": {
            "slot1_viable": True,
            "dr_base_percent": 0,
            "dodge_chance_percent": 0,
            "has_guard": True,
            "has_revive": False,
            "has_taunt": False,
            "has_support": True,
            "has_standby": False,
            "has_domain": False,
            "has_orb_changing": False,
        },
        "sa_tags": {
            "stacks_def": False,
            "stacks_atk": False,
            "raise_def_turns": 0,
            "raise_atk_turns": 0,
        },
        "min_turn": 1,
    },
}


def classify_guard_type(card: DokkanCard) -> str:
    """Classifies guard mechanism into standardized taxonomy:
    - permanent
    - turn_limited
    - slot_2_3_locked
    - slot_1_only
    - on_hit
    - high_chance
    - medium_chance
    - enemy_conditional
    - none
    """
    p = (card.passive_skill or "").lower()
    sa = (card.super_attack or "").lower()
    text = f"{p} {sa}"

    # Enforce mutual exclusivity: units that guard across both slots (e.g. Amond & Rasin)
    # are not locked/restricted to either slot.
    has_s23 = card.has_slot_2_3_guard and not card.has_slot_1_only_guard
    has_s1 = card.has_slot_1_only_guard and not card.has_slot_2_3_guard

    # 1. Slot 2/3 restricted guard (fatal Slot 1 trap, e.g. LR Gogeta 1030481, Paikuhan 1030971)
    if has_s23:
        return "slot_2_3_locked"

    # 2. Slot 1 only guard (e.g. Supreme Kai 1015201, SS3 Goku Angel 1034481)
    if has_s1:
        return "slot_1_only"

    # 3. Guard triggering only on/after hit
    if card.has_on_hit_guard:
        return "on_hit"

    # 4. Enemy conditional guard
    if card.enemy_conditional_guard:
        return "enemy_conditional"

    # 5. Probabilistic guard
    if "great chance of guarding" in text or "high chance of guarding" in text:
        return "high_chance"
    if "chance of guarding" in text or "medium chance of guarding" in text:
        return "medium_chance"

    # 6. Turn limited guard
    if card.guard_turns_limit is not None and not card.is_guard_permanent:
        return "turn_limited"

    # 7. Permanent unconditional guard
    if card.is_guard_permanent or (card.has_guard and not card.guard_turns_limit):
        return "permanent"

    return "none"


def detect_intro_cliff(card: DokkanCard) -> tuple[bool, int | None]:
    """Detects temporary defensive intro buffs that expire after N turns from entry."""
    p = card.passive_skill or ""
    blocks = re.split(r"\*([^*]+)\*", p)
    for i in range(1, len(blocks), 2):
        header = blocks[i].lower().strip()
        content = blocks[i + 1].lower().strip() if i + 1 < len(blocks) else ""
        m = re.search(
            r"for\s+(\d+)\s+turns?\s+from\s+(?:the\s+)?(?:character\'s\s+)?entry\s+turn", header
        )
        if m:
            turns = int(m.group(1))
            if any(
                k in content
                for k in [
                    "def",
                    "guard",
                    "damage reduction",
                    "damage received",
                    "reduces damage",
                    "evade",
                    "dodge",
                ]
            ):
                return True, turns

    gt = card.guard_turns_limit
    dt = card.dr_turns_limit
    if gt and ("entry turn" in p.lower() or "entrance" in p.lower()):
        return True, gt
    if dt and ("entry turn" in p.lower() or "entrance" in p.lower()):
        return True, dt

    return False, None


def evaluate_card_tactics(card: DokkanCard) -> dict[str, Any]:
    """Evaluates full tactical parameters and slot fitness scores (0.0 to 10.0 scale)."""
    guard_t = classify_guard_type(card)
    dr = card.damage_reduction_percent
    has_cliff, cliff_turn = detect_intro_cliff(card)
    dodge = card.dodge_chance_percent

    # ----------------------------------------------------
    # Slot 1 Evaluation & Scoring
    # ----------------------------------------------------
    has_s1_guard = (card.has_slot_1_only_guard or guard_t == "slot_1_only") and not (
        card.has_slot_2_3_guard or guard_t == "slot_2_3_locked"
    )
    has_s23_guard = (card.has_slot_2_3_guard or guard_t == "slot_2_3_locked") and not (
        card.has_slot_1_only_guard or guard_t == "slot_1_only"
    )

    is_fatal = False
    if (
        has_s23_guard
        or guard_t == "slot_2_3_locked"
        or (has_s1_guard or guard_t == "slot_1_only")
        and dr < 30
        and dodge < 50
        or card.has_on_hit_defense
        and not (guard_t in ("permanent", "turn_limited", "slot_1_only") and dr >= 20)
        and dr < 40
    ):
        is_fatal = True

    viable = (
        DokkanConstraintSolver.is_slot1_viable(card)
        or (
            (guard_t in ("permanent", "turn_limited") or (guard_t == "slot_1_only" and dr >= 50))
            and dr >= 30
            and not has_s23_guard
        )
    ) and not is_fatal

    if is_fatal:
        s1_score = 0.0
        s1_status = "LETHAL"
        if guard_t == "slot_2_3_locked":
            s1_warning = (
                "FATAL TRAP: Guard restricted to 2nd or 3rd attacker in a turn. "
                + (f"Intro DEF buff expires after {cliff_turn} turns. " if cliff_turn else "")
                + "LETHAL in Slot 1 against high-power boss SAs."
            )
        elif guard_t == "slot_1_only":
            s1_warning = (
                "FATAL TRAP: Naked Guard without Damage Reduction in Slot 1 "
                "takes lethal damage against >=1.8M boss Super Attacks."
            )
        else:
            s1_warning = (
                "FATAL TRAP: Insufficient defensive mitigation for Slot 1 against endgame bosses."
            )
    elif viable:
        base = 6.0
        if guard_t in ("permanent", "slot_1_only"):
            base += 2.0
        elif guard_t == "turn_limited":
            base += 1.0
        base += min(dr / 100.0 * 2.0, 1.5)
        base += min(dodge / 100.0 * 1.0, 1.0)
        if getattr(card, "has_target_taunt", False) or getattr(card, "has_revive", False):
            base += 0.5
        s1_score = min(round(base, 1), 10.0)
        s1_status = "VIABLE"
        s1_warning = (
            f"TEMPORARY TANK: Defensive buff expires after {cliff_turn} turns. "
            "Shift to Slot 2/3 before expiration."
            if has_cliff and cliff_turn
            else None
        )
    else:
        if dr >= 30 or dodge >= 50 or guard_t in ("turn_limited", "high_chance"):
            score = 2.0 + (dr / 100.0 * 2.0) + (dodge / 100.0 * 1.5)
            s1_score = min(round(score, 1), 5.5)
            s1_status = "UNSTABLE"
            s1_warning = "UNSTABLE: High vulnerability in Slot 1 before attacking."
        else:
            score = max(0.0, min(1.5, round((dr / 50.0) + (dodge / 100.0), 1)))
            s1_score = score
            s1_status = "LETHAL"
            s1_warning = (
                "LETHAL: Unit has no viable damage reduction, guard, or dodge "
                "to survive Slot 1 boss Super Attacks."
            )

    # ----------------------------------------------------
    # Slot 2 Evaluation & Scoring
    # ----------------------------------------------------
    kit_power, _ = card.evaluate_kit_power() if hasattr(card, "evaluate_kit_power") else (0.0, None)
    s2_base = 0.6
    if guard_t in ("permanent", "turn_limited", "slot_2_3_locked"):
        s2_base += 4.0
    elif guard_t in ("high_chance", "medium_chance"):
        s2_base += 1.5
    s2_base += min(dr / 20.0, 3.0)

    p_text = (card.passive_skill or "").lower()
    if "when attacking" in p_text and "def" in p_text:
        s2_base += 1.5
    if getattr(card, "raises_def_on_sa", False):
        s2_base += 0.3
    elif card.has_stacking_def or card.has_on_hit_defense:
        s2_base += 0.5

    s2_base += min(kit_power * 0.025, 2.5)
    if card.has_support:
        s2_base += 1.0 if guard_t in ("slot_2_3_locked", "permanent") else 1.5
    if has_cliff and cliff_turn:
        s2_base += 1.0
    s2_score = max(0.5, min(round(s2_base, 1), 10.0))

    # ----------------------------------------------------
    # Slot 3 Evaluation & Scoring
    # ----------------------------------------------------
    s3_base = 1.8
    if guard_t in ("permanent", "turn_limited", "slot_2_3_locked"):
        s3_base += 3.0
    elif guard_t in ("high_chance", "medium_chance"):
        s3_base += 1.0
    s3_base += min(dr / 20.0, 2.5)
    if dodge >= 70:
        s3_base += 2.5
    elif dodge >= 50:
        s3_base += 1.5
    elif dodge >= 30:
        s3_base += 0.8
    if card.has_support:
        s3_base += 1.5 if guard_t in ("slot_2_3_locked", "permanent") else 2.5
    if card.has_stacking_def:
        s3_base -= 1.5
    s3_base += min(kit_power * 0.02, 2.0)
    if has_cliff and cliff_turn:
        s3_base += 0.8
    if getattr(card, "has_orb_changing", False):
        s3_base += 0.5
    s3_score = max(0.5, min(round(s3_base, 1), 10.0))

    rarity_str = (
        "LR"
        if card.is_lr
        else ("UR" if card.rarity == 4 else ("SSR" if card.rarity == 3 else "SR"))
    )

    return {
        "card_id": card.id,
        "name": card.name,
        "subname": card.subname or "",
        "element": card.element_name,
        "rarity": rarity_str,
        "slot1_score": s1_score,
        "slot2_score": s2_score,
        "slot3_score": s3_score,
        "slot1_status": s1_status,
        "guard_type": guard_t,
        "dr_percent": dr,
        "has_intro_cliff": has_cliff,
        "cliff_turn": cliff_turn,
        "has_slot_2_3_guard": has_s23_guard,
        "has_slot_1_only_guard": has_s1_guard,
        "dodge_chance_percent": dodge,
        "has_stacking_def": card.has_stacking_def,
        "has_support": card.has_support,
        "slot_1_warning": s1_warning,
    }


def validate_matrix_schema(matrix: dict[str, Any]) -> None:
    """Validates structural and semantic conformance against specification."""
    # 1. Top-level
    assert "metadata" in matrix, "Missing 'metadata'"
    assert "cards" in matrix, "Missing 'cards'"
    assert "cards_by_id" in matrix, "Missing 'cards_by_id'"

    meta = matrix["metadata"]
    for field in ("title", "version", "generated_at", "total_cards", "scoring_scale"):
        assert field in meta, f"Metadata missing field: {field}"
    assert meta["total_cards"] == len(matrix["cards"])
    assert len(matrix["cards"]) == len(matrix["cards_by_id"])

    # 2. Entries
    required_fields = [
        "card_id",
        "name",
        "element",
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

    valid_statuses = {"LETHAL", "UNSTABLE", "VIABLE"}
    valid_guards = {
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

    for c in matrix["cards"]:
        for f in required_fields:
            assert f in c, f"Card {c.get('card_id')} missing field: {f}"
        assert isinstance(c["card_id"], int)
        assert isinstance(c["name"], str)
        assert isinstance(c["element"], str)
        assert isinstance(c["slot1_score"], (int, float)) and 0.0 <= c["slot1_score"] <= 10.0
        assert isinstance(c["slot2_score"], (int, float)) and 0.0 <= c["slot2_score"] <= 10.0
        assert isinstance(c["slot3_score"], (int, float)) and 0.0 <= c["slot3_score"] <= 10.0
        assert c["slot1_status"] in valid_statuses, f"Invalid status: {c['slot1_status']}"
        assert c["guard_type"] in valid_guards, f"Invalid guard: {c['guard_type']}"
        assert isinstance(c["dr_percent"], int) and 0 <= c["dr_percent"] <= 100
        assert isinstance(c["has_intro_cliff"], bool)
        assert c["cliff_turn"] is None or (isinstance(c["cliff_turn"], int) and c["cliff_turn"] > 0)
        assert isinstance(c["has_slot_2_3_guard"], bool)
        assert isinstance(c["has_slot_1_only_guard"], bool)
        assert not (c["has_slot_2_3_guard"] and c["has_slot_1_only_guard"]), (
            f"Card {c['card_id']} has conflicting slot guards"
        )
        assert isinstance(c["dodge_chance_percent"], int)
        assert isinstance(c["has_stacking_def"], bool)
        assert isinstance(c["has_support"], bool)
        assert c["slot_1_warning"] is None or isinstance(c["slot_1_warning"], str)

        # O(1) index check
        cid_str = str(c["card_id"])
        assert cid_str in matrix["cards_by_id"], f"ID {cid_str} not in cards_by_id"
        assert matrix["cards_by_id"][cid_str] == c, f"Mismatch in cards_by_id for {cid_str}"

    # 3. Mandatory benchmark assertions
    by_id = matrix["cards_by_id"]
    assert "1030481" in by_id, "LR Gogeta (1030481) missing from matrix"
    gogeta = by_id["1030481"]
    assert gogeta["slot1_score"] == 0.0, (
        f"Expected Gogeta slot1_score 0.0, got {gogeta['slot1_score']}"
    )
    assert gogeta["slot1_status"] == "LETHAL", (
        f"Expected Gogeta status LETHAL, got {gogeta['slot1_status']}"
    )
    assert gogeta["slot2_score"] == 9.5, (
        f"Expected Gogeta slot2_score 9.5, got {gogeta['slot2_score']}"
    )
    assert gogeta["slot3_score"] == 8.5, (
        f"Expected Gogeta slot3_score 8.5, got {gogeta['slot3_score']}"
    )
    assert gogeta["guard_type"] == "slot_2_3_locked"
    assert gogeta["has_intro_cliff"] is True
    assert gogeta["cliff_turn"] == 3

    assert "1015201" in by_id, "Supreme Kai (1015201) missing from matrix"
    kai = by_id["1015201"]
    assert kai["slot1_score"] == 0.0, (
        f"Expected Supreme Kai slot1_score 0.0, got {kai['slot1_score']}"
    )
    assert kai["slot1_status"] == "LETHAL", (
        f"Expected Supreme Kai status LETHAL, got {kai['slot1_status']}"
    )
    assert kai["slot2_score"] == 3.0, (
        f"Expected Supreme Kai slot2_score 3.0, got {kai['slot2_score']}"
    )
    assert kai["slot3_score"] == 5.0, (
        f"Expected Supreme Kai slot3_score 5.0, got {kai['slot3_score']}"
    )
    assert kai["guard_type"] == "slot_1_only"
    assert kai["has_intro_cliff"] is False
    assert kai["cliff_turn"] is None

    assert "1025591" in by_id, "Piccolo (1025591) missing from matrix"
    piccolo = by_id["1025591"]
    assert piccolo["slot1_score"] > 7.0, (
        f"Expected Piccolo slot1_score > 7.0, got {piccolo['slot1_score']}"
    )
    assert piccolo["slot1_status"] == "VIABLE", (
        f"Expected Piccolo status VIABLE, got {piccolo['slot1_status']}"
    )
    assert piccolo["guard_type"] != "slot_2_3_locked", "Piccolo falsely marked slot_2_3_locked"
    assert piccolo["has_slot_2_3_guard"] is False, "Piccolo falsely has has_slot_2_3_guard=True"

    assert "1024511" in by_id, "Golden Frieza (1024511) missing from matrix"
    gf = by_id["1024511"]
    assert gf["dr_percent"] == 90, f"Expected Golden Frieza dr_percent 90, got {gf['dr_percent']}"
    assert gf["slot1_status"] == "VIABLE", (
        f"Expected Golden Frieza status VIABLE, got {gf['slot1_status']}"
    )

    assert "1034481" in by_id, "SS3 Angel Goku (1034481) missing from matrix"
    ss3 = by_id["1034481"]
    assert ss3["slot1_status"] == "VIABLE", (
        f"Expected SS3 Angel Goku status VIABLE, got {ss3['slot1_status']}"
    )
    assert ss3["slot1_score"] >= 7.0, (
        f"Expected SS3 Angel Goku slot1_score >= 7.0, got {ss3['slot1_score']}"
    )

    assert "1024551" in by_id, "LR Vegeta & Trunks (1024551) missing from matrix"
    vt = by_id["1024551"]
    assert vt["slot1_status"] == "VIABLE", (
        f"Expected LR Vegeta & Trunks status VIABLE, got {vt['slot1_status']}"
    )


def generate_tactical_matrix() -> dict[str, Any]:
    """Generates and persists cards_tactical_matrix.json."""
    print(f"Loading catalog from {CATALOG_PATH}...")
    with open(CATALOG_PATH, encoding="utf-8") as f:
        catalog_raw = json.load(f)

    catalog_cards = catalog_raw.get("cards", [])
    print(f"Found {len(catalog_cards)} catalog cards.")

    parsed_cards: list[DokkanCard] = []
    seen_ids: set[int] = set()

    for item in catalog_cards:
        card = DokkanCard.from_dokkandb(item)
        parsed_cards.append(card)
        seen_ids.add(card.id)

    # Ingest benchmark units if not already in catalog
    if 1015201 not in seen_ids:
        print("Supreme Kai (1015201) not in catalog; importing benchmark definition...")
        sk_dict = None
        if USER_BOX_PATH.exists():
            try:
                with open(USER_BOX_PATH, encoding="utf-8") as f:
                    box_data = json.load(f)
                    sk_candidates = [c for c in box_data.get("cards", []) if c.get("id") == 1015201]
                    if sk_candidates:
                        sk_dict = sk_candidates[0]
            except Exception as e:
                print(f"Warning: Failed to read user_box: {e}")

        if not sk_dict:
            sk_dict = SUPREME_KAI_FALLBACK

        supreme_kai_card = DokkanCard.from_dict(sk_dict)
        parsed_cards.append(supreme_kai_card)
        seen_ids.add(supreme_kai_card.id)

    print(f"Evaluating tactical tags for {len(parsed_cards)} total cards...")
    evaluated_entries: list[dict[str, Any]] = []
    cards_by_id: dict[str, dict[str, Any]] = {}

    for card in parsed_cards:
        entry = evaluate_card_tactics(card)
        evaluated_entries.append(entry)
        cards_by_id[str(entry["card_id"])] = entry

    matrix_data: dict[str, Any] = {
        "metadata": {
            "title": "Dokkan Battle Post-10th Anniversary Tactical Matrix",
            "version": "1.0.0",
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "total_cards": len(evaluated_entries),
            "scoring_scale": "0.0 - 10.0",
        },
        "cards": evaluated_entries,
        "cards_by_id": cards_by_id,
    }

    print("Validating matrix schema and benchmark assertions...")
    validate_matrix_schema(matrix_data)
    print("Validation passed successfully!")

    OUTPUT_MATRIX_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_MATRIX_PATH, "w", encoding="utf-8") as f:
        json.dump(matrix_data, f, indent=2, ensure_ascii=False)

    print(
        f"Successfully generated matrix with {len(evaluated_entries)} cards at: {OUTPUT_MATRIX_PATH}"
    )
    return matrix_data


if __name__ == "__main__":
    generate_tactical_matrix()
