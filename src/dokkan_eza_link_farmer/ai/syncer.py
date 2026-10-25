from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import time
from typing import Any

import requests

from dokkan_eza_link_farmer.ai.models import (
    CardForm,
    DokkanCard,
    LeaderSkillSpec,
    PassiveTags,
    SATags,
)

logger = logging.getLogger(__name__)


def parse_passive_tags(passive_text: str, sa_tags: SATags | None = None) -> PassiveTags:
    """
    Parses tactical tags from passive skill text, identifying defensive viability,
    damage reduction %, dodge chance %, guard, revive, taunt, support, on-hit defense,
    and enemy category/class conditional defense mechanics.
    """
    _ = sa_tags
    raw_text = passive_text or ""
    text = raw_text.lower()

    # Split by markdown headers / condition blocks
    blocks = re.split(r"\*([^*]+)\*", raw_text)
    sections: list[tuple[str, str]] = []
    if len(blocks) == 1:
        sections.append(("", blocks[0].lower()))
    else:
        sections.append(("", blocks[0].lower()))
        for i in range(1, len(blocks), 2):
            header = blocks[i].lower().strip()
            content = blocks[i + 1].lower().strip() if i + 1 < len(blocks) else ""
            sections.append((header, content))

    ON_HIT_PATTERNS = (
        "when receiving an attack",
        "after receiving an attack",
        "after receiving attack",
        "for every attack received",
        "for each attack received",
        "with each attack received",
        "per attack received",
        "when receiving a super attack",
        "when receiving a normal attack",
        "starting from the turn in which the character receives an attack",
        "starting from the turn in which the character receives a super attack",
        "when receiving damage",
        "after receiving damage",
    )
    ONCE_ONLY_PATTERNS = (
        "{passiveimg:once}",
        "(once only)",
        "once only",
    )
    SLOT_2_3_PATTERNS = (
        "as the 2nd or 3rd attacker",
        "as the 2nd attacker",
        "as the 3rd attacker",
        "in the 2nd or 3rd slot",
        "in the 2nd slot",
        "in the 3rd slot",
    )
    ALLY_CONDITIONAL_PATTERNS = (
        "allies attacking in the same turn",
        "when there are",
        "when there is another",
        "extreme class allies",
        "super class allies",
        "category ally",
        "category allies",
    )

    unconditional_dr_base = 0
    pre_hit_dr = 0
    has_guard = False
    pre_hit_guard = False
    dodge_chance = 0

    has_on_hit_def = False
    has_on_hit_guard = False
    has_on_hit_dr = False
    is_once_only_dr = False
    has_slot_2_3_buff = False

    has_enemy_conditional_defense = False
    enemy_conditional_categories: list[str] = []
    enemy_conditional_classes: list[str] = []
    enemy_conditional_dr = 0
    enemy_conditional_guard = False
    enemy_conditional_dodge = 0

    for header, content in sections:
        header_is_on_hit = any(p in header for p in ON_HIT_PATTERNS)
        header_is_once_only = any(p in header for p in ONCE_ONLY_PATTERNS)
        header_is_slot_2_3 = any(p in header for p in SLOT_2_3_PATTERNS)
        header_is_ally_conditional = any(p in header for p in ALLY_CONDITIONAL_PATTERNS)

        header_clean = " ".join(header.split())
        header_is_enemy_conditional = (
            any(
                p in header_clean
                for p in ("category enemy", "category enemies", "class enemy", "class enemies")
            )
            or (
                "when facing" in header_clean
                and any(k in header_clean for k in ("enemy", "enemies"))
            )
            or (
                "when there is a" in header_clean
                and any(k in header_clean for k in ("enemy", "enemies"))
            )
            or ("against" in header_clean and any(k in header_clean for k in ("enemy", "enemies")))
        )
        header_req_cats: list[str] = []
        header_req_classes: list[str] = []
        if header_is_enemy_conditional:
            cats_found = [x.title() for x in re.findall(r'"([^"]+)"', header_clean)]
            header_req_cats = [c for c in cats_found if "class" not in c.lower()]
            class_m = re.search(r"(extreme|super)\s+class", header_clean, re.I)
            if class_m:
                header_req_classes.append(class_m.group(1).title())
            for c in cats_found:
                if "extreme" in c.lower() and "Extreme" not in header_req_classes:
                    header_req_classes.append("Extreme")
                elif "super" in c.lower() and "Super" not in header_req_classes:
                    header_req_classes.append("Super")

        is_basic = "basic effect" in header or header == ""
        is_conditional_header = (
            "ki spheres obtained" in header
            or "collecting" in header
            or "when hp is" in header
            or "when attacking" in header
            or header_is_slot_2_3
            or header_is_on_hit
            or header_is_ally_conditional
            or header_is_enemy_conditional
            or "starting from" in header
            or "after the character's" in header
        )

        lines = [line.strip() for line in content.split("\n") if line.strip()]
        for line in lines:
            line_clean = " ".join(line.split())
            line_is_on_hit = header_is_on_hit or any(p in line for p in ON_HIT_PATTERNS)
            line_is_once_only = header_is_once_only or any(p in line for p in ONCE_ONLY_PATTERNS)
            line_is_slot_2_3 = header_is_slot_2_3 or any(p in line for p in SLOT_2_3_PATTERNS)
            line_is_ally_conditional = header_is_ally_conditional or any(
                p in line for p in ALLY_CONDITIONAL_PATTERNS
            )

            line_is_enemy_conditional = header_is_enemy_conditional or (
                any(
                    p in line_clean
                    for p in ("category enemy", "category enemies", "class enemy", "class enemies")
                )
                or (
                    "when facing" in line_clean
                    and any(k in line_clean for k in ("enemy", "enemies"))
                )
                or (
                    "when there is a" in line_clean
                    and any(k in line_clean for k in ("enemy", "enemies"))
                )
                or ("against" in line_clean and any(k in line_clean for k in ("enemy", "enemies")))
            )
            line_req_cats = list(header_req_cats)
            line_req_classes = list(header_req_classes)
            if line_is_enemy_conditional and not line_req_cats and not line_req_classes:
                cats_found = [x.title() for x in re.findall(r'"([^"]+)"', line_clean)]
                line_req_cats = [c for c in cats_found if "class" not in c.lower()]
                class_m = re.search(r"(extreme|super)\s+class", line_clean, re.I)
                if class_m:
                    line_req_classes.append(class_m.group(1).title())
                for c in cats_found:
                    if "extreme" in c.lower() and "Extreme" not in line_req_classes:
                        line_req_classes.append("Extreme")
                    elif "super" in c.lower() and "Super" not in line_req_classes:
                        line_req_classes.append("Super")

            if line_is_slot_2_3:
                has_slot_2_3_buff = True

            # On-Hit DEF check
            if line_is_on_hit and re.search(r"def\s*\+?\s*(\d+)%", line):
                has_on_hit_def = True

            # Damage Reduction %
            dr_m = re.findall(
                r"(?:damage reduction (?:rate|of)?|damage received by(?:\s+up to)?|reduces damage(?: received)? by(?:\s+up to)?(?:\s+an additional)?|damage received\s*-\s*)\s*(\d+)%",
                line,
            )
            for d in dr_m:
                val = int(d)
                if line_is_on_hit:
                    has_on_hit_dr = True
                if line_is_once_only:
                    is_once_only_dr = True
                if line_is_enemy_conditional:
                    has_enemy_conditional_defense = True
                    if val > enemy_conditional_dr:
                        enemy_conditional_dr = val
                    for c in line_req_cats:
                        if c not in enemy_conditional_categories:
                            enemy_conditional_categories.append(c)
                    for cl in line_req_classes:
                        if cl not in enemy_conditional_classes:
                            enemy_conditional_classes.append(cl)
                else:
                    if val > unconditional_dr_base:
                        unconditional_dr_base = val
                    if (
                        (is_basic or not is_conditional_header)
                        and not line_is_on_hit
                        and not line_is_once_only
                        and not line_is_slot_2_3
                        and not line_is_ally_conditional
                        and val > pre_hit_dr
                    ):
                        pre_hit_dr = val

            # Guard
            if (
                "guard" in line
                and "chance of guarding" not in line
                and "disables enemy" not in line
                and any(
                    k in line
                    for k in (
                        "guards all attacks",
                        "guards against all attacks",
                        "all attacks guarded",
                        "guaranteed to guard",
                    )
                )
            ):
                if line_is_on_hit:
                    has_on_hit_guard = True
                if line_is_enemy_conditional:
                    has_enemy_conditional_defense = True
                    enemy_conditional_guard = True
                    for c in line_req_cats:
                        if c not in enemy_conditional_categories:
                            enemy_conditional_categories.append(c)
                    for cl in line_req_classes:
                        if cl not in enemy_conditional_classes:
                            enemy_conditional_classes.append(cl)
                else:
                    has_guard = True
                    if (
                        (is_basic or not is_conditional_header)
                        and not line_is_on_hit
                        and not line_is_once_only
                        and not line_is_ally_conditional
                        and not line_is_slot_2_3
                    ):
                        pre_hit_guard = True

            # Dodge %
            if any(k in line for k in ("evad", "evasion", "dodge")):
                line_dodge = 0
                if any(
                    g in line
                    for g in ("guaranteed to evade", "guaranteed to dodge", "guaranteed evasion")
                ):
                    line_dodge = 100
                elif "great chance" in line:
                    line_dodge = 70
                elif "high chance" in line:
                    line_dodge = 50
                elif "medium chance" in line or "med chance" in line:
                    line_dodge = 30
                elif "rare chance" in line:
                    line_dodge = 20
                elif re.search(
                    r"(?<!chance of )(?<!chance to )(?<!great )(?<!high )(?<!medium )(?<!rare )(?<!med )(?<!guaranteed to )evades?\s+enemy(?:'s)?\s+attacks?",
                    line,
                ):
                    line_dodge = 100
                for m in re.finditer(r"(\d+)%\s*chance of evading", line):
                    line_dodge = max(line_dodge, int(m.group(1)))
                for m in re.finditer(
                    r"(?:chance of evading|chance to evade|chance of dodging|chance to dodge|evasion rate)\s*(?:enemy(?:'s)?\s+attacks?)?\s*(?:\([^)]*\))?\s*(?:rate\s*)?\+?\s*(\d+)%",
                    line,
                ):
                    line_dodge = max(line_dodge, int(m.group(1)))
                for m in re.finditer(
                    r"(?:evad\w*|dodge\w*)[^.\n\*\-]{0,60}\(up to (\d+)%\)",
                    line,
                ):
                    line_dodge = max(line_dodge, int(m.group(1)))

                if line_dodge > 0:
                    if line_is_enemy_conditional:
                        has_enemy_conditional_defense = True
                        if line_dodge > enemy_conditional_dodge:
                            enemy_conditional_dodge = line_dodge
                        for c in line_req_cats:
                            if c not in enemy_conditional_categories:
                                enemy_conditional_categories.append(c)
                        for cl in line_req_classes:
                            if cl not in enemy_conditional_classes:
                                enemy_conditional_classes.append(cl)
                    elif (
                        (is_basic or not is_conditional_header)
                        and not line_is_on_hit
                        and line_dodge > dodge_chance
                    ):
                        dodge_chance = line_dodge

    # Global text fallbacks for unconditional Guard / Dodge / Support
    if (
        not has_guard
        and not has_enemy_conditional_defense
        and (
            bool(re.search(r"guard(?:s|ing)?\s+(?:against\s+)?all", text))
            or "all attacks guarded" in text
            or "guaranteed to guard" in text
        )
        and "chance of guarding" not in text
        and "disables enemy" not in text
    ):
        has_guard = True
        if not has_on_hit_guard and not any(p in text for p in ALLY_CONDITIONAL_PATTERNS):
            pre_hit_guard = True

    # 4. Revive, Taunt, Support, Mechanics
    has_revive = "revive" in text or "revival" in text
    has_taunt = (
        "target of enemy" in text
        or "directs enemy" in text
        or "redirects enemy" in text
        or "taunt" in text
    )
    has_support = (
        "allies' ki" in text
        or "all allies' atk" in text
        or "all allies' def" in text
        or "allies' atk" in text
        or "allies' def" in text
        or "all allies ki" in text
        or "allies atk" in text
        or "allies def" in text
        or "super class allies" in text
        or "extreme class allies" in text
        or "category allies" in text
        or "for all allies" in text
        or "to all allies" in text
        or "for allies" in text
    )
    has_standby = "standby" in text
    has_domain = "domain" in text
    has_orb_changing = (
        "changes ki spheres" in text
        or "changes spheres" in text
        or "orb changing" in text
        or "rainbow ki sphere" in text
    )

    has_on_hit_defense = bool(
        has_on_hit_guard
        or has_on_hit_dr
        or (has_on_hit_def and pre_hit_dr < 50 and not pre_hit_guard)
        or (is_once_only_dr and pre_hit_dr < 50)
    )

    slot1_exclusive = (
        (
            "1st attacker in a turn" in text
            or "in the 1st slot" in text
            or "as the 1st attacker" in text
        )
        and not is_once_only_dr
        and not has_on_hit_dr
        and not has_on_hit_guard
        and ("guard" in text or "damage reduction" in text or "reduces damage" in text)
    )

    # slot1_viable requires genuine unconditional defense in base form
    slot1_viable = False
    if (
        pre_hit_dr >= 50
        or dodge_chance >= 70
        or pre_hit_guard
        and not has_on_hit_defense
        or slot1_exclusive
        and (pre_hit_dr >= 30 or pre_hit_guard)
    ):
        slot1_viable = True

    has_slot_2_3_buff = has_slot_2_3_buff or any(p in text for p in SLOT_2_3_PATTERNS)

    return PassiveTags(
        slot1_viable=slot1_viable,
        dr_base_percent=unconditional_dr_base,
        permanent_dr_percent=pre_hit_dr,
        pre_hit_dr_percent=pre_hit_dr,
        pre_hit_guard=pre_hit_guard,
        has_on_hit_defense=has_on_hit_defense,
        has_on_hit_guard=has_on_hit_guard,
        has_on_hit_dr=has_on_hit_dr,
        has_on_hit_def=has_on_hit_def,
        is_once_only_dr=is_once_only_dr,
        has_slot_2_3_buff=has_slot_2_3_buff,
        has_enemy_conditional_defense=has_enemy_conditional_defense,
        enemy_conditional_categories=enemy_conditional_categories,
        enemy_conditional_classes=enemy_conditional_classes,
        enemy_conditional_dr=enemy_conditional_dr,
        enemy_conditional_guard=enemy_conditional_guard,
        enemy_conditional_dodge=enemy_conditional_dodge,
        dodge_chance_percent=dodge_chance,
        has_guard=has_guard,
        has_revive=has_revive,
        has_taunt=has_taunt,
        has_support=has_support,
        has_standby=has_standby,
        has_domain=has_domain,
        has_orb_changing=has_orb_changing,
    )


