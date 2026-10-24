"""Box storage resolution, loading, saving, and cache synchronization."""

from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

CANONICAL_BOX_PATH = "config/box.json"
CACHE_BOX_PATH = os.path.join(os.path.expanduser("~"), ".dokkan-farmer", "cache", "user_box.json")
DEFAULT_USER_BOX_PATH = CACHE_BOX_PATH


def resolve_box_path(preferred_path: str | None = None) -> str:
    """Resolves canonical user box path."""
    if preferred_path and preferred_path not in (
        DEFAULT_USER_BOX_PATH,
        CACHE_BOX_PATH,
        CANONICAL_BOX_PATH,
    ):
        return preferred_path
    if os.path.exists(CANONICAL_BOX_PATH):
        return CANONICAL_BOX_PATH
    if os.path.exists(CACHE_BOX_PATH):
        return CACHE_BOX_PATH
    return preferred_path or CANONICAL_BOX_PATH


def sync_box_cache(source_path: str, target_path: str | None = None) -> None:
    """Synchronizes source box file to target paths (keeping config/box.json and cache mirror in sync)."""
    if not source_path or not os.path.exists(source_path):
        return
    if target_path:
        destinations = [target_path]
    elif os.path.abspath(source_path) == os.path.abspath(CANONICAL_BOX_PATH):
        destinations = [CACHE_BOX_PATH]
    elif os.path.abspath(source_path) == os.path.abspath(CACHE_BOX_PATH):
        destinations = [CANONICAL_BOX_PATH]
    else:
        return

    source_real = os.path.abspath(source_path)
    for dest in destinations:
        if not dest:
            continue
        dest_real = os.path.abspath(dest)
        if source_real != dest_real:
            try:
                os.makedirs(os.path.dirname(dest_real), exist_ok=True)
                shutil.copy2(source_path, dest_real)
                logger.debug("Synchronized box file from %s to %s", source_path, dest_real)
            except Exception as exc:
                logger.debug("Failed to sync box from %s to %s: %s", source_path, dest_real, exc)


def load_existing_box(output_file: str | None = None) -> dict[int, dict[str, Any]]:
    """Loads previously scanned cards so scans are incremental and resumeable."""
    target_path = resolve_box_path(output_file)
    cards: dict[int, dict[str, Any]] = {}
    if os.path.exists(target_path):
        try:
            with open(target_path, encoding="utf-8") as f:
                data = json.load(f)
            card_list = data if isinstance(data, list) else data.get("cards", [])
            for item in card_list:
                if isinstance(item, dict) and "id" in item:
                    cards[int(item["id"])] = item
                elif isinstance(item, int):
                    cards[item] = {"id": item, "copies": 1}
            logger.info("Loaded %d existing cards from %s", len(cards), target_path)
        except Exception as exc:
            logger.warning("Could not load existing box from %s: %s", target_path, exc)
    return cards


def save_box(
    output_file: str,
    scanned_cards: dict[int, dict[str, Any]],
    dokkandb: Any = None,
    enrich: bool = True,
) -> None:
    """Persists discovered cards to output_file, optionally enriching with DokkanDB details."""
    os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
    card_list = list(scanned_cards.values())
    if enrich and dokkandb:
        try:
            enriched = dokkandb.enrich_box(card_list)
            if isinstance(enriched, list):
                card_list = enriched
                for ec in card_list:
                    if isinstance(ec, dict):
                        cid = int(ec.get("id") or 0)
                        if cid and cid in scanned_cards:
                            orig = scanned_cards[cid]
                            ec["copies"] = orig.get("copies", 1)
                            ec["swipe_page"] = orig.get("swipe_page", 0)
                            ec["grid_slot"] = orig.get("grid_slot", 0)
                            ec["is_rainbow"] = orig.get("is_rainbow", False)
                            ec["is_eza"] = orig.get("is_eza", False)
                            ec["is_seza"] = orig.get("is_seza", False)
                            ec["potential_percent"] = orig.get("potential_percent", 0)
                            if "scanned_at" in orig:
                                ec["scanned_at"] = orig["scanned_at"]
                            for k in (
                                "leader_spec",
                                "passive_tags",
                                "sa_tags",
                                "link_ids",
                                "category_ids",
                                "links",
                                "categories",
                                "best_in_box_partners",
                            ):
                                if k not in ec and k in orig:
                                    ec[k] = orig[k]
                            scanned_cards[cid] = ec
        except Exception as exc:
            logger.warning("Error enriching box with DokkanDB: %s", exc)

    total_instances = sum(int(c.get("copies", 1)) for c in scanned_cards.values())
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "total_cards": total_instances,
        "unique_cards": len(scanned_cards),
        "cards": card_list,
    }
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    sync_box_cache(output_file)


__all__ = [
    "CACHE_BOX_PATH",
    "CANONICAL_BOX_PATH",
    "DEFAULT_USER_BOX_PATH",
    "load_existing_box",
    "resolve_box_path",
    "save_box",
    "sync_box_cache",
]
