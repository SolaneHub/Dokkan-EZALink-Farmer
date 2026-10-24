from __future__ import annotations

import copy
import itertools
import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any

import requests

from dokkan_eza_link_farmer.ai.client import DokkanAIClient
from dokkan_eza_link_farmer.ai.models import (
    BossStage,
    DokkanCard,
    RotationPair,
    TeamRecommendation,
)
from dokkan_eza_link_farmer.ai.solver import (
    ELEMENT_ADVANTAGE,
    ELEMENT_DISADVANTAGE,
    CandidateEvaluation,
    ConstraintSolverResult,
    DokkanConstraintSolver,
)
from dokkan_eza_link_farmer.integrations.dokkandb_client import DokkanDBClient

logger = logging.getLogger(__name__)

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
class FailureReport:
    """Combat failure context passed from telemetry after defeat."""

    defeat_turn: int = 1
    phase_index: int = 1
    boss_element: int = 0
    boss_hp_percent: float = 100.0
    culprit_card_id: int | None = None
    classification: str = ""
    reason: str = ""


class TeamBuilder:
    """
    Combines high-speed algorithmic constraint solving with local Ollama AI
    (DeepSeek-R1 / Qwen) tactical reasoning for Red Zone & Blue Zone challenge stages.
    """

    def __init__(
        self,
        dokkandb: DokkanDBClient | None = None,
        ai_client: DokkanAIClient | None = None,
        solver: DokkanConstraintSolver | None = None,
        settings_path: str = "config/settings.yaml",
    ):
        self.dokkandb = dokkandb or DokkanDBClient()
        self.ai_client = ai_client
        self.solver = solver or DokkanConstraintSolver(dokkandb=self.dokkandb)
        self.settings_path = settings_path

    # =========================================================================
    # LINK SYNERGY & ROTATION PAIRING
    # =========================================================================

    @staticmethod
    def calculate_link_synergy(
        card_a: DokkanCard, card_b: DokkanCard
    ) -> tuple[float, list[str], list[str]]:
        """
        Calculates synergy score between two cards based on shared link skills.
        Returns: (score, all_shared_links, shared_ki_links).
        """
        if card_a.id == card_b.id:
            return 0.0, [], []

        # Same Name Link Rule: Cards sharing the exact same base name cannot link in base form
        if card_a.name.strip().lower() == card_b.name.strip().lower():
            # If neither is transformed yet, links are inactive (score = 0)
            return 0.0, [], []

        links_a = set(card_a.links)
        links_b = set(card_b.links)
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

    @staticmethod
    def calculate_slot1_def_priority(card: DokkanCard, boss_stage: Any = None) -> float:
        """Evaluates defensive priority for Slot 1 anchor: Permanent Guard > Permanent DR > Taunt/Revive > Infinite DEF Stack."""
        priority = 0.0
        cancels_dodge = False
        is_long_event = False
        if boss_stage:
            phases = getattr(boss_stage, "phases", [])
            cancels_dodge = any(getattr(p, "cancels_dodge", False) for p in phases)
            is_long_event = len(phases) >= 3 or getattr(boss_stage, "is_multi_battle", False)

        if getattr(card, "is_guard_permanent", False) and getattr(
            card, "is_guard_unconditional", False
        ):
            priority += 50.0
        elif card.has_guard:
            if is_long_event and card.guard_turns_limit and card.guard_turns_limit <= 6:
                priority += 5.0
            else:
                priority += 20.0

        perm_dr = getattr(card, "permanent_damage_reduction_percent", 0)
        if perm_dr > 0:
            priority += float(perm_dr) * 1.0

        dr_limit = getattr(card, "dr_turns_limit", None)
        if dr_limit and dr_limit <= 6 and is_long_event:
            priority += 2.0
        elif dr_limit and dr_limit <= 3:
            priority += 10.0
        elif card.damage_reduction_percent >= 40 and not perm_dr:
            priority += 15.0

        if getattr(card, "has_target_taunt", False):
            priority += 35.0
        if getattr(card, "has_revive", False):
            priority += 30.0

        if card.has_stacking_def:
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

    @classmethod
    def calculate_slot1_anchor_weight(cls, card: DokkanCard, boss_stage: Any = None) -> float:
        """Assigns rotation anchor fitness bonus: Heavily rewards god-tier permanent tanks in Slot 1."""
        bonus = 0.0
        if getattr(card, "is_guard_permanent", False) and getattr(
            card, "is_guard_unconditional", False
        ):
            bonus += 10.0
        if getattr(card, "permanent_damage_reduction_percent", 0) >= 40:
            bonus += 8.0
        if card.has_target_taunt or card.has_revive:
            bonus += 6.0
        if DokkanConstraintSolver.is_slot1_viable(card, boss_stage):
            bonus += 6.0
        return bonus

    def evaluate_rotation_pair(
        self, card_a: DokkanCard, card_b: DokkanCard, boss_stage: Any = None
    ) -> RotationPair:
        """Determines who should be in Slot 1 (tank/defensive anchor) and Slot 2 (damage/link partner)."""
        score, shared, shared_ki = self.calculate_link_synergy(card_a, card_b)

        a_def_priority = self.calculate_slot1_def_priority(card_a, boss_stage=boss_stage)
        b_def_priority = self.calculate_slot1_def_priority(card_b, boss_stage=boss_stage)

        kit_a, _ = card_a.evaluate_kit_power()
        kit_b, _ = card_b.evaluate_kit_power()

        if a_def_priority > b_def_priority:
            slot1, slot2 = card_a, card_b
        elif b_def_priority > a_def_priority:
            slot1, slot2 = card_b, card_a
        else:
            slot1, slot2 = (
                (card_a, card_b) if (card_a.is_lr or kit_a >= kit_b) else (card_b, card_a)
            )

        return RotationPair(
            slot1=slot1,
            slot2=slot2,
            shared_links=shared,
            shared_ki_links=shared_ki,
            synergy_score=score,
        )

    def optimize_rotations_for_team(
        self, cards: list[DokkanCard], boss_stage: Any = None
    ) -> tuple[RotationPair, RotationPair, list[DokkanCard]]:
        """
        Given 6 or 7 cards, finds the 2 optimal rotation pairs (Rotation A & Rotation B)
        that maximize overall team synergy, leaving the rest as Floaters (Slot 3).
        """
        if len(cards) < 6:
            raise ValueError(f"Need at least 6 cards to optimize rotations, got {len(cards)}")

        best_score = -1.0
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
                rot1 = self.evaluate_rotation_pair(p1_a, p1_b, boss_stage=boss_stage)
                rot2 = self.evaluate_rotation_pair(p2_a, p2_b, boss_stage=boss_stage)
                total = (rot1.synergy_score + rot2.synergy_score) + (
                    self.calculate_slot1_anchor_weight(rot1.slot1, boss_stage=boss_stage)
                    + self.calculate_slot1_anchor_weight(rot2.slot1, boss_stage=boss_stage)
                )

                # Rotation consistency: Friend Leader should not displace a core unit if receiving lower boost
                leader_card = cards[0]
                rot_units = [rot1.slot1, rot1.slot2, rot2.slot1, rot2.slot2]
                friend_in_rot = next(
                    (c for c in rot_units if getattr(c, "is_friend_leader", False)), None
                )
                if friend_in_rot is not None and leader_card.leader_spec:

                    def _get_boost(card: DokkanCard, lead: DokkanCard = leader_card) -> float:
                        is_cov, boost, _ = card.is_covered_by_leader(lead)
                        if (
                            (not is_cov or boost < 170.0)
                            and not card.category_ids
                            and lead.leader_spec
                            and lead.leader_spec.main_category_ids
                            and any(
                                c_name.lower() in lead.leader_skill.lower()
                                for c_name in card.categories
                            )
                        ):
                            boost = max(boost, float(lead.leader_spec.base_boost_pct))
                        return boost

                    friend_boost = _get_boost(friend_in_rot)
                    non_friends_in_rot = [
                        c for c in rot_units if not getattr(c, "is_friend_leader", False)
                    ]
                    min_rot_boost = min(
                        (_get_boost(c) for c in non_friends_in_rot),
                        default=200.0,
                    )
                    # Candidate floaters in this formation
                    cand_floaters = [cards[i] for i in range(n) if i not in idxs]
                    floaters_max_boost = max((_get_boost(c) for c in cand_floaters), default=0.0)

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
            best_rot_a = self.evaluate_rotation_pair(cards[0], cards[1], boss_stage=boss_stage)
            best_rot_b = self.evaluate_rotation_pair(cards[2], cards[3], boss_stage=boss_stage)
            best_floaters = cards[4:]

        return best_rot_a, best_rot_b, best_floaters

    def select_best_friend_leader(
        self, cards: list[DokkanCard], candidate_pool: list[DokkanCard]
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

            kit, _ = cand.evaluate_kit_power()
            score += kit * 0.2
            if cand.is_slot1_tank:
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
        self, card: DokkanCard, candidate_pool: list[DokkanCard], top_k: int = 5
    ) -> list[tuple[DokkanCard, float, list[str]]]:
        """Finds the highest-synergy linking partners for a specific card."""
        scored: list[tuple[DokkanCard, float, list[str]]] = []
        for cand in candidate_pool:
            if cand.id == card.id:
                continue
            score, shared, _ = self.calculate_link_synergy(card, cand)
            if shared:
                scored.append((cand, score, shared))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    @staticmethod
    def format_card_for_strategy(card: DokkanCard) -> str:
        """Formats card name and key kit mechanics for tactical strategy analysis."""
        tags = []
        if card.has_guard:
            tags.append("Guardia garantita")
        dr_pct = getattr(card, "damage_reduction_percent", 0)
        if dr_pct > 0:
            tags.append(f"Riduzione danno {dr_pct}%")
        elif getattr(card, "has_damage_reduction", False):
            tags.append("Riduzione danno")
        if getattr(card, "has_stacking_def", False):
            tags.append("Stacking DEF")
        if getattr(card, "has_target_taunt", False):
            tags.append("Taunt/Bersaglio")
        if getattr(card, "has_dodge", False):
            tags.append("Schivata")
        if getattr(card, "has_active_skill", False):
            tags.append("Active Skill")
        if getattr(card, "has_standby", False):
            tags.append("Standby")
        if getattr(card, "has_revive", False):
            tags.append("Revive")
        if getattr(card, "has_support", False):
            tags.append("Supporto alleati")
        if getattr(card, "has_orb_changing", False):
            tags.append("Cambia-orbi")

        kit_desc = f" [Kit: {', '.join(tags)}]" if tags else ""
        return f"{card.full_name}{kit_desc}"

    def build_team_plan(
        self,
        cards: list[DokkanCard],
        boss_target: str | None = None,
        language: str = "it",
        generate_tactics: bool = True,
        friend_leader: DokkanCard | None = None,
        candidate_pool: list[DokkanCard] | None = None,
        boss_stage: Any = None,
    ) -> TeamRecommendation:
        """
        Builds a full team recommendation following the 3-level priority hierarchy:
        1. Leader skill category coverage
        2. Card effects & kit mechanics
        3. Link skill rotation synergy
        """
        if len(cards) < 6:
            raise ValueError(f"Need 6 cards for team formation, got {len(cards)}")

        leader = cards[0]
        if friend_leader is not None:
            friend = copy.copy(friend_leader)
            friend.is_friend_leader = True
        elif candidate_pool:
            friend = self.select_best_friend_leader(cards, candidate_pool)
        elif len(cards) >= 7:
            friend = copy.copy(cards[6])
            friend.is_friend_leader = True
        else:
            friend = copy.copy(leader)
            friend.is_friend_leader = True

        # Optimize rotations for the complete 7-unit battle team (Leader + 5 Subs + Friend Leader)
        combat_team = list(cards[:6]) + [friend]
        rot_a, rot_b, floaters = self.optimize_rotations_for_team(
            combat_team, boss_stage=boss_stage
        )

        def _label_card(c: DokkanCard) -> str:
            badge = ""
            if c is friend or getattr(c, "is_friend_leader", False):
                badge = " [Friend Leader]"
            elif c is leader:
                badge = " [Leader]"
            return f"{self.format_card_for_strategy(c)}{badge}"

        # Generate structured summary highlighting kit mechanics and links (7 units across rotations & floaters)
        summary_lines = [
            f"- Leader Skill attiva: {leader.full_name} ({leader.leader_skill})",
            f"- Rotazione A: Slot 1 [{_label_card(rot_a.slot1)}] + Slot 2 [{_label_card(rot_a.slot2)}] (Link: {', '.join(rot_a.shared_links)})",
            f"- Rotazione B: Slot 1 [{_label_card(rot_b.slot1)}] + Slot 2 [{_label_card(rot_b.slot2)}] (Link: {', '.join(rot_b.shared_links)})",
            f"- Floaters (Slot 3): {', '.join(_label_card(f) for f in floaters)}",
        ]
        summary_text = "\n".join(summary_lines)

        tactical_guide = ""
        ai_reasoning: str | None = None

        if generate_tactics and self.ai_client and self.ai_client.is_available():
            try:
                tactical_guide, ai_reasoning = self.ai_client.analyze_team_strategy(
                    team_summary=summary_text,
                    boss_info=boss_target,
                    language=language,
                )
            except Exception as e:
                logger.warning(f"AI strategy generation skipped due to error: {e}")

        if not tactical_guide:

            def _name_with_badge(c: DokkanCard) -> str:
                badge = ""
                if c is friend or getattr(c, "is_friend_leader", False):
                    badge = " [Friend Leader]"
                elif c is leader:
                    badge = " [Leader]"
                return f"{c.name}{badge}"

            # Algorithmic fallback guide adhering to the clean bulleted structure
            tactical_guide = (
                f"### 🛡️ Piano Tattico Deterministico - Rotazioni\n"
                f"- **Rotazione A**: Mantieni **{_name_with_badge(rot_a.slot1)}** in Slot 1 come difensore primario. **{_name_with_badge(rot_a.slot2)}** in Slot 2 attiva {len(rot_a.shared_links)} link e massimizza i danni.\n"
                f"- **Rotazione B**: **{_name_with_badge(rot_b.slot1)}** in Slot 1 assorbe i colpi diretti. **{_name_with_badge(rot_b.slot2)}** in Slot 2 guida la fase offensiva.\n"
                f"- **Floaters (Slot 3)**: Fai ruotare **{', '.join(_name_with_badge(f) for f in floaters)}** in Slot 3 per Ki support, gestione orbi e rotazione difensiva.\n\n"
                f"### 💊 Gestione Oggetti di Supporto\n"
                f"- **Whis**: Attivalo nei turni ad alto rischio o contro la Super Attack nemica per ridurre il danno del 40% per 2 turni.\n"
                f"- **Ghost Usher**: Usalo se il floater in Slot 3 subisce troppi attacchi o per saltare un turno critico del boss.\n"
                f"- **Princess Snake**: Usalo per recuperare il 55% di HP e ottenere il 30% di riduzione danno nei turni di emergenza."
            )

        items = ["Whis", "Ghost Usher", "Princess Snake"]

        return TeamRecommendation(
            leader=leader,
            friend_leader=friend,
            rotation_a=rot_a,
            rotation_b=rot_b,
            floaters=floaters,
            all_cards=cards[:6],
            tactical_analysis=tactical_guide,
            recommended_items=items,
            ai_reasoning=ai_reasoning,
            boss_stage=boss_stage,
        )

    # =========================================================================
    # BATCH & MISSION TEAM BUILDING
    # =========================================================================

    @staticmethod
    def rate_leader_for_batch(card: DokkanCard, batch: Any) -> float:
        """
        Rates how effective a card is as a leader for the required batch missions.
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

        kit_power, _ = card.evaluate_kit_power()
        score += kit_power * 0.1

        return score

    @staticmethod
    def rate_sub_unit(card: DokkanCard, leader: DokkanCard) -> float:
        """
        Rates an individual sub unit according to the 3-level Dokkan Battle priority hierarchy.
        """
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

        kit_score, _ = card.evaluate_kit_power()

        shared_cnt = len(set(card.links).intersection(set(leader.links)))
        shared_ki_cnt = len([lnk for lnk in card.links if lnk in leader.links and lnk in KI_LINKS])
        top_stat_cnt = len(
            [lnk for lnk in card.links if lnk in leader.links and lnk in TOP_TIER_STAT_LINKS]
        )
        link_score = (shared_cnt * 1.5) + (shared_ki_cnt * 2.0) + (top_stat_cnt * 1.5)

        return lead_score + kit_score + link_score

    def build_best_team_for_batch(
        self,
        candidate_pool: list[DokkanCard],
        batch: Any,
        attempt: int = 1,
        boss_target: str | None = None,
        language: str = "it",
    ) -> TeamRecommendation:
        """
        Builds the optimal team for a mission batch, adapting and permuting team composition
        across retry attempts.
        """
        from dokkan_eza_link_farmer.ai.mission_solver import MissionBundler

        eligible = MissionBundler.filter_cards_for_batch(batch, candidate_pool)
        if len(eligible) < 6:
            eligible = candidate_pool[:]
        if len(eligible) < 6:
            raise ValueError(f"Need at least 6 cards in pool, only {len(eligible)} found.")

        leaders = sorted(
            eligible,
            key=lambda c: self.rate_leader_for_batch(c, batch),
            reverse=True,
        )

        leader_idx = (attempt - 1) % min(len(leaders), 3)
        chosen_leader = leaders[leader_idx]

        remaining = [c for c in eligible if c.id != chosen_leader.id]
        remaining_sorted = sorted(
            remaining,
            key=lambda c: self.rate_sub_unit(c, chosen_leader),
            reverse=True,
        )

        if attempt > 1 and len(remaining_sorted) > 5:
            shift = (attempt - 1) % (len(remaining_sorted) - 4)
            top_subs = remaining_sorted[shift : shift + 5]
        else:
            top_subs = remaining_sorted[:5]

        chosen_team = [chosen_leader] + top_subs
        if len(chosen_team) < 6:
            chosen_team = eligible[:6]

        return self.build_team_plan(chosen_team, boss_target=boss_target, language=language)

    # =========================================================================
    # CONSTRAINT SOLVER DELEGATION & ADVISOR HELPERS
    # =========================================================================

    @staticmethod
    def check_type_matchup(attacker_element: int, defender_element: int) -> int:
        """
        Determines elemental matchup:
        Returns +1 for Type Advantage, -1 for Type Disadvantage, 0 for Neutral.
        """
        return DokkanConstraintSolver.check_type_matchup(attacker_element, defender_element)

    def evaluate_card_against_boss(
        self,
        card: DokkanCard,
        leader: DokkanCard,
        boss_stage: BossStage | None = None,
        selected_team: list[DokkanCard] | None = None,
    ) -> CandidateEvaluation:
        """
        Evaluates a candidate card against a leader and target boss stage using DokkanConstraintSolver.
        Maintains backward compatibility with legacy test assertions.
        """
        ev = self.solver.evaluate_card(
            card, leader, boss_stage=boss_stage, selected_team=selected_team
        )
        # Determine exact base form slot 1 viability
        base_s1 = (
            bool(card.base_form.passive_tags.slot1_viable)
            if (card.base_form and card.base_form.passive_tags)
            else bool(card.is_slot1_tank)
        )
        ev.base_slot1_viable = base_s1
        if not base_s1:
            ev.counter_points = [
                cp
                for cp in ev.counter_points
                if "Base Form is Slot 1 viable" not in cp
                and "Slot 1 viable (guaranteed survival" not in cp
            ]

        # Ensure backward-compatible counter_point strings for legacy tests
        if ev.lead_boost_pct >= 200.0:
            if "Full 200% Leader Skill coverage" not in ev.counter_points:
                ev.counter_points.append("Full 200% Leader Skill coverage")
        elif ev.lead_boost_pct >= 150.0:
            lead_tag = f"{int(ev.lead_boost_pct)}% Leader Skill coverage"
            if lead_tag not in ev.counter_points:
                ev.counter_points.append(lead_tag)

        return ev

    def get_top_candidates(
        self,
        candidate_pool: list[DokkanCard],
        leader: DokkanCard,
        boss_stage: BossStage | None = None,
        top_k: int = 5,
        exclude_ids: set[int] | None = None,
    ) -> list[CandidateEvaluation]:
        """
        Ranks all eligible sub units from candidate_pool under leader, returning the Top-K candidates.
        """
        return self.solver.get_shortlist(
            candidate_pool=candidate_pool,
            leader=leader,
            boss_stage=boss_stage,
            exclude_ids=exclude_ids,
            top_k=top_k,
        )

    def is_ai_advisor_enabled(self) -> bool:
        """Checks whether the Ollama AI Advisor is enabled in ai_client config or settings.yaml."""
        if (
            self.ai_client
            and hasattr(self.ai_client, "config")
            and self.ai_client.config is not None
        ):
            return bool(getattr(self.ai_client.config, "enabled", False))

        if os.path.exists(self.settings_path):
            try:
                import yaml

                with open(self.settings_path, encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                ai_section = data.get("ai", {})
                if isinstance(ai_section, dict):
                    return bool(ai_section.get("enabled", False))
            except Exception as e:
                logger.debug(f"Could not read settings from {self.settings_path}: {e}")
        return False

    @staticmethod
    def build_advisor_payload(
        boss_stage: BossStage,
        current_team: list[DokkanCard],
        top_candidates: list[CandidateEvaluation],
        failure_report: FailureReport | None = None,
        mission_batch: Any | None = None,
    ) -> dict[str, Any]:
        """
        Constructs the compact JSON payload sent to Ollama AI Advisor:
        - Target BossStage details and phase gimmicks
        - Optional FailureReport from telemetry
        - Optional active mission constraints
        - Current 5 team members with roles
        - Top 5 candidates with full passive and Super Attack texts
        """
        phases_payload = [
            {
                "phase_index": p.phase_index,
                "element": p.element,
                "element_name": p.element_name,
                "cancels_dodge": p.cancels_dodge,
                "has_aoe": p.has_aoe,
                "locks_slots": p.locks_slots,
                "enemy_count": getattr(p, "enemy_count", 1),
                "is_multi_enemy": getattr(p, "is_multi_enemy", False),
                "is_rainbow": getattr(p, "is_rainbow", False),
                **(
                    {
                        "enemies": [
                            {
                                "name": b.name,
                                "element": b.type_name,
                                "hp": b.hp,
                                "atk": b.atk,
                            }
                            for b in getattr(p, "bosses", [])
                        ]
                    }
                    if getattr(p, "is_multi_enemy", False)
                    else {}
                ),
            }
            for p in boss_stage.phases
        ]

        failure_payload = None
        if failure_report is not None:
            failure_payload = {
                "defeat_turn": failure_report.defeat_turn,
                "phase_index": failure_report.phase_index,
                "boss_element": failure_report.boss_element,
                "boss_hp_percent": failure_report.boss_hp_percent,
                "culprit_card_id": failure_report.culprit_card_id,
                "classification": failure_report.classification,
                "reason": failure_report.reason,
            }

        mission_payload = None
        if mission_batch is not None:
            mission_payload = {
                "summary": getattr(mission_batch, "summary", ""),
                "required_categories": [
                    {"count": count, "category": cat}
                    for count, cat in getattr(mission_batch, "required_categories", [])
                ],
                "requires_rainbow": bool(getattr(mission_batch, "requires_rainbow", False)),
                "requires_all_super": bool(getattr(mission_batch, "requires_all_super", False)),
                "requires_all_extreme": bool(getattr(mission_batch, "requires_all_extreme", False)),
                "requires_no_items": bool(getattr(mission_batch, "requires_no_items", False)),
                "max_turns": getattr(mission_batch, "max_turns", None),
            }

        team_payload = [
            {
                "card_id": c.id,
                "name": c.full_name,
                "element": c.element_name,
                "role": (
                    "Slot 1 Tank"
                    if (
                        c.is_slot1_tank
                        or (
                            c.base_form
                            and c.base_form.passive_tags
                            and c.base_form.passive_tags.slot1_viable
                        )
                    )
                    else "Damage/Support"
                ),
            }
            for c in current_team
        ]

        candidates_payload: list[dict[str, Any]] = []
        for i, ev in enumerate(top_candidates[:5]):
            card = ev.card
            candidates_payload.append(
                {
                    "rank": i + 1,
                    "card_id": card.id,
                    "name": card.full_name,
                    "element": card.element_name,
                    "leader_coverage_pct": ev.lead_boost_pct,
                    "base_slot1_viable": ev.base_slot1_viable,
                    "solver_score": ev.score,
                    "passive_skill": card.passive_skill or "",
                    "super_attack": card.super_attack or "",
                    "counter_points": ev.counter_points,
                    "penalty_points": ev.penalty_points,
                }
            )

        payload: dict[str, Any] = {
            "boss_stage": {
                "event_name": boss_stage.event_name,
                "stage_name": boss_stage.stage_name,
                "difficulty": boss_stage.difficulty,
                "phases": phases_payload,
            },
            "failure_report": failure_payload,
            "current_team": team_payload,
            "top_5_candidates": candidates_payload,
        }
        if mission_payload is not None:
            payload["mission_batch"] = mission_payload

        return payload

    # =========================================================================
    # STEP 1 & 2: BEST TEAM SELECTION & LOCAL OLLAMA AI ADVISOR
    # =========================================================================

    def select_best_team_for_boss(
        self,
        candidate_pool: list[DokkanCard],
        boss_stage: BossStage | None = None,
        forced_leader: DokkanCard | None = None,
        language: str = "it",
        failure_report: FailureReport | None = None,
        ai_client: DokkanAIClient | None = None,
        use_ai_advisor: bool | None = None,
        generate_tactics: bool = True,
        mission_batch: Any | None = None,
    ) -> tuple[TeamRecommendation, list[CandidateEvaluation]]:
        """
        Synthesizes the optimal 6-card team for a BossStage:
        1. Employs DokkanConstraintSolver to produce optimal 6 cards and Top-5 runner-up shortlist
           satisfying boss gimmicks and optional mission_batch constraints.
        2. If Ollama AI Advisor is enabled and boss_stage is provided:
           - Constructs compact JSON payload with stage, failure report, 5 current team members,
             and top 5 candidates.
           - Consults Ollama AI Advisor for semantic tie-breaking.
           - Employs strict zero-crash graceful degradation (fallback to Candidate #1).
        3. Optimizes rotations A and B with linking partner heuristics.
        4. Returns (TeamRecommendation, top_5_shortlist_substitutes).
        """
        if len(candidate_pool) < 6:
            raise ValueError(f"Need at least 6 cards in pool, found {len(candidate_pool)}")

        # 1. Run Algorithmic Constraint Solver
        solver_res: ConstraintSolverResult = self.solver.solve(
            candidate_pool=candidate_pool,
            boss_stage=boss_stage,
            forced_leader=forced_leader,
            mission_batch=mission_batch,
        )
        team_cards: list[DokkanCard] = list(solver_res.team_cards)
        shortlist: list[CandidateEvaluation] = list(solver_res.shortlist)
        advisor_reason: str | None = None

        # 2. Determine whether AI Advisor should be consulted
        client = ai_client or self.ai_client
        should_consult = False
        if use_ai_advisor is not None:
            should_consult = use_ai_advisor
        elif (
            client
            and hasattr(client, "config")
            and client.config
            and getattr(client.config, "enabled", False)
        ) or self.is_ai_advisor_enabled():
            should_consult = True

        if should_consult and boss_stage is not None and len(team_cards) >= 6:
            current_5 = team_cards[:5]
            leader = team_cards[0]

            # Formulate the candidates: Solver pick for 6th slot as Candidate #1 + runner-ups
            cand1_ev = self.evaluate_card_against_boss(
                team_cards[5], leader, boss_stage=boss_stage, selected_team=current_5
            )
            raw_eval_candidates = [cand1_ev]
            for ev in shortlist:
                if len(raw_eval_candidates) >= 5:
                    break
                if ev.card.id != cand1_ev.card.id:
                    raw_eval_candidates.append(ev)

            # Check if Slot 6 is needed to fulfill a mission category requirement
            eval_candidates = raw_eval_candidates
            if mission_batch is not None:
                required_categories = getattr(mission_batch, "required_categories", [])
                for req_count, cat_name in required_categories:
                    cat_lower = cat_name.strip().lower()
                    current_count = sum(
                        1
                        for tc in current_5
                        if any(c_cat.strip().lower() == cat_lower for c_cat in tc.categories)
                    )
                    deficit = req_count - current_count
                    if deficit > 0:
                        # Category deficit exists and slot 6 must fulfill it
                        filtered = [
                            ev
                            for ev in eval_candidates
                            if any(
                                c_cat.strip().lower() == cat_lower for c_cat in ev.card.categories
                            )
                        ]
                        if filtered:
                            eval_candidates = filtered
                        logger.info(
                            f"[TeamBuilder] Mission deficit for '{cat_name}' (needed: {req_count}, current_5: {current_count}). "
                            f"Filtered candidates to {len(eval_candidates)} matching cards."
                        )

            chosen_card, reason = self.consult_ollama_advisor(
                top_candidates=eval_candidates,
                current_team=current_5,
                boss_stage=boss_stage,
                ai_client=client,
                failure_report=failure_report,
                mission_batch=mission_batch,
            )
            advisor_reason = reason
            team_cards[5] = chosen_card

            # Adjust shortlist to exclude active team cards
            active_ids = {c.id for c in team_cards}
            shortlist = [ev for ev in eval_candidates if ev.card.id not in active_ids]
            for ev in solver_res.shortlist:
                if len(shortlist) >= 5:
                    break
                if ev.card.id not in active_ids and not any(
                    s.card.id == ev.card.id for s in shortlist
                ):
                    shortlist.append(ev)

        # 3. Build Team Recommendation Plan
        boss_target_str = (
            format_stage_tactical_briefing(boss_stage, language=language) if boss_stage else None
        )
        team_rec = self.build_team_plan(
            team_cards,
            boss_target=boss_target_str,
            language=language,
            generate_tactics=generate_tactics,
            candidate_pool=candidate_pool,
            boss_stage=boss_stage,
        )
        if mission_batch is not None:
            team_rec.target_missions = list(getattr(mission_batch, "missions", []))
            team_rec.mission_summary = getattr(mission_batch, "summary", "")
            if getattr(mission_batch, "requires_no_items", False):
                team_rec.recommended_items = []

        if advisor_reason:
            team_rec.ai_reasoning = advisor_reason

        table_str = format_team_summary_table(team_cards)
        logger.info(f"\n[TeamBuilder] Optimal Team Selection:\n{table_str}\n")

        return team_rec, shortlist

    def consult_ollama_advisor(
        self,
        top_candidates: list[CandidateEvaluation],
        current_team: list[DokkanCard],
        boss_stage: BossStage,
        ai_client: DokkanAIClient | None = None,
        failure_report: FailureReport | None = None,
        mission_batch: Any | None = None,
    ) -> tuple[DokkanCard, str]:
        """
        Consults local Ollama LLM (DeepSeek-R1 / Qwen) to evaluate subtle semantic conditions
        in passive skills across the Top 5 candidates, acting as a semantic tie-breaker.
        Gracefully falls back to Candidate #1 if Ollama is disabled, offline, times out (>75s),
        returns malformed output, or returns an ID outside the Top 5 shortlist.
        """
        client = ai_client or self.ai_client
        if not top_candidates:
            raise ValueError("No candidates provided for Ollama Advisor.")

        fallback_choice = top_candidates[0].card

        # 1. Check if explicitly disabled in config
        if client and hasattr(client, "config") and client.config is not None:
            if getattr(client.config, "enabled", True) is False:
                logger.debug("Ollama AI Advisor disabled in client config.")
                return (
                    fallback_choice,
                    "Algorithmic Solver Top-Ranked Choice (AI Advisor Disabled in Settings)",
                )
        elif not self.is_ai_advisor_enabled() and client is None:
            logger.debug("Ollama AI Advisor disabled in settings.")
            return (
                fallback_choice,
                "Algorithmic Solver Top-Ranked Choice (AI Advisor Disabled in Settings)",
            )

        # 2. Server availability check (Offline)
        if not client or not client.is_available():
            logger.info("Ollama AI server not responding; using Algorithmic Solver Candidate #1.")
            return (
                fallback_choice,
                "Algorithmic Solver Top-Ranked Choice (Offline / Graceful Fallback)",
            )

        # 3. Construct structured payload
        payload = self.build_advisor_payload(
            boss_stage=boss_stage,
            current_team=current_team,
            top_candidates=top_candidates,
            failure_report=failure_report,
            mission_batch=mission_batch,
        )

        team_names = [f"[{c.element_name}] {c.full_name}" for c in current_team]
        phases_desc = []
        for p in boss_stage.phases:
            desc = f"Phase {p.phase_index}: {p.element_name}"
            if getattr(p, "is_multi_enemy", False):
                hp_val = getattr(p, "hp", 0)
                hp_str = (
                    f"{hp_val / 1_000_000:.0f}M"
                    if hp_val >= 1_000_000
                    else (f"{hp_val:,}" if hp_val else "N/A")
                )
                actions_val = getattr(p, "actions_per_turn", 0)
                act_str = f"{actions_val}/turn" if actions_val else "standard"
                desc += f" - Total HP: {hp_str}, Actions: {act_str}"
            desc += f" (Cancels Dodge: {p.cancels_dodge}, AoE: {p.has_aoe}, Locks Slots: {p.locks_slots})"
            phases_desc.append(desc)

        mission_constraint_rules = ""
        mission_user_section = ""
        if mission_batch is not None:
            summary = getattr(mission_batch, "summary", "")
            req_cats = getattr(mission_batch, "required_categories", [])
            req_cats_str = (
                ", ".join(f"{cnt}x '{cat}'" for cnt, cat in req_cats) if req_cats else "None"
            )
            requires_rainbow = getattr(mission_batch, "requires_rainbow", False)
            requires_all_super = getattr(mission_batch, "requires_all_super", False)
            requires_all_extreme = getattr(mission_batch, "requires_all_extreme", False)

            mission_constraint_rules = (
                "CRITICAL MANDATORY REQUIREMENT: Active mission constraints are in effect. "
                "The chosen card MUST strictly satisfy all required mission criteria "
                "(e.g., requested categories, rainbow type balance, Super/Extreme class restrictions). "
                "Do NOT select any card that violates or fails to advance these mission requirements. "
            )
            mission_user_section = (
                "=== ACTIVE MISSION CONSTRAINTS (MANDATORY) ===\n"
                f"Summary: {summary}\n"
                f"Required Categories: {req_cats_str}\n"
                f"Requires Rainbow (All 5 Types): {requires_rainbow}\n"
                f"Requires All Super: {requires_all_super}\n"
                f"Requires All Extreme: {requires_all_extreme}\n"
                "The selected card MUST satisfy these mission constraints!\n\n"
            )

        system_msg = (
            "You are an expert Dokkan Battle Grandmaster AI Advisor. "
            "Your task is to analyze semantic passive conditions that regex rules may miss "
            "(e.g., ally-specific guard conditions, category-restricted critical hits, specific turn restrictions). "
            + mission_constraint_rules
            + "When multi-enemy phases are present, strongly prioritize AoE attackers that hit all targets simultaneously "
            "and units with unconditional Guard that protect against rainbow attacks. "
            "You MUST select exactly ONE card from the provided candidates JSON list that best complements the team "
            "and counters the boss gimmicks. "
            "You MUST return ONLY a valid JSON object with format: "
            '{"selected_card_id": <int>, "reasoning": "<concise explanation in Italian>"}'
        )

        failure_text = ""
        if failure_report:
            failure_text = (
                f"=== PREVIOUS DEFEAT REPORT ===\n"
                f"Turn: {failure_report.defeat_turn}, Phase: {failure_report.phase_index}, Boss HP: {failure_report.boss_hp_percent}%\n"
                f"Accused Culprit ID: {failure_report.culprit_card_id}\n"
                f"Defeat Cause: {failure_report.reason}\n\n"
            )

        user_content = (
            f"=== TARGET BOSS STAGE ===\n"
            f"Event: {boss_stage.event_name}\n"
            f"Stage: {boss_stage.stage_name} (Difficulty: {boss_stage.difficulty})\n"
            f"Phases:\n"
            + "\n".join(f"- {pd}" for pd in phases_desc)
            + "\n\n"
            + failure_text
            + mission_user_section
            + "=== CURRENT TEAM ROSTER (5 MEMBERS) ===\n"
            + "\n".join(f"- {tn}" for tn in team_names)
            + "\n\n"
            "=== TOP 5 CANDIDATES PRE-FILTERED BY SOLVER ===\n"
            f"{json.dumps(payload['top_5_candidates'], ensure_ascii=False, indent=2)}\n\n"
            "Select the best candidate ID and explain why its passive conditions fit this exact matchup."
        )

        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_content},
        ]

        try:
            logger.info("Querying local Ollama AI Advisor for semantic tie-break...")
            content, reasoning = client.chat_completion(
                messages,
                temperature=0.3,
                max_tokens=2048,
                response_format={"type": "json_object"},
            )
        except (requests.exceptions.Timeout, TimeoutError) as e:
            logger.warning(f"Ollama Advisor call timed out (> 75s): {e}. Falling back smoothly.")
            return (
                fallback_choice,
                "Algorithmic Solver Top-Ranked Choice (Ollama Timeout Fallback (>75s))",
            )
        except Exception as e:
            logger.warning(f"Ollama Advisor call failed: {e}. Falling back smoothly.")
            return (
                fallback_choice,
                "Algorithmic Solver Top-Ranked Choice (Offline / Graceful Fallback)",
            )

        # Strip markdown code blocks if returned
        clean_json = content.strip()
        if "```" in clean_json:
            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", clean_json, re.DOTALL)
            if match:
                clean_json = match.group(1).strip()

        # If clean_json has text outside the outermost JSON object
        if (
            "{" in clean_json
            and "}" in clean_json
            and not (clean_json.startswith("{") and clean_json.endswith("}"))
        ):
            match = re.search(r"(\{.*\})", clean_json, re.DOTALL)
            if match:
                clean_json = match.group(1).strip()

        # Fallback: If clean_json is empty or has no '{', try extracting JSON from reasoning if available
        if (not clean_json or "{" not in clean_json) and reasoning:
            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", reasoning, re.DOTALL)
            if not match:
                match = re.search(r"(\{.*\})", reasoning, re.DOTALL)
            if match:
                clean_json = match.group(1).strip()

        sel_id = 0
        advisor_reason = ""
        try:
            parsed = json.loads(clean_json)
            if not isinstance(parsed, dict):
                raise ValueError("Parsed JSON is not an object")
            sel_id = int(parsed.get("selected_card_id", 0))
            advisor_reason = str(parsed.get("reasoning", "") or "")
        except Exception as e:
            # Fallback A: Extract candidate ID via regex (e.g. card_id: 1029051 or selected_card_id: 1029051)
            reg_match = re.search(
                r"(?:selected_card_id|card_id|candidate_id)[\s*:]+(\d+)", clean_json, re.IGNORECASE
            )
            if reg_match:
                sel_id = int(reg_match.group(1))
                advisor_reason = clean_json.strip()
            else:
                # Fallback B: Scan if any candidate ID in the top shortlist is mentioned in the response
                for ev in top_candidates[:5]:
                    if str(ev.card.id) in clean_json:
                        sel_id = ev.card.id
                        advisor_reason = clean_json.strip()
                        break

            if not sel_id:
                logger.warning(
                    f"Ollama Advisor returned malformed response: {e}. Falling back smoothly."
                )
                return (
                    fallback_choice,
                    "Algorithmic Solver Top-Ranked Choice (Malformed Response Fallback)",
                )

        # Verify that the selected ID is among the top candidates shortlist
        shortlist_ids = {ev.card.id for ev in top_candidates[:5]}
        if sel_id not in shortlist_ids:
            logger.warning(
                f"Ollama returned ID {sel_id} not in candidates shortlist ({shortlist_ids}); falling back to Solver #1."
            )
            return (
                fallback_choice,
                "Algorithmic Solver Top-Ranked Choice (Invalid / Hallucinated ID Fallback)",
            )

        for ev in top_candidates[:5]:
            if ev.card.id == sel_id:
                full_reason = f"Qwen Advisor: {advisor_reason}"
                logger.info(f"Qwen Advisor selected card {sel_id} ({ev.card.name})")
                return ev.card, full_reason

        return fallback_choice, "Algorithmic Solver Top-Ranked Choice (Offline / Graceful Fallback)"

    # =========================================================================
    # USER BOX LOADER HELPER
    # =========================================================================

    @staticmethod
    def load_user_box(
        box_path: str | None = None,
        dokkandb: DokkanDBClient | None = None,
    ) -> list[DokkanCard]:
        """
        Loads DokkanCards from user_box.json, supporting unified cache directory
        `~/.dokkan-farmer/cache/user_box.json` with fallback to `config/box.json`.
        """
        del dokkandb
        from dokkan_eza_link_farmer.ai.syncer import DokkanSyncer
        from dokkan_eza_link_farmer.automation.tasks.box_scanner import resolve_box_path

        box_path = resolve_box_path(box_path)

        if not os.path.exists(box_path):
            logger.warning(f"Box file {box_path} not found.")
            return []

        with open(box_path, encoding="utf-8") as f:
            data = json.load(f)

        card_dicts = data if isinstance(data, list) else data.get("cards", [])
        syncer = DokkanSyncer()

        cards: list[DokkanCard] = []
        for c in card_dicts:
            if not isinstance(c, dict):
                continue
            try:
                dokkan_card = DokkanCard.from_dict(c)
                cards.append(dokkan_card)
            except Exception as e:
                try:
                    dokkan_card = syncer.build_dokkan_card(c)
                    cards.append(dokkan_card)
                except Exception as inner_e:
                    logger.debug(f"Failed parsing card {c.get('id')}: {e} / {inner_e}")

        logger.info(f"Loaded {len(cards)} cards from {box_path}")
        return cards


_GLOBAL_CATEGORIES_CACHE: dict[int, str] | None = None


def _get_global_category_map() -> dict[int, str]:
    global _GLOBAL_CATEGORIES_CACHE
    if _GLOBAL_CATEGORIES_CACHE is not None:
        return _GLOBAL_CATEGORIES_CACHE

    cat_map: dict[int, str] = {}
    cache_file = os.path.join(
        os.path.expanduser("~"), ".dokkan-farmer", "cache", "dokkandb_categories.json"
    )
    if os.path.exists(cache_file):
        try:
            with open(cache_file, encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and "id" in item and "name" in item:
                            cat_map[int(item["id"])] = str(item["name"])
        except Exception as e:
            logger.debug(f"Could not load global categories cache: {e}")

    _GLOBAL_CATEGORIES_CACHE = cat_map
    return cat_map


def _resolve_category_name(cid: int, card: DokkanCard, leader: DokkanCard) -> str:
    """Helper to map a category ID to human-readable name using card, leader, or global catalog metadata."""
    c_map = dict(zip(card.category_ids, card.categories, strict=False))
    lead_map = dict(zip(leader.category_ids, leader.categories, strict=False))
    global_map = _get_global_category_map()
    return c_map.get(cid) or lead_map.get(cid) or global_map.get(cid) or str(cid)


def format_team_summary_table(
    team_cards: list[DokkanCard], leader: DokkanCard | None = None, boss_stage: Any = None
) -> str:
    """
    Renders a clear tabular summary for the 6 team slots:
    [card_id] | [Element/Class] | Name (Subname) | Leader Boost (170% o 200%) | Categorie Condivise col Leader | Ruolo (Slot 1 Tank / Stacker / Floater) | Tag Difensivi (Guard / DR% / Dodge%)
    """
    if not team_cards:
        return "No team cards provided."

    lead = leader or team_cards[0]
    headers = [
        "Slot",
        "Card ID",
        "Element/Class",
        "Name (Subname)",
        "Leader Boost",
        "Categorie Condivise col Leader",
        "Ruolo",
        "Tag Difensivi",
    ]

    rows: list[list[str]] = []

    # Pre-calculate designated battle rotation roles if 6-card team
    rot_role_map: dict[int, str] = {}
    if len(team_cards) == 6:
        try:
            tb_rot = TeamBuilder()
            rot_a, rot_b, floaters = tb_rot.optimize_rotations_for_team(team_cards)
            rot_role_map[rot_a.slot1.id] = "Slot 1 Tank (Rot A)"
            rot_role_map[rot_a.slot2.id] = (
                "Slot 2 Stacker (Rot A)"
                if rot_a.slot2.has_stacking_def
                or (
                    rot_a.slot2.base_form
                    and rot_a.slot2.base_form.sa_tags
                    and rot_a.slot2.base_form.sa_tags.stacks_def
                )
                else "Slot 2 DPS (Rot A)"
            )
            rot_role_map[rot_b.slot1.id] = "Slot 1 Tank (Rot B)"
            rot_role_map[rot_b.slot2.id] = (
                "Slot 2 Stacker (Rot B)"
                if rot_b.slot2.has_stacking_def
                or (
                    rot_b.slot2.base_form
                    and rot_b.slot2.base_form.sa_tags
                    and rot_b.slot2.base_form.sa_tags.stacks_def
                )
                else "Slot 2 DPS (Rot B)"
            )
            for fl in floaters:
                if fl.has_support or (
                    fl.base_form
                    and fl.base_form.passive_tags
                    and fl.base_form.passive_tags.has_support
                ):
                    fl_role = "Floater (Support)"
                elif fl.has_stacking_def or (
                    fl.base_form and fl.base_form.sa_tags and fl.base_form.sa_tags.stacks_def
                ):
                    fl_role = "Floater (Stacker)"
                else:
                    fl_role = "Floater (Slot 3)"
                rot_role_map[fl.id] = fl_role
        except Exception:
            pass

    for idx, c in enumerate(team_cards, start=1):
        slot_str = str(idx)
        cid_str = f"[{c.id}]"
        elem_str = f"[{c.element_name}]" if c.element_name else f"[{c.element}]"
        clean_name = " ".join(c.name.split())
        clean_sub = " ".join(c.subname.split()) if c.subname else ""
        name_str = f"{clean_name} ({clean_sub})" if clean_sub else clean_name

        # Leader Boost
        if idx == 1:
            is_cov, boost_val, _ = lead.is_covered_by_leader(lead)
            if is_cov:
                boost_str = f"{int(boost_val)}% (Lead)"
            elif lead.leader_spec:
                boost_str = f"{lead.leader_spec.base_boost_pct}% (Lead)"
            else:
                boost_str = "Leader"
        else:
            is_cov, boost_val, _ = c.is_covered_by_leader(lead)
            boost_str = f"{int(boost_val)}%" if is_cov else "0%"

        # Categorie Condivise col Leader
        if idx == 1:
            if lead.leader_spec and (
                lead.leader_spec.main_category_ids or lead.leader_spec.extra_category_ids
            ):
                main_names = [
                    _resolve_category_name(cid, lead, lead)
                    for cid in lead.leader_spec.main_category_ids
                ]
                extra_names = [
                    _resolve_category_name(cid, lead, lead)
                    for cid in lead.leader_spec.extra_category_ids
                ]
                main_str = f"Main: [{', '.join(main_names)}]" if main_names else "Main: Nessuna"
                extra_str = (
                    f"Extra: [{', '.join(extra_names)}]" if extra_names else "Extra: Nessuna"
                )
                shared_str = f"{main_str} | {extra_str}"
            else:
                shared_str = ", ".join(lead.categories[:2]) if lead.categories else "None"
        else:
            if lead.leader_spec and (
                lead.leader_spec.main_category_ids or lead.leader_spec.extra_category_ids
            ):
                main_set = set(lead.leader_spec.main_category_ids)
                extra_set = set(lead.leader_spec.extra_category_ids)

                shared_main = [
                    _resolve_category_name(cid, c, lead)
                    for cid in c.category_ids
                    if cid in main_set
                ]
                shared_extra = [
                    _resolve_category_name(cid, c, lead)
                    for cid in c.category_ids
                    if cid in extra_set
                ]

                if shared_main:
                    main_str = f"Main: [{', '.join(shared_main)}]"
                    extra_str = (
                        f"Extra: [{', '.join(shared_extra)}]" if shared_extra else "Extra: Nessuna"
                    )
                    shared_str = f"{main_str} | {extra_str}"
                else:
                    shared_str = "Main: Nessuna | Extra: Nessuna"
            else:
                shared_names = [cat for cat in c.categories if cat in lead.categories]
                shared_str = ", ".join(shared_names) if shared_names else "None"

        # Ruolo (Designated battle role or individual archetype)
        if c.id in rot_role_map:
            role_str = rot_role_map[c.id]
        else:
            is_s1 = DokkanConstraintSolver.is_slot1_viable(c)
            stacks = bool(
                (c.base_form and c.base_form.sa_tags and c.base_form.sa_tags.stacks_def)
                or c.has_stacking_def
            )
            if is_s1 and stacks:
                role_str = "Slot 1 Viable / Stacker"
            elif is_s1:
                role_str = "Slot 1 Viable"
            elif stacks:
                role_str = "Stacker"
            else:
                role_str = "Floater"

        # Tag Difensivi (Guard / DR% / Dodge%)
        has_guard = c.has_guard or bool(
            c.base_form and c.base_form.passive_tags and c.base_form.passive_tags.has_guard
        )
        is_guard_perm = getattr(c, "is_guard_permanent", False)
        is_guard_uncond = getattr(c, "is_guard_unconditional", False)
        guard_limit = getattr(c, "guard_turns_limit", None)
        if is_guard_perm and is_guard_uncond:
            guard_label = "Guard (Perm)"
        elif is_guard_perm:
            guard_label = "Guard (Cond)"
        elif guard_limit:
            guard_label = f"Guard ({guard_limit}T)"
        elif has_guard:
            guard_label = "Guard"
        else:
            guard_label = "No Guard"

        dr_pct = max(
            c.damage_reduction_percent,
            c.base_form.passive_tags.dr_base_percent
            if c.base_form and c.base_form.passive_tags
            else 0,
        )
        dr_limit = getattr(c, "dr_turns_limit", None)
        perm_dr = getattr(c, "permanent_damage_reduction_percent", 0)
        if dr_pct > 0:
            if perm_dr == dr_pct and getattr(c, "is_dr_permanent", False):
                dr_label = f"DR {dr_pct}% (Perm)"
            elif dr_limit:
                dr_label = f"DR {dr_pct}% ({dr_limit}T)"
            else:
                dr_label = f"DR {dr_pct}%"
        else:
            dr_label = "DR 0%"

        dodge_pct = c.dodge_chance_percent
        dodge_limit = getattr(c, "dodge_turns_limit", None)
        cancels_dodge_boss = bool(
            boss_stage
            and any(getattr(p, "cancels_dodge", False) for p in getattr(boss_stage, "phases", []))
        )
        if dodge_pct > 0:
            if cancels_dodge_boss:
                dodge_label = f"Dodge {dodge_pct}% [Nullificato]"
            elif dodge_limit:
                dodge_label = f"Dodge {dodge_pct}% ({dodge_limit}T)"
            else:
                dodge_label = f"Dodge {dodge_pct}%"
        else:
            dodge_label = "Dodge 0%"

        def_tags_str = f"{guard_label} / {dr_label} / {dodge_label}"

        rows.append(
            [
                slot_str,
                cid_str,
                elem_str,
                name_str,
                boost_str,
                shared_str,
                role_str,
                def_tags_str,
            ]
        )

    col_widths = [max(len(headers[i]), max(len(r[i]) for r in rows)) for i in range(len(headers))]
    header_line = " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    divider_line = "-+-".join("-" * col_widths[i] for i in range(len(headers)))
    data_lines = [" | ".join(col.ljust(col_widths[i]) for i, col in enumerate(row)) for row in rows]

    return "\n".join([header_line, divider_line] + data_lines)


def render_team_summary_table_rich(
    team_cards: list[DokkanCard], leader: DokkanCard | None = None, boss_stage: Any = None
) -> Any:
    """Renders a rich.table.Table summary for the 6 team slots with Dokkan type colors:
    - Slot (1 to 6)
    - Type (Super AGL, Extreme STR, etc. colored with Dokkan typing color)
    - Character (full name styled with Dokkan typing color)
    - Leader Boost (200%, 170%, etc.)
    - Ruolo (Slot 1 Tank, Stacker, Floater)
    - Tag Difensivi (Guard, DR %, Dodge %)
    """
    from rich.table import Table
    from rich.text import Text

    lead = leader or (team_cards[0] if team_cards else None)
    t = Table(
        title="🛡️ Dokkan AI Optimal 6-Card Team Formation",
        border_style="green",
        expand=True,
    )
    t.add_column("Slot", style="bold cyan", justify="center", width=6, no_wrap=True)
    t.add_column("Type", justify="center", width=13, no_wrap=True)
    t.add_column("Character", ratio=5, no_wrap=False)
    t.add_column("Leader Boost", justify="center", width=13, no_wrap=True)
    t.add_column("Ruolo", justify="center", width=16, no_wrap=False)
    t.add_column("Tag Difensivi", ratio=3, no_wrap=False)

    if not team_cards:
        return t

    # Pre-calculate designated battle rotation roles if 6-card team
    rot_role_map: dict[int, str] = {}
    if len(team_cards) == 6:
        try:
            tb_rot = TeamBuilder()
            rot_a, rot_b, floaters = tb_rot.optimize_rotations_for_team(team_cards)
            rot_role_map[rot_a.slot1.id] = "Slot 1 Tank (Rot A)"
            rot_role_map[rot_a.slot2.id] = (
                "Slot 2 Stacker (Rot A)"
                if rot_a.slot2.has_stacking_def
                or (
                    rot_a.slot2.base_form
                    and rot_a.slot2.base_form.sa_tags
                    and rot_a.slot2.base_form.sa_tags.stacks_def
                )
                else "Slot 2 DPS (Rot A)"
            )
            rot_role_map[rot_b.slot1.id] = "Slot 1 Tank (Rot B)"
            rot_role_map[rot_b.slot2.id] = (
                "Slot 2 Stacker (Rot B)"
                if rot_b.slot2.has_stacking_def
                or (
                    rot_b.slot2.base_form
                    and rot_b.slot2.base_form.sa_tags
                    and rot_b.slot2.base_form.sa_tags.stacks_def
                )
                else "Slot 2 DPS (Rot B)"
            )
            for fl in floaters:
                if fl.has_support or (
                    fl.base_form
                    and fl.base_form.passive_tags
                    and fl.base_form.passive_tags.has_support
                ):
                    fl_role = "Floater (Support)"
                elif fl.has_stacking_def or (
                    fl.base_form and fl.base_form.sa_tags and fl.base_form.sa_tags.stacks_def
                ):
                    fl_role = "Floater (Stacker)"
                else:
                    fl_role = "Floater (Slot 3)"
                rot_role_map[fl.id] = fl_role
        except Exception:
            pass

    for idx, c in enumerate(team_cards, start=1):
        slot_str = str(idx)
        color = c.element_color
        type_str = c.element_name if c.element_name else c.type_tag

        clean_name = " ".join(c.name.split())
        clean_sub = " ".join(c.subname.split()) if c.subname else ""
        name_str = f"{clean_name} ({clean_sub})" if clean_sub else clean_name

        # Leader Boost
        if idx == 1:
            if lead:
                is_cov, boost_val, _ = lead.is_covered_by_leader(lead)
                if is_cov:
                    boost_style = "bold green" if boost_val >= 200 else "bold cyan"
                    boost_text = Text(f"{int(boost_val)}% (Lead)", style=boost_style)
                elif lead.leader_spec:
                    boost_style = (
                        "bold green" if lead.leader_spec.base_boost_pct >= 200 else "bold cyan"
                    )
                    boost_text = Text(
                        f"{lead.leader_spec.base_boost_pct}% (Lead)", style=boost_style
                    )
                else:
                    boost_text = Text("Leader", style="bold cyan")
            else:
                boost_text = Text("Leader", style="bold cyan")
        else:
            if lead:
                is_cov, boost_val, _ = c.is_covered_by_leader(lead)
                if is_cov:
                    boost_style = "bold green" if boost_val >= 200 else "cyan"
                    boost_text = Text(f"{int(boost_val)}%", style=boost_style)
                else:
                    boost_text = Text("0%", style="dim red")
            else:
                boost_text = Text("N/A", style="dim")

        # Ruolo (Designated battle role or individual archetype)
        if c.id in rot_role_map:
            role_label = rot_role_map[c.id]
            if "Slot 1 Tank" in role_label:
                role_text = Text(role_label, style="bold cyan")
            elif "Slot 2" in role_label:
                role_text = Text(role_label, style="bold green")
            else:
                role_text = Text(role_label, style="dim yellow")
        else:
            is_s1 = DokkanConstraintSolver.is_slot1_viable(c)
            stacks = bool(
                (c.base_form and c.base_form.sa_tags and c.base_form.sa_tags.stacks_def)
                or c.has_stacking_def
            )
            if is_s1 and stacks:
                role_text = Text("Slot 1 Viable / Stacker", style="bold cyan")
            elif is_s1:
                role_text = Text("Slot 1 Viable", style="bold cyan")
            elif stacks:
                role_text = Text("Stacker", style="bold yellow")
            else:
                role_text = Text("Floater", style="dim")

        # Tag Difensivi
        has_guard = c.has_guard or bool(
            c.base_form and c.base_form.passive_tags and c.base_form.passive_tags.has_guard
        )
        is_guard_perm = getattr(c, "is_guard_permanent", False)
        is_guard_uncond = getattr(c, "is_guard_unconditional", False)
        guard_limit = getattr(c, "guard_turns_limit", None)
        if is_guard_perm and is_guard_uncond:
            guard_part = "Guard (Perm)"
        elif is_guard_perm:
            guard_part = "Guard (Cond)"
        elif guard_limit:
            guard_part = f"Guard ({guard_limit}T)"
        elif has_guard:
            guard_part = "Guard"
        else:
            guard_part = "No Guard"

        dr_pct = max(
            c.damage_reduction_percent,
            c.base_form.passive_tags.dr_base_percent
            if c.base_form and c.base_form.passive_tags
            else 0,
        )
        dr_limit = getattr(c, "dr_turns_limit", None)
        perm_dr = getattr(c, "permanent_damage_reduction_percent", 0)
        if dr_pct > 0:
            if perm_dr == dr_pct and getattr(c, "is_dr_permanent", False):
                dr_part = f"DR {dr_pct}% (Perm)"
            elif dr_limit:
                dr_part = f"DR {dr_pct}% ({dr_limit}T)"
            else:
                dr_part = f"DR {dr_pct}%"
        else:
            dr_part = "DR 0%"

        dodge_pct = c.dodge_chance_percent
        dodge_limit = getattr(c, "dodge_turns_limit", None)
        cancels_dodge_boss = bool(
            boss_stage
            and any(getattr(p, "cancels_dodge", False) for p in getattr(boss_stage, "phases", []))
        )
        if dodge_pct > 0:
            if cancels_dodge_boss:
                dodge_part = f"Dodge {dodge_pct}% [Nullificato]"
            elif dodge_limit:
                dodge_part = f"Dodge {dodge_pct}% ({dodge_limit}T)"
            else:
                dodge_part = f"Dodge {dodge_pct}%"
        else:
            dodge_part = "Dodge 0%"

        def_tags_str = f"{guard_part} / {dr_part} / {dodge_part}"

        t.add_row(
            slot_str,
            Text(type_str, style=color),
            Text(name_str, style=color),
            boost_text,
            role_text,
            def_tags_str,
        )

    return t


def format_stage_tactical_briefing(boss_stage: Any, language: str = "it") -> str:
    """Formats complete multi-battle stage intelligence, HP, ATK, actions, immunities, and skills."""
    if not boss_stage:
        return ""
    lines: list[str] = []
    total_battles = getattr(boss_stage, "total_battles", 1)
    is_multi_battle = getattr(boss_stage, "is_multi_battle", False)
    phases = getattr(boss_stage, "phases", [])

    if language == "it":
        lines.append(
            f"**Evento**: {boss_stage.event_name} | **Stage**: {boss_stage.stage_name} (ID: {boss_stage.stage_id})"
        )
        lines.append(
            f"- **Struttura Evento**: {total_battles} Battagli{'a' if total_battles == 1 else 'e'} distinte ({len(phases)} Fasi totali)"
        )
        if is_multi_battle:
            lines.append(
                "> ⚠️ **AVVISO MECCANICA DI GIOCO (RESET STACKING)**: Questo evento è suddiviso in "
                f"{total_battles} battaglie separate! Lo stacking permanente di ATK e DEF "
                "NON si conserva tra una battaglia e l'altra (si azzera a 0 all'inizio di ogni battaglia). "
                "I bonus 'Entrance Animation' si riattivano all'inizio di ciascuna battaglia."
            )
        lines.append("\n**Scheda Dettagliata Battaglie & Fasi Boss**:")
        for p in phases:
            hp_val = getattr(p, "hp", 0)
            atk_val = getattr(p, "atk", 0)
            sa_est_val = getattr(p, "estimated_sa_damage", 0)
            actions_val = getattr(p, "actions_per_turn", 0)
            skills = getattr(p, "special_skills", [])

            hp_str = (
                f"{hp_val / 1_000_000:.0f}M"
                if hp_val >= 1_000_000
                else (f"{hp_val:,}" if hp_val else "N/A")
            )
            atk_str = (
                f"{atk_val / 1_000:.0f}k"
                if atk_val >= 1_000
                else (str(atk_val) if atk_val else "N/A")
            )
            sa_est = (
                f"~{sa_est_val / 1_000_000:.1f}M"
                if sa_est_val >= 1_000_000
                else (f"~{sa_est_val:,}" if sa_est_val else "N/A")
            )
            actions_str = f"{actions_val} attacchi/turno" if actions_val else "Attacchi standard"
            skills_str = ", ".join(skills) if skills else "Nessuna abilità speciale rilevata"
            stacking_note = (
                "Inizio evento (stacking da 0)"
                if getattr(p, "phase_index", 1) == 1
                else (
                    "⚠️ NUOVA BATTAGLIA (Stacking azzerato a 0!)"
                    if getattr(p, "is_new_battle", False)
                    else "Stacking conservato dalla fase precedente"
                )
            )

            is_multi = getattr(p, "is_multi_enemy", False)
            if is_multi:
                e_cnt = getattr(p, "enemy_count", len(getattr(p, "bosses", [])))
                header = (
                    f"- **Battaglia {getattr(p, 'battle_index', 1)} - Round {getattr(p, 'round_index', 1)} (Fase {getattr(p, 'phase_index', 1)})**: "
                    f"👥 {e_cnt} Nemici [{getattr(p, 'element_name', '')}]"
                )
                lines.append(header)
                lines.append(
                    f"  - **HP Totali**: {hp_str} | **ATK Base (Fase)**: {atk_str} (Super Attack stimata: {sa_est}) | **Azioni Totali**: {actions_str}"
                )
                lines.append(f"  - **Abilità & Gimmick**: {skills_str}")
                lines.append(f"  - **Stato Stacking**: {stacking_note}")
                lines.append("  - **Nemici Presenti**:")
                for b in getattr(p, "bosses", []):
                    b_sub = f" ({b.subname})" if getattr(b, "subname", None) else ""
                    b_hp = (
                        f"{b.hp / 1_000_000:.0f}M"
                        if b.hp >= 1_000_000
                        else (f"{b.hp:,}" if b.hp else "N/A")
                    )
                    b_atk = (
                        f"{b.atk / 1_000:.0f}k"
                        if b.atk >= 1_000
                        else (str(b.atk) if b.atk else "N/A")
                    )
                    lines.append(
                        f"    - **{b.name}{b_sub}** [{b.type_name}]: HP {b_hp}, ATK {b_atk}"
                    )
                lines.append(
                    f"  - 💡 CONSIGLIO TATTICO: La fase contiene {e_cnt} nemici simultanei. "
                    "Personaggi con Super Attacchi AoE o con Guardia incondizionata eccellono qui per ripulire rapidamente il campo!"
                )
            else:
                b = p.bosses[0] if getattr(p, "bosses", None) else None
                b_name = b.name if b else "Boss"
                sub = f" ({b.subname})" if b and getattr(b, "subname", None) else ""
                lines.append(
                    f"- **Battaglia {getattr(p, 'battle_index', 1)} - Round {getattr(p, 'round_index', 1)} (Fase {getattr(p, 'phase_index', 1)})**: "
                    f"**{b_name}{sub}** [{getattr(p, 'element_name', '')}]\n"
                    f"  - **HP**: {hp_str} | **ATK Base**: {atk_str} (Super Attack stimata: {sa_est}) | **Azioni**: {actions_str}\n"
                    f"  - **Abilità & Gimmick**: {skills_str}\n"
                    f"  - **Stato Stacking**: {stacking_note}"
                )
    else:
        lines.append(
            f"**Event**: {boss_stage.event_name} | **Stage**: {boss_stage.stage_name} (ID: {boss_stage.stage_id})"
        )
        lines.append(
            f"- **Event Structure**: {total_battles} Distinct Battle(s) ({len(phases)} Total Phases)"
        )
        if is_multi_battle:
            lines.append(
                "> ⚠️ **CRITICAL GAME MECHANIC (STACKING RESET)**: This stage consists of "
                f"{total_battles} separate battles! Permanent ATK & DEF stacking "
                "DOES NOT carry over between battles (it resets to 0 at the start of each battle). "
                "Entrance Animations re-trigger upon entry in each battle."
            )
        lines.append("\n**Detailed Battles, Phases, Damage & Boss Gimmicks**:")
        for p in phases:
            hp_val = getattr(p, "hp", 0)
            atk_val = getattr(p, "atk", 0)
            sa_est_val = getattr(p, "estimated_sa_damage", 0)
            actions_val = getattr(p, "actions_per_turn", 0)
            skills = getattr(p, "special_skills", [])

            hp_str = (
                f"{hp_val / 1_000_000:.0f}M"
                if hp_val >= 1_000_000
                else (f"{hp_val:,}" if hp_val else "N/A")
            )
            atk_str = (
                f"{atk_val / 1_000:.0f}k"
                if atk_val >= 1_000
                else (str(atk_val) if atk_val else "N/A")
            )
            sa_est = (
                f"~{sa_est_val / 1_000_000:.1f}M"
                if sa_est_val >= 1_000_000
                else (f"~{sa_est_val:,}" if sa_est_val else "N/A")
            )
            actions_str = f"{actions_val} attacks/turn" if actions_val else "Standard actions"
            skills_str = ", ".join(skills) if skills else "No special skills detected"
            stacking_note = (
                "Stage start (0 stacks)"
                if getattr(p, "phase_index", 1) == 1
                else (
                    "⚠️ NEW BATTLE: DEF stacks reset to 0!"
                    if getattr(p, "is_new_battle", False)
                    else "Stacks carried over from previous phase"
                )
            )

            is_multi = getattr(p, "is_multi_enemy", False)
            if is_multi:
                e_cnt = getattr(p, "enemy_count", len(getattr(p, "bosses", [])))
                header = (
                    f"- **Battle {getattr(p, 'battle_index', 1)} - Round {getattr(p, 'round_index', 1)} (Phase {getattr(p, 'phase_index', 1)})**: "
                    f"👥 {e_cnt} Enemies [{getattr(p, 'element_name', '')}]"
                )
                lines.append(header)
                lines.append(
                    f"  - **Total HP**: {hp_str} | **Phase Base ATK**: {atk_str} (Estimated Super Attack: {sa_est}) | **Total Actions**: {actions_str}"
                )
                lines.append(f"  - **Skills & Gimmicks**: {skills_str}")
                lines.append(f"  - **Stacking Status**: {stacking_note}")
                lines.append("  - **Enemies Present**:")
                for b in getattr(p, "bosses", []):
                    b_sub = f" ({b.subname})" if getattr(b, "subname", None) else ""
                    b_hp = (
                        f"{b.hp / 1_000_000:.0f}M"
                        if b.hp >= 1_000_000
                        else (f"{b.hp:,}" if b.hp else "N/A")
                    )
                    b_atk = (
                        f"{b.atk / 1_000:.0f}k"
                        if b.atk >= 1_000
                        else (str(b.atk) if b.atk else "N/A")
                    )
                    lines.append(
                        f"    - **{b.name}{b_sub}** [{b.type_name}]: HP {b_hp}, ATK {b_atk}"
                    )
                lines.append(
                    f"  - 💡 TACTICAL ADVICE: Phase contains {e_cnt} simultaneous enemies. "
                    "AoE Super Attack units and unconditional Guard units excel here to wipe out targets quickly!"
                )
            else:
                b = p.bosses[0] if getattr(p, "bosses", None) else None
                b_name = b.name if b else "Boss"
                sub = f" ({b.subname})" if b and getattr(b, "subname", None) else ""
                lines.append(
                    f"- **Battle {getattr(p, 'battle_index', 1)} - Round {getattr(p, 'round_index', 1)} (Phase {getattr(p, 'phase_index', 1)})**: "
                    f"**{b_name}{sub}** [{getattr(p, 'element_name', '')}]\n"
                    f"  - **HP**: {hp_str} | **Normal ATK**: {atk_str} (Estimated Super Attack: {sa_est}) | **Actions**: {actions_str}\n"
                    f"  - **Skills & Gimmicks**: {skills_str}\n"
                    f"  - **Stacking Status**: {stacking_note}"
                )
    return "\n".join(lines)


def render_stage_intel_rich(boss_stage: Any) -> Any:
    """Renders a rich table of complete stage intelligence: Battles, HP, ATK, Actions, Immunities, and Stacking."""
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    total_battles = getattr(boss_stage, "total_battles", 1)
    is_multi_battle = getattr(boss_stage, "is_multi_battle", False)
    phases = getattr(boss_stage, "phases", [])

    title = f"🎯 Stage Intelligence: {boss_stage.event_name} - {boss_stage.stage_name} ({total_battles} Battagli{'e' if total_battles > 1 else 'a'})"
    t = Table(show_header=True, header_style="bold magenta", expand=True)
    t.add_column("Fase", style="bold cyan", width=12, no_wrap=True)
    t.add_column("Boss Nemico", style="bold", ratio=4, no_wrap=False)
    t.add_column("HP", justify="right", style="green", width=7, no_wrap=True)
    t.add_column("ATK / Super", justify="right", style="yellow", width=13, no_wrap=True)
    t.add_column("Azioni", justify="center", width=7, no_wrap=True)
    t.add_column("Gimmick & Immunità", style="white", ratio=4, no_wrap=False)
    t.add_column("Stacking DEF", justify="center", width=12, no_wrap=False)

    for p in phases:
        phase_label = f"B{getattr(p, 'battle_index', 1)} - R{getattr(p, 'round_index', 1)} (F{getattr(p, 'phase_index', 1)})"

        elem_name = getattr(p, "element_name", "")
        elem_color = (
            "bold green"
            if "TEQ" in elem_name
            else (
                "bold blue"
                if "AGL" in elem_name
                else (
                    "bold red"
                    if "STR" in elem_name
                    else ("bold yellow" if "PHY" in elem_name else "bold magenta")
                )
            )
        )

        is_multi = getattr(p, "is_multi_enemy", False)
        if is_multi:
            e_cnt = getattr(p, "enemy_count", len(getattr(p, "bosses", [])))
            boss_text = Text()
            boss_text.append(f"👥 {e_cnt} Nemici ({elem_name})\n", style="bold cyan")
            for idx, b in enumerate(getattr(p, "bosses", [])):
                b_color = (
                    "green"
                    if "TEQ" in b.type_name
                    else (
                        "blue"
                        if "AGL" in b.type_name
                        else (
                            "red"
                            if "STR" in b.type_name
                            else ("yellow" if "PHY" in b.type_name else "magenta")
                        )
                    )
                )
                boss_text.append(f"• [{b.type_name}] {b.name}", style=b_color)
                if idx < len(p.bosses) - 1:
                    boss_text.append("\n")
        else:
            b = p.bosses[0] if getattr(p, "bosses", None) else None
            b_name = b.name if b else "Boss"
            boss_text = Text(f"[{elem_name}] {b_name}", style=elem_color)

        hp_val = getattr(p, "hp", 0)
        atk_val = getattr(p, "atk", 0)
        sa_val = getattr(p, "estimated_sa_damage", 0)
        act_val = getattr(p, "actions_per_turn", 0)
        skills = getattr(p, "special_skills", [])

        hp_str = (
            f"{hp_val / 1_000_000:.0f}M"
            if hp_val >= 1_000_000
            else (f"{hp_val:,}" if hp_val else "-")
        )
        atk_str = f"{atk_val / 1_000:.0f}k / ~{sa_val / 1_000_000:.1f}M" if atk_val else "-"
        act_str = f"{act_val}/t" if act_val else "-"
        gimmicks_str = ", ".join(skills) if skills else "Nessuna"

        p_idx = getattr(p, "phase_index", 1)
        is_new = getattr(p, "is_new_battle", False)
        if p_idx == 1:
            stack_text = Text("Inizio (0)", style="dim")
        elif is_new:
            stack_text = Text("⚠️ Reset a 0!", style="bold red")
        else:
            stack_text = Text("Mantiene", style="bold green")

        t.add_row(
            phase_label,
            boss_text,
            hp_str,
            atk_str,
            act_str,
            gimmicks_str,
            stack_text,
        )

    if is_multi_battle:
        from rich.console import Group

        warning_text = (
            "[bold yellow]⚠️ NOTA MULTI-BATTAGLIA:[/bold yellow] "
            "[bold red]Lo Stacking di ATK e DEF si AZZERA all'inizio di ciascuna nuova battaglia "
            "(i buff accumulati NON si trasferiscono tra Battaglia 1, 2 e 3)![/bold red]\n"
            "[dim]Le rotazioni A e B sono coppie d'ancoraggio sinergiche: puoi e devi adattarle "
            "dinamicamente in base ai tipi e agli attacchi di ogni fase.[/dim]\n"
        )
        content = Group(warning_text, t)
    else:
        content = t

    return Panel(
        content,
        title=title,
        subtitle=f"[dim]Fasi totali: {len(phases)} | Difficoltà: {getattr(boss_stage, 'difficulty', 1)}[/dim]",
        border_style="cyan",
    )


__all__ = [
    "CandidateEvaluation",
    "ConstraintSolverResult",
    "DokkanConstraintSolver",
    "FailureReport",
    "TeamBuilder",
    "KI_LINKS",
    "TOP_TIER_STAT_LINKS",
    "ELEMENT_ADVANTAGE",
    "ELEMENT_DISADVANTAGE",
    "format_team_summary_table",
    "render_team_summary_table_rich",
    "format_stage_tactical_briefing",
    "render_stage_intel_rich",
]