def parse_sa_tags(sa_text: str) -> SATags:
    """
    Parses Super Attack text to determine defense/attack stacking and turn duration.
    """
    text = (sa_text or "").lower()

    # Remove turn-limited buffs first:
    clean_sa = re.sub(
        r"(?:greatly|massively)?\s*raises\s+(?:atk\s*(?:and|&)\s*def|def\s*(?:and|&)\s*atk|def|atk)\s+for\s+\d+\s+turns?",
        "",
        text,
    )

    # Permanent Defense Stacking check
    stacks_def = bool(
        re.search(r"raises\s+(?:atk\s*(?:and|&)\s*)?def", clean_sa)
        or re.search(r"raises\s+def\s*(?:and|&)\s*atk", clean_sa)
    )

    # Permanent Attack Stacking check
    stacks_atk = bool(
        re.search(r"raises\s+(?:def\s*(?:and|&)\s*)?atk", clean_sa)
        or re.search(r"raises\s+atk\s*(?:and|&)\s*def", clean_sa)
    )

    # Turn-limited buffs
    def_turns = 0
    match_def_turn = re.search(
        r"raises\s+(?:atk\s*(?:and|&)\s*)?def.*?for\s+(\d+)\s+turns?", text
    ) or re.search(r"raises\s+def\s*(?:and|&)\s*atk.*?for\s+(\d+)\s+turns?", text)
    if match_def_turn:
        with contextlib.suppress(ValueError):
            def_turns = int(match_def_turn.group(1))

    atk_turns = 0
    match_atk_turn = re.search(
        r"raises\s+(?:def\s*(?:and|&)\s*)?atk.*?for\s+(\d+)\s+turns?", text
    ) or re.search(r"raises\s+atk\s*(?:and|&)\s*def.*?for\s+(\d+)\s+turns?", text)
    if match_atk_turn:
        with contextlib.suppress(ValueError):
            atk_turns = int(match_atk_turn.group(1))

    return SATags(
        stacks_def=stacks_def,
        stacks_atk=stacks_atk,
        raise_def_turns=def_turns,
        raise_atk_turns=atk_turns,
    )


