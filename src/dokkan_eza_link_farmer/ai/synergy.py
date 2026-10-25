"""Dokkan Battle Link and Rotation Synergy Engine.

Provides pure mathematical functions for link skill matching, Ki synergy scoring,
and rotation pairing optimization. All functions are pure, deterministic, and free of side effects.
"""

from __future__ import annotations

import copy
import itertools
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dokkan_eza_link_farmer.ai.models import DokkanCard

KI_LINKS = {
    "Prepared for Battle",
    "Over in a Flash",
    "Shocking Speed",
    "Fused Fighter",
    "Tournament of Power",
    "GT",
    "Fear and Faith",
    "Strongest Clan in Space",
    "Royal Lineage",
}

TOP_TIER_STAT_LINKS = {
    "Big Bad Bosses",
    "Fierce Battle",
    "Legendary Power",
    "Super Saiyan",
    "Warrior Gods",
    "Saiyan Roar",
    "Majin",
    "Power Bestowed by God",
}


@dataclass
class RotationPair:
    """A pair of cards locked together in main rotation."""

    slot1: DokkanCard
    slot2: DokkanCard
    shared_links: list[str]
    shared_ki_links: list[str]
    synergy_score: float

    def to_dict(self) -> dict[str, Any]:
        """Serializes RotationPair into a dictionary for JSON persistence."""
        return {
            "slot1": self.slot1.to_dict(),
            "slot2": self.slot2.to_dict(),
            "shared_links": list(self.shared_links),
            "shared_ki_links": list(self.shared_ki_links),
            "synergy_score": self.synergy_score,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | Any) -> RotationPair:
        if isinstance(data, RotationPair):
            return data
        if not isinstance(data, dict):
            raise TypeError(f"Expected dict for RotationPair.from_dict, got {type(data)}")
        from dokkan_eza_link_farmer.ai.models import DokkanCard

        slot1_raw = data["slot1"]
        slot2_raw = data["slot2"]
        slot1 = slot1_raw if isinstance(slot1_raw, DokkanCard) else DokkanCard.from_dict(slot1_raw)
        slot2 = slot2_raw if isinstance(slot2_raw, DokkanCard) else DokkanCard.from_dict(slot2_raw)

        return cls(
            slot1=slot1,
            slot2=slot2,
            shared_links=list(data.get("shared_links", [])),
            shared_ki_links=list(data.get("shared_ki_links", [])),
            synergy_score=float(data.get("synergy_score", 0.0)),
        )


def calculate_link_synergy(
    card_a: DokkanCard, card_b: DokkanCard
) -> tuple[float, list[str], list[str]]:
    """Calculates synergy score between two cards based on shared link skills.

    Returns: (score, all_shared_links, shared_ki_links).
    """
    if card_a is None or card_b is None or card_a.id == card_b.id:
        return 0.0, [], []

    # Same Name Link Rule: Cards sharing the exact same base name cannot link in base form
    name_a = (getattr(card_a, "name", "") or "").strip().lower()
    name_b = (getattr(card_b, "name", "") or "").strip().lower()
    if name_a and name_a == name_b:
        # If neither is transformed yet, links are inactive (score = 0)
        return 0.0, [], []

    links_a = set(card_a.links or [])
    links_b = set(card_b.links or [])
    shared = sorted(links_a.intersection(links_b))
    shared_ki = [lnk for lnk in shared if lnk in KI_LINKS]

    score = float(len(shared)) * 1.5
    score += float(len(shared_ki)) * 2.0

    for lnk in shared:
        if lnk in TOP_TIER_STAT_LINKS:
            score += 1.5
        if lnk == "Big Bad Bosses":
            score += 2.0

    # Bonus if at least one card in the pair is a verified Slot 1 defensive tank
    if card_a.is_slot1_tank or card_b.is_slot1_tank:
        score += 2.5

    return score, shared, shared_ki


