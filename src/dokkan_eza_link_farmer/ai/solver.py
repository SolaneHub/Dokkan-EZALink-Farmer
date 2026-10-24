"""Algorithmic Constraint Solver for Dokkan AI Teambuilder.

Provides pure deterministic mathematical constraint solving:
- O(1) set operation filter with LeaderSkillSpec (170% and 200% boosts, sub-elements)
- Strict 6 distinct cards constraint (unique card.id)
- Same-name penalty for base form (form_index: 0)
- Two-phase survival: hard constraint requiring >= 2 units with slot1_viable == True in Base Form (Turns 1-3)
- Late-game scaling: transformations (min_turn >= 4) and permanent DEF stacking
- Cyclic type wheel matrix (AGL > STR > PHY > INT > TEQ > AGL)
- Boss gimmick overrides:
  * Mitigate type disadvantage if has_guard or dr_base_percent >= 60
  * Annull dodge contribution if cancels_dodge == True with vulnerability penalty on unshielded dodge units
  * Penalize Slot 2/3 floaters lacking start-of-turn guard/DR if has_aoe == True
  * Prioritize / bonus to slot1_viable units if locks_slots == True
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

from dokkan_eza_link_farmer.ai.models import (
    BossStage,
    DokkanCard,
)
from dokkan_eza_link_farmer.integrations.dokkandb_client import DokkanDBClient

logger = logging.getLogger(__name__)

# Dokkan cyclic type effectiveness mapping: Base type ID % 10 (0: AGL, 1: TEQ, 2: INT, 3: STR, 4: PHY)
# Attacker element beats defender element:
# AGL (0) beats STR (3)
# STR (3) beats PHY (4)
# PHY (4) beats INT (2)
# INT (2) beats TEQ (1)
# TEQ (1) beats AGL (0)
ELEMENT_ADVANTAGE: dict[int, int] = {
    0: 3,  # AGL > STR
    3: 4,  # STR > PHY
    4: 2,  # PHY > INT
    2: 1,  # INT > TEQ
    1: 0,  # TEQ > AGL
}

ELEMENT_DISADVANTAGE: dict[int, int] = {
    0: 1,  # AGL < TEQ
    1: 2,  # TEQ < INT
    2: 4,  # INT < PHY
    3: 0,  # STR < AGL
    4: 3,  # PHY < STR
}

SAME_NAME_BASE_PENALTY: float = 25.0
MIN_SLOT1_REQUIRED: int = 2
MIN_LEADER_BOOST_PCT: float = 170.0


_GLOBAL_CATEGORIES_CACHE: dict[int, str] | None = None


def _get_global_category_map() -> dict[int, str]:
    global _GLOBAL_CATEGORIES_CACHE
    if _GLOBAL_CATEGORIES_CACHE is not None:
        return _GLOBAL_CATEGORIES_CACHE

    cat_map: dict[int, str] = {}
    cache_dir = os.path.join(os.path.expanduser("~"), ".dokkan-farmer", "cache")
    possible_cache_files = [
        os.path.join(cache_dir, "dokkandb_categories_glb.json"),
        os.path.join(cache_dir, "dokkandb_categories.json"),
    ]
    for cache_file in possible_cache_files:
        if os.path.exists(cache_file):
            try:
                with open(cache_file, encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict) and "id" in item and "name" in item:
                                cat_map[int(item["id"])] = str(item["name"])
                if cat_map:
                    break
            except Exception as e:
                logger.debug(
                    f"Could not load global categories cache in solver from {cache_file}: {e}"
                )

    _GLOBAL_CATEGORIES_CACHE = cat_map
    return cat_map


def _resolve_category_name(cid: int, card: DokkanCard, leader: DokkanCard) -> str:
    """Helper to map a category ID to human-readable name using card, leader, or global catalog metadata."""
    c_map = dict(zip(card.category_ids, card.categories, strict=False))
    lead_map = dict(zip(leader.category_ids, leader.categories, strict=False))
    global_map = _get_global_category_map()
    return c_map.get(cid) or lead_map.get(cid) or global_map.get(cid) or str(cid)


def _get_category_id_by_name(cat_name: str, dokkandb: DokkanDBClient | None = None) -> int | None:
    """Resolves a category name to its integer ID using the global category map or dokkandb categories."""
    target_lower = cat_name.strip().lower()
    global_map = _get_global_category_map()
    for cid, name in global_map.items():
        if name.strip().lower() == target_lower:
            return cid

    if dokkandb is not None:
        try:
            cats = dokkandb.get_categories()
            if isinstance(cats, list):
                for item in cats:
                    if (
                        isinstance(item, dict)
                        and "id" in item
                        and "name" in item
                        and str(item["name"]).strip().lower() == target_lower
                    ):
                        cid = int(item["id"])
                        global_map[cid] = str(item["name"])
                        return cid
        except Exception as e:
            logger.debug(f"Failed resolving category id via dokkandb.get_categories: {e}")

    return None


def get_base_form_name(card: DokkanCard) -> str:
    """Extracts and normalizes the base form name (form_index: 0) for same-name checks."""
    name = card.base_form.form_name if card.base_form and card.base_form.form_name else card.name
    cleaned = name.strip().lower()
    if cleaned.endswith(" (base)"):
        cleaned = cleaned[:-7].strip()
    return cleaned


@dataclass
class CandidateEvaluation:
    """Detailed score and tactical rationale for a candidate sub unit."""

    card: DokkanCard
    score: float
    lead_boost_pct: float
    base_slot1_viable: bool
    counter_points: list[str] = field(default_factory=list)
    penalty_points: list[str] = field(default_factory=list)
    shared_links_with_core: list[str] = field(default_factory=list)

    @property
    def reasoning(self) -> str:
        """Synthesizes human-readable strengths or tactical rationale."""
        if self.counter_points:
            return "; ".join(self.counter_points)
        if self.base_slot1_viable:
            return "Slot 1 Tank viable"
        return ", ".join(self.card.categories[:3]) if self.card.categories else ""


@dataclass
class ConstraintSolverResult:
    """Outcome of algorithmic constraint solving: optimal 6-card team and runner-up shortlist."""

    leader: DokkanCard
    team_cards: list[DokkanCard]  # Exactly 6 cards
    shortlist: list[CandidateEvaluation]  # Top-5 runner-up candidates
    base_slot1_count: int  # Must be >= 2
    solver_logs: list[str] = field(default_factory=list)
    mission_batch: Any | None = None


class DokkanConstraintSolver:
    """
    Deterministic mathematical engine enforcing leader skill coverage, team uniqueness,
    base slot 1 viability, late-game scaling, cyclic type wheel, and boss gimmick overrides.
    """

    def __init__(self, dokkandb: DokkanDBClient | None = None) -> None:
        self.dokkandb = dokkandb or DokkanDBClient()

    @staticmethod
    def check_type_matchup(attacker_element: int, defender_element: int) -> int:
        """
        Determines Dokkan Battle cyclic type effectiveness:
        AGL (0) > STR (3) > PHY (4) > INT (2) > TEQ (1) > AGL (0)

        Returns:
            +1: Attacker has type advantage
            -1: Attacker has type disadvantage
             0: Neutral matchup
        """
        attacker = attacker_element % 10
        defender = defender_element % 10

        if ELEMENT_ADVANTAGE.get(attacker) == defender:
            return 1
        if ELEMENT_DISADVANTAGE.get(attacker) == defender:
            return -1
        return 0

    @staticmethod
    def is_slot1_viable(card: DokkanCard, boss_stage: Any = None) -> bool:
        """
        Determines whether a card is viable as a defensive anchor in Slot 1 in its Base Form (Turns 1-3).
        A true Slot 1 anchor must have pre-attack defensive survival against Endgame Super Attacks:
        1. Guaranteed Guard against all attacks (excludes RNG chance of guarding or enemy guard disabling).
        2. High Damage Reduction (DR >= 50% against all attacks, excludes normal-attacks-only DR).
        3. High/Guaranteed Dodge (>= 70% great chance or guaranteed to evade), neutralized if Boss cancels dodge.
        4. Explicit 1st Slot passive buffs granting Guard or DR >= 30% when placed in Slot 1.
        In long battles (>= 3 phases or multi-battle), temporary guard/DR (<= 6T) that expires is disqualified.
        """
        if card.is_tank_override is not None:
            return card.is_tank_override

        text = f"{card.passive_skill or ''} {card.super_attack or ''}".lower()

        cancels_dodge = False
        is_long_event = False
        if boss_stage:
            phases = getattr(boss_stage, "phases", [])
            cancels_dodge = any(getattr(p, "cancels_dodge", False) for p in phases)
            is_long_event = len(phases) >= 3 or getattr(boss_stage, "is_multi_battle", False)

        # 1. Guaranteed Pre-Attack Guard (Start-of-Turn)
        has_guard = False
        if (
            getattr(card, "is_guard_unconditional", False)
            or (
                "guards all attacks" in text
                or "guards against all attacks" in text
                or "all attacks guarded" in text
                or "guaranteed to guard" in text
            )
            or card.has_guard
        ):
            has_guard = True

        # Invalidate guard if it is an RNG chance or enemy-oriented
        if re.search(r"chance\s+of\s+guarding", text):
            has_guard = False
        if (
            "disables enemy" in text
            and "guard" in text
            and not (
                "guards all attacks" in text
                or "guards against all attacks" in text
                or "all attacks guarded" in text
            )
        ):
            has_guard = False

        # In long fights or multi-battles, timed guard <= 6 turns expires before the boss
        if (
            is_long_event
            and card.guard_turns_limit
            and card.guard_turns_limit <= 6
            and not card.is_guard_permanent
        ):
            has_guard = False

        # 2. Damage Reduction %
        dr = 0
        if card.base_form and card.base_form.passive_tags:
            dr = card.base_form.passive_tags.dr_base_percent
        else:
            dr = card.damage_reduction_percent

        # Exclude normal-attacks-only DR (e.g. PHY Vegito Blue takes full super attack damage)
        if "damage received from normal attacks" in text:
            clean_text = text.replace("damage received from normal attacks", "")
            if not any(
                k in clean_text for k in ("damage reduction", "reduces damage", "damage received -")
            ):
                dr = 0

        # In long fights or multi-battles, timed DR <= 6 turns expires before the boss
        if (
            is_long_event
            and card.dr_turns_limit
            and card.dr_turns_limit <= 6
            and getattr(card, "permanent_damage_reduction_percent", 0) < 50
        ):
            dr = getattr(card, "permanent_damage_reduction_percent", 0)

        # 3. Dodge % (Neutralized if boss cancels dodge)
        dodge = 0 if cancels_dodge else card.dodge_chance_percent

        # 4. Slot 1 specific buffs
        slot1_exclusive = (
            "1st attacker in a turn" in text
            or "in the 1st slot" in text
            or "as the 1st attacker" in text
        ) and ("guard" in text or "damage reduction" in text or "reduces damage" in text)

        if has_guard:
            return True
        if dr >= 50:
            return True
        if dodge >= 70:
            return True
        return bool(slot1_exclusive and (dr >= 30 or has_guard))

    def filter_by_leader_skill(
        self,
        candidates: list[DokkanCard],
        leader: DokkanCard,
        min_pct: float = MIN_LEADER_BOOST_PCT,
    ) -> list[tuple[DokkanCard, float]]:
        """
        O(1) set-based evaluation of leader skill coverage supporting 170%, 200%, and sub-element boosts.
        Returns tuples of (card, boost_percentage) for all cards meeting or exceeding min_pct.
        Strict rule: Candidates must share at least one category with leader.leader_spec.main_category_ids.
        """
        eligible: list[tuple[DokkanCard, float]] = []

        if not leader.leader_spec or not leader.leader_spec.main_category_ids:
            for card in candidates:
                is_cov, boost, _ = card.is_covered_by_leader(leader)
                if is_cov and boost >= min_pct:
                    eligible.append((card, boost))
            return eligible

        spec = leader.leader_spec
        main_cats = set(spec.main_category_ids)
        extra_cats = set(spec.extra_category_ids)
        sub_elems = set(spec.sub_elements_classes)

        for card in candidates:
            if not card.category_ids:
                continue
            card_cats = set(card.category_ids)
            shared_main = card_cats & main_cats
            if shared_main:
                if (card_cats & extra_cats) and spec.extra_boost_pct > 0:
                    boost = float(spec.base_boost_pct + spec.extra_boost_pct)
                else:
                    boost = float(spec.base_boost_pct)
                if boost >= min_pct:
                    eligible.append((card, boost))
            elif (
                min_pct < 170.0
                and sub_elems
                and (card.element in sub_elems or (card.element % 10) in sub_elems)
            ):
                boost = (
                    float(spec.sub_boost_pct)
                    if spec.sub_boost_pct > 0
                    else (float(spec.base_boost_pct) if not spec.main_category_ids else 90.0)
                )
                if boost >= min_pct:
                    eligible.append((card, boost))

        return eligible

    def evaluate_boss_gimmicks(
        self,
        card: DokkanCard,
        boss_stage: BossStage | None,
    ) -> tuple[float, list[str], list[str]]:
        """
        Evaluates boss phase gimmicks and calculates score modifiers and tactical points:
        1. Type Advantage vs Disadvantage against final phase (mitigated if has_guard or DR >= 60%).
        2. Cancels Dodge: zero out dodge contribution and penalize unshielded dodge units.
        3. Multi-Battle Structure Mechanics (Stacking Resets & Turn 1 Safety).
        4. Defensive Expiration in Multi-Phase Single Battles (>= 3 phases in 1 continuous battle).
        5. AoE attacks: penalize floaters lacking start-of-turn Guard/DR.
        6. Locks slots: bonus to slot 1 viable units, penalty to fragile units.
        """
        delta = 0.0
        counters: list[str] = []
        penalties: list[str] = []

        if not boss_stage or not boss_stage.phases:
            return delta, counters, penalties

        num_phases = len(boss_stage.phases)
        cancels_dodge_any = any(p.cancels_dodge for p in boss_stage.phases)
        has_aoe_any = any(p.has_aoe for p in boss_stage.phases)
        locks_slots_any = any(p.locks_slots for p in boss_stage.phases)
        is_multi_battle = getattr(boss_stage, "is_multi_battle", False)
        total_battles = getattr(boss_stage, "total_battles", 1)

        # 1. Type Matchup against All Phases and Battles
        is_long_event = num_phases >= 3 or is_multi_battle
        card_dr = (
            card.permanent_damage_reduction_percent
            if is_long_event
            else card.damage_reduction_percent
        )
        if (
            card.base_form
            and card.base_form.passive_tags
            and (not is_long_event or card.base_form.passive_tags.is_dr_permanent)
            and card.base_form.passive_tags.dr_base_percent > card_dr
        ):
            card_dr = card.base_form.passive_tags.dr_base_percent

        card_has_guard = (
            (card.is_guard_permanent and card.is_guard_unconditional)
            if is_long_event
            else (
                card.has_guard
                or (
                    card.base_form is not None
                    and card.base_form.passive_tags is not None
                    and card.base_form.passive_tags.has_guard
                )
            )
        )

        for p_idx, p in enumerate(boss_stage.phases):
            is_final_phase = p_idx == num_phases - 1
            if getattr(p, "is_rainbow", False):
                continue

            phase_num = getattr(p, "phase_index", p_idx + 1)
            is_multi = getattr(p, "is_multi_enemy", False) and bool(getattr(p, "bosses", None))
            enemies: list[tuple[str, int, str]] = []
            if is_multi:
                for b in p.bosses:
                    enemy_elem = getattr(b, "element", 0)
                    enemy_name = getattr(b, "name", "Enemy")
                    enemy_type = getattr(b, "type_name", "") or str(enemy_elem)
                    enemies.append((enemy_name, enemy_elem, enemy_type))
            else:
                p_elem = getattr(p, "element", 0)
                p_name = getattr(p, "element_name", "") or str(p_elem)
                enemies.append((p_name, p_elem, p_name))

            dr_threshold = 50 if is_multi else 60
            is_mitigated = card_has_guard or (card_dr >= dr_threshold)

            phase_disadv_applied = False
            phase_adv_applied = False
            for enemy_name, enemy_elem, enemy_type in enemies:
                matchup = self.check_type_matchup(card.element, enemy_elem)
                if matchup < 0:
                    if is_mitigated:
                        if is_final_phase:
                            if not phase_disadv_applied:
                                delta -= 5.0
                                counters.append(
                                    f"Type Disadvantage against Final Phase mitigated by Guard/DR ({card_dr}%)"
                                    if card_dr >= dr_threshold and not card_has_guard
                                    else "Type Disadvantage against Final Phase mitigated by Guard/DR"
                                )
                                phase_disadv_applied = True
                        else:
                            if not phase_disadv_applied:
                                counters.append(
                                    f"Type Disadvantage in Phase {phase_num} mitigated by Guard/DR"
                                )
                                phase_disadv_applied = True
                    else:
                        if is_final_phase:
                            if not phase_disadv_applied:
                                delta -= 25.0
                                penalties.append(
                                    f"Severe Type Disadvantage against Boss Final Phase ({p.element_name})"
                                )
                                phase_disadv_applied = True
                        else:
                            if not phase_disadv_applied:
                                delta -= 15.0
                                penalties.append(
                                    f"Type Disadvantage in Phase {phase_num} (vs {enemy_name} [{enemy_type}]) without Guard/DR"
                                )
                                phase_disadv_applied = True
                elif matchup > 0 and not phase_adv_applied:
                    if is_final_phase:
                        delta += 5.0
                        counters.append(
                            f"Type Advantage against Boss Final Phase ({p.element_name}) (+5.0)"
                        )
                        phase_adv_applied = True
                    else:
                        delta += 3.0
                        counters.append(
                            f"Type Advantage in Phase {phase_num} ({p.element_name or enemy_type}) (+3.0)"
                        )
                        phase_adv_applied = True

        # 2. Cancels Dodge Gimmick
        if cancels_dodge_any:
            dodge_pct = card.dodge_chance_percent
            if dodge_pct > 0 or card.has_dodge:
                effective_dodge_pct = dodge_pct if dodge_pct > 0 else 30
                penalties.append(
                    f"Dodge ({effective_dodge_pct}%) neutralized by Boss (Cancels Dodge)"
                )

                is_long_event = num_phases >= 3 or is_multi_battle
                dr_base = max(
                    card.damage_reduction_percent,
                    card.base_form.passive_tags.dr_base_percent
                    if card.base_form and card.base_form.passive_tags
                    else 0,
                )
                effective_dr = card.permanent_damage_reduction_percent if is_long_event else dr_base
                has_guard_defense = (
                    (card.is_guard_permanent and card.is_guard_unconditional)
                    if is_long_event
                    else (
                        card.has_guard
                        or (
                            card.base_form is not None
                            and card.base_form.passive_tags is not None
                            and card.base_form.passive_tags.has_guard
                        )
                    )
                )
                has_stacking = card.has_stacking_def or (
                    card.base_form is not None
                    and card.base_form.sa_tags is not None
                    and card.base_form.sa_tags.stacks_def
                )

                # In multi-battle events, stacking cannot be relied upon because it resets each battle
                stacking_reliable = has_stacking and not is_multi_battle

                # If card has only dodge without reliable Guard or DR against Cancels Dodge
                if (
                    not has_guard_defense
                    and (effective_dr == 0 or effective_dr < 40)
                    and not stacking_reliable
                ):
                    delta -= 60.0
                    penalties.append(
                        "Severe Glass Cannon Vulnerability: relies on dodge but lacks Guard/DR against Cancels Dodge (-60.0)"
                    )
                else:
                    counters.append(
                        "Resilience preserved via Guard/DR/Stacking despite Cancels Dodge"
                    )

        # 3. Multi-Battle Structure Mechanics (Stacking Resets & Turn 1 Safety)
        if is_multi_battle:
            # Check for permanent or reliable multi-battle shield
            # Note: Intro/Entrance guard only triggers in Battle 1 (once only per stage)!
            is_intro_only = (
                card.guard_turns_limit is not None
                and card.guard_turns_limit <= 6
                and not card.is_guard_permanent
            )
            has_guard_reliable = (
                (card.has_guard and not is_intro_only)
                or (card.is_guard_permanent and card.is_guard_unconditional)
                or bool(
                    card.base_form
                    and card.base_form.passive_tags
                    and card.base_form.passive_tags.has_guard
                    and card.base_form.passive_tags.is_guard_permanent
                )
            )
            dr_any = max(
                card.permanent_damage_reduction_percent,
                card.base_form.passive_tags.permanent_dr_percent
                if card.base_form and card.base_form.passive_tags
                else (
                    card.damage_reduction_percent
                    if not card.dr_turns_limit or card.dr_turns_limit > 6
                    else 0
                ),
            )
            has_turn1_shield = has_guard_reliable or dr_any >= 45

            if has_turn1_shield:
                delta += 15.0
                counters.append(
                    f"Multi-Battle Reliability: Immediate Turn-1 Guard/DR ({dr_any}%) protects unit across all {total_battles} separate battles (+15.0)"
                )
            elif card.has_stacking_def and not has_turn1_shield:
                delta -= 20.0
                penalties.append(
                    f"Stacking Reset Vulnerability: Stage has {total_battles} separate battles. DEF stacks reset to 0 at each battle start, exposing unit to Turn 1 fatal attacks (-20.0)"
                )

        # 4. Defensive Expiration in Long Battles (>= 3 phases or Multi-Battle)
        if num_phases >= 3 or is_multi_battle:
            if (
                card.dr_turns_limit is not None
                and card.dr_turns_limit <= 6
                and card.permanent_damage_reduction_percent == 0
            ):
                delta -= 25.0
                penalties.append(
                    f"Defensive Expiration: DR ({card.damage_reduction_percent}%) expires after {card.dr_turns_limit} turn(s), leaving unit vulnerable in late game (-25.0)"
                )
            if (
                card.guard_turns_limit is not None
                and card.guard_turns_limit <= 6
                and not card.is_guard_permanent
            ):
                delta -= 25.0
                penalties.append(
                    f"Guard Expiration: Guard expires after {card.guard_turns_limit} turn(s) / intro animation, leaving unit unprotected against late-game bosses (-25.0)"
                )

        # 5. AoE Attacks Gimmick
        if has_aoe_any:
            has_sot_def = card.has_guard or card.damage_reduction_percent >= 40
            if not has_sot_def:
                delta -= 22.0
                penalties.append(
                    "AoE Vulnerability: lacks start-of-turn Guard/DR against pre-attack Super/AoE"
                )
            else:
                delta += 15.0
                counters.append("Start-of-turn Guard/DR mitigates Boss AoE attacks")

        # 6. Locks Slots Gimmick
        if locks_slots_any:
            is_slot1 = self.is_slot1_viable(card)
            if is_slot1:
                delta += 15.0
                counters.append(
                    "Slot locking immunity: unit is Slot 1 viable even if locked into position 1"
                )
            else:
                if not card.has_guard and card.damage_reduction_percent < 30:
                    delta -= 15.0
                    penalties.append(
                        "Slot Lock Vulnerability: squishy unit lacks defensive kit if locked into Slot 1"
                    )

        # 7. Multi-Enemy and Rainbow Phase Gimmicks
        has_multi_enemy = any(getattr(p, "is_multi_enemy", False) for p in boss_stage.phases)
        if has_multi_enemy and card.has_aoe:
            delta += 25.0
            counters.append(
                "AoE Specialist: Attacks all enemies simultaneously, highly effective in multi-target stage phases (+25.0)"
            )

        has_debuffable_multi_phase = any(
            getattr(p, "is_multi_enemy", False) and not getattr(p, "nullifies_atk_down", False)
            for p in boss_stage.phases
        )
        if has_debuffable_multi_phase and card.lowers_enemy_atk:
            delta += 15.0
            counters.append(
                "Debuff Specialist: Lowers enemy ATK in multi-enemy phase lacking ATK debuff immunity (+15.0)"
            )

        rainbow_phases = [p for p in boss_stage.phases if getattr(p, "is_rainbow", False)]
        if rainbow_phases:
            # Check unconditional guard or permanent guard, or DR >= 50%
            is_omni_guard = (
                card.is_guard_unconditional
                or card.is_guard_permanent
                or (
                    card.base_form is not None
                    and card.base_form.passive_tags is not None
                    and (
                        card.base_form.passive_tags.is_guard_unconditional
                        or card.base_form.passive_tags.is_guard_permanent
                    )
                )
            )
            has_high_dr = card.damage_reduction_percent >= 50 or (
                card.base_form is not None
                and card.base_form.passive_tags is not None
                and card.base_form.passive_tags.dr_base_percent >= 50
            )

            if is_omni_guard or has_high_dr:
                delta += 15.0
                counters.append(
                    "Omni-Guard/High-DR: Neutralizes all 5 enemy typings in multi-target Rainbow phase (+15.0)"
                )
            else:
                delta -= 15.0
                penalties.append(
                    "Rainbow Phase Vulnerability: lacks unconditional Guard or high DR (>= 50%) against diverse enemy typings (-15.0)"
                )

        return delta, counters, penalties

    def evaluate_card(
        self,
        card: DokkanCard,
        leader: DokkanCard,
        boss_stage: BossStage | None = None,
        selected_team: list[DokkanCard] | None = None,
    ) -> CandidateEvaluation:
        """
        Computes a comprehensive mathematical fitness score for a candidate sub-unit under a leader.
        Considers Leader %, Base Slot 1 Viability, Base Kit Power, DEF Stacking, Boss Gimmicks,
        Late-Game Transformations, and Same-Name Base Form Penalty.
        """
        score = 0.0
        counter_points: list[str] = []
        penalty_points: list[str] = []

        # 1. Leader Skill Boost
        if (
            not leader.leader_spec
            or not leader.leader_spec.main_category_ids
            or leader.leader_spec.base_boost_pct < MIN_LEADER_BOOST_PCT
            or not card.category_ids
        ):
            return CandidateEvaluation(
                card=card,
                score=-1000.0,
                lead_boost_pct=0.0,
                base_slot1_viable=self.is_slot1_viable(card),
                penalty_points=["Insufficient Leader Coverage (< 170% or un-enriched leader/card)"],
            )

        main_cats = set(leader.leader_spec.main_category_ids)
        if not bool(set(card.category_ids) & main_cats):
            return CandidateEvaluation(
                card=card,
                score=-1000.0,
                lead_boost_pct=0.0,
                base_slot1_viable=self.is_slot1_viable(card),
                penalty_points=["Zero shared categories with Leader main categories"],
            )

        is_cov, lead_pct, _ = card.is_covered_by_leader(leader)
        if not is_cov or lead_pct < MIN_LEADER_BOOST_PCT:
            return CandidateEvaluation(
                card=card,
                score=-1000.0,
                lead_boost_pct=lead_pct,
                base_slot1_viable=self.is_slot1_viable(card),
                penalty_points=[
                    f"Insufficient Leader Coverage ({lead_pct}% < {MIN_LEADER_BOOST_PCT}%)"
                ],
            )

        if lead_pct >= 200.0:
            score += 32.0
            counter_points.append(f"Full 200% Leader Boost ({lead_pct}%)")
        elif lead_pct >= 170.0:
            score += 24.0
            counter_points.append(f"170% Base Leader Boost ({lead_pct}%)")
        elif lead_pct >= 150.0:
            score += 12.0
            counter_points.append(f"150% Sub-Leader Boost ({lead_pct}%)")

        # 2. Early-Game Slot 1 Viability (Turns 1-3 Survival)
        base_s1 = self.is_slot1_viable(card)
        if base_s1:
            score += 28.0
            counter_points.append("Base Form is Slot 1 viable (guaranteed survival Turns 1-3)")

        # 3. Base Kit Power
        kit_power, _ = card.evaluate_kit_power()
        score += kit_power * 0.4

        # 4. Permanent Defense Stacking
        has_stacking = bool(
            (card.base_form and card.base_form.sa_tags and card.base_form.sa_tags.stacks_def)
            or card.has_stacking_def
        )
        if has_stacking:
            score += 10.0
            counter_points.append(
                "Permanent DEF stacking on Super Attack provides late-game defense scaling"
            )

        # 5. Boss Gimmick Overrides
        gimmick_delta, g_counters, g_penalties = self.evaluate_boss_gimmicks(card, boss_stage)
        score += gimmick_delta
        counter_points.extend(g_counters)
        penalty_points.extend(g_penalties)

        # 6. Late-Game Scaling (Transformations at Turn 4+)
        if card.transformations:
            for form in card.transformations:
                if form.min_turn >= 4:
                    t_score = 0.0
                    pt = form.passive_tags
                    if pt.has_guard:
                        t_score += 10.0
                    if pt.dr_base_percent >= 40:
                        t_score += 10.0
                    if pt.has_revive or pt.has_taunt:
                        t_score += 12.0
                    if form.sa_tags.stacks_def:
                        t_score += 8.0

                    if boss_stage and boss_stage.phases:
                        num_p = len(boss_stage.phases)
                        # For min_turn >= 4: check intermediate and final phases (from phase 2 onwards, or all if 1-2 phases)
                        target_phases = boss_stage.phases[1:] if num_p >= 3 else boss_stage.phases
                        if any(
                            self.check_type_matchup(form.element, getattr(p, "element", 0)) > 0
                            for p in target_phases
                            if not getattr(p, "is_rainbow", False)
                        ):
                            t_score += 12.0

                    score += t_score * 0.5
                    counter_points.append(
                        f"Transformation '{form.form_name}' (Turn {form.min_turn}+) adds late-game power (+{t_score * 0.5:.1f} pts)"
                    )
                elif form.min_turn > 1:
                    t_score = 0.0
                    if form.passive_tags.has_guard:
                        t_score += 6.0
                    if form.passive_tags.dr_base_percent >= 40:
                        t_score += 6.0

                    if boss_stage and boss_stage.phases:
                        # For min_turn <= 3: check early phases
                        target_phases = (
                            boss_stage.phases[:2]
                            if len(boss_stage.phases) >= 2
                            else boss_stage.phases
                        )
                        if any(
                            self.check_type_matchup(form.element, getattr(p, "element", 0)) > 0
                            for p in target_phases
                            if not getattr(p, "is_rainbow", False)
                        ):
                            t_score += 8.0

                    score += t_score * 0.3

        # 7. Same-Name Base Form Penalty (form_index: 0)
        if selected_team:
            cand_base_name = get_base_form_name(card)
            for member in selected_team:
                if member.id != card.id:
                    member_base_name = get_base_form_name(member)
                    if cand_base_name == member_base_name:
                        score -= SAME_NAME_BASE_PENALTY
                        penalty_points.append(
                            f"Same-Name Base Form Penalty: shares base form '{cand_base_name}' with {member.name}"
                        )
                        break

        # 8. Shared Links with Core (Leader)
        cand_base = get_base_form_name(card)
        lead_base = get_base_form_name(leader)
        if card.id != leader.id and cand_base != lead_base:
            shared_links = sorted(list(set(card.links) & set(leader.links)))
            score += float(len(shared_links)) * 1.0
        else:
            shared_links = []

        return CandidateEvaluation(
            card=card,
            score=round(score, 2),
            lead_boost_pct=lead_pct,
            base_slot1_viable=base_s1,
            counter_points=counter_points,
            penalty_points=penalty_points,
            shared_links_with_core=shared_links,
        )

    def get_shortlist(
        self,
        candidate_pool: list[DokkanCard],
        leader: DokkanCard,
        boss_stage: BossStage | None = None,
        exclude_ids: set[int] | None = None,
        top_k: int = 5,
    ) -> list[CandidateEvaluation]:
        """Returns the top K candidate evaluations from candidate_pool under leader, excluding exclude_ids."""
        exclude = set(exclude_ids or set())
        exclude.add(leader.id)

        evaluations: list[CandidateEvaluation] = []
        for card in candidate_pool:
            if card.id in exclude:
                continue
            ev = self.evaluate_card(card, leader, boss_stage)
            if ev.score > -90.0:
                evaluations.append(ev)

        evaluations.sort(key=lambda x: x.score, reverse=True)
        return evaluations[:top_k]

    def solve(
        self,
        candidate_pool: list[DokkanCard],
        boss_stage: BossStage | None = None,
        forced_leader: DokkanCard | None = None,
        mission_batch: Any | None = None,
    ) -> ConstraintSolverResult:
        """
        Synthesizes the optimal 6-card team for a BossStage:
        1. Selects best leader (or uses forced_leader).
        2. Filters candidate pool under leader skill (>= 150%).
        3. Strictly enforces 6 distinct cards (unique card.id).
        4. Enforces Two-Phase Survival: >= 2 units with base_slot1_viable == True.
        5. Greedily selects sub-units applying Same-Name Base Form penalty dynamically.
        6. Enforces mission constraints (full/partial categories, 5 types rainbow, super/extreme).
        7. Extracts Top-5 shortlist of runner-up candidates.
        """
        logs: list[str] = []

        # Deduplicate pool by card.id to ensure uniqueness
        unique_map: dict[int, DokkanCard] = {}
        for card in candidate_pool:
            if card.id not in unique_map:
                unique_map[card.id] = card
        unique_pool = list(unique_map.values())

        if len(unique_pool) < 6:
            raise ValueError(
                f"Need at least 6 distinct cards in candidate pool, found {len(unique_pool)}"
            )

        # Enforce mission pre-filters on unique_pool
        if mission_batch is not None:
            logs.append(f"Mission Targeting Active: {mission_batch.summary}")
            if getattr(mission_batch, "requires_all_super", False):
                unique_pool = [c for c in unique_pool if getattr(c, "card_class", "") == "Super"]
                logs.append(
                    f"Enforced Super Class Only restriction ({len(unique_pool)} cards remaining)"
                )
            elif getattr(mission_batch, "requires_all_extreme", False):
                unique_pool = [c for c in unique_pool if getattr(c, "card_class", "") == "Extreme"]
                logs.append(
                    f"Enforced Extreme Class Only restriction ({len(unique_pool)} cards remaining)"
                )

            for req_count, cat_name in getattr(mission_batch, "required_categories", []):
                if req_count >= 6:
                    c_name_lower = cat_name.strip().lower()
                    filtered = [
                        c
                        for c in unique_pool
                        if any(c_cat.strip().lower() == c_name_lower for c_cat in c.categories)
                    ]
                    if len(filtered) < 6:
                        raise ValueError(
                            f"Cannot build team for mission 6x '{cat_name}': box only contains {len(filtered)} matching cards (need 6)."
                        )
                    unique_pool = filtered
                    logs.append(
                        f"Enforced 6x '{cat_name}' Category requirement (Pool: {len(unique_pool)} cards)"
                    )

            if len(unique_pool) < 6:
                raise ValueError(
                    f"Need at least 6 distinct cards in candidate pool to satisfy mission criteria, found {len(unique_pool)}"
                )

        # Query and enrich cards using DokkanDB official category leaders endpoint
        category_leaders_by_cat: dict[int, dict[int, dict[str, Any]]] = {}
        if mission_batch is not None:
            for _req_cnt, req_cat in getattr(mission_batch, "required_categories", []):
                cat_id = _get_category_id_by_name(req_cat, dokkandb=self.dokkandb)
                if cat_id is not None:
                    try:
                        category_leaders_by_cat[cat_id] = self.dokkandb.get_category_leaders_map(
                            cat_id
                        )
                    except Exception as e:
                        logger.debug(
                            f"Could not load category leaders for category {cat_id} ({req_cat}): {e}"
                        )

        if category_leaders_by_cat:
            from dokkan_eza_link_farmer.ai.models import LeaderSkillSpec

            for c in unique_pool:
                for cid, leaders_map in category_leaders_by_cat.items():
                    if c.id in leaders_map:
                        official_info = leaders_map[c.id]
                        if c.leader_spec is None:
                            c.leader_spec = LeaderSkillSpec(
                                base_boost_pct=official_info["base_boost_pct"],
                                extra_boost_pct=official_info["extra_boost_pct"],
                                hp_stat_pct=official_info.get(
                                    "hp_stat_pct", official_info["base_boost_pct"]
                                ),
                                atk_stat_pct=official_info["base_boost_pct"],
                                def_stat_pct=official_info["base_boost_pct"],
                            )
                        else:
                            c.leader_spec.base_boost_pct = max(
                                c.leader_spec.base_boost_pct, official_info["base_boost_pct"]
                            )
                            c.leader_spec.extra_boost_pct = max(
                                c.leader_spec.extra_boost_pct, official_info["extra_boost_pct"]
                            )
                            if official_info.get("hp_stat_pct", 0) > 0:
                                c.leader_spec.hp_stat_pct = max(
                                    c.leader_spec.hp_stat_pct, official_info["hp_stat_pct"]
                                )

                        if (
                            official_info.get("is_main_leader")
                            and cid not in c.leader_spec.main_category_ids
                        ):
                            c.leader_spec.main_category_ids.append(cid)
                        if (
                            official_info.get("is_extra_leader")
                            and cid not in c.leader_spec.extra_category_ids
                        ):
                            c.leader_spec.extra_category_ids.append(cid)

        # 1. Determine Leader
        leader = forced_leader
        if leader is None:
            # Tiered search criteria:
            # Tier 1: Boost >= 220%
            # Tier 2: Boost >= 200%
            # Tier 3: Boost >= 170%
            # Tier 4: Boost >= 150%
            tier_thresholds = [220.0, 200.0, 170.0, 150.0]

            def analyze_leader_mission_coverage(
                c: DokkanCard, m_batch: Any
            ) -> tuple[bool, bool, bool]:
                if not m_batch:
                    return False, False, False
                main_match = False
                extra_match = False
                personal_match = False
                req_categories = getattr(m_batch, "required_categories", [])
                for _req_cnt, req_cat in req_categories:
                    r_lower = req_cat.strip().lower()
                    if any(c_cat.strip().lower() == r_lower for c_cat in c.categories):
                        personal_match = True
                    cid = _get_category_id_by_name(req_cat, dokkandb=self.dokkandb)
                    if (
                        cid is not None
                        and cid in category_leaders_by_cat
                        and c.id in category_leaders_by_cat[cid]
                    ):
                        off = category_leaders_by_cat[cid][c.id]
                        if off.get("is_main_leader"):
                            main_match = True
                        if off.get("is_extra_leader"):
                            extra_match = True
                    if c.leader_spec:
                        for l_cid in c.leader_spec.main_category_ids:
                            if _resolve_category_name(l_cid, c, c).strip().lower() == r_lower:
                                main_match = True
                        for l_cid in c.leader_spec.extra_category_ids:
                            if _resolve_category_name(l_cid, c, c).strip().lower() == r_lower:
                                extra_match = True
                return main_match, extra_match, personal_match

            chosen_leader: DokkanCard | None = None
            chosen_score: float = 0.0

            # Gather all candidate leaders having valid spec and category
            leader_candidates: list[tuple[DokkanCard, float, list[DokkanCard]]] = []
            for c in unique_pool:
                if (
                    not c.leader_spec
                    or not c.leader_spec.main_category_ids
                    or c.leader_spec.base_boost_pct < 150.0
                    or not c.category_ids
                    or not bool(set(c.category_ids) & set(c.leader_spec.main_category_ids))
                ):
                    continue
                main_cats = set(c.leader_spec.main_category_ids)
                eligible = [
                    o
                    for o in unique_pool
                    if o.id != c.id
                    and o.category_ids
                    and bool(set(o.category_ids) & main_cats)
                    and o.is_covered_by_leader(c)[1] >= MIN_LEADER_BOOST_PCT
                ]
                # Verifica che nel box esistano almeno 5 sub-unità uniche compatibili con copertura >= MIN_LEADER_BOOST_PCT
                if len(eligible) < 5:
                    continue

                max_boost = float(c.leader_spec.base_boost_pct + c.leader_spec.extra_boost_pct)
                leader_candidates.append((c, max_boost, eligible))

            for tier_min in tier_thresholds:
                # Find candidates whose max_boost falls into this tier and hasn't been picked by a higher tier
                # Notice: Tier 1: >= 220; Tier 2: 200 <= boost < 220; Tier 3: 170 <= boost < 200; Tier 4: 150 <= boost < 170
                if tier_min == 220.0:
                    tier_cands = [item for item in leader_candidates if item[1] >= 220.0]
                elif tier_min == 200.0:
                    tier_cands = [item for item in leader_candidates if 200.0 <= item[1] < 220.0]
                elif tier_min == 170.0:
                    tier_cands = [item for item in leader_candidates if 170.0 <= item[1] < 200.0]
                else:
                    tier_cands = [item for item in leader_candidates if 150.0 <= item[1] < 170.0]

                if not tier_cands:
                    continue

                has_mission_reqs = bool(
                    mission_batch is not None
                    and getattr(mission_batch, "required_categories", None)
                )

                # Analyze tier-wide leader skill coverage for mission categories
                tier_cov_analysis: dict[int, tuple[bool, bool, bool]] = {}
                tier_has_lead_spec_match = False
                if has_mission_reqs:
                    for c, _, _ in tier_cands:
                        analysis = analyze_leader_mission_coverage(c, mission_batch)
                        tier_cov_analysis[c.id] = analysis
                        if analysis[0] or analysis[1]:
                            tier_has_lead_spec_match = True

                scored_tier_leaders: list[tuple[DokkanCard, float, int]] = []
                for c, max_boost, eligible in tier_cands:
                    boosted_200 = [o for o in eligible if o.is_covered_by_leader(c)[1] >= 200.0]
                    count_200 = len(boosted_200)

                    kit_power, _ = c.evaluate_kit_power()
                    s1_bonus = 15.0 if self.is_slot1_viable(c) else 0.0

                    type_bonus = 0.0
                    if boss_stage and boss_stage.phases:
                        num_p = len(boss_stage.phases)
                        weighted_sum = 0.0
                        total_weight = 0.0
                        for p_idx, p in enumerate(boss_stage.phases):
                            if getattr(p, "is_rainbow", False):
                                continue
                            weight = 2.0 if (p_idx == num_p - 1 and num_p > 1) else 1.0
                            is_multi = getattr(p, "is_multi_enemy", False) and bool(
                                getattr(p, "bosses", None)
                            )
                            if is_multi:
                                p_matchups = [
                                    self.check_type_matchup(c.element, getattr(b, "element", 0))
                                    for b in p.bosses
                                ]
                                p_matchup = sum(p_matchups) / len(p_matchups) if p_matchups else 0.0
                            else:
                                p_matchup = float(
                                    self.check_type_matchup(c.element, getattr(p, "element", 0))
                                )
                            weighted_sum += p_matchup * weight
                            total_weight += weight

                        if total_weight > 0:
                            avg_matchup = weighted_sum / total_weight
                            # Elemental type_bonus capped between -10.0 and +10.0 so it cannot override tier differences
                            type_bonus = max(-10.0, min(10.0, avg_matchup * 10.0))

                    boost_200_bonus = (30.0 if count_200 >= 5 else 0.0) + min(count_200, 300) * 0.1
                    priority_bonus = 0.0

                    # Mission synergy bonus & priority determination
                    mission_leader_bonus = 0.0
                    coverage_priority = 0

                    if has_mission_reqs:
                        main_m, extra_m, personal_m = tier_cov_analysis.get(
                            c.id, (False, False, False)
                        )
                        if tier_has_lead_spec_match:
                            if main_m:
                                coverage_priority = 2
                                mission_leader_bonus = 60.0
                            elif extra_m:
                                coverage_priority = 1
                                mission_leader_bonus = 30.0
                        else:
                            # Fallback on personal card categories when no card in tier has category in leader skill
                            if personal_m:
                                coverage_priority = 1
                                mission_leader_bonus = 30.0

                    l_score = (
                        max_boost * 0.2
                        + kit_power * 0.08
                        + s1_bonus
                        + type_bonus
                        + boost_200_bonus
                        + priority_bonus
                        + mission_leader_bonus
                        + min(len(eligible), 20) * 0.5
                    )
                    scored_tier_leaders.append((c, l_score, coverage_priority))

                # Within the tier, if mission_batch is active with required categories,
                # absolute precedence is given to leaders covering the mission category
                if has_mission_reqs:
                    # Sort primarily by coverage_priority (2 > 1 > 0), then by l_score descending
                    scored_tier_leaders.sort(key=lambda item: (item[2], item[1]), reverse=True)
                else:
                    scored_tier_leaders.sort(key=lambda item: item[1], reverse=True)

                chosen_leader = scored_tier_leaders[0][0]
                chosen_score = scored_tier_leaders[0][1]
                break

            if chosen_leader is None:
                raise ValueError(
                    f"No valid leader found meeting >= {MIN_LEADER_BOOST_PCT}% coverage requirement with >= 5 eligible sub-units."
                )

            leader = chosen_leader
            logs.append(f"Selected Leader: {leader.full_name} (Score: {chosen_score:.1f})")
        else:
            if leader.leader_spec is None and leader.leader_skill:
                from dokkan_eza_link_farmer.ai.syncer import parse_leader_spec

                leader.leader_spec = parse_leader_spec(leader.leader_skill)

            if (
                not leader.leader_spec
                or not leader.leader_spec.main_category_ids
                or leader.leader_spec.base_boost_pct < MIN_LEADER_BOOST_PCT
                or not leader.category_ids
                or not bool(set(leader.category_ids) & set(leader.leader_spec.main_category_ids))
            ):
                raise ValueError(
                    f"Forced leader {leader.full_name} has no valid category leader skill meeting >= {MIN_LEADER_BOOST_PCT}% coverage."
                )
            logs.append(f"Using Forced Leader: {leader.full_name}")

        # 2. Filter candidates under leader (strictly >= 170% and shared category)
        eligible_subs = [c for c in unique_pool if c.id != leader.id and c.category_ids]
        filtered = self.filter_by_leader_skill(eligible_subs, leader, min_pct=MIN_LEADER_BOOST_PCT)
        covered_cards = [c for c, _ in filtered]

        if len(covered_cards) < 5:
            raise ValueError(
                f"Leader {leader.full_name} cannot form a valid team: only {len(covered_cards)} units meet strict >= {MIN_LEADER_BOOST_PCT}% leader coverage and shared category requirement."
            )

        # 3. Two-Phase Survival & Team Selection
        team_cards: list[DokkanCard] = [leader]
        remaining_candidates = list(covered_cards)

        while len(team_cards) < 6 and remaining_candidates:
            slots_left = 6 - len(team_cards)
            current_s1_count = sum(1 for c in team_cards if self.is_slot1_viable(c))
            s1_deficit = max(0, MIN_SLOT1_REQUIRED - current_s1_count)

            candidate_subset = remaining_candidates

            # Mission partial category enforcement
            if mission_batch is not None:
                for req_count, cat_name in getattr(mission_batch, "required_categories", []):
                    if req_count < 6:
                        c_name_lower = cat_name.strip().lower()
                        current_cnt = sum(
                            1
                            for tc in team_cards
                            if any(c_cat.strip().lower() == c_name_lower for c_cat in tc.categories)
                        )
                        deficit = req_count - current_cnt
                        if deficit > 0 and slots_left <= deficit:
                            cat_cands = [
                                c
                                for c in candidate_subset
                                if any(
                                    c_cat.strip().lower() == c_name_lower for c_cat in c.categories
                                )
                            ]
                            if cat_cands:
                                candidate_subset = cat_cands
                                logs.append(
                                    f"Enforced slot for mission Category '{cat_name}' (Current: {current_cnt}/{req_count})"
                                )

                # Mission Rainbow enforcement (5 types)
                if getattr(mission_batch, "requires_rainbow", False):
                    curr_types = {tc.element % 10 for tc in team_cards}
                    missing_types = {0, 1, 2, 3, 4} - curr_types
                    if missing_types and slots_left <= len(missing_types):
                        rainbow_cands = [
                            c for c in candidate_subset if (c.element % 10) in missing_types
                        ]
                        if rainbow_cands:
                            candidate_subset = rainbow_cands
                            logs.append(
                                f"Enforced slot for Rainbow type ({len(missing_types)} missing types)"
                            )

            if slots_left <= s1_deficit:
                s1_pool = [c for c in candidate_subset if self.is_slot1_viable(c)]
                if s1_pool:
                    candidate_subset = s1_pool
                else:
                    logs.append(
                        f"Warning: Candidate pool lacks sufficient base slot 1 viable units (target: {MIN_SLOT1_REQUIRED})."
                    )

            scored_cands: list[tuple[DokkanCard, CandidateEvaluation]] = []
            for cand in candidate_subset:
                ev = self.evaluate_card(cand, leader, boss_stage, selected_team=team_cards)

                # Bonus points for fulfilling pending mission conditions
                if mission_batch is not None:
                    if getattr(mission_batch, "requires_rainbow", False):
                        curr_types = {tc.element % 10 for tc in team_cards}
                        if (cand.element % 10) not in curr_types:
                            ev.score += 15.0
                    for req_count, cat_name in getattr(mission_batch, "required_categories", []):
                        if req_count < 6:
                            c_name_lower = cat_name.strip().lower()
                            current_cnt = sum(
                                1
                                for tc in team_cards
                                if any(
                                    c_cat.strip().lower() == c_name_lower for c_cat in tc.categories
                                )
                            )
                            if current_cnt < req_count and any(
                                c_cat.strip().lower() == c_name_lower for c_cat in cand.categories
                            ):
                                ev.score += 20.0

                scored_cands.append((cand, ev))

            scored_cands.sort(key=lambda item: item[1].score, reverse=True)
            best_card, best_ev = scored_cands[0]
            team_cards.append(best_card)
            remaining_candidates.remove(best_card)
            logs.append(
                f"Added Slot {len(team_cards)}: {best_card.full_name} (Score: {best_ev.score:.1f}, S1: {best_ev.base_slot1_viable})"
            )

        base_slot1_count = sum(1 for c in team_cards if self.is_slot1_viable(c))
        if base_slot1_count < MIN_SLOT1_REQUIRED:
            logs.append(
                f"Warning: Final team has {base_slot1_count} base slot 1 viable units (required >= {MIN_SLOT1_REQUIRED})."
            )

        # 4. Mission verification and feedback logging
        if mission_batch is not None and hasattr(mission_batch, "matches_team"):
            passed, reasons = mission_batch.matches_team(team_cards)
            for r in reasons:
                logs.append(f"Mission Check: {r}")

        # 5. Top-5 Shortlist Generation strictly from covered candidates
        team_ids = {c.id for c in team_cards}
        shortlist_candidates = [c for c in covered_cards if c.id not in team_ids]
        shortlist_evals: list[CandidateEvaluation] = []
        for cand in shortlist_candidates:
            ev = self.evaluate_card(cand, leader, boss_stage, selected_team=team_cards)
            if ev.score > -90.0:
                shortlist_evals.append(ev)

        shortlist_evals.sort(key=lambda ev: ev.score, reverse=True)
        shortlist = shortlist_evals[:5]

        return ConstraintSolverResult(
            leader=leader,
            team_cards=team_cards,
            shortlist=shortlist,
            base_slot1_count=base_slot1_count,
            solver_logs=logs,
            mission_batch=mission_batch,
        )
