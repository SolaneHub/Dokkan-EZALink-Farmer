"""Card tactical heuristics, form timelines, kit evaluation, and leader coverage."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from dokkan_eza_link_farmer.ai.boss_models import TYPE_NAMES

if TYPE_CHECKING:
    pass


def get_tactical_form_timeline(card: Any) -> list[dict[str, str]]:
    self = card
    events: list[dict[str, str]] = []

    # 1. Standby Skill
    if self.standby_skill_name or self.has_standby:
        name = self.standby_skill_name or "Standby Mode"
        cond = (self.standby_skill_condition or "").lower()
        timing = (
            "Turno 4 (HP <= 50%)" if "4" in cond else ("Turno 3+" if "3" in cond else "Turno 4+")
        )
        eff = self.standby_skill_effect or "Enters Standby Mode"
        events.append(
            {
                "type": "Standby Mode",
                "name": name,
                "timing": timing,
                "condition": self.standby_skill_condition,
                "effect": eff,
            }
        )

    # 2. Active Skill (Exchange, Switch, or standard Active)
    if self.active_skill_name or self.has_active_skill:
        name = self.active_skill_name or "Active Skill"
        name_lower = name.lower()
        eff_lower = (self.active_skill_effect or "").lower()
        cond_lower = (self.active_skill_condition or "").lower()

        if "switch" in name_lower or "switch" in eff_lower:
            events.append(
                {
                    "type": "Scambio Reversibile (Switch)",
                    "name": name,
                    "timing": "Turno 1+ (Ogni Turno)",
                    "condition": self.active_skill_condition,
                    "effect": self.active_skill_effect,
                }
            )
        elif "exchange" in name_lower or "exchange" in eff_lower:
            timing = (
                "Turno 3"
                if "3" in cond_lower
                else ("Turno 4+" if "4" in cond_lower else "Turno 3+")
            )
            events.append(
                {
                    "type": "Scambio (Exchange)",
                    "name": name,
                    "timing": timing,
                    "condition": self.active_skill_condition,
                    "effect": self.active_skill_effect,
                }
            )
        elif (
            "fusion" in name_lower
            or "fusion" in eff_lower
            or "potara" in eff_lower
            or "potara" in name_lower
        ):
            timing = (
                "Turno 5+"
                if "5" in cond_lower
                else ("Turno 4+" if "4" in cond_lower else "Turno 4+")
            )
            events.append(
                {
                    "type": "Fusione (Potara / Fusion)",
                    "name": name,
                    "timing": timing,
                    "condition": self.active_skill_condition,
                    "effect": self.active_skill_effect,
                }
            )
        else:
            timing = (
                "Turno 5+"
                if "5" in cond_lower
                else ("Turno 4+" if "4" in cond_lower else "Attivabile")
            )
            events.append(
                {
                    "type": "Abilità Attiva (Active)",
                    "name": name,
                    "timing": timing,
                    "condition": self.active_skill_condition,
                    "effect": self.active_skill_effect,
                }
            )

    # 3. Transformations
    if self.transformations:
        for form in self.transformations:
            turn = form.min_turn if form.min_turn > 1 else 4
            events.append(
                {
                    "type": "Trasformazione",
                    "name": form.form_name or f"Form {form.form_index}",
                    "timing": f"Fase Finale (Turno {turn}+)",
                    "condition": f"A partire dal Turno {turn}",
                    "effect": form.passive_skill_text,
                }
            )

    return events


def evaluate_kit_power(card: Any) -> tuple[float, dict[str, Any]]:
    self = card
    def_score = 0.0
    breakdown: dict[str, Any] = {}

    has_guard = self.has_guard
    dr_pct = self.damage_reduction_percent
    has_stack_def = self.has_stacking_def
    dodge_chance = self.dodge_chance_percent
    is_guaranteed_dodge = bool(dodge_chance >= 100)

    # Base defensive attributes
    if has_guard:
        def_score += 15.0
        breakdown["guard"] = 15.0

    if dr_pct >= 50:
        def_score += 16.0
        breakdown["dr"] = f"{dr_pct}% (+16.0)"
    elif dr_pct >= 30 or self.has_damage_reduction:
        def_score += 12.0
        breakdown["dr"] = f"{dr_pct or 'present'}% (+12.0)"

    if has_stack_def:
        def_score += 12.0
        breakdown["stack_def"] = 12.0

    if self.has_dodge or dodge_chance > 0:
        if dodge_chance >= 100 or is_guaranteed_dodge:
            def_score += 16.0
            breakdown["dodge_tier"] = "100% Guaranteed (+16.0)"
        elif dodge_chance >= 70:
            def_score += 12.0
            breakdown["dodge_tier"] = "70% Great Chance (+12.0)"
        elif dodge_chance >= 50:
            def_score += 9.0
            breakdown["dodge_tier"] = "50% High Chance (+9.0)"
        elif dodge_chance >= 30:
            def_score += 6.0
            breakdown["dodge_tier"] = "30% Medium Chance (+6.0)"
        else:
            def_score += 4.0
            breakdown["dodge_tier"] = f"{dodge_chance}% Tier (+4.0)"

    if self.is_slot1_tank:
        def_score += 10.0
        breakdown["slot1_tank"] = 10.0

    # Composite Defense Survival Thresholds
    is_true_god_tank = (
        self.is_guard_permanent
        and self.is_guard_unconditional
        and (self.permanent_damage_reduction_percent >= 30 or dr_pct >= 50)
    )
    if is_true_god_tank:
        def_score += 35.0
        breakdown["composite_god_tank_guard_dr"] = 35.0
    elif has_guard and dr_pct >= 30:
        def_score += 18.0
        breakdown["composite_conditional_guard_dr"] = 18.0

    if self.permanent_damage_reduction_percent >= 70:
        def_score += 30.0
        breakdown["composite_heavy_dr_70"] = 30.0
    elif dr_pct >= 70:
        def_score += 20.0
        breakdown["composite_timed_heavy_dr"] = 20.0

    has_great_or_guaranteed_dodge = (self.has_dodge or dodge_chance > 0) and (
        dodge_chance >= 70 or is_guaranteed_dodge
    )
    if has_great_or_guaranteed_dodge:
        if self.is_dodge_permanent:
            def_score += 28.0
            breakdown["composite_great_or_guaranteed_dodge"] = 28.0
        else:
            def_score += 16.0
            breakdown["composite_timed_dodge"] = 16.0

    # 2. Game-Changing Mechanics (Revive, Standby, Taunt, Domain)
    mech_score = 0.0
    if self.has_revive:
        mech_score += 10.0
        breakdown["revive"] = 10.0
    if self.has_standby:
        mech_score += 8.0
        breakdown["standby"] = 8.0
    if self.has_target_taunt:
        mech_score += 10.0
        breakdown["taunt"] = 10.0
    if self.has_domain:
        mech_score += 6.0
        breakdown["domain"] = 6.0

    # 3. Utility & Team Support
    util_score = 0.0
    if self.has_support:
        util_score += 8.0
        breakdown["support"] = 8.0
    if self.has_orb_changing:
        util_score += 6.0
        breakdown["orb_changing"] = 6.0

    # 4. Offense & Multipliers
    atk_score = 0.0
    if self.has_additionals_or_crit:
        atk_score += 6.0
        breakdown["additionals_crit"] = 6.0
    if self.has_stacking_atk:
        atk_score += 4.0
        breakdown["stack_atk"] = 4.0
    if self.has_active_skill:
        atk_score += 4.0
        breakdown["active_skill"] = 4.0

    # 5. Base Card Tier & Progression
    tier_score = 0.0
    if self.is_lr:
        tier_score += 5.0
        breakdown["lr"] = 5.0
    if self.has_eza:
        tier_score += 4.0
        breakdown["eza"] = 4.0
    pot_pct = getattr(self, "potential_percent", 100 if self.is_rainbow else 0)
    if self.is_rainbow or pot_pct > 0:
        pot_bonus = (pot_pct / 100.0) * 4.0 if pot_pct > 0 else (4.0 if self.is_rainbow else 0.0)
        tier_score += pot_bonus
        if self.is_rainbow:
            breakdown["rainbow"] = 4.0
        elif pot_bonus > 0:
            breakdown["potential"] = round(pot_bonus, 2)

    total_score = def_score + mech_score + util_score + atk_score + tier_score
    return total_score, breakdown


def is_covered_by_leader(card: Any, leader: Any) -> tuple[bool, float, str]:
    self = card
    # Fast path: check leader_spec if available
    if leader.leader_spec and (
        leader.leader_spec.main_category_ids
        or leader.leader_spec.extra_category_ids
        or leader.leader_spec.sub_elements_classes
    ):
        spec = leader.leader_spec
        my_cats = set(self.category_ids)
        has_main = bool(my_cats & set(spec.main_category_ids))
        has_extra = bool(my_cats & set(spec.extra_category_ids))

        if has_main:
            if has_extra and spec.extra_boost_pct > 0:
                total_pct = float(spec.base_boost_pct + spec.extra_boost_pct)
                label = "200%" if int(total_pct) == 200 else f"{int(total_pct)}%"
                return (
                    True,
                    total_pct,
                    f"{label} ({spec.base_boost_pct}+{spec.extra_boost_pct}%) Leader Spec Match",
                )
            return True, float(spec.base_boost_pct), f"{spec.base_boost_pct}% Leader Spec Match"

        if spec.sub_elements_classes and (
            self.element in spec.sub_elements_classes
            or (self.element % 10) in spec.sub_elements_classes
        ):
            boost = (
                float(spec.sub_boost_pct)
                if spec.sub_boost_pct > 0
                else (float(spec.base_boost_pct) if not spec.main_category_ids else 90.0)
            )
            return True, boost, f"{int(boost)}% Sub-Element/Class Leader Spec Match"

        return False, 0.0, "No matching main category or sub-element on Leader Skill"

    lead_text = leader.leader_skill.strip()
    if not lead_text:
        return False, 0.0, "No leader skill"

    lead_lower = lead_text.lower()

    # Case A: Category Leader Skill
    matched_base_cat = None
    matched_extra_cat = None

    parts = re.split(r"plus an (?:additional|extra)", lead_text, flags=re.IGNORECASE)
    base_part = parts[0]
    extra_part = parts[1] if len(parts) > 1 else ""

    for cat in self.categories:
        if cat.lower() in base_part.lower():
            matched_base_cat = cat
            break

    if matched_base_cat:
        for cat in self.categories:
            if cat.lower() in extra_part.lower():
                matched_extra_cat = cat
                break

        if "200%" in base_part:
            return True, 200.0, f"Flat 200% on '{matched_base_cat}'"
        elif matched_extra_cat:
            extra_pct = 50.0 if "50%" in extra_part else 30.0
            total_pct = 170.0 + extra_pct
            label = f"{int(total_pct)}%"
            return (
                True,
                total_pct,
                f"170%+{int(extra_pct)}% ({label}) on '{matched_base_cat}' & '{matched_extra_cat}'",
            )
        elif "170%" in base_part:
            return True, 170.0, f"170% on '{matched_base_cat}'"
        elif "150%" in base_part:
            return True, 150.0, f"150% on '{matched_base_cat}'"
        elif "130%" in base_part:
            return True, 130.0, f"130% on '{matched_base_cat}'"
        else:
            return True, 120.0, f"Category lead on '{matched_base_cat}'"

    # Case B: All Types / Super Class / Extreme Class Leader
    is_super = 10 <= self.element < 20
    is_extreme = self.element >= 20

    if "all types" in lead_lower:
        pct = 150.0 if "150%" in lead_lower else (130.0 if "130%" in lead_lower else 100.0)
        return True, pct, "All Types Leader"

    if ("super class" in lead_lower or "super type" in lead_lower) and is_super:
        pct = 150.0 if "150%" in lead_lower else (130.0 if "130%" in lead_lower else 120.0)
        return True, pct, "Super Class Leader"

    if ("extreme class" in lead_lower or "extreme type" in lead_lower) and is_extreme:
        pct = 150.0 if "150%" in lead_lower else (130.0 if "130%" in lead_lower else 120.0)
        return True, pct, "Extreme Class Leader"

    # Case C: Mono-Type Leader
    card_type_idx = self.element % 10
    card_type_name = TYPE_NAMES.get(card_type_idx, "").lower()

    if card_type_name and f"{card_type_name} type" in lead_lower:
        pct = 130.0 if "130%" in lead_lower else (120.0 if "120%" in lead_lower else 100.0)
        return True, pct, f"Mono-{card_type_name.upper()} Type Leader"

    return False, 0.0, "No matching category or type on Leader Skill"


__all__ = ["get_tactical_form_timeline", "evaluate_kit_power", "is_covered_by_leader"]