def calculate_slot1_def_priority(card: DokkanCard, boss_stage: Any = None) -> float:
    """Evaluates defensive priority for Slot 1 anchor: Permanent Guard > Permanent DR > Taunt/Revive > Infinite DEF Stack."""
    from dokkan_eza_link_farmer.ai.solver import DokkanConstraintSolver

    priority = 0.0
    cancels_dodge = False
    is_long_event = False
    if boss_stage:
        phases = getattr(boss_stage, "phases", [])
        cancels_dodge = any(getattr(p, "cancels_dodge", False) for p in phases)
        is_long_event = len(phases) >= 3 or getattr(boss_stage, "is_multi_battle", False)

    has_guard = getattr(card, "has_guard", False)
    guard_limit = getattr(card, "guard_turns_limit", None)
    if getattr(card, "is_guard_permanent", False) and getattr(
        card, "is_guard_unconditional", False
    ):
        priority += 50.0
    elif has_guard:
        if is_long_event and guard_limit and guard_limit <= 6:
            priority += 5.0
        else:
            priority += 20.0

    perm_dr = getattr(card, "permanent_damage_reduction_percent", 0)
    if perm_dr > 0:
        priority += float(perm_dr) * 1.0

    dr_limit = getattr(card, "dr_turns_limit", None)
    dr_percent = getattr(card, "damage_reduction_percent", 0)
    if dr_limit and dr_limit <= 6 and is_long_event:
        priority += 2.0
    elif dr_limit and dr_limit <= 3:
        priority += 10.0
    elif dr_percent >= 40 and not perm_dr:
        priority += 15.0

    if getattr(card, "has_target_taunt", False):
        priority += 35.0
    if getattr(card, "has_revive", False):
        priority += 30.0

    if getattr(card, "has_stacking_def", False):
        priority += 10.0 if getattr(boss_stage, "is_multi_battle", False) else 20.0

    if not cancels_dodge:
        dodge = getattr(card, "dodge_chance_percent", 0)
        if dodge >= 70:
            priority += 15.0
        elif dodge >= 50:
            priority += 10.0

    if DokkanConstraintSolver.is_slot1_viable(card, boss_stage):
        priority += 25.0

    return priority


def calculate_slot1_anchor_weight(card: DokkanCard, boss_stage: Any = None) -> float:
    """Assigns rotation anchor fitness bonus: Heavily rewards god-tier permanent tanks in Slot 1."""
    from dokkan_eza_link_farmer.ai.solver import DokkanConstraintSolver

    bonus = 0.0
    if getattr(card, "is_guard_permanent", False) and getattr(
        card, "is_guard_unconditional", False
    ):
        bonus += 10.0
    if getattr(card, "permanent_damage_reduction_percent", 0) >= 40:
        bonus += 8.0
    if getattr(card, "has_target_taunt", False) or getattr(card, "has_revive", False):
        bonus += 6.0
    if DokkanConstraintSolver.is_slot1_viable(card, boss_stage):
        bonus += 6.0
    return bonus


def evaluate_rotation_pair(
    card_a: DokkanCard, card_b: DokkanCard, boss_stage: Any = None
) -> RotationPair:
    """Determines who should be in Slot 1 (tank/defensive anchor) and Slot 2 (damage/link partner)."""
    score, shared, shared_ki = calculate_link_synergy(card_a, card_b)

    a_def_priority = calculate_slot1_def_priority(card_a, boss_stage=boss_stage)
    b_def_priority = calculate_slot1_def_priority(card_b, boss_stage=boss_stage)

    kit_a, _ = card_a.evaluate_kit_power() if hasattr(card_a, "evaluate_kit_power") else (0.0, None)
    kit_b, _ = card_b.evaluate_kit_power() if hasattr(card_b, "evaluate_kit_power") else (0.0, None)

    if a_def_priority != b_def_priority:
        slot1, slot2 = (card_a, card_b) if a_def_priority > b_def_priority else (card_b, card_a)
    else:
        a_is_lr = bool(getattr(card_a, "is_lr", False))
        b_is_lr = bool(getattr(card_b, "is_lr", False))
        if a_is_lr != b_is_lr:
            slot1, slot2 = (card_a, card_b) if a_is_lr else (card_b, card_a)
        elif kit_a != kit_b:
            slot1, slot2 = (card_a, card_b) if kit_a > kit_b else (card_b, card_a)
        else:
            slot1, slot2 = (
                (card_a, card_b)
                if getattr(card_a, "id", 0) <= getattr(card_b, "id", 0)
                else (card_b, card_a)
            )

    return RotationPair(
        slot1=slot1,
        slot2=slot2,
        shared_links=shared,
        shared_ki_links=shared_ki,
        synergy_score=score,
    )


