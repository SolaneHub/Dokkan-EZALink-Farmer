from __future__ import annotations

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
        self.solver = solver or DokkanConstraintSolver()
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

    def evaluate_rotation_pair(self, card_a: DokkanCard, card_b: DokkanCard) -> RotationPair:
        """Determines who should be in Slot 1 (tank/defensive anchor) and Slot 2 (damage/link partner)."""
        score, shared, shared_ki = self.calculate_link_synergy(card_a, card_b)

        # Evaluate defensive priority for Slot 1: Guard > DR >= 40% > Infinite DEF Stack > Dodge
        kit_a, _ = card_a.evaluate_kit_power()
        kit_b, _ = card_b.evaluate_kit_power()

        a_def_priority = 0
        if card_a.has_guard:
            a_def_priority += 40
        if card_a.damage_reduction_percent >= 40:
            a_def_priority += 35
        elif card_a.has_damage_reduction:
            a_def_priority += 20
        if card_a.has_stacking_def:
            a_def_priority += 25
        if card_a.has_dodge:
            a_def_priority += 15
        if card_a.is_slot1_tank:
            a_def_priority += 20

        b_def_priority = 0
        if card_b.has_guard:
            b_def_priority += 40
        if card_b.damage_reduction_percent >= 40:
            b_def_priority += 35
        elif card_b.has_damage_reduction:
            b_def_priority += 20
        if card_b.has_stacking_def:
            b_def_priority += 25
        if card_b.has_dodge:
            b_def_priority += 15
        if card_b.is_slot1_tank:
            b_def_priority += 20

        if a_def_priority > b_def_priority:
            slot1, slot2 = card_a, card_b
        elif b_def_priority > a_def_priority:
            slot1, slot2 = card_b, card_a
        else:
            # Tie-break: Higher kit power or LR rarity
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
        self, cards: list[DokkanCard]
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

        # Evaluate combinations of 4 cards to form 2 pairs
        for four_cards in itertools.combinations(cards, 4):
            c1, c2, c3, c4 = four_cards
            pairings = [
                ((c1, c2), (c3, c4)),
                ((c1, c3), (c2, c4)),
                ((c1, c4), (c2, c3)),
            ]
            for (p1_a, p1_b), (p2_a, p2_b) in pairings:
                rot1 = self.evaluate_rotation_pair(p1_a, p1_b)
                rot2 = self.evaluate_rotation_pair(p2_a, p2_b)
                total = rot1.synergy_score + rot2.synergy_score

                if total > best_score:
                    best_score = total
                    best_rot_a = rot1
                    best_rot_b = rot2
                    used_ids = {p1_a.id, p1_b.id, p2_a.id, p2_b.id}
                    best_floaters = [c for c in cards if c.id not in used_ids]

        if best_rot_a is None or best_rot_b is None:
            best_rot_a = self.evaluate_rotation_pair(cards[0], cards[1])
            best_rot_b = self.evaluate_rotation_pair(cards[2], cards[3])
            best_floaters = cards[4:]

        return best_rot_a, best_rot_b, best_floaters

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

    def build_team_plan(
        self,
        cards: list[DokkanCard],
        boss_target: str | None = None,
        language: str = "it",
        generate_tactics: bool = True,
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
        friend_leader = cards[6] if len(cards) >= 7 else leader

        rot_a, rot_b, floaters = self.optimize_rotations_for_team(cards[:6])

        # Generate structured summary highlighting kit mechanics and links
        summary_lines = [
            f"1. Leader: {leader.full_name} ({leader.leader_skill})",
            f"2. Rotazione A: Slot 1 [{rot_a.slot1.full_name}] + Slot 2 [{rot_a.slot2.full_name}] (Link: {', '.join(rot_a.shared_links)})",
            f"3. Rotazione B: Slot 1 [{rot_b.slot1.full_name}] + Slot 2 [{rot_b.slot2.full_name}] (Link: {', '.join(rot_b.shared_links)})",
            f"4. Floaters (Slot 3): {', '.join(f.full_name for f in floaters)}",
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
            # Algorithmic fallback guide adhering to the 3-level hierarchy
            tactical_guide = (
                f"### Piano Tattico Deterministico (Gerarchia Dokkan):\n"
                f"1. **Copertura Leader Skill**: Tutte le unità selezionate beneficiano del boost della Leader Skill ({leader.name}).\n"
                f"2. **Kit & Ruoli Difensivi (Slot 1)**:\n"
                f"   - **Rotazione A**: Mantieni {rot_a.slot1.name} in Slot 1 (difensore principale). {rot_a.slot2.name} in Slot 2 attiva {len(rot_a.shared_links)} link e gestisce i danni/Active.\n"
                f"   - **Rotazione B**: {rot_b.slot1.name} in Slot 1 come baluardo difensivo. {rot_b.slot2.name} in Slot 2 attiva {len(rot_b.shared_links)} link.\n"
                f"3. **Link Skill & Supporto (Slot 3 Floaters)**:\n"
                f"   - Fai ruotare {', '.join(f.name for f in floaters)} in Slot 3 per Ki support, orbi e rotazione strategica.\n"
                f"4. **Oggetti di Supporto Consigliati**: Whis (riduzione 40% per 2 turni) o Princess Snake (cura 55% + 30% riduzione danno)."
            )

        items = ["Whis", "Ghost Usher", "Princess Snake"]

        return TeamRecommendation(
            leader=leader,
            friend_leader=friend_leader,
            rotation_a=rot_a,
            rotation_b=rot_b,
            floaters=floaters,
            all_cards=cards[:6],
            tactical_analysis=tactical_guide,
            recommended_items=items,
            ai_reasoning=ai_reasoning,
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
        if self.ai_client and hasattr(self.ai_client, "config") and self.ai_client.config is not None:
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
    ) -> dict[str, Any]:
        """
        Constructs the compact JSON payload sent to Ollama AI Advisor:
        - Target BossStage details and phase gimmicks
        - Optional FailureReport from telemetry
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

        return {
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

            # Formulate the 5 candidates: Solver pick for 6th slot as Candidate #1 + runner-ups
            cand1_ev = self.evaluate_card_against_boss(
                team_cards[5], leader, boss_stage=boss_stage, selected_team=current_5
            )
            eval_candidates = [cand1_ev]
            for ev in shortlist:
                if len(eval_candidates) >= 5:
                    break
                if ev.card.id != cand1_ev.card.id:
                    eval_candidates.append(ev)

            chosen_card, reason = self.consult_ollama_advisor(
                top_candidates=eval_candidates,
                current_team=current_5,
                boss_stage=boss_stage,
                ai_client=client,
                failure_report=failure_report,
            )
            advisor_reason = reason
            team_cards[5] = chosen_card

            # Adjust shortlist to exclude active team cards
            active_ids = {c.id for c in team_cards}
            shortlist = [ev for ev in eval_candidates if ev.card.id not in active_ids]
            for ev in solver_res.shortlist:
                if len(shortlist) >= 5:
                    break
                if ev.card.id not in active_ids and not any(s.card.id == ev.card.id for s in shortlist):
                    shortlist.append(ev)

        # 3. Build Team Recommendation Plan
        boss_target_str = (
            f"{boss_stage.event_name} - {boss_stage.stage_name}" if boss_stage else None
        )
        team_rec = self.build_team_plan(
            team_cards,
            boss_target=boss_target_str,
            language=language,
            generate_tactics=generate_tactics,
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
        )

        team_names = [f"[{c.element_name}] {c.full_name}" for c in current_team]
        phases_desc = [
            f"Phase {p.phase_index}: {p.element_name} (Cancels Dodge: {p.cancels_dodge}, AoE: {p.has_aoe}, Locks Slots: {p.locks_slots})"
            for p in boss_stage.phases
        ]

        system_msg = (
            "You are an expert Dokkan Battle Grandmaster AI Advisor. "
            "Your task is to analyze semantic passive conditions that regex rules may miss "
            "(e.g., ally-specific guard conditions, category-restricted critical hits, specific turn restrictions). "
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
            f"Phases:\n" + "\n".join(f"- {pd}" for pd in phases_desc) + "\n\n"
            + failure_text
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
        if "{" in clean_json and "}" in clean_json and not (clean_json.startswith("{") and clean_json.endswith("}")):
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
            reg_match = re.search(r"(?:selected_card_id|card_id|candidate_id)[\s*:]+(\d+)", clean_json, re.IGNORECASE)
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
                logger.warning(f"Ollama Advisor returned malformed response: {e}. Falling back smoothly.")
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
                full_reason = f"Ollama Advisor Selection: {advisor_reason}"
                if reasoning:
                    full_reason += f" [CoT: {reasoning[:200]}...]"
                logger.info(f"Ollama Advisor selected card {sel_id} ({ev.card.name})")
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

        if box_path is None:
            default_user_box = os.path.join(
                os.path.expanduser("~"), ".dokkan-farmer", "cache", "user_box.json"
            )
            box_path = default_user_box if os.path.exists(default_user_box) else "config/box.json"

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
    team_cards: list[DokkanCard], leader: DokkanCard | None = None
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
                    fl.base_form
                    and fl.base_form.sa_tags
                    and fl.base_form.sa_tags.stacks_def
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
                extra_str = f"Extra: [{', '.join(extra_names)}]" if extra_names else "Extra: Nessuna"
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
                    _resolve_category_name(cid, c, lead) for cid in c.category_ids if cid in main_set
                ]
                shared_extra = [
                    _resolve_category_name(cid, c, lead) for cid in c.category_ids if cid in extra_set
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
            c.base_form
            and c.base_form.passive_tags
            and c.base_form.passive_tags.has_guard
        )
        dr_pct = max(
            c.damage_reduction_percent,
            c.base_form.passive_tags.dr_base_percent
            if c.base_form and c.base_form.passive_tags
            else 0,
        )
        dodge_pct = max(
            100 if c.has_dodge else 0,
            c.base_form.passive_tags.dodge_chance_percent
            if c.base_form and c.base_form.passive_tags
            else 0,
        )
        guard_label = "Guard" if has_guard else "No Guard"
        def_tags_str = f"{guard_label} / DR {dr_pct}% / Dodge {dodge_pct}%"

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

    col_widths = [
        max(len(headers[i]), max(len(r[i]) for r in rows)) for i in range(len(headers))
    ]
    header_line = " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    divider_line = "-+-".join("-" * col_widths[i] for i in range(len(headers)))
    data_lines = [
        " | ".join(col.ljust(col_widths[i]) for i, col in enumerate(row))
        for row in rows
    ]

    return "\n".join([header_line, divider_line] + data_lines)


def render_team_summary_table_rich(
    team_cards: list[DokkanCard], leader: DokkanCard | None = None
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
    t = Table(title="🛡️ Dokkan AI Optimal 6-Card Team Formation", border_style="green")
    t.add_column("Slot", style="bold cyan", justify="center")
    t.add_column("Type", justify="center")
    t.add_column("Character")
    t.add_column("Leader Boost", justify="center")
    t.add_column("Ruolo", justify="center")
    t.add_column("Tag Difensivi")

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
                    fl.base_form
                    and fl.base_form.sa_tags
                    and fl.base_form.sa_tags.stacks_def
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
                    boost_style = "bold green" if lead.leader_spec.base_boost_pct >= 200 else "bold cyan"
                    boost_text = Text(f"{lead.leader_spec.base_boost_pct}% (Lead)", style=boost_style)
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
            c.base_form
            and c.base_form.passive_tags
            and c.base_form.passive_tags.has_guard
        )
        dr_pct = max(
            c.damage_reduction_percent,
            c.base_form.passive_tags.dr_base_percent
            if c.base_form and c.base_form.passive_tags
            else 0,
        )
        dodge_pct = max(
            100 if c.has_dodge else 0,
            c.base_form.passive_tags.dodge_chance_percent
            if c.base_form and c.base_form.passive_tags
            else 0,
        )
        guard_part = "Guard" if has_guard else "No Guard"
        def_tags_str = f"{guard_part} / DR {dr_pct}% / Dodge {dodge_pct}%"

        t.add_row(
            slot_str,
            Text(type_str, style=color),
            Text(name_str, style=color),
            boost_text,
            role_text,
            def_tags_str,
        )

    return t


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
]
