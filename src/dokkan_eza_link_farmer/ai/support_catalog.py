from __future__ import annotations

import json
import logging
import os
from typing import Any

import requests

from dokkan_eza_link_farmer.ai.models import DokkanCard
from dokkan_eza_link_farmer.core.system_tools import AppPaths

logger = logging.getLogger(__name__)

CACHE_DIR = AppPaths.get_cache_dir()
MEMORIES_CACHE_FILE = os.path.join(CACHE_DIR, "dokkandb_support_memories.json")
_DEFAULT_IMPORT_MEMORIES_CACHE_FILE = MEMORIES_CACHE_FILE

# Curated Tier-1 Support Items ranked strictly from strongest to weakest
TIER_1_SUPPORT_ITEMS: list[dict[str, Any]] = [
    {
        "rank": 1,
        "id": 30505,
        "name": "Whis",
        "effect": "Danno subito ridotto del 40% per 2 turni",
        "rarity": "SSR",
        "tactical_timing": (
            "Usa a cavallo di 2 turni ad alta pressione o durante fasi boss con attacchi AoE / Super Attack letali."
        ),
    },
    {
        "rank": 2,
        "id": 1700,
        "name": "Ghost Usher",
        "effect": "Ritarda tutti gli attacchi nemici per 1 turno",
        "rarity": "SSR",
        "tactical_timing": (
            "Salva-vita immediato: usa quando la salute è critica (< 40%) o le rotazioni iniziali non consentono una difesa solida."
        ),
    },
    {
        "rank": 3,
        "id": 31502,
        "name": "Icarus",
        "effect": "Danno subito ridotto del 35% per 2 turni",
        "rarity": "SSR",
        "tactical_timing": (
            "Ottimo per concatenare la riduzione danno con Whis e mantenere il team protetto per 4 turni consecutivi."
        ),
    },
    {
        "rank": 4,
        "id": 32301,
        "name": "Princess Snake",
        "effect": "Recupera il 55% di HP e riduce i danni subiti del 30% per 1 turno",
        "rarity": "SSR",
        "tactical_timing": (
            "Doppia utilità: cura di emergenza combinata a mitigazione del danno nello stesso turno."
        ),
    },
    {
        "rank": 5,
        "id": 32102,
        "name": "Android #8",
        "effect": "Recupera il 70% di HP e DEF alleati +50% per 2 turni",
        "rarity": "SSR",
        "tactical_timing": (
            "Alternativa eccellente per team basati su statistiche grezze di difesa e cure massive."
        ),
    },
]

# Permanent Support Memories (Buffs lasting for the entire duration of the battle)
CURATED_PERMANENT_MEMORIES: list[dict[str, Any]] = [
    {
        "id": 10002,
        "name": "Goku Gets Married!",
        "categories": ["Goku's Family"],
        "effect": "\"Goku's Family\" Category allies' Ki +1 and ATK & DEF +20% in battle",
        "duration": "Tutta la durata della battaglia (Permanente)",
        "priority": 10,
    },
    {
        "id": 20025,
        "name": "Buu's Slumber",
        "categories": ["Majin Buu Saga"],
        "effect": '"Majin Buu Saga" Category allies\' ATK & DEF +20% in battle',
        "duration": "Tutta la durata della battaglia (Permanente)",
        "priority": 10,
    },
    {
        "id": 20024,
        "name": "Vow to Return",
        "categories": ["Saiyan Saga"],
        "effect": '"Saiyan Saga" Category allies\' ATK & DEF +20% in battle',
        "duration": "Tutta la durata della battaglia (Permanente)",
        "priority": 10,
    },
    {
        "id": 50020,
        "name": "Thank You",
        "categories": ["Gifted Warriors", "Pure Saiyans"],
        "effect": '"Gifted Warriors" or "Pure Saiyans" Category allies\' ATK & DEF +10% in battle',
        "duration": "Tutta la durata della battaglia (Permanente)",
        "priority": 9,
    },
    {
        "id": 10007,
        "name": "Reunion Guided by Fate",
        "categories": ["Otherworld Warriors", "Time Limit"],
        "effect": '"Otherworld Warriors" or "Time Limit" Category allies\' Ki +1 and ATK & DEF +20% in battle',
        "duration": "Tutta la durata della battaglia (Permanente)",
        "priority": 9,
    },
    {
        "id": 20016,
        "name": "Wavering Thoughts",
        "categories": ["Androids", "Earthlings"],
        "effect": '"Androids" or "Earthlings" Category allies\' Ki +1 and ATK & DEF +20% in battle',
        "duration": "Tutta la durata della battaglia (Permanente)",
        "priority": 9,
    },
    {
        "id": 30012,
        "name": "A Hundred Years Later...",
        "categories": ["Goku's Family", "Vegeta's Family"],
        "effect": '"Goku\'s Family" or "Vegeta\'s Family" Category allies\' ATK & DEF +10% in battle',
        "duration": "Tutta la durata della battaglia (Permanente)",
        "priority": 8,
    },
    {
        "id": 50017,
        "name": "Super Hero Fading Away",
        "categories": ["Super Heroes"],
        "effect": '"Super Heroes" Category allies\' ATK & DEF +10% in battle',
        "duration": "Tutta la durata della battaglia (Permanente)",
        "priority": 10,
    },
    {
        "id": 50014,
        "name": "Kakarot",
        "categories": ["Movie Heroes"],
        "effect": '"Movie Heroes" Category allies\' Ki +1 and ATK & DEF +20% in battle',
        "duration": "Tutta la durata della battaglia (Permanente)",
        "priority": 10,
    },
    {
        "id": 50018,
        "name": "Goku and Chi-Chi's Interview",
        "categories": ["Bond of Parent and Child"],
        "effect": '"Bond of Parent and Child" Category allies\' ATK & DEF +10% in battle',
        "duration": "Tutta la durata della battaglia (Permanente)",
        "priority": 9,
    },
    {
        "id": 30014,
        "name": "Confident Gogeta",
        "categories": ["Fused Fighters"],
        "effect": '"Fused Fighters" Category allies\' ATK & DEF +10% in battle',
        "duration": "Tutta la durata della battaglia (Permanente)",
        "priority": 9,
    },
    {
        "id": 40011,
        "name": "Trunks and Mai's Departure",
        "categories": ["Future Saga"],
        "effect": '"Future Saga" Category allies\' ATK & DEF +10% in battle',
        "duration": "Tutta la durata della battaglia (Permanente)",
        "priority": 9,
    },
    {
        "id": 40012,
        "name": "Endless Battles of Saiyans",
        "categories": ["Power Beyond Super Saiyan"],
        "effect": '"Power Beyond Super Saiyan" Category allies\' Ki +1 and ATK & DEF +20% in battle',
        "duration": "Tutta la durata della battaglia (Permanente)",
        "priority": 9,
    },
    {
        "id": 10003,
        "name": "Training Complete!",
        "categories": [],  # Universal
        "effect": "Tutti gli alleati: ATK & DEF +4000 e Critico +4% per l'intera durata della battaglia (4000 turni)",
        "duration": "Tutta la durata della battaglia (Permanente)",
        "priority": 5,
    },
]


