"""Passive skill parsing, evasion extraction, and conditional defense calculations."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dokkan_eza_link_farmer.ai.card_models import TeamConditionalBuff


def parse_dodge_percentage_from_text(text: str) -> int:
    """Extracts dodge / evasion percentage from passive skill or SA description."""
    clean_text = " ".join(text.lower().split())
    if not any(k in clean_text for k in ("evad", "evasion", "dodge")):
        return 0

    named = 0
    if (
        "guaranteed to evade" in clean_text
        or "guaranteed to dodge" in clean_text
        or "guaranteed evasion" in clean_text
    ):
        named = 100
    elif "great chance" in clean_text:
        named = 70
    elif "high chance" in clean_text:
        named = 50
    elif "medium chance" in clean_text or "med chance" in clean_text:
        named = 30
    elif "rare chance" in clean_text:
        named = 20
    elif re.search(
        r"(?<!chance of )(?<!chance to )(?<!great )(?<!high )(?<!medium )(?<!rare )(?<!med )(?<!guaranteed to )evades?\s+enemy(?:'s)?\s+attacks?",
        clean_text,
    ):
        named = 100

    explicit_vals: list[int] = []
    for m in re.finditer(r"(\d+)%\s*chance of evading", clean_text):
        explicit_vals.append(int(m.group(1)))
    for m in re.finditer(
        r"(?:chance of evading|chance to evade|chance of dodging|chance to dodge|evasion rate)\s*(?:enemy(?:'s)?\s+attacks?)?\s*(?:&[^\d%]*|\([^)]*\))?\s*(?:rate\s*)?\+?\s*(\d+)%",
        clean_text,
    ):
        explicit_vals.append(int(m.group(1)))
    for m in re.finditer(
        r"(?:evad\w*|dodge\w*)[^.\n\*\-]{0,60}\(up to (\d+)%\)",
        clean_text,
    ):
        explicit_vals.append(int(m.group(1)))

    valid_explicit = [v for v in explicit_vals if v <= 100]
    if valid_explicit:
        return max(named, max(valid_explicit))

    return named if named > 0 else 30


def parse_defense_mechanics(card: Any) -> dict[str, Any]:
    self = card
    """Parses passive skill and super attack to extract permanent vs timed defense attributes."""
    cached = getattr(self, "_cached_defense_mechanics", None)
    if cached is not None:
        return cached

    passive = self.passive_skill or ""
    sa = self.super_attack or ""

    blocks = re.split(r"\*([^*]+)\*", passive)
    sections = []
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
    SLOT_1_PATTERNS = (
        "as the 1st attacker in a turn",
        "as the 1st attacker",
        "in the 1st slot",
        "1st attacker in a turn",
        "1st slot",
    )
    SLOT_2_ONLY_PATTERNS = (
        "as the 2nd attacker in a turn",
        "as the 2nd attacker",
        "in the 2nd slot",
        "2nd attacker in a turn",
        "2nd slot",
    )
    SLOT_3_ONLY_PATTERNS = (
        "as the 3rd attacker in a turn",
        "as the 3rd attacker",
        "in the 3rd slot",
        "3rd attacker in a turn",
        "3rd slot",
    )
    SLOT_2_AND_3_PATTERNS = (
        "as the 2nd or 3rd attacker",
        "in the 2nd or 3rd slot",
        "2nd or 3rd attacker",
        "2nd or 3rd slot",
    )
    SLOT_2_PATTERNS = SLOT_2_ONLY_PATTERNS + SLOT_2_AND_3_PATTERNS
    SLOT_3_PATTERNS = SLOT_3_ONLY_PATTERNS + SLOT_2_AND_3_PATTERNS
    ALLY_CONDITIONAL_PATTERNS = (
        "allies attacking in the same turn",
        "when there are",
        "when there is another",
        "extreme class allies",
        "super class allies",
        "category ally",
        "category allies",
    )
    PRE_ATTACK_PATTERNS = (
        "before attacking",
        "before the character attacks",
        "before launching a super attack",
    )

    max_dr = 0
    permanent_dr = 0
    pre_hit_dr = 0
    dr_turn_limits: list[int] = []

    has_guard = False
    is_guard_permanent = False
    is_guard_unconditional = False
    pre_hit_guard = False
    guard_turn_limits: list[int] = []

    has_on_hit_guard = False
    has_on_hit_dr = False
    has_on_hit_def = False
    is_once_only_dr = False
    has_pre_attack_only_dr = False
    pre_attack_dr = 0
    pre_attack_ki_req: int | None = None
    has_pre_attack_only_guard = False
    has_slot_1_buff = False
    has_slot_2_buff = False
    has_slot_3_buff = False
    _has_slot_2_3_buff = False
    has_slot_2_3_guard = False
    has_slot_1_only_guard = False
    has_slot_1_only_dr = False
    is_slot_1_or_3_only = False
    slot_1_dr = 0
    slot_1_dodge = 0
    slot_3_dr = 0
    slot_3_dodge = 0

    has_enemy_conditional_defense = False
    enemy_conditional_categories: list[str] = []
    enemy_conditional_classes: list[str] = []
    enemy_conditional_dr = 0
    enemy_conditional_guard = False
    enemy_conditional_dodge = 0

    has_dodge = False
    base_dodge = 0
    is_dodge_permanent = True
    dodge_turn_limits: list[int] = []

    for header, content in sections:
        is_timed_header = False
        header_turns = None
        m_ht = re.search(r"for\s+(\d+)\s+turns?", header)
        if m_ht:
            is_timed_header = True
            header_turns = int(m_ht.group(1))
        elif "for 1 turn" in header or "within the character's next attacking turn" in header:
            is_timed_header = True
            header_turns = 1

        is_entrance = "entrance animation" in header or "upon the character's entry" in header

        header_is_on_hit = any(p in header for p in ON_HIT_PATTERNS)
        header_is_once_only = any(p in header for p in ONCE_ONLY_PATTERNS)
        header_is_slot_1 = any(p in header for p in SLOT_1_PATTERNS)
        header_is_slot_2 = any(p in header for p in SLOT_2_PATTERNS)
        header_is_slot_3 = any(p in header for p in SLOT_3_PATTERNS)
        header_is_slot_2_3 = header_is_slot_2 or header_is_slot_3
        header_is_ally_conditional = any(p in header for p in ALLY_CONDITIONAL_PATTERNS)
        header_is_pre_attack = any(p in header for p in PRE_ATTACK_PATTERNS)
        m_hki = re.search(r"(?:with\s+)?(\d+)\s+or\s+more\s+ki", header)
        header_ki_req = int(m_hki.group(1)) if m_hki else None

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

        is_conditional_header = (
            "ki spheres obtained" in header
            or "sphere" in header
            or "spheres" in header
            or "collecting" in header
            or "when hp is" in header
            or "when attacking" in header
            or header_is_slot_1
            or header_is_slot_2_3
            or header_is_on_hit
            or header_is_pre_attack
            or header_is_ally_conditional
            or header_is_enemy_conditional
            or "starting from" in header
            or "after the character's" in header
            or is_timed_header
            or is_entrance
        )
        is_basic = "basic effect" in header or header == ""

        raw_lines = [line.strip() for line in content.split("\n") if line.strip()]
        lines: list[str] = []
        for rline in raw_lines:
            if rline.startswith("-") or not lines:
                lines.append(rline)
            else:
                lines[-1] = f"{lines[-1]} {rline}"
        for line in lines:
            line_timed = is_timed_header
            line_turns = header_turns

            m_lt = re.search(r"for\s+(\d+)\s+turns?", line)
            if m_lt:
                line_timed = True
                line_turns = int(m_lt.group(1))
            elif (
                "for 1 turn" in line
                or "within the same turn" in line
                or "within the character's next attacking turn" in line
            ):
                line_timed = True
                line_turns = 1
            elif is_entrance and not line_timed:
                line_timed = True
                line_turns = 4

            line_is_on_hit = header_is_on_hit or any(p in line for p in ON_HIT_PATTERNS)
            line_is_once_only = header_is_once_only or any(p in line for p in ONCE_ONLY_PATTERNS)
            line_is_slot_1 = header_is_slot_1 or any(p in line for p in SLOT_1_PATTERNS)
            line_is_slot_2 = header_is_slot_2 or any(p in line for p in SLOT_2_PATTERNS)
            line_is_slot_3 = header_is_slot_3 or any(p in line for p in SLOT_3_PATTERNS)
            line_is_slot_2_3 = line_is_slot_2 or line_is_slot_3
            line_is_ally_conditional = header_is_ally_conditional or any(
                p in line for p in ALLY_CONDITIONAL_PATTERNS
            )
            line_is_pre_attack = header_is_pre_attack or any(p in line for p in PRE_ATTACK_PATTERNS)
            line_ki_req = header_ki_req
            if not line_ki_req:
                m_lki = re.search(r"(?:with\s+)?(\d+)\s+or\s+more\s+ki", line)
                if m_lki:
                    line_ki_req = int(m_lki.group(1))

            if line_is_slot_1:
                has_slot_1_buff = True
            if line_is_slot_2:
                has_slot_2_buff = True
            if line_is_slot_3:
                has_slot_3_buff = True

            line_clean = " ".join(line.split())
            line_is_enemy_conditional = header_is_enemy_conditional or (
                any(
                    p in line_clean
                    for p in (
                        "category enemy",
                        "category enemies",
                        "class enemy",
                        "class enemies",
                    )
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
                _has_slot_2_3_buff = True

            # Check on-hit DEF
            if line_is_on_hit and re.search(r"def\s*\+?\s*(\d+)%", line):
                has_on_hit_def = True

            # Damage Reduction
            dr_m = re.findall(
                r"(?:damage reduction rate\s*&[^\d%]*|damage reduction (?:rate|of)?|damage received by(?:\s+up to)?|reduces damage(?: received)? by(?:\s+up to)?(?:\s+an additional)?|damage received\s*-\s*)\s*(\d+)%",
                line,
                re.I,
            )
            for d in dr_m:
                val = int(d)
                if val > max_dr:
                    max_dr = val
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

                if line_is_pre_attack:
                    has_pre_attack_only_dr = True
                    if val > pre_attack_dr:
                        pre_attack_dr = val
                    if line_ki_req:
                        pre_attack_ki_req = line_ki_req
                if line_is_slot_1:
                    has_slot_1_only_dr = True
                    if val > slot_1_dr:
                        slot_1_dr = val
                if line_is_slot_3 and val > slot_3_dr:
                    slot_3_dr = val

                if line_timed:
                    if line_turns:
                        dr_turn_limits.append(line_turns)
                elif (
                    (is_basic or not is_conditional_header)
                    and not line_is_on_hit
                    and not line_is_once_only
                    and not line_is_slot_1
                    and not line_is_slot_2_3
                    and not line_is_enemy_conditional
                    and not line_is_pre_attack
                ):
                    if val > permanent_dr:
                        permanent_dr = val
                    if val > pre_hit_dr:
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
                has_guard = True
                if line_is_slot_2_3:
                    has_slot_2_3_guard = True
                if line_is_on_hit:
                    has_on_hit_guard = True
                if line_is_slot_1:
                    has_slot_1_only_guard = True
                if line_is_pre_attack:
                    has_pre_attack_only_guard = True
                if line_is_enemy_conditional:
                    has_enemy_conditional_defense = True
                    enemy_conditional_guard = True
                    for c in line_req_cats:
                        if c not in enemy_conditional_categories:
                            enemy_conditional_categories.append(c)
                    for cl in line_req_classes:
                        if cl not in enemy_conditional_classes:
                            enemy_conditional_classes.append(cl)

                if line_timed:
                    if line_turns:
                        guard_turn_limits.append(line_turns)
                else:
                    if (
                        not line_is_enemy_conditional
                        and not line_is_slot_1
                        and not line_is_slot_2_3
                        and not line_is_pre_attack
                    ):
                        is_guard_permanent = True
                    if (
                        (is_basic or not is_conditional_header)
                        and not line_is_on_hit
                        and not line_is_once_only
                        and not line_is_ally_conditional
                        and not line_is_slot_1
                        and not line_is_slot_2_3
                        and not line_is_enemy_conditional
                        and not line_is_pre_attack
                    ):
                        is_guard_unconditional = True
                        pre_hit_guard = True

            # Dodge
            if any(k in line for k in ("evad", "evasion", "dodge")):
                has_dodge = True
                line_val = parse_dodge_percentage_from_text(line)

                if line_is_enemy_conditional:
                    has_enemy_conditional_defense = True
                    if line_val > enemy_conditional_dodge:
                        enemy_conditional_dodge = line_val
                    for c in line_req_cats:
                        if c not in enemy_conditional_categories:
                            enemy_conditional_categories.append(c)
                    for cl in line_req_classes:
                        if cl not in enemy_conditional_classes:
                            enemy_conditional_classes.append(cl)

                if line_is_slot_1 and line_val > slot_1_dodge:
                    slot_1_dodge = line_val
                if line_is_slot_3 and line_val > slot_3_dodge:
                    slot_3_dodge = line_val

                if line_timed:
                    if line_turns:
                        dodge_turn_limits.append(line_turns)
                elif (
                    (is_basic or not is_conditional_header)
                    and not line_is_enemy_conditional
                    and line_val > base_dodge
                ):
                    base_dodge = line_val

    if not has_guard and re.search(r"guard(?:s|ing)?\s+(?:against\s+)?all", sa.lower()):
        has_guard = True
        is_guard_permanent = True
        pre_hit_guard = False

    if has_slot_1_only_guard and has_slot_2_3_guard:
        # Multi-slot guard (e.g. Amond & Rasin 1026771): unit guards across slots,
        # not restricted exclusively to either slot. Falls through to permanent.
        has_slot_1_only_guard = False
        has_slot_2_3_guard = False

    if (
        has_guard
        and not guard_turn_limits
        and not has_on_hit_guard
        and not has_slot_1_only_guard
        and not has_slot_2_3_guard
    ):
        is_guard_permanent = True
    elif (
        has_guard
        and (guard_turn_limits or has_on_hit_guard or has_slot_1_only_guard or has_slot_2_3_guard)
        and not is_guard_permanent
    ):
        is_guard_permanent = False

    if self.base_form and self.base_form.passive_tags:
        bt = self.base_form.passive_tags
        if getattr(bt, "has_slot_1_only_guard", False):
            has_slot_1_only_guard = True
        if getattr(bt, "has_slot_2_3_guard", False):
            has_slot_2_3_guard = True
        if getattr(bt, "has_slot_1_only_dr", False):
            has_slot_1_only_dr = True
        if bt.has_guard:
            has_guard = True
        if bt.is_guard_permanent:
            is_guard_permanent = True
        if bt.is_guard_unconditional:
            is_guard_unconditional = True
        if bt.pre_hit_guard:
            pre_hit_guard = True
        if bt.permanent_dr_percent > permanent_dr:
            permanent_dr = bt.permanent_dr_percent
        if bt.pre_hit_dr_percent > pre_hit_dr:
            pre_hit_dr = bt.pre_hit_dr_percent
        if bt.dr_base_percent > max_dr:
            max_dr = bt.dr_base_percent
        if bt.has_on_hit_defense:
            has_on_hit_def = True
        if bt.has_on_hit_guard:
            has_on_hit_guard = True
        if bt.has_on_hit_dr:
            has_on_hit_dr = True
        if bt.has_on_hit_def:
            has_on_hit_def = True
        if bt.is_once_only_dr:
            is_once_only_dr = True
        if getattr(bt, "has_pre_attack_only_dr", False):
            has_pre_attack_only_dr = True
            if getattr(bt, "pre_attack_dr_percent", 0) > pre_attack_dr:
                pre_attack_dr = bt.pre_attack_dr_percent
            if getattr(bt, "pre_attack_dr_ki_req", None):
                pre_attack_ki_req = bt.pre_attack_dr_ki_req
        if getattr(bt, "has_pre_attack_only_guard", False):
            has_pre_attack_only_guard = True
        if getattr(bt, "has_slot_2_3_buff", False):
            _has_slot_2_3_buff = True
        if getattr(bt, "has_slot_1_buff", False):
            has_slot_1_buff = True
        if getattr(bt, "has_slot_2_buff", False):
            has_slot_2_buff = True
        if getattr(bt, "has_slot_3_buff", False):
            has_slot_3_buff = True
        if getattr(bt, "is_slot_1_or_3_only", False):
            is_slot_1_or_3_only = True
        if getattr(bt, "slot_1_dr_percent", 0) > slot_1_dr:
            slot_1_dr = bt.slot_1_dr_percent
        if getattr(bt, "slot_1_dodge_percent", 0) > slot_1_dodge:
            slot_1_dodge = bt.slot_1_dodge_percent
        if getattr(bt, "slot_3_dr_percent", 0) > slot_3_dr:
            slot_3_dr = bt.slot_3_dr_percent
        if getattr(bt, "slot_3_dodge_percent", 0) > slot_3_dodge:
            slot_3_dodge = bt.slot_3_dodge_percent
        if getattr(bt, "has_enemy_conditional_defense", False):
            has_enemy_conditional_defense = True
            for c in getattr(bt, "enemy_conditional_categories", []):
                if c not in enemy_conditional_categories:
                    enemy_conditional_categories.append(c)
            for cl in getattr(bt, "enemy_conditional_classes", []):
                if cl not in enemy_conditional_classes:
                    enemy_conditional_classes.append(cl)
            enemy_conditional_dr = max(enemy_conditional_dr, getattr(bt, "enemy_conditional_dr", 0))
            if getattr(bt, "enemy_conditional_guard", False):
                enemy_conditional_guard = True
            enemy_conditional_dodge = max(
                enemy_conditional_dodge, getattr(bt, "enemy_conditional_dodge", 0)
            )

    if has_slot_1_only_guard and has_slot_2_3_guard:
        has_slot_1_only_guard = False
        has_slot_2_3_guard = False

    _has_slot_2_3_buff = has_slot_2_buff
    is_slot_1_or_3_only = (has_slot_1_buff or has_slot_3_buff) and not has_slot_2_buff
    if has_slot_1_only_dr and slot_3_dr > 0:
        has_slot_1_only_dr = False
    if has_slot_1_only_guard and (
        has_slot_3_buff or has_slot_2_buff or has_slot_2_3_guard or is_guard_unconditional
    ):
        has_slot_1_only_guard = False

    res = {
        "max_dr": max_dr,
        "permanent_dr": permanent_dr,
        "pre_hit_dr": pre_hit_dr,
        "is_dr_permanent": permanent_dr > 0,
        "dr_turns_limit": min(dr_turn_limits) if dr_turn_limits else None,
        "has_guard": has_guard,
        "pre_hit_guard": pre_hit_guard,
        "is_guard_permanent": is_guard_permanent,
        "guard_turns_limit": min(guard_turn_limits) if guard_turn_limits else None,
        "is_guard_unconditional": is_guard_unconditional,
        "has_on_hit_guard": has_on_hit_guard,
        "has_on_hit_dr": has_on_hit_dr,
        "has_on_hit_def": has_on_hit_def,
        "is_once_only_dr": is_once_only_dr,
        "has_pre_attack_only_dr": has_pre_attack_only_dr,
        "pre_attack_dr": pre_attack_dr,
        "pre_attack_ki_req": pre_attack_ki_req,
        "has_pre_attack_only_guard": has_pre_attack_only_guard,
        "has_slot_1_only_guard": has_slot_1_only_guard,
        "has_slot_1_only_dr": has_slot_1_only_dr,
        "has_slot_2_3_guard": has_slot_2_3_guard,
        "has_slot_2_3_buff": has_slot_2_buff,
        "has_slot_1_buff": has_slot_1_buff,
        "has_slot_2_buff": has_slot_2_buff,
        "has_slot_3_buff": has_slot_3_buff,
        "is_slot_1_or_3_only": is_slot_1_or_3_only,
        "slot_1_dr": slot_1_dr,
        "slot_1_dodge": slot_1_dodge,
        "slot_3_dr": slot_3_dr,
        "slot_3_dodge": slot_3_dodge,
        "has_enemy_conditional_defense": has_enemy_conditional_defense,
        "enemy_conditional_categories": enemy_conditional_categories,
        "enemy_conditional_classes": enemy_conditional_classes,
        "enemy_conditional_dr": enemy_conditional_dr,
        "enemy_conditional_guard": enemy_conditional_guard,
        "enemy_conditional_dodge": enemy_conditional_dodge,
        "has_dodge": has_dodge,
        "base_dodge": base_dodge,
        "is_dodge_permanent": is_dodge_permanent and (not dodge_turn_limits or base_dodge > 0),
        "dodge_turns_limit": min(dodge_turn_limits) if dodge_turn_limits else None,
    }
    self._cached_defense_mechanics = res
    return res


def calculate_team_conditional_defense(card: Any, team: list[Any] | None) -> dict[str, Any]:
    self = card
    """Calculates dynamic DR, Guard, and Dodge activated by team composition (e.g. Extreme/Super allies on team)."""
    # Retrieve parsed team conditional buffs and base defensive values
    buffs: list[TeamConditionalBuff] = []
    if self.base_form and getattr(self.base_form.passive_tags, "team_conditional_buffs", None):
        buffs = list(self.base_form.passive_tags.team_conditional_buffs)
        base_dr = self.base_form.passive_tags.pre_hit_dr_percent
        base_guard = self.base_form.passive_tags.pre_hit_guard
        base_dodge = self.base_form.passive_tags.dodge_chance_percent
    elif self.passive_skill:
        from dokkan_eza_link_farmer.ai.syncer import parse_passive_tags

        pt = parse_passive_tags(self.passive_skill)
        buffs = list(pt.team_conditional_buffs)
        base_dr = pt.pre_hit_dr_percent
        base_guard = pt.pre_hit_guard
        base_dodge = pt.dodge_chance_percent
    else:
        base_dr = self.damage_reduction_percent
        base_guard = self.has_guard
        base_dodge = self.dodge_chance_percent

    if not team:
        return {
            "dr": base_dr,
            "guard": base_guard,
            "dodge": base_dodge,
            "is_slot1_safe": False,
            "bypasses_orb_requirement": False,
        }

    if not buffs:
        is_safe = (
            (base_guard and base_dr >= 30)
            or base_dr >= 50
            or (base_dodge >= 70)
            or (
                base_guard
                and not getattr(self, "has_on_hit_defense", False)
                and not getattr(self, "has_orb_conditional_guard", False)
                and not getattr(self, "has_slot_2_3_guard", False)
            )
        )
        return {
            "dr": base_dr,
            "guard": base_guard,
            "dodge": base_dodge,
            "is_slot1_safe": is_safe,
            "bypasses_orb_requirement": False,
        }

    extreme_count = sum(
        1 for c in team if getattr(c, "is_extreme", False) or getattr(c, "element", 0) >= 20
    )
    super_count = sum(
        1 for c in team if getattr(c, "is_super", False) or (10 <= getattr(c, "element", 0) < 20)
    )
    total_allies = len(team)

    dr = base_dr
    guard = base_guard
    dodge = base_dodge
    bypasses_orbs = False

    for b in buffs:
        c_type = b.condition_type
        satisfied = False

        if c_type in ("class_count", "dual_orb_class"):
            req_c = b.req_class
            cnt = extreme_count if req_c == "Extreme" else super_count
            if cnt >= b.min_allies:
                satisfied = True
                if b.has_orb_alternative:
                    bypasses_orbs = True

        elif c_type == "all_class":
            req_c = b.req_class
            cnt = extreme_count if req_c == "Extreme" else super_count
            req_cats = [x.lower() for x in b.req_categories]
            cat_match = False
            if req_cats:
                cat_match = any(
                    any(
                        rc in [tc.lower() for tc in getattr(c, "categories", [])] for rc in req_cats
                    )
                    for c in team
                    if c is not self and getattr(c, "id", None) != getattr(self, "id", None)
                )
            if (cnt == total_allies and total_allies > 0) or cat_match:
                satisfied = True
                if b.has_orb_alternative:
                    bypasses_orbs = True

        elif c_type == "turn_allies":
            req_c = b.req_class
            req_cats = [x.lower() for x in b.req_categories]
            matching = 0
            for c in team:
                c_elem = getattr(c, "element", 0)
                is_ext = getattr(c, "is_extreme", False) or c_elem >= 20
                is_sup = getattr(c, "is_super", False) or (10 <= c_elem < 20)
                class_ok = True
                if req_c == "Extreme" and not is_ext or req_c == "Super" and not is_sup:
                    class_ok = False
                cat_ok = True
                if req_cats:
                    cat_ok = any(
                        rc in [tc.lower() for tc in getattr(c, "categories", [])] for rc in req_cats
                    )
                if class_ok and cat_ok:
                    matching += 1
            if matching >= b.min_allies:
                satisfied = True
                if b.has_orb_alternative:
                    bypasses_orbs = True

        elif c_type == "category_count":
            req_cats = [x.lower() for x in b.req_categories]
            cnt = sum(
                1
                for c in team
                if any(rc in [tc.lower() for tc in getattr(c, "categories", [])] for rc in req_cats)
            )
            if cnt >= b.min_allies:
                satisfied = True
                if b.has_orb_alternative:
                    bypasses_orbs = True

        elif c_type == "another_category":
            req_cats = [x.lower() for x in b.req_categories]
            cnt = sum(
                1
                for c in team
                if any(rc in [tc.lower() for tc in getattr(c, "categories", [])] for rc in req_cats)
            )
            if cnt >= 2 or (
                cnt >= 1
                and any(
                    rc not in [tc.lower() for tc in getattr(self, "categories", [])]
                    for rc in req_cats
                )
            ):
                satisfied = True
                if b.has_orb_alternative:
                    bypasses_orbs = True

        elif c_type == "per_name":
            substr = (b.name_substr or "").lower()
            name_cnt = sum(1 for c in team if substr in getattr(c, "name", "").lower())
            add_dr = min(b.max_dr or 999, name_cnt * b.per_ally_dr) if b.per_ally_dr else 0
            add_dodge = (
                min(b.max_dodge or 999, name_cnt * b.per_ally_dodge) if b.per_ally_dodge else 0
            )
            dr += add_dr
            dodge += add_dodge

        elif c_type == "per_category":
            req_cats = [x.lower() for x in b.req_categories]
            cat_cnt = sum(
                1
                for c in team
                if any(rc in [tc.lower() for tc in getattr(c, "categories", [])] for rc in req_cats)
            )
            add_dr = min(b.max_dr or 999, cat_cnt * b.per_ally_dr) if b.per_ally_dr else 0
            add_dodge = (
                min(b.max_dodge or 999, cat_cnt * b.per_ally_dodge) if b.per_ally_dodge else 0
            )
            dr += add_dr
            dodge += add_dodge

        if satisfied:
            dr += b.dr_percent
            if b.has_guard:
                guard = True
            dodge += b.dodge_percent

    # Determine Slot 1 safety
    if getattr(self, "has_orb_conditional_defense", False) or getattr(self, "is_orb_hungry", False):
        if not bypasses_orbs:
            is_slot1_safe = False
        else:
            is_slot1_safe = (guard and dr >= 30) or dr >= 50 or (dodge >= 70)
    else:
        is_slot1_safe = (
            (guard and dr >= 30)
            or dr >= 50
            or (dodge >= 70)
            or (
                guard
                and not getattr(self, "has_on_hit_defense", False)
                and not getattr(self, "has_slot_2_3_guard", False)
            )
        )

    return {
        "dr": dr,
        "guard": guard,
        "dodge": dodge,
        "is_slot1_safe": is_slot1_safe,
        "bypasses_orb_requirement": bypasses_orbs,
    }


__all__ = [
    "parse_dodge_percentage_from_text",
    "parse_defense_mechanics",
    "calculate_team_conditional_defense",
]