def parse_leader_spec(
    leader_text: str, categories_catalog: list[dict[str, Any]] | None = None
) -> LeaderSkillSpec:
    """
    Parses a Leader Skill description into a structured LeaderSkillSpec object,
    extracting main categories (170/200%), extra bonus categories (+30%), and sub-elements.
    """
    if not leader_text or not isinstance(leader_text, str):
        return LeaderSkillSpec()

    lead_clean = leader_text.replace("\n", " ").strip()

    # Split into base part and extra bonus part (+30%)
    parts = re.split(
        r"plus an (?:additional|extra)|plus (?:additional|extra)", lead_clean, flags=re.IGNORECASE
    )
    base_part = parts[0]
    extra_part = parts[1] if len(parts) > 1 else ""

    # Detect base and extra boost percentages (prioritizing ATK & DEF over standalone HP)
    base_pct = 170
    match_atk_def = re.search(
        r"(?:atk\s*(?:and|&)\s*def|def\s*(?:and|&)\s*atk|hp,\s*atk\s*(?:and|&)\s*def)\s*\+\s*(\d{2,3})%",
        base_part,
        re.IGNORECASE,
    )
    if match_atk_def:
        with contextlib.suppress(ValueError):
            base_pct = int(match_atk_def.group(1))
    else:
        match_stat = re.search(r"(?:atk|def)\s*\+\s*(\d{2,3})%", base_part, re.IGNORECASE)
        if match_stat:
            with contextlib.suppress(ValueError):
                base_pct = int(match_stat.group(1))
        else:
            match_base = re.search(r"(\d{2,3})%", base_part)
            if match_base:
                with contextlib.suppress(ValueError):
                    base_pct = int(match_base.group(1))

    extra_pct = 0
    if extra_part:
        extra_pct = 30
        match_extra_stat = re.search(
            r"(?:atk\s*(?:and|&)\s*def|def\s*(?:and|&)\s*atk|hp,\s*atk\s*(?:and|&)\s*def|atk|def)?\s*\+\s*(\d{1,3})%",
            extra_part,
            re.IGNORECASE,
        )
        if match_extra_stat:
            with contextlib.suppress(ValueError):
                extra_pct = int(match_extra_stat.group(1))
        else:
            match_extra = re.search(r"(\d{1,3})%", extra_part)
            if match_extra:
                with contextlib.suppress(ValueError):
                    extra_pct = int(match_extra.group(1))

    hp_pct = base_pct
    match_hp = re.search(r"hp\s*\+\s*(\d{2,3})%", base_part, re.IGNORECASE)
    if match_hp:
        with contextlib.suppress(ValueError):
            hp_pct = int(match_hp.group(1))

    main_category_ids: list[int] = []
    extra_category_ids: list[int] = []

    # Extract quoted categories in base and extra parts
    base_quoted = [q.lower().strip() for q in re.findall(r'"([^"]+)"', base_part)]
    extra_quoted = (
        [q.lower().strip() for q in re.findall(r'"([^"]+)"', extra_part)] if extra_part else []
    )

    # Map category names to IDs if catalog is available
    if categories_catalog and isinstance(categories_catalog, list):
        for cat in categories_catalog:
            if not isinstance(cat, dict):
                continue
            c_name = cat.get("name")
            c_id = cat.get("id")
            if not c_name or not isinstance(c_name, str) or c_id is None:
                continue

            c_name_lower = c_name.lower().strip()
            try:
                cid_int = int(c_id)
            except (ValueError, TypeError):
                continue

            # Check base part: quoted match first, then word-boundary fallback
            if (
                c_name_lower in base_quoted
                or not base_quoted
                and re.search(rf"\b{re.escape(c_name_lower)}\s+category\b", base_part.lower())
            ) and cid_int not in main_category_ids:
                main_category_ids.append(cid_int)

            # Check extra part: quoted match first, then word-boundary fallback
            if (
                extra_part
                and (
                    c_name_lower in extra_quoted
                    or not extra_quoted
                    and re.search(rf"\b{re.escape(c_name_lower)}\s+category\b", extra_part.lower())
                )
                and cid_int not in extra_category_ids
            ):
                extra_category_ids.append(cid_int)

    # Detect sub-elements and classes
    sub_elements: list[int] = []
    lead_lower = lead_clean.lower()
    if "all types" in lead_lower:
        sub_elements.extend(range(25))
    elif "super class" in lead_lower or "super type" in lead_lower:
        sub_elements.extend([10, 11, 12, 13, 14])
    elif "extreme class" in lead_lower or "extreme type" in lead_lower:
        sub_elements.extend([20, 21, 22, 23, 24])

    # Check mono types (e.g. "Super AGL", "Extreme TEQ", or general "AGL Type")
    mono_tokens = {
        "agl": {"all": [0, 10, 20], "super": 10, "extreme": 20},
        "teq": {"all": [1, 11, 21], "super": 11, "extreme": 21},
        "int": {"all": [2, 12, 22], "super": 12, "extreme": 22},
        "str": {"all": [3, 13, 23], "super": 13, "extreme": 23},
        "phy": {"all": [4, 14, 24], "super": 14, "extreme": 24},
    }
    for t_str, t_info in mono_tokens.items():
        if f"super {t_str}" in lead_lower and t_info["super"] not in sub_elements:
            sub_elements.append(t_info["super"])
        if f"extreme {t_str}" in lead_lower and t_info["extreme"] not in sub_elements:
            sub_elements.append(t_info["extreme"])
        if (
            f"{t_str} type" in lead_lower
            and f"super {t_str}" not in lead_lower
            and f"extreme {t_str}" not in lead_lower
        ):
            for eid in t_info["all"]:
                if eid not in sub_elements:
                    sub_elements.append(eid)

    # Extract secondary clause boost (e.g. "; or INT Type Ki +3 and HP, ATK & DEF +90%")
    sub_boost_pct = 0
    sub_clause_match = re.search(r";\s*or\s+([^;\n]+)", lead_clean, re.IGNORECASE)
    if sub_clause_match:
        sub_text = sub_clause_match.group(1)
        m_sub = re.search(r"(\d{2,3})%", sub_text)
        if m_sub:
            with contextlib.suppress(ValueError):
                sub_boost_pct = int(m_sub.group(1))
    elif not main_category_ids and sub_elements:
        m_elem_pct = re.search(
            r"(?:all types|super class|extreme class|super type|extreme type|[a-z]{3}\s+type)[^;\n]*?(\d{2,3})%",
            lead_lower,
        )
        if m_elem_pct:
            with contextlib.suppress(ValueError):
                sub_boost_pct = int(m_elem_pct.group(1))
        else:
            sub_boost_pct = 0
            sub_elements.clear()

    return LeaderSkillSpec(
        main_category_ids=main_category_ids,
        extra_category_ids=extra_category_ids,
        sub_elements_classes=sub_elements,
        base_boost_pct=base_pct,
        extra_boost_pct=extra_pct,
        sub_boost_pct=sub_boost_pct,
        hp_stat_pct=hp_pct,
        atk_stat_pct=base_pct,
        def_stat_pct=base_pct,
    )