def calculate_leader_boost_coverage(card: DokkanCard, leader: DokkanCard) -> float:
    """Calculates leader skill boost percentage for a card, supporting category name fallback."""
    is_cov, boost, _ = card.is_covered_by_leader(leader)
    if (
        (not is_cov or boost < 170.0)
        and not card.category_ids
        and leader.leader_spec
        and leader.leader_spec.main_category_ids
        and any(c_name.lower() in leader.leader_skill.lower() for c_name in card.categories)
    ):
        boost = max(boost, float(leader.leader_spec.base_boost_pct))
    return boost


def optimize_rotations_for_team(
    cards: list[DokkanCard], boss_stage: Any = None
) -> tuple[RotationPair, RotationPair, list[DokkanCard]]:
    """Given 6 or 7 cards, finds the 2 optimal rotation pairs (Rotation A & Rotation B)

    that maximize overall team synergy, leaving the rest as Floaters (Slot 3).
    """
    if len(cards) < 6:
        raise ValueError(f"Need at least 6 cards to optimize rotations, got {len(cards)}")

    best_score = -float("inf")
    best_rot_a: RotationPair | None = None
    best_rot_b: RotationPair | None = None
    best_floaters: list[DokkanCard] = []

    n = len(cards)
    # Evaluate combinations of 4 card indices to form 2 rotation pairs
    for idxs in itertools.combinations(range(n), 4):
        i1, i2, i3, i4 = idxs
        pairings = [
            ((cards[i1], cards[i2]), (cards[i3], cards[i4])),
            ((cards[i1], cards[i3]), (cards[i2], cards[i4])),
            ((cards[i1], cards[i4]), (cards[i2], cards[i3])),
        ]
        for (p1_a, p1_b), (p2_a, p2_b) in pairings:
            rot1 = evaluate_rotation_pair(p1_a, p1_b, boss_stage=boss_stage)
            rot2 = evaluate_rotation_pair(p2_a, p2_b, boss_stage=boss_stage)
            total = (rot1.synergy_score + rot2.synergy_score) + (
                calculate_slot1_anchor_weight(rot1.slot1, boss_stage=boss_stage)
                + calculate_slot1_anchor_weight(rot2.slot1, boss_stage=boss_stage)
            )

            # Rotation consistency: Friend Leader should not displace a core unit if receiving lower boost
            leader_card = cards[0]
            rot_units = [rot1.slot1, rot1.slot2, rot2.slot1, rot2.slot2]
            friend_in_rot = next(
                (c for c in rot_units if getattr(c, "is_friend_leader", False)), None
            )
            if friend_in_rot is not None and leader_card.leader_spec:
                friend_boost = calculate_leader_boost_coverage(friend_in_rot, leader_card)
                non_friends_in_rot = [
                    c for c in rot_units if not getattr(c, "is_friend_leader", False)
                ]
                min_rot_boost = min(
                    (calculate_leader_boost_coverage(c, leader_card) for c in non_friends_in_rot),
                    default=200.0,
                )
                # Candidate floaters in this formation
                cand_floaters = [cards[i] for i in range(n) if i not in idxs]
                floaters_max_boost = max(
                    (calculate_leader_boost_coverage(c, leader_card) for c in cand_floaters),
                    default=0.0,
                )

                # If friend receives strictly lower boost than titular rotation units or titular floaters,
                # or lacks 200/220% boost while displaced titolari have >= 200%, penalize heavily so friend floats
                if (
                    friend_boost < min_rot_boost
                    or friend_boost < floaters_max_boost
                    or (friend_boost < 200.0 and floaters_max_boost >= 200.0)
                ):
                    diff = max(200.0 - friend_boost, floaters_max_boost - friend_boost, 30.0)
                    total -= diff * 2.0

            if total > best_score:
                best_score = total
                best_rot_a = rot1
                best_rot_b = rot2
                used_indices = {i1, i2, i3, i4}
                best_floaters = [cards[i] for i in range(n) if i not in used_indices]

    if best_rot_a is None or best_rot_b is None:
        best_rot_a = evaluate_rotation_pair(cards[0], cards[1], boss_stage=boss_stage)
        best_rot_b = evaluate_rotation_pair(cards[2], cards[3], boss_stage=boss_stage)
        best_floaters = cards[4:]

    return best_rot_a, best_rot_b, best_floaters


