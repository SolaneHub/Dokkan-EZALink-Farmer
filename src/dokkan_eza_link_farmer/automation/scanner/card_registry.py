"""Card registration and inventory management for the box scanner."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import numpy as np


def register_card(
    task: Any,
    cand: dict[str, Any] | None,
    score: float,
    crop: np.ndarray | None = None,
    cy: float = 0.0,
    cx: int = 0,
    swipe_page: int = 0,
    grid_slot: int = 0,
    is_rainbow: bool | None = None,
    is_eza: bool | None = None,
    potential_percent: int | None = None,
) -> bool:
    """Registers a recognized card into task.scanned_cards with duplicate and adjacency protection."""
    if not cand or score < 0.65:
        if cand and score >= 0.50:
            task.log(
                f"  [LOW_CONF] Candidate [{cand.get('id') or cand.get('card_id')}] {cand.get('name')} score {score:.2f} < 0.65"
            )
        return False

    cid = int(cand.get("card_id") or cand.get("id") or 0)
    if cid == 0:
        task.log(f"  [INVALID_CARD] Candidate has invalid id {cid}, skipping registration.")
        return False

    if not hasattr(task, "_session_seen_ids") or task._session_seen_ids is None:
        task._session_seen_ids = set()
    if not hasattr(task, "_recently_scanned_positions") or task._recently_scanned_positions is None:
        task._recently_scanned_positions = {}
    if not hasattr(task, "scanned_cards") or task.scanned_cards is None:
        task.scanned_cards = {}

    cat_card = task._id_index.get(cid, {}) if hasattr(task, "_id_index") and task._id_index else {}
    cname = cat_card.get("name") or cand.get("name", "Unknown")
    csub = cat_card.get("subname") or cand.get("subname", "")
    rarity = cat_card.get("rarity") or cand.get("rarity", 4)
    elem = cat_card.get("element") or cand.get("element")

    if is_rainbow is None:
        is_rainbow = task._detect_rainbow_star(crop) if crop is not None else False
    if potential_percent is None:
        potential_percent = 100 if is_rainbow else 0
    elif potential_percent == 100:
        is_rainbow = True
    if is_rainbow and potential_percent == 0:
        potential_percent = 100

    if is_eza is None:
        has_eza_data = bool(
            cat_card.get("eza_leader_skill")
            or cat_card.get("passive_skills_rows_eza")
            or cat_card.get("eza_leader_skill_set_id")
            or cand.get("has_eza")
        )
        has_seza_data = bool(
            cat_card.get("eza_passive_skill_description_pre")
            or cat_card.get("passive_skills_rows_eza_pre")
            or cat_card.get("eza_leader_skill_set_id_pre")
            or cand.get("has_seza")
        )
        is_seza = has_seza_data
        is_eza = has_eza_data or is_seza
    else:
        is_seza = bool(cand.get("has_seza") or cat_card.get("eza_leader_skill_set_id_pre"))

    prev_pos = task._recently_scanned_positions.get(cid)
    if prev_pos is not None:
        if isinstance(prev_pos, (tuple, list)):
            if len(prev_pos) >= 2:
                p_cy, p_cx = float(prev_pos[0]), float(prev_pos[1])
            elif len(prev_pos) == 1:
                p_cy, p_cx = float(prev_pos[0]), float(cx)
            else:
                p_cy, p_cx = 0.0, float(cx)
        elif isinstance(prev_pos, (int, float, str)):
            p_cy, p_cx = float(prev_pos), float(cx)
        else:
            p_cy, p_cx = 0.0, float(cx)
        if abs(p_cx - cx) < 60.0 and abs(p_cy - cy) < 180.0 and (cx != 0 or cy != 0):
            task._recently_scanned_positions[cid] = (cy, cx)
            return True

    if cid not in task.scanned_cards:
        existing = task.scanned_cards.get(cid, {})
        card_record = dict(existing)
        card_record.update(
            {
                "id": cid,
                "name": cname,
                "title": csub,
                "subname": csub,
                "rarity": rarity,
                "element": elem,
                "rainbow": is_rainbow,
                "is_rainbow": is_rainbow,
                "is_eza": is_eza,
                "is_seza": is_seza,
                "potential_percent": potential_percent,
                "copies": 1,
                "swipe_page": swipe_page,
                "grid_slot": grid_slot,
                "scanned_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        card_record.setdefault("leader_skill", "")
        card_record.setdefault("categories", [])
        for k in (
            "leader_spec",
            "passive_tags",
            "sa_tags",
            "link_ids",
            "category_ids",
            "links",
            "categories",
            "leader_skill",
            "passive_skill",
            "best_in_box_partners",
        ):
            if k in cat_card:
                card_record[k] = cat_card[k]
            elif k in cand:
                card_record[k] = cand[k]
        task.scanned_cards[cid] = card_record
        task._session_seen_ids.add(cid)
        task._last_registered_card_id = cid
        task._recently_scanned_positions[cid] = (cy, cx)
        r_str = "LR" if rarity == 5 else ("UR" if rarity == 4 else "SSR")
        star_str = "★ Rainbow" if is_rainbow else "★"
        task.log(
            f"  [NEW] [{score:.2f}] #{len(task.scanned_cards)}: "
            f"[{cid}] {cname} - '{csub}' ({r_str} {star_str}) [p:{swipe_page}, s:{grid_slot}]"
        )
    else:
        from_ocr = bool(cand.get("from_ocr"))
        if (
            not from_ocr
            and task._last_registered_card_id is not None
            and task._last_registered_card_id != cid
        ):
            task.log(
                f"  [ANTI-COLLISION] Skipping non-adjacent DUPE registration for [{cid}] "
                f"(last registered: {task._last_registered_card_id})."
            )
            return False
        task.scanned_cards[cid]["copies"] = task.scanned_cards[cid].get("copies", 1) + 1
        task._last_registered_card_id = cid
        task._recently_scanned_positions[cid] = (cy, cx)
        task.log(
            f"  [DUPE] [{score:.2f}] Card [{cid}] {cname}: copy #{task.scanned_cards[cid]['copies']}"
        )
    return True


__all__ = ["register_card"]