class DokkanSyncer:
    """
    Autonomous DokkanDB synchronizer:
    1. Downloads 2 catalog chunks (/api/cards-catalog-with-transformations?chunk=1 & 2), filtering UR/LR.
    2. Downloads 250x250 transparent thumbnails from Supabase mirror into cache/thumbs/.
    3. Performs Lazy Details Fetching (/api/card?code={id}) with rate-limit semaphore ONLY for cards in user_box.json.
    4. Parses passive/SA tactical tags distinguishing Base vs EZA vs SEZA.
    """

    API_BASE = "https://api.dokkandb.com/api"
    SUPABASE_THUMB_URL = (
        "https://enaskhebnjtktdfszdcb.supabase.co/storage/v1/object/public/assets/character/thumb"
        "/card_{thumb_id}_thumb_folder/card_{thumb_id}_thumb.png"
    )

    DEFAULT_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://dokkandb.com/",
        "Origin": "https://dokkandb.com",
        "Accept": "application/json, image/*, */*",
    }

    def __init__(self, cache_dir: str | None = None) -> None:
        if cache_dir is None:
            cache_dir = os.path.join(os.path.expanduser("~"), ".dokkan-farmer", "cache")
        self.cache_dir = os.path.abspath(cache_dir)
        self.thumbs_dir = os.path.join(self.cache_dir, "thumbs")
        self.cards_dir = os.path.join(self.cache_dir, "cards")
        self.catalog_cache_file = os.path.join(self.cache_dir, "dokkandb_catalog.json")
        self.user_box_file = os.path.join(self.cache_dir, "user_box.json")
        self.categories_cache_file = os.path.join(self.cache_dir, "dokkandb_categories.json")

        self._ensure_dirs()
        self._categories_catalog: list[dict[str, Any]] = []

    def _ensure_dirs(self) -> None:
        os.makedirs(self.cache_dir, exist_ok=True)
        os.makedirs(self.thumbs_dir, exist_ok=True)
        os.makedirs(self.cards_dir, exist_ok=True)

    @staticmethod
    def get_thumb_id(card_id: int) -> str:
        """Calculates Supabase thumbnail ID according to formula: str(card_id)[:-1] + '0'."""
        cid_str = str(card_id)
        if len(cid_str) <= 1:
            return "0"
        return cid_str[:-1] + "0"

    def get_thumb_url(self, card_id: int) -> str:
        """Returns direct Supabase CDN image URL for a given card ID."""
        tid = self.get_thumb_id(card_id)
        return self.SUPABASE_THUMB_URL.format(thumb_id=tid)

    def get_categories(self, force: bool = False) -> list[dict[str, Any]]:
        """Loads categories from local cache or fetches from DokkanDB."""
        if not force and self._categories_catalog:
            return self._categories_catalog

        if not force and os.path.exists(self.categories_cache_file):
            try:
                with open(self.categories_cache_file, encoding="utf-8") as f:
                    self._categories_catalog = json.load(f)
                    return self._categories_catalog
            except Exception as e:
                logger.warning(f"Error reading categories cache: {e}")

        url = f"{self.API_BASE}/categories"
        try:
            resp = requests.get(url, headers=self.DEFAULT_HEADERS, timeout=12)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                self._categories_catalog = data
                with open(self.categories_cache_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                return self._categories_catalog
        except Exception as e:
            logger.error(f"Error fetching categories from DokkanDB: {e}")

        return self._categories_catalog

    def sync_catalog(
        self,
        force: bool = False,
        include_ssr: bool = False,
        rarities: tuple[int, ...] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Synchronizes DokkanDB catalog chunks (/api/cards-catalog-with-transformations?chunk=N),
        dynamically fetching until exhausted, filtering UR (4) and LR (5) characters by default (or SSR (3) if include_ssr=True).
        """
        # Default covers all 1,437 playable cards (SSR base awakened to UR Lv. 100 + natural UR + LR)
        _ = include_ssr
        allowed_rarities = set(rarities) if rarities is not None else {3, 4, 5}

        if not force and os.path.exists(self.catalog_cache_file):
            try:
                with open(self.catalog_cache_file, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list) and len(data) >= 800:
                    cached_rarities = {c.get("rarity") for c in data if isinstance(c, dict)}
                    # If caller needs SSR (rarity 3) but cache lacks SSRs, fetch chunks from API
                    if 3 in allowed_rarities and 3 not in cached_rarities:
                        logger.info(
                            f"Catalog cache missing SSRs (has {cached_rarities}); re-downloading chunks..."
                        )
                    else:
                        filtered = [
                            c
                            for c in data
                            if isinstance(c, dict) and c.get("rarity") in allowed_rarities
                        ]
                        if filtered:
                            logger.info(
                                f"Loaded {len(filtered)} cards from catalog cache (rarities: {allowed_rarities})."
                            )
                            return filtered
            except Exception as e:
                logger.warning(f"Error loading catalog cache: {e}")

        logger.info("Downloading catalog chunks from DokkanDB until exhausted...")
        combined: list[dict[str, Any]] = []
        chunk_id = 1
        while chunk_id <= 20:
            url = f"{self.API_BASE}/cards-catalog-with-transformations?chunk={chunk_id}"
            try:
                resp = requests.get(url, headers=self.DEFAULT_HEADERS, timeout=25)
                if resp.status_code == 404:
                    break
                resp.raise_for_status()
                data = resp.json()
                if not data or not isinstance(data, list):
                    break
                combined.extend(data)
                logger.info(f"Downloaded chunk {chunk_id}: {len(data)} cards.")
                chunk_id += 1
            except Exception as e:
                if chunk_id > 2:
                    logger.debug(f"Finished downloading catalog at chunk {chunk_id}: {e}")
                else:
                    logger.error(f"Failed to fetch chunk {chunk_id} from {url}: {e}")
                break

        # Save all standard valid cards with rarities in {3, 4, 5} to disk cache
        all_cacheable_cards: list[dict[str, Any]] = []
        seen_all_ids: set[int] = set()
        for card in combined:
            if not isinstance(card, dict):
                continue
            cid = card.get("id")
            rarity = card.get("rarity")
            if rarity in (allowed_rarities | {3, 4, 5}) and cid and int(cid) not in seen_all_ids:
                seen_all_ids.add(int(cid))
                all_cacheable_cards.append(card)

        # Cache on disk
        with open(self.catalog_cache_file, "w", encoding="utf-8") as f:
            json.dump(all_cacheable_cards, f, ensure_ascii=False, indent=2)

        filtered_cards = [c for c in all_cacheable_cards if c.get("rarity") in allowed_rarities]

        logger.info(
            f"Successfully synced catalog: total raw {len(combined)}, filtered {len(filtered_cards)} (rarities: {allowed_rarities})."
        )
        return filtered_cards

    def sync_thumbnails(
        self,
        cards: list[dict[str, Any]] | None = None,
        max_workers: int = 8,
        limit: int | None = None,
    ) -> int:
        """
        Downloads 250x250 transparent character thumbnails from Supabase into cache/thumbs/.
        Skips already downloaded images.
        Returns number of newly downloaded thumbnails.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        if cards is None:
            cards = self.sync_catalog()

        # Collect distinct thumb IDs
        thumb_map: dict[str, int] = {}  # {thumb_id: card_id}
        for c in cards:
            cid = c.get("id")
            if cid:
                tid = self.get_thumb_id(int(cid))
                if tid not in thumb_map:
                    thumb_map[tid] = int(cid)

        items_to_download: list[tuple[str, int, str]] = []
        for tid, cid in thumb_map.items():
            dest = os.path.join(self.thumbs_dir, f"card_{tid}_thumb.png")
            if not os.path.exists(dest) or os.path.getsize(dest) < 100:
                url = self.get_thumb_url(cid)
                items_to_download.append((tid, cid, url))

        if limit is not None and limit > 0:
            items_to_download = items_to_download[:limit]

        if not items_to_download:
            logger.info("All thumbnails already present in cache.")
            return 0

        logger.info(f"Downloading {len(items_to_download)} thumbnails from Supabase...")
        downloaded = 0

        def _download_single(item: tuple[str, int, str]) -> bool:
            tid, _, url = item
            target_path = os.path.join(self.thumbs_dir, f"card_{tid}_thumb.png")
            try:
                r = requests.get(url, headers=self.DEFAULT_HEADERS, timeout=10)
                if r.status_code == 200 and len(r.content) > 100:
                    with open(target_path, "wb") as f:
                        f.write(r.content)
                    return True
            except Exception as e:
                logger.debug(f"Failed downloading thumb {tid} from {url}: {e}")
            return False

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(_download_single, item) for item in items_to_download]
            for f in as_completed(futures):
                if f.result():
                    downloaded += 1

        logger.info(f"Downloaded {downloaded}/{len(items_to_download)} thumbnails.")
        return downloaded

    def get_cached_card_detail(self, card_id: int, region: str = "glb") -> dict[str, Any] | None:
        """Retrieves card deep detail JSON from disk cache if present."""
        path = os.path.join(self.cards_dir, f"card_{card_id}_{region.lower()}.json")
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Error reading card cache {path}: {e}")
        return None

    def fetch_card_detail_sync(
        self, card_id: int, region: str = "glb", force: bool = False
    ) -> dict[str, Any] | None:
        """
        Synchronously fetches deep card details (/api/card?code={id}) with disk caching.
        """
        cached = self.get_cached_card_detail(card_id, region=region)
        if not force and cached:
            return cached

        url = f"{self.API_BASE}/card?code={card_id}"
        target_path = os.path.join(self.cards_dir, f"card_{card_id}_{region.lower()}.json")
        try:
            resp = requests.get(url, headers=self.DEFAULT_HEADERS, timeout=12)
            resp.raise_for_status()
            data = resp.json()
            card_info = (
                data[0]
                if isinstance(data, list) and data
                else (data if isinstance(data, dict) else None)
            )
            if not card_info:
                # Try fallback variant code (e.g. 1015822 -> 1015821 or 1015820)
                cid_str = str(card_id)
                if len(cid_str) > 1 and cid_str[-1] not in ("0", "1"):
                    for fallback_last in ("1", "0"):
                        alt_code = int(cid_str[:-1] + fallback_last)
                        alt_url = f"{self.API_BASE}/card?code={alt_code}"
                        try:
                            alt_resp = requests.get(
                                alt_url, headers=self.DEFAULT_HEADERS, timeout=8
                            )
                            if alt_resp.status_code == 200:
                                alt_data = alt_resp.json()
                                cand = (
                                    alt_data[0]
                                    if isinstance(alt_data, list) and alt_data
                                    else (alt_data if isinstance(alt_data, dict) else None)
                                )
                                if cand:
                                    card_info = dict(cand)
                                    card_info["id"] = card_id
                                    break
                        except Exception:
                            pass
            if card_info:
                with open(target_path, "w", encoding="utf-8") as f:
                    json.dump(card_info, f, ensure_ascii=False, indent=2)
            return card_info
        except Exception as e:
            logger.error(f"Error fetching card detail for {card_id} ({url}): {e}")
            return cached

    async def fetch_card_detail_async(
        self,
        card_id: int,
        semaphore: asyncio.Semaphore,
        region: str = "glb",
        force: bool = False,
    ) -> dict[str, Any] | None:
        """
        Asynchronously fetches card deep details (/api/card?code={id}) respecting rate limits.
        """
        cached = self.get_cached_card_detail(card_id, region=region)
        if not force and cached:
            return cached

        async with semaphore:
            loop = asyncio.get_running_loop()
            res = await loop.run_in_executor(
                None, self.fetch_card_detail_sync, card_id, region, force
            )
            await asyncio.sleep(0.08)  # Gentle rate-limit pacing
            return res

    def build_dokkan_card(
        self,
        card_data: dict[str, Any],
        is_rainbow: bool = False,
        is_eza: bool | None = None,
        is_seza: bool | None = None,
        potential_percent: int = 0,
        swipe_page: int = 0,
        grid_slot: int = 0,
    ) -> DokkanCard:
        """
        Builds a fully parsed DokkanCard with structured LeaderSkillSpec,
        PassiveTags, SATags, and CardForm, properly respecting Base vs EZA vs SEZA text.
        """
        # Parse basic fields via DokkanCard factory
        card = DokkanCard.from_dokkandb(
            card_data,
            is_rainbow=is_rainbow,
            is_eza=is_eza,
            is_seza=is_seza,
        )

        card.potential_percent = (
            potential_percent if potential_percent > 0 else (100 if is_rainbow else 0)
        )
        card.swipe_page = swipe_page
        card.grid_slot = grid_slot

        # Parse SA tags
        sa_tags = parse_sa_tags(card.super_attack)

        # Parse Passive tags
        passive_tags = parse_passive_tags(card.passive_skill, sa_tags=sa_tags)

        # Build LeaderSkillSpec
        categories = self.get_categories()
        card.leader_spec = parse_leader_spec(card.leader_skill, categories_catalog=categories)

        # Build Base CardForm
        card.base_form = CardForm(
            form_id=card.id,
            form_index=0,
            form_name=card.name,
            element=card.element,
            links=list(card.links),
            link_ids=list(card.link_ids),
            passive_skill_text=card.passive_skill,
            super_attack_text=card.super_attack,
            passive_tags=passive_tags,
            sa_tags=sa_tags,
            min_turn=1,
        )

        # Parse in-battle transformations if available in DokkanDB card data
        card.transformations = []
        trans_data = card_data.get("transformation_data")
        if isinstance(trans_data, list) and trans_data:
            for idx, trans in enumerate(trans_data, start=1):
                if not isinstance(trans, dict):
                    continue
                t_sa_text = " | ".join(
                    str(s) for s in (trans.get("special_descriptions") or []) if s
                )
                t_sa_tags = parse_sa_tags(t_sa_text)
                t_pass_text = trans.get("passive_skill_description") or ""
                t_pass_tags = parse_passive_tags(t_pass_text, sa_tags=t_sa_tags)

                trans_form = CardForm(
                    form_id=int(trans.get("id") or 0),
                    form_index=idx,
                    form_name=str(trans.get("name") or f"Transform_{idx}"),
                    element=int(trans.get("element") or card.element),
                    links=[
                        str(trans.get(f"link_skill_name_{i}"))
                        for i in range(1, 8)
                        if trans.get(f"link_skill_name_{i}")
                    ],
                    link_ids=[int(lid) for lid in (trans.get("link_ids") or []) if lid is not None],
                    passive_skill_text=t_pass_text,
                    super_attack_text=t_sa_text,
                    passive_tags=t_pass_tags,
                    sa_tags=t_sa_tags,
                    min_turn=int(trans.get("min_turn", idx + 2)),
                )
                card.transformations.append(trans_form)
        elif card_data.get("transformation_names") or card_data.get("transformation_ids"):
            t_names = card_data.get("transformation_names") or []
            t_ids = card_data.get("transformation_ids") or []
            t_elems = card_data.get("transformation_elements") or []
            count = max(len(t_names), len(t_ids))
            for idx in range(count):
                tid = int(t_ids[idx]) if idx < len(t_ids) else 0
                tname = str(t_names[idx]) if idx < len(t_names) else f"Transform_{idx + 1}"
                telem = int(t_elems[idx]) if idx < len(t_elems) else card.element

                # Try to load cached detail for the transformed card code if present
                tdetail = self.get_cached_card_detail(tid) if tid else None
                t_pass = ""
                t_sa_list = []
                if tdetail:
                    if card.is_seza and tdetail.get("eza_passive_skill_description"):
                        t_pass = tdetail.get("eza_passive_skill_description")
                    elif card.is_eza and tdetail.get("eza_passive_skill_description"):
                        t_pass = (
                            tdetail.get("eza_passive_skill_description_pre")
                            if tdetail.get("eza_passive_skill_description_pre")
                            else tdetail.get("eza_passive_skill_description")
                        )
                    else:
                        t_pass = tdetail.get("passive_skill_description") or ""

                    t_sa_list = (
                        tdetail.get("special_descriptions_eza")
                        if card.is_eza
                        else tdetail.get("special_descriptions")
                    ) or []

                t_sa_text = " | ".join(str(s) for s in t_sa_list if s)
                t_sa_tags = parse_sa_tags(t_sa_text)
                t_pass_tags = parse_passive_tags(str(t_pass or ""), sa_tags=t_sa_tags)

                trans_form = CardForm(
                    form_id=tid,
                    form_index=idx + 1,
                    form_name=tname,
                    element=telem,
                    passive_skill_text=str(t_pass or ""),
                    super_attack_text=t_sa_text,
                    passive_tags=t_pass_tags,
                    sa_tags=t_sa_tags,
                    min_turn=idx + 3,
                )
                card.transformations.append(trans_form)

        return card

    def sync_user_box_details(
        self,
        user_box_file: str | None = None,
        concurrency: int = 5,
        region: str = "glb",
        force: bool = False,
    ) -> list[DokkanCard]:
        """
        LAZY DETAILS FETCHING: Reads user_box.json and ONLY fetches detailed card records
        for characters actually owned by the player, respecting rate limits and caching to disk.
        """
        box_path = user_box_file or self.user_box_file
        if not os.path.exists(box_path):
            logger.warning(f"User box file {box_path} does not exist.")
            return []

        try:
            with open(box_path, encoding="utf-8") as f:
                raw_box = json.load(f)
        except Exception as e:
            logger.error(f"Failed to read user box file {box_path}: {e}")
            return []

        card_entries = raw_box if isinstance(raw_box, list) else raw_box.get("cards", [])
        if not card_entries:
            return []

        async def _run_async_sync() -> list[DokkanCard]:
            semaphore = asyncio.Semaphore(concurrency)
            tasks = []
            metadata_map: dict[int, dict[str, Any]] = {}

            for item in card_entries:
                if isinstance(item, int):
                    cid = item
                    metadata_map[cid] = {"id": cid, "copies": 1}
                elif isinstance(item, dict) and "id" in item:
                    cid = int(item["id"])
                    metadata_map[cid] = item
                else:
                    continue

                tasks.append(
                    self.fetch_card_detail_async(
                        cid, semaphore=semaphore, region=region, force=force
                    )
                )

            details_results = await asyncio.gather(*tasks, return_exceptions=True)
            dokkan_cards: list[DokkanCard] = []

            for (_cid, meta), res in zip(metadata_map.items(), details_results, strict=False):
                if isinstance(res, dict) and "id" in res:
                    is_rainbow = bool(meta.get("is_rainbow", False))
                    is_eza = meta.get("is_eza")
                    is_seza = meta.get("is_seza")
                    pot_pct = int(meta.get("potential_percent", 0))
                    swipe_page = int(meta.get("swipe_page", 0))
                    grid_slot = int(meta.get("grid_slot", 0))

                    d_card = self.build_dokkan_card(
                        card_data=res,
                        is_rainbow=is_rainbow,
                        is_eza=is_eza,
                        is_seza=is_seza,
                        potential_percent=pot_pct,
                        swipe_page=swipe_page,
                        grid_slot=grid_slot,
                    )
                    dokkan_cards.append(d_card)
                elif meta.get("name") and meta.get("category_ids") is not None:
                    dokkan_cards.append(DokkanCard.from_dict(meta))

            return dokkan_cards

        try:
            return asyncio.run(_run_async_sync())
        except RuntimeError:
            # Fallback if already in an active event loop
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(_run_async_sync())

    def sync_box_details(
        self,
        box_file: str | None = None,
        concurrency: int = 10,
        region: str = "glb",
        force: bool = False,
        save_to_file: bool = True,
    ) -> list[DokkanCard]:
        """
        Enriches all cards in box_file (defaulting to config/box.json or user_box.json)
        with category_ids, LeaderSkillSpec, and passive tactical tags from DokkanDB,
        persisting full models back to disk cache.
        """
        target_path = box_file
        if not target_path:
            if os.path.exists("config/box.json"):
                target_path = "config/box.json"
            else:
                target_path = self.user_box_file

        cards = self.sync_user_box_details(
            user_box_file=target_path,
            concurrency=concurrency,
            region=region,
            force=force,
        )

        if save_to_file and os.path.exists(target_path):
            try:
                with open(target_path, encoding="utf-8") as f:
                    raw_data = json.load(f)

                meta_map: dict[int, dict[str, Any]] = {}
                entries = raw_data if isinstance(raw_data, list) else raw_data.get("cards", [])
                for it in entries:
                    if isinstance(it, dict) and "id" in it:
                        meta_map[int(it["id"])] = it

                enriched_entries = []
                for c in cards:
                    c_dict = c.to_dict()
                    orig = meta_map.get(c.id, {})
                    for k in ("copies", "scanned_at", "best_in_box_partners"):
                        if k in orig and k not in c_dict:
                            c_dict[k] = orig[k]
                    enriched_entries.append(c_dict)

                if isinstance(raw_data, dict) and "cards" in raw_data:
                    raw_data["cards"] = enriched_entries
                    raw_data["unique_cards"] = len(enriched_entries)
                    raw_data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    output_payload = raw_data
                else:
                    output_payload = enriched_entries

                with open(target_path, "w", encoding="utf-8") as f:
                    json.dump(output_payload, f, ensure_ascii=False, indent=2)

                if os.path.abspath(target_path) != os.path.abspath(self.user_box_file):
                    os.makedirs(os.path.dirname(self.user_box_file), exist_ok=True)
                    with open(self.user_box_file, "w", encoding="utf-8") as f:
                        json.dump(output_payload, f, ensure_ascii=False, indent=2)

                logger.info(
                    f"Enriched and saved {len(cards)} cards to {target_path} and {self.user_box_file}."
                )
            except Exception as e:
                logger.error(f"Failed to write enriched box to {target_path}: {e}")

        return cards