def select_best_friend_leader(
    cards: list[DokkanCard], candidate_pool: list[DokkanCard]
) -> DokkanCard:
    """Selects the optimal complementary Friend Leader from candidate_pool for the team."""
    if not cards:
        raise ValueError("Cannot select friend leader for an empty team")

    leader = cards[0]
    if not candidate_pool:
        lead = copy.copy(leader)
        lead.is_friend_leader = True
        return lead

    # 1. Top priority: exact same card (card.id == leader.id) if present in pool
    for cand in candidate_pool:
        if cand.id == leader.id:
            friend = copy.copy(cand)
            friend.is_friend_leader = True
            return friend

    # 2. Alternative: candidates with compatible leader skill covering leader's main_category_ids,
    # verifying they cover at least 5 team members with boost >= 170.0.
    leader_main_cats = set()
    if leader.leader_spec and leader.leader_spec.main_category_ids:
        leader_main_cats = set(leader.leader_spec.main_category_ids)

    best_cand: DokkanCard | None = None
    best_score = -1000.0

    for cand in candidate_pool:
        cand_main_cats = set()
        if cand.leader_spec and cand.leader_spec.main_category_ids:
            cand_main_cats = set(cand.leader_spec.main_category_ids)

        # Must share/cover the leader's primary categories if specified
        if leader_main_cats and not (leader_main_cats & cand_main_cats):
            continue

        score = 0.0
        covered_count = 0
        for c in cards:
            is_cov, boost, _ = c.is_covered_by_leader(cand)
            # Fallback: if category_ids is not populated on card, check if card.categories matches cand's main categories
            if (
                (not is_cov or boost < 170.0)
                and not c.category_ids
                and cand_main_cats
                and any(c_name.lower() in cand.leader_skill.lower() for c_name in c.categories)
            ):
                is_cov = True
                boost = max(boost, 170.0)
            if is_cov and boost >= 170.0:
                covered_count += 1
                score += boost * 0.1

        # Must cover at least 5 team members with boost >= 170.0
        if covered_count < 5:
            continue

        kit, _ = cand.evaluate_kit_power() if hasattr(cand, "evaluate_kit_power") else (0.0, None)
        score += kit * 0.2
        if getattr(cand, "is_slot1_tank", False):
            score += 15.0
        if getattr(cand, "permanent_damage_reduction_percent", 0) >= 40:
            score += 20.0
        if getattr(cand, "is_guard_permanent", False) and getattr(
            cand, "is_guard_unconditional", False
        ):
            score += 25.0

        if score > best_score:
            best_score = score
            best_cand = cand

    # Fallback: if no identical or fully complementary friend exists in candidate_pool,
    # fallback to an exact copy of the team leader.
    friend = copy.copy(leader) if best_cand is None else copy.copy(best_cand)

    friend.is_friend_leader = True
    return friend


