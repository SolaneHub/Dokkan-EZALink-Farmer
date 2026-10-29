"""Art variant mappings and identity resolution for Dokkan Battle cards.

Art variant cards (DokkanDB tag 11, 'Alternative Art') share the same character
gameplay identity, name, subname, leader skill, passive skills, links, and categories
as their original base cards, but possess different card IDs and exclusive card artwork.
In Dokkan Battle team building, a variant card and its base counterpart represent the
same card identity and cannot legally be placed on the same team.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Canonical mapping of DokkanDB Alternative Art (tag 11) cards to their base counterpart cards
# Mapping direction: {variant_card_id: base_card_id}
KNOWN_ART_VARIANT_PAIRS: dict[int, int] = {
    # LR PHY Super Saiyan Goku & Super Saiyan Vegeta (Fused Super Power - Gogeta)
    1034761: 1012901,
    # LR INT Super Saiyan Goku (Angel) & Super Saiyan Vegeta (Angel) (Fused Fighting Force - Vegito)
    1034741: 1012931,
    # LR STR Goku (Thousandfold Plea - 1000/2000 Days Goku)
    1032521: 1012361,
    # UR AGL Super Saiyan 3 Goku (Angel) (Pressed-for-Time Showdown)
    1034481: 1028791,
    # UR PHY Super Saiyan God Goku (Fighter Entrusted with Allies' Wishes)
    1034461: 1026251,
    # UR PHY Goku Black (Super Saiyan Rosé) (Clone) [PHY]
    1031811: 1032191,
    # UR STR Goku Black (Super Saiyan Rosé) (Clone) [STR]
    1031801: 1032181,
    # UR INT Goku Black (Super Saiyan Rosé) (Clone) [INT]
    1031791: 1032171,
    # UR TEQ Goku Black (Super Saiyan Rosé) (Clone) [TEQ]
    1031781: 1032161,
    # UR AGL Goku Black (Super Saiyan Rosé) (Clone) [AGL]
    1031771: 1031761,
}

# Dynamic registry extending KNOWN_ART_VARIANT_PAIRS
_RUNTIME_VARIANT_MAP: dict[int, int] = dict(KNOWN_ART_VARIANT_PAIRS)
_RUNTIME_BASE_TO_VARIANTS: dict[int, set[int]] = {}


def _rebuild_reverse_index() -> None:
    """Rebuilds the reverse base_id -> set of variant_ids index."""
    _RUNTIME_BASE_TO_VARIANTS.clear()
    for var_id, base_id in _RUNTIME_VARIANT_MAP.items():
        _RUNTIME_BASE_TO_VARIANTS.setdefault(base_id, set()).add(var_id)


_rebuild_reverse_index()


def register_art_variant(variant_card_id: int, base_card_id: int) -> None:
    """Registers an art variant to its base canonical card ID at runtime."""
    _RUNTIME_VARIANT_MAP[int(variant_card_id)] = int(base_card_id)
    _rebuild_reverse_index()


def is_art_variant(card_id: int | None) -> bool:
    """Returns True if the card_id is recognized as an alternative art variant."""
    if card_id is None:
        return False
    return int(card_id) in _RUNTIME_VARIANT_MAP


def get_canonical_card_id(card_id: int | None) -> int:
    """
    Returns the canonical base card ID for any given card ID.
    If the card is an art variant, returns its base counterpart card ID.
    Otherwise returns card_id itself.
    """
    if card_id is None:
        return 0
    cid = int(card_id)
    return _RUNTIME_VARIANT_MAP.get(cid, cid)


def get_variant_card_ids(base_card_id: int | None) -> set[int]:
    """Returns all known variant card IDs associated with a given base card ID."""
    if base_card_id is None:
        return set()
    return set(_RUNTIME_BASE_TO_VARIANTS.get(int(base_card_id), set()))


def are_same_card_identity(card_id_a: int | None, card_id_b: int | None) -> bool:
    """
    Determines if two card IDs represent the exact same gameplay identity
    (i.e., they are identical or one is an art variant of the other).
    """
    if card_id_a is None or card_id_b is None:
        return False
    return get_canonical_card_id(card_id_a) == get_canonical_card_id(card_id_b)


def discover_art_variants_from_catalog(catalog: list[dict[str, Any]]) -> dict[int, int]:
    """
    Analyzes catalog cards to dynamically discover and register art variants
    tagged with tag 11 or '11' or matching subname/element/unique_info_id.
    """
    discovered: dict[int, int] = {}
    variant_cands: list[dict[str, Any]] = []
    standard_cands: list[dict[str, Any]] = []

    for card in catalog:
        if not isinstance(card, dict):
            continue
        cid = card.get("id")
        if not cid:
            continue
        tag = card.get("tag")
        is_tag_11 = (
            tag == 11 or str(tag) == "11" or (isinstance(tag, list) and (11 in tag or "11" in tag))
        )
        if is_tag_11:
            variant_cands.append(card)
        else:
            standard_cands.append(card)

    for var in variant_cands:
        v_id = int(var["id"])
        # If already known, retain canonical pair
        if v_id in _RUNTIME_VARIANT_MAP:
            discovered[v_id] = _RUNTIME_VARIANT_MAP[v_id]
            continue

        v_sub = (var.get("subname") or "").strip().lower()
        v_uid = var.get("card_unique_info_id")
        v_elem = var.get("element")
        v_rarity = var.get("rarity")

        match: dict[str, Any] | None = None
        for std in standard_cands:
            s_id = int(std["id"])
            if s_id == v_id:
                continue
            s_sub = (std.get("subname") or "").strip().lower()
            s_uid = std.get("card_unique_info_id")
            s_elem = std.get("element")
            s_rarity = std.get("rarity")

            if v_sub and s_sub == v_sub and v_elem == s_elem and v_rarity == s_rarity:
                if v_uid is not None and s_uid is not None:
                    if v_uid == s_uid:
                        match = std
                        break
                else:
                    match = std
                    break

        if match:
            base_id = int(match["id"])
            register_art_variant(v_id, base_id)
            discovered[v_id] = base_id
            logger.info("Discovered and registered Art Variant: [%d] -> Base [%d]", v_id, base_id)

    return discovered