def get_recommended_support_items(
    boss_stage: Any | None = None,
    max_items: int = 4,
) -> list[dict[str, Any]]:
    """
    Returns the top recommended support items ranked strictly from strongest to weakest.
    Maximum items allowed: 4.
    """
    _ = boss_stage
    return TIER_1_SUPPORT_ITEMS[:max_items]


def fetch_all_support_memories(force_refresh: bool = False) -> list[dict[str, Any]]:
    """Fetches support memories from DokkanDB API or local cache."""
    cache_dir = AppPaths.get_cache_dir()
    cache_file = os.path.join(cache_dir, "dokkandb_support_memories.json")
    if os.path.abspath(MEMORIES_CACHE_FILE) != os.path.abspath(_DEFAULT_IMPORT_MEMORIES_CACHE_FILE):
        target_load = MEMORIES_CACHE_FILE
    else:
        target_load = cache_file
    if not force_refresh and os.path.exists(target_load):
        try:
            with open(target_load, encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and data:
                    return data
        except Exception as e:
            logger.debug(f"Failed loading support memories cache: {e}")

    url = "https://api.dokkandb.com/api/support-memories"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://dokkandb.com/",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                target_save = (
                    MEMORIES_CACHE_FILE
                    if os.path.abspath(MEMORIES_CACHE_FILE)
                    != os.path.abspath(_DEFAULT_IMPORT_MEMORIES_CACHE_FILE)
                    else cache_file
                )
                os.makedirs(os.path.dirname(os.path.abspath(target_save)), exist_ok=True)
                with open(target_save, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                return data
    except Exception as e:
        logger.debug(f"Could not fetch support memories from DokkanDB: {e}")

    return CURATED_PERMANENT_MEMORIES


def get_recommended_support_memory(
    team_cards: list[DokkanCard],
    boss_stage: Any | None = None,
) -> dict[str, Any]:
    """
    Recommends the best Support Memory prioritizing those that last for the entire battle duration
    ("in battle" / "rest of battle") matching the dominant categories of the synthesized team.
    """
    _ = boss_stage
    if not team_cards:
        return CURATED_PERMANENT_MEMORIES[-1]

    # Gather category frequencies across all cards in the team
    cat_counts: dict[str, int] = {}
    for card in team_cards:
        for cat in card.categories:
            c_clean = cat.strip()
            cat_counts[c_clean] = cat_counts.get(c_clean, 0) + 1

    best_memory: dict[str, Any] | None = None
    best_score = -1

    # Check curated permanent memories first (guaranteed permanent battle duration)
    for mem in CURATED_PERMANENT_MEMORIES:
        cats = mem.get("categories", [])
        if not cats:
            # Universal memory fallback
            score = 1
        else:
            # Score based on how many team members belong to targeted categories
            matched_members = 0
            for card in team_cards:
                if any(c in card.categories for c in cats):
                    matched_members += 1
            if matched_members == 0:
                continue
            score = (matched_members * 10) + mem.get("priority", 0)

        if score > best_score:
            best_score = score
            best_memory = mem

    if best_memory:
        target_cats = best_memory.get("categories", [])
        cat_str = ", ".join(target_cats) if target_cats else "Tutte le categorie"
        return {
            "id": best_memory.get("id"),
            "name": best_memory.get("name"),
            "effect": best_memory.get("effect"),
            "duration": best_memory.get("duration", "Tutta la durata della battaglia (Permanente)"),
            "matched_category": cat_str,
            "tactical_rationale": (
                f"Potenzia permanentemente ({cat_str}) per tutta la durata del combattimento."
            ),
        }

    # Fallback to universal permanent memory
    universal = CURATED_PERMANENT_MEMORIES[-1]
    return {
        "id": universal.get("id"),
        "name": universal.get("name"),
        "effect": universal.get("effect"),
        "duration": universal.get("duration"),
        "matched_category": "Universale (Tutti gli alleati)",
        "tactical_rationale": "Garantisce un aumento statistico costante per tutta la durata della battaglia.",
    }