def find_best_partners_for_card(
    card: DokkanCard, candidate_pool: list[DokkanCard], top_k: int = 5
) -> list[tuple[DokkanCard, float, list[str]]]:
    """Finds the highest-synergy linking partners for a specific card."""
    scored: list[tuple[DokkanCard, float, list[str]]] = []
    for cand in candidate_pool:
        if cand.id == card.id:
            continue
        score, shared, _ = calculate_link_synergy(card, cand)
        if shared:
            scored.append((cand, score, shared))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


def rate_leader_for_batch(card: DokkanCard, batch: Any) -> float:
    """Rates how effective a card is as a leader for the required batch missions.

    Scores high if it leads the required categories with high percentages (+170%, +200%).
    """
    leader_text = card.leader_skill.lower()
    if not leader_text:
        return 0.0

    score = 0.0
    if "200%" in leader_text:
        score += 12.0
    elif "170%" in leader_text:
        score += 9.0
    elif "150%" in leader_text:
        score += 6.0
    elif "130%" in leader_text:
        score += 4.0
    elif "120%" in leader_text:
        score += 3.0

    req_cats = getattr(batch, "required_categories", [])
    if req_cats:
        matched_cats = 0
        for _, cat_name in req_cats:
            if cat_name.lower() in leader_text:
                matched_cats += 1
        if matched_cats > 0:
            score += matched_cats * 8.0
        else:
            score *= 0.1

    if getattr(batch, "requires_rainbow", False) and any(
        k in leader_text
        for k in ("all types", "super type", "extreme type", "super class", "extreme class")
    ):
        score += 6.0

    kit_power, _ = card.evaluate_kit_power() if hasattr(card, "evaluate_kit_power") else (0.0, None)
    score += kit_power * 0.1

    return score


def rate_sub_unit(card: DokkanCard, leader: DokkanCard) -> float:
    """Rates an individual sub unit according to the 3-level Dokkan Battle priority hierarchy."""
    is_covered, lead_pct, _ = card.is_covered_by_leader(leader)
    if not is_covered:
        return -100.0

    if lead_pct >= 200.0:
        lead_score = 30.0
    elif lead_pct >= 170.0:
        lead_score = 22.0
    elif lead_pct >= 150.0:
        lead_score = 15.0
    elif lead_pct >= 130.0:
        lead_score = 10.0
    else:
        lead_score = 5.0

    kit_score, _ = card.evaluate_kit_power() if hasattr(card, "evaluate_kit_power") else (0.0, None)

    name_card = (getattr(card, "name", "") or "").strip().lower()
    name_lead = (getattr(leader, "name", "") or "").strip().lower()
    if name_card and name_card == name_lead:
        link_score = 0.0
    else:
        links_card = set(card.links or [])
        links_lead = set(leader.links or [])
        shared_cnt = len(links_card.intersection(links_lead))
        shared_ki_cnt = len([lnk for lnk in links_card if lnk in links_lead and lnk in KI_LINKS])
        top_stat_cnt = len(
            [lnk for lnk in links_card if lnk in links_lead and lnk in TOP_TIER_STAT_LINKS]
        )
        link_score = (shared_cnt * 1.5) + (shared_ki_cnt * 2.0) + (top_stat_cnt * 1.5)

    return lead_score + kit_score + link_score


def check_type_matchup(attacker_element: int, defender_element: int) -> int:
    """Determines elemental matchup:

    Returns +1 for Type Advantage, -1 for Type Disadvantage, 0 for Neutral.
    """
    from dokkan_eza_link_farmer.ai.solver import DokkanConstraintSolver

    return DokkanConstraintSolver.check_type_matchup(attacker_element, defender_element)


__all__ = [
    "KI_LINKS",
    "TOP_TIER_STAT_LINKS",
    "RotationPair",
    "calculate_link_synergy",
    "calculate_slot1_def_priority",
    "calculate_slot1_anchor_weight",
    "evaluate_rotation_pair",
    "optimize_rotations_for_team",
    "select_best_friend_leader",
    "find_best_partners_for_card",
    "rate_leader_for_batch",
    "rate_sub_unit",
    "check_type_matchup",
    "calculate_leader_boost_coverage",
]
