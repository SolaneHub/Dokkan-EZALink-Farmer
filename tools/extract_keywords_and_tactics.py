"""Refined Tactical Dokkan Battle Keyword & Incremental Effect Extractor.

Processes data/dokkan_cards_post_10th_anniversary.json and produces:
- data/dokkan_tactical_dictionary.json
- src/dokkan_eza_link_farmer/ai/tactical_dictionary.py
"""

import json
import os
import re
from collections import Counter

CARDS_JSON_PATH = "data/dokkan_cards_post_10th_anniversary.json"
OUTPUT_DICT_JSON = "data/dokkan_tactical_dictionary.json"
OUTPUT_MODULE_PY = "src/dokkan_eza_link_farmer/ai/tactical_dictionary.py"


def clean_dokkan_text(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"\{passiveImg:[^}]+\}", "", text)
    cleaned = re.sub(r"\{[^}]+\}", "", cleaned)
    return " ".join(cleaned.split())


def extract_keywords_and_tactics():
    if not os.path.exists(CARDS_JSON_PATH):
        raise FileNotFoundError(f"Missing {CARDS_JSON_PATH}")

    with open(CARDS_JSON_PATH, encoding="utf-8") as f:
        data = json.load(f)

    cards = data.get("cards", [])
    print(f"Loaded {len(cards)} cards from {CARDS_JSON_PATH}")

    slot_1_viable = []
    slot_2_3_locked = []
    stacking_cards = []
    intro_cliff_cards = []
    scouter_cards = []
    taunt_cards = []
    domain_cards = []
    standby_cards = []
    revival_cards = []
    action_break_cards = []
    counter_cards = []

    keyword_stats = Counter()

    for c in cards:
        cid = c.get("id")
        name = c.get("name", "Unknown")

        passive = c.get("passive_skill_description") or c.get("eza_passive_skill_description") or ""
        clean_p = clean_dokkan_text(passive)
        active = c.get("active_skill_effect") or ""
        clean_a = clean_dokkan_text(active)
        standby = c.get("standby_skill_effect") or ""
        clean_sb = clean_dokkan_text(standby)
        domain = c.get("dokkan_field_name") or ""
        clean_d = clean_dokkan_text(c.get("dokkan_field_description") or "")
        full_text = f"{clean_p} {clean_a} {clean_sb} {clean_d}".lower()

        # Check Super Attack descriptions for stacking
        sa_descs = (c.get("special_descriptions") or []) + (c.get("special_descriptions_eza") or [])
        sa_def_stack = False
        sa_atk_stack = False
        for sd in sa_descs:
            if sd:
                # 'Raises DEF', 'Greatly raises DEF', 'Raises ATK & DEF' without 'for 1 turn'
                low_sd = sd.lower()
                if (
                    ("raises def" in low_sd or "raises atk & def" in low_sd)
                    and "for 1 turn" not in low_sd
                    and "for 3 turns" not in low_sd
                ):
                    sa_def_stack = True
                if (
                    ("raises atk" in low_sd or "raises atk & def" in low_sd)
                    and "for 1 turn" not in low_sd
                    and "for 3 turns" not in low_sd
                ):
                    sa_atk_stack = True

        # Check Passive Stacking (forever or up to X%)
        passive_stack_def = bool(
            re.search(
                r"def \d+%[^)]*with each attack (?:performed|received) \(up to",
                clean_p,
                re.IGNORECASE,
            )
        )
        passive_stack_atk = bool(
            re.search(
                r"atk \d+%[^)]*with each attack (?:performed|received) \(up to",
                clean_p,
                re.IGNORECASE,
            )
        )
        passive_stack_dr = bool(
            re.search(
                r"damage reduction rate \d+%[^)]*with each attack (?:performed|received) \(up to",
                clean_p,
                re.IGNORECASE,
            )
        )
        passive_stack_dodge = bool(
            re.search(
                r"chance of evading[^)]*with each attack evaded \(up to", clean_p, re.IGNORECASE
            )
        )

        if (
            sa_def_stack
            or passive_stack_def
            or sa_atk_stack
            or passive_stack_atk
            or passive_stack_dr
            or passive_stack_dodge
        ):
            keyword_stats["stacking"] += 1
            stacking_cards.append(
                {
                    "id": cid,
                    "name": name,
                    "stacks_def_sa": sa_def_stack,
                    "stacks_atk_sa": sa_atk_stack,
                    "stacks_def_passive": passive_stack_def,
                    "stacks_atk_passive": passive_stack_atk,
                    "stacks_dr_passive": passive_stack_dr,
                    "stacks_dodge_passive": passive_stack_dodge,
                }
            )

        # 2. Section-based slot analysis
        sections = re.findall(r"\*([^*]+)\*([^*]+)", passive)
        has_slot23_guard = False
        has_slot23_dr = False
        has_slot1_guard = False

        for header, body in sections:
            hdr_low = header.lower()
            body_low = body.lower()
            if "2nd or 3rd" in hdr_low or "2nd or 3rd" in body_low:
                if "guards all attacks" in body_low or "guards all attacks" in hdr_low:
                    has_slot23_guard = True
                if "damage reduction rate" in body_low:
                    has_slot23_dr = True
            if ("1st attacker" in hdr_low or "1st attacker" in body_low) and (
                "guards all attacks" in body_low or "guards all attacks" in hdr_low
            ):
                has_slot1_guard = True

        # Check unconditional guard or entry-turn guard
        unconditional_guard = (
            bool(re.search(r"\*basic effect\(s\)\*[^*]*guards all attacks", passive, re.IGNORECASE))
            and not has_slot23_guard
        )
        intro_guard = bool(
            re.search(
                r"\*for \d+ turns from the character's entry turn\*[^*]*guards all attacks",
                passive,
                re.IGNORECASE,
            )
        )
        slot1_guard = has_slot1_guard or intro_guard

        # Base DR rate
        base_dr_match = re.search(
            r"\*basic effect\(s\)\*[^*]*damage reduction rate (\d+)%", passive, re.IGNORECASE
        )
        base_dr = int(base_dr_match.group(1)) if base_dr_match else 0

        # Intro turn buffs (e.g. 3-turn cliff)
        intro_match = re.search(
            r"\*for (\d+) turns from the character's entry turn\*", passive, re.IGNORECASE
        )
        intro_turns = int(intro_match.group(1)) if intro_match else 0
        if intro_turns > 0:
            intro_cliff_cards.append(
                {
                    "id": cid,
                    "name": name,
                    "intro_turns": intro_turns,
                    "warning": f"Intro buff expires starting on Turn {intro_turns + 2}! Heavy defensive loss on subsequent rotations.",
                }
            )

        # Slot 2/3 lock identification
        if has_slot23_guard or has_slot23_dr:
            slot_2_3_locked.append(
                {
                    "id": cid,
                    "name": name,
                    "has_slot23_guard": has_slot23_guard,
                    "has_slot23_dr": has_slot23_dr,
                    "intro_turns": intro_turns,
                    "warning": "Guard/DR is restricted to 2nd or 3rd attacker in a turn. DO NOT PLACE IN SLOT 1"
                    + (f" once intro ({intro_turns} turns) expires!" if intro_turns else "!"),
                }
            )

        # Slot 1 viability check
        if unconditional_guard or slot1_guard or (base_dr >= 50):
            slot_1_viable.append(
                {
                    "id": cid,
                    "name": name,
                    "has_unconditional_guard": unconditional_guard,
                    "has_slot1_guard": slot1_guard,
                    "base_dr": base_dr,
                }
            )

        # Scouter
        if "foresees enemy's super attack" in full_text:
            keyword_stats["scouter"] += 1
            scouter_cards.append({"id": cid, "name": name})

        # Taunt / Target
        if (
            "directs enemy's attack" in full_text
            or "directs enemy attacks" in full_text
            or "target skill" in full_text
        ):
            keyword_stats["taunt"] += 1
            taunt_cards.append({"id": cid, "name": name, "active": clean_a})

        # Delay / Ghost Usher
        if "delays a single targeted enemy" in full_text or "delays targeted enemy" in full_text:
            keyword_stats["delay_turn"] += 1

        # Super Attack Nullification & Counters
        if "nullifies it" in full_text:
            keyword_stats["nullification"] += 1
        if "counters with" in full_text:
            keyword_stats["counter"] += 1
            counter_cards.append({"id": cid, "name": name})

        # Anti-Dodge-Cancel
        if "nullify attacks that are guaranteed to hit" in full_text:
            keyword_stats["anti_dodge_cancel"] += 1

        # Domain
        if domain or "dokkan field" in full_text:
            keyword_stats["domain"] += 1
            domain_cards.append({"id": cid, "name": name, "domain": domain})

        # Standby
        if c.get("standby_skill_name"):
            keyword_stats["standby"] += 1
            standby_cards.append({"id": cid, "name": name, "standby": c.get("standby_skill_name")})

        # Revival
        if "revives with" in full_text or "revival skill" in full_text:
            keyword_stats["revival"] += 1
            revival_cards.append({"id": cid, "name": name})

        # Action break
        if "cancels enemy's action" in full_text or "action break" in full_text:
            keyword_stats["action_break"] += 1
            action_break_cards.append({"id": cid, "name": name})

        # Ki Sphere conditional defense and orb changers
        is_rainbow_changer = bool(
            re.search(r"changes?\s+.*to\s+rainbow\s+ki sphere", clean_p, re.I)
            or re.search(r"randomly changes?\s+.*to\s+rainbow", clean_p, re.I)
            or re.search(
                r"changes?\s+.*ki spheres?\s+(?:of\s+a\s+certain\s+type\s+)?to\s+rainbow",
                clean_p,
                re.I,
            )
        )
        is_orb_changer = is_rainbow_changer or bool(
            re.search(r"changes?\s+.*ki spheres?\s+to\s+", clean_p, re.I)
            or "orb changing" in clean_p
        )

        has_orb_dr = False
        has_orb_dodge = False
        has_orb_guard = False

        for header, body in sections:
            hdr_low = header.lower()
            body_low = body.lower()
            is_sph_sec = (
                "sphere" in hdr_low
                or "spheres" in hdr_low
                or "ki sphere" in body_low
                or "per ki sphere" in body_low
            )
            if is_sph_sec:
                if (
                    "damage reduction" in body_low
                    or "reduces damage" in body_low
                    or "damage received" in body_low
                ):
                    has_orb_dr = True
                if "evad" in body_low or "dodge" in body_low:
                    has_orb_dodge = True
                if "guard" in body_low and "disables enemy" not in body_low:
                    has_orb_guard = True

        if has_orb_dr:
            keyword_stats["orb_dr"] += 1
        if has_orb_dodge:
            keyword_stats["orb_dodge"] += 1
        if has_orb_guard:
            keyword_stats["orb_guard"] += 1
        if is_rainbow_changer:
            keyword_stats["rainbow_orb_changer"] += 1
        if is_orb_changer:
            keyword_stats["orb_changer"] += 1

    tactical_dict = {
        "metadata": {
            "title": "Dokkan Battle Modern Meta Tactical Dictionary (Post-10th Anniversary)",
            "cards_analyzed": len(cards),
            "generated_from": "DokkanDB (>= 2025-01-28)",
            "description": "Comprehensive tactical keyword ontology, slot viability rules, and incremental effect tracking for Qwen team generation.",
        },
        "order_of_operations_damage_formula": {
            "formula": "{[(Enemy_ATK x Variance x Type_Modifier) x (1 - Damage_Reduction)] - Ally_DEF} x Guard_Reduction",
            "mechanics_explanation": {
                "damage_reduction": "Applied FIRST to Enemy ATK. Multiplicative scaling makes DR mathematically superior at higher boss attack stats.",
                "defense_stat": "Subtracted SECOND after DR has reduced the incoming ATK. A unit with 500k DEF facing 3M ATK with 50% DR takes (1.5M - 500k) = 1M before guard.",
                "guard_reduction": "Applied LAST as a 0.5x multiplier on the remaining post-DEF value. Also locks Type Modifier to 0.8x if passive guard.",
                "critical_takeaway": "Naked guard (0% DR) is INSUFFICIENT for Slot 1 against 2.5M+ Boss Super Attacks. Slot 1 requires either Guard + DR (>= 40-50%) or massive raw DEF (> 1M) or high evasion (>= 70%).",
            },
        },
        "slot_positioning_matrix": {
            "slot_1_tank": {
                "role": "Absorbs pre-attack Super Attacks before the rotation has attacked.",
                "prerequisites": [
                    "Must have pre-attack Guard (Unconditional or active at turn start)",
                    "Damage Reduction >= 50% prior to attacking",
                    "Or pre-attack Evasion >= 70% with fallback defense",
                ],
                "fatal_traps": [
                    "Card whose guard only triggers 'As the 2nd or 3rd attacker in a turn' (e.g. LR Gogeta post-turn 3, Supreme Kai)",
                    "Card whose defense multiplies only 'When attacking' or 'When performing a Super Attack'",
                    "Card relying purely on on-hit or on-super stacking before building up",
                    "Expired intro shield (e.g. Turn 5 onwards for a 3-turn intro unit)",
                ],
                "verified_viable_card_ids": [c["id"] for c in slot_1_viable],
            },
            "slot_2_anchor": {
                "role": "Main damage dealer and linker. Shielded from pre-attack slot 1 supers; benefits from post-attack DEF boosts and builds attack/defense stacks safely.",
                "prerequisites": [
                    "High post-attack DEF multiplier ('When attacking', 'When performing a Super Attack')",
                    "Multiple Super Attacks ('Launches an additional Super Attack')",
                    "Critical hit chance and Type Effectiveness",
                ],
            },
            "slot_3_floater": {
                "role": "Rotates every 3 turns. Brings teamwide support, scouter intelligence, or high dodge without hogging Ki or requiring high link synergy.",
                "prerequisites": [
                    "Support passive: Allies' Ki +1..3 and DEF +30..50%",
                    "High evasion (>= 70%) or 3rd slot evasion buff",
                    "Scouter: Foresees enemy Super Attack",
                ],
            },
        },
        "incremental_mechanics_catalog": {
            "permanent_stacking": {
                "definition": "Stat buffs that persist for 99 turns (infinite stacking). Crucial for long battles (Red Zone / Supreme Magnificent Battle 4+ phases).",
                "types": [
                    {
                        "type": "Super Attack DEF Stack",
                        "value": "+20% to +30% to SA multiplier per Super Attack",
                    },
                    {
                        "type": "Super Attack Greatly Raises DEF",
                        "value": "+50% to SA multiplier per Super Attack",
                    },
                    {
                        "type": "Passive Stacking",
                        "value": "+10% to +30% ATK & DEF per attack performed/received up to cap",
                    },
                    {
                        "type": "Passive DR Stacking",
                        "value": "+5% to +10% DR per attack received/performed up to cap",
                    },
                ],
                "cards_with_stacking_count": len(stacking_cards),
            },
            "intro_cliff_effect": {
                "definition": "Temporary buffs active 'For X turns from character's entry turn'. Once expired, the card experiences a sharp defensive drop.",
                "cliff_timing": "Turn 1 (Active) -> Turn 3 (Active) -> Turn 5 (EXPIRED!).",
                "cards_with_intro_cliff_count": len(intro_cliff_cards),
                "tactical_rule": "On Turn 5, if the fight is not over, rotate the unit out to Slot 2 or Slot 3 unless it has permanent stacks or transformed!",
            },
            "slot_2_3_conditional_lock": {
                "definition": "Skills explicitly requiring the unit to be 2nd or 3rd attacker in a turn to receive Guard or DR.",
                "cards_count": len(slot_2_3_locked),
                "locked_card_sample": slot_2_3_locked[:15],
            },
            "utility_skills": {
                "scouter_count": len(scouter_cards),
                "taunt_target_count": len(taunt_cards),
                "domain_count": len(domain_cards),
                "standby_count": len(standby_cards),
                "revival_count": len(revival_cards),
                "action_break_count": len(action_break_cards),
                "counter_count": len(counter_cards),
            },
        },
        "slot_2_3_restricted_cards": slot_2_3_locked,
    }

    # Save JSON dictionary
    os.makedirs(os.path.dirname(os.path.abspath(OUTPUT_DICT_JSON)), exist_ok=True)
    with open(OUTPUT_DICT_JSON, "w", encoding="utf-8") as f:
        json.dump(tactical_dict, f, ensure_ascii=False, indent=2)
    print(f"Generated {OUTPUT_DICT_JSON} ({os.path.getsize(OUTPUT_DICT_JSON)} bytes)")

    # Save Python module
    py_module_content = f'''"""Tactical Dokkan Battle Keywords & Slot Optimization Rules (Post-10th Anniversary Meta).

Auto-generated from DokkanDB data analysis ({len(cards)} cards released >= 2025-01-28).
Provides structured rules and prompt fragments for Qwen LLM advisor and rotation optimizer.
"""

from typing import Any

TACTICAL_DAMAGE_FORMULA = (
    "{{[(Enemy_ATK x Variance x Type_Modifier) x (1 - DR)] - Ally_DEF}} x Guard_Reduction"
)

SLOT_1_MANDATORY_CRITERIA = [
    "Pre-attack Guard (Unconditional or Active on turn start without attacking)",
    "Damage Reduction >= 50% (prior to DEF subtraction)",
    "High start-of-turn DEF (>= 400k) with Guard, or >= 70% Damage Reduction",
    "Pre-attack high/great evasion (>= 70%)",
]

SLOT_1_ANTI_PATTERNS = [
    "Guards all attacks ONLY as 2nd or 3rd attacker in a turn",
    "DEF boost applied ONLY 'When attacking' or 'When performing a Super Attack'",
    "Guard/DR/Dodge conditional on Ki Spheres obtained ('with X or more Ki Spheres' / 'per Ki Sphere') - INACTIVE pre-attack in Slot 1!",
    "Heavy ramp-up dependency ('with each attack performed') with low base turn-1 stats",
    "Intro/entry-turn shield expired (Turn 5+ after a 3-turn intro)",
]

# Cards confirmed to have conditional guard/DR restricted to Slot 2/3
SLOT_2_3_LOCKED_IDS: set[int] = {{
    {", ".join(str(c["id"]) for c in slot_2_3_locked)}
}}


def get_qwen_system_prompt_tactical_rules() -> str:
    """Returns compact tactical Dokkan rules to inject into Qwen system/user prompts."""
    return """### CRITICAL DOKKAN BATTLE TACTICAL RULES & SLOT ALLOCATION:
1. ORDER OF OPERATIONS DAMAGE FORMULA:
   Damage Taken = {{[(Enemy ATK x Variance x Type_Mod) x (1 - DR)] - Ally DEF}} x Guard_Mod
   - Damage Reduction (DR) applies BEFORE Ally DEF is subtracted.
   - Ally DEF is subtracted AFTER Damage Reduction.
   - Guard applies at the END (Type_Mod = 0.8, Guard_Mod = 0.5).
   - NAKED GUARD IS NOT ENOUGH: Against a 3M+ Boss Super Attack, a unit with Guard but NO DR and only 300k DEF will still take over 1,000,000 LETHAL damage!

2. SLOT 1 VIABILITY CRITERIA:
   - Must have PRE-ATTACK DEFENSE: Unconditional Guard, high DR (>= 50%), or pre-attack evasion (>= 70%).
   - NEVER put a card in Slot 1 if its Guard or DR is conditional on:
     * 'As the 2nd or 3rd attacker in a turn'
     * 'When attacking' / 'When performing a Super Attack'
     * 'With X or more Ki Spheres obtained' / 'Per Ki Sphere obtained' (INACTIVE pre-attack before collecting spheres!)
   - Watch out for Intro Turn Expiration: Units with 'For 3 turns from entry turn' lose their shield on Turn 5!

3. ROTATION ASSIGNMENTS:
   - Slot 1: Pure Wall / Pre-attack Tank / Taunt / Scouter.
   - Slot 2: Main Attacker / Heavy Link Partner / Stacker (protected by Slot 1).
   - Slot 3: Floater / Support (Allies' Ki & DEF) / High Evasion.

4. KI SPHERE CONDITIONAL DEFENSE & ORB HUNGER:
   - Ki Spheres are collected WHEN THE UNIT ATTACKS.
   - Therefore, Damage Reduction, Guard, or Dodge requiring Ki Spheres is INACTIVE pre-attack in Slot 1.
   - Orb-dependent units MUST be placed in Slot 2 or 3 to collect orbs first, and MUST be paired with Orb Changers (especially Rainbow Ki Sphere Changers) to guarantee their defensive buffs activate every turn without orb starvation.
"""
'''

    os.makedirs(os.path.dirname(os.path.abspath(OUTPUT_MODULE_PY)), exist_ok=True)
    with open(OUTPUT_MODULE_PY, "w", encoding="utf-8") as f:
        f.write(py_module_content)
    print(f"Generated {OUTPUT_MODULE_PY}")


if __name__ == "__main__":
    extract_keywords_and_tactics()
