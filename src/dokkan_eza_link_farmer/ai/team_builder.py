from __future__ import annotations

import copy
import json
import logging
import os
from typing import Any

from dokkan_eza_link_farmer.ai.client import DokkanAIClient
from dokkan_eza_link_farmer.ai.formatters import (
    _get_global_category_map,
    _resolve_category_name,
    format_card_for_strategy,
    format_stage_tactical_briefing,
    format_team_summary_table,
    generate_deterministic_tactical_guide,
    render_stage_intel_rich,
    render_team_summary_table_rich,
)
from dokkan_eza_link_farmer.ai.llm_advisor import (
    FailureReport,
    build_advisor_payload,
    consult_ollama_advisor,
    is_ai_advisor_enabled,
    recommend_candidate,
)
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
from dokkan_eza_link_farmer.ai.synergy import (
    KI_LINKS,
    TOP_TIER_STAT_LINKS,
    calculate_link_synergy,
    calculate_slot1_anchor_weight,
    calculate_slot1_def_priority,
    check_type_matchup,
    evaluate_rotation_pair,
    find_best_partners_for_card,
    optimize_rotations_for_team,
    rate_leader_for_batch,
    rate_sub_unit,
    select_best_friend_leader,
)
from dokkan_eza_link_farmer.integrations.dokkandb_client import DokkanDBClient

logger = logging.getLogger(__name__)


class TeamBuilder:
    """Combines high-speed algorithmic constraint solving with local Ollama AI

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
    # LINK SYNERGY & ROTATION PAIRING (DELEGATED TO AI.SYNERGY)
    # =========================================================================

    @staticmethod
    def calculate_link_synergy(
        card_a: DokkanCard, card_b: DokkanCard
    ) -> tuple[float, list[str], list[str]]:
        return calculate_link_synergy(card_a, card_b)

    @staticmethod
    def calculate_slot1_def_priority(card: DokkanCard, boss_stage: Any = None) -> float:
        return calculate_slot1_def_priority(card, boss_stage=boss_stage)

    @staticmethod
    def calculate_slot1_anchor_weight(card: DokkanCard, boss_stage: Any = None) -> float:
        return calculate_slot1_anchor_weight(card, boss_stage=boss_stage)

    def evaluate_rotation_pair(
        self, card_a: DokkanCard, card_b: DokkanCard, boss_stage: Any = None
    ) -> RotationPair:
        return evaluate_rotation_pair(card_a, card_b, boss_stage=boss_stage)

    def optimize_rotations_for_team(
        self, cards: list[DokkanCard], boss_stage: Any = None
    ) -> tuple[RotationPair, RotationPair, list[DokkanCard]]:
        return optimize_rotations_for_team(cards, boss_stage=boss_stage)

    def select_best_friend_leader(
        self, cards: list[DokkanCard], candidate_pool: list[DokkanCard]
    ) -> DokkanCard:
        return select_best_friend_leader(cards, candidate_pool)

    def find_best_partners_for_card(
        self, card: DokkanCard, candidate_pool: list[DokkanCard], top_k: int = 5
    ) -> list[tuple[DokkanCard, float, list[str]]]:
        return find_best_partners_for_card(card, candidate_pool, top_k=top_k)

    @staticmethod
    def rate_leader_for_batch(card: DokkanCard, batch: Any) -> float:
        return rate_leader_for_batch(card, batch)

    @staticmethod
    def rate_sub_unit(card: DokkanCard, leader: DokkanCard) -> float:
        return rate_sub_unit(card, leader)

    @staticmethod
    def check_type_matchup(attacker_element: int, defender_element: int) -> int:
        return check_type_matchup(attacker_element, defender_element)

    # =========================================================================
    # LLM ADVISOR & FALLBACK (DELEGATED TO AI.LLM_ADVISOR)
    # =========================================================================

    def is_ai_advisor_enabled(self) -> bool:
        return is_ai_advisor_enabled(self.ai_client, self.settings_path)

    @staticmethod
    def build_advisor_payload(
        boss_stage: BossStage,
        current_team: list[DokkanCard],
        top_candidates: list[CandidateEvaluation],
        failure_report: FailureReport | None = None,
        mission_batch: Any | None = None,
    ) -> dict[str, Any]:
        return build_advisor_payload(
            boss_stage=boss_stage,
            current_team=current_team,
            top_candidates=top_candidates,
            failure_report=failure_report,
            mission_batch=mission_batch,
        )

    def consult_ollama_advisor(
        self,
        top_candidates: list[CandidateEvaluation],
        current_team: list[DokkanCard],
        boss_stage: BossStage,
        ai_client: DokkanAIClient | None = None,
        failure_report: FailureReport | None = None,
        mission_batch: Any | None = None,
    ) -> tuple[DokkanCard, str]:
        return consult_ollama_advisor(
            top_candidates=top_candidates,
            current_team=current_team,
            boss_stage=boss_stage,
            ai_client=ai_client or self.ai_client,
            failure_report=failure_report,
            mission_batch=mission_batch,
            settings_path=self.settings_path,
        )

    def recommend_candidate(
        self,
        top_candidates: list[CandidateEvaluation],
        current_team: list[DokkanCard],
        boss_stage: BossStage,
        ai_client: DokkanAIClient | None = None,
        failure_report: FailureReport | None = None,
        mission_batch: Any | None = None,
    ) -> tuple[DokkanCard, str]:
        return recommend_candidate(
            top_candidates=top_candidates,
            current_team=current_team,
            boss_stage=boss_stage,
            ai_client=ai_client or self.ai_client,
            failure_report=failure_report,
            mission_batch=mission_batch,
            settings_path=self.settings_path,
        )

    # =========================================================================
    # TEAM RECOMMENDATION & STRATEGY
    # =========================================================================

    @staticmethod
    def format_card_for_strategy(card: DokkanCard) -> str:
        return format_card_for_strategy(card)

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

        combat_team = list(cards[:6]) + [friend]
        rot_a, rot_b, floaters = self.optimize_rotations_for_team(
            combat_team, boss_stage=boss_stage
        )

        def _label_card(c: DokkanCard) -> str:
            badge = (
                " [Friend Leader]"
                if (c is friend or getattr(c, "is_friend_leader", False))
                else (" [Leader]" if c is leader else "")
            )
            return f"{self.format_card_for_strategy(c)}{badge}"

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
            tactical_guide = generate_deterministic_tactical_guide(
                rot_a=rot_a, rot_b=rot_b, floaters=floaters, leader=leader, friend=friend
            )

        return TeamRecommendation(
            leader=leader,
            friend_leader=friend,
            rotation_a=rot_a,
            rotation_b=rot_b,
            floaters=floaters,
            all_cards=cards[:6],
            tactical_analysis=tactical_guide,
            recommended_items=["Whis", "Ghost Usher", "Princess Snake"],
            ai_reasoning=ai_reasoning,
            boss_stage=boss_stage,
        )

    def build_best_team_for_batch(
        self,
        candidate_pool: list[DokkanCard],
        batch: Any,
        attempt: int = 1,
        boss_target: str | None = None,
        language: str = "it",
    ) -> TeamRecommendation:
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
        chosen_leader = leaders[(attempt - 1) % min(len(leaders), 3)]

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
    # CONSTRAINT SOLVER DELEGATION
    # =========================================================================

    def evaluate_card_against_boss(
        self,
        card: DokkanCard,
        leader: DokkanCard,
        boss_stage: BossStage | None = None,
        selected_team: list[DokkanCard] | None = None,
    ) -> CandidateEvaluation:
        ev = self.solver.evaluate_card(
            card, leader, boss_stage=boss_stage, selected_team=selected_team
        )
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
        return self.solver.get_shortlist(
            candidate_pool=candidate_pool,
            leader=leader,
            boss_stage=boss_stage,
            exclude_ids=exclude_ids,
            top_k=top_k,
        )

    # =========================================================================
    # OPTIMAL TEAM SYNTHESIS & ORCHESTRATION
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
        if len(candidate_pool) < 6:
            raise ValueError(f"Need at least 6 cards in pool, found {len(candidate_pool)}")

        solver_res: ConstraintSolverResult = self.solver.solve(
            candidate_pool=candidate_pool,
            boss_stage=boss_stage,
            forced_leader=forced_leader,
            mission_batch=mission_batch,
        )
        team_cards: list[DokkanCard] = list(solver_res.team_cards)
        shortlist: list[CandidateEvaluation] = list(solver_res.shortlist)
        advisor_reason: str | None = None

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

            cand1_ev = self.evaluate_card_against_boss(
                team_cards[5], leader, boss_stage=boss_stage, selected_team=current_5
            )
            raw_eval_candidates = [cand1_ev]
            for ev in shortlist:
                if len(raw_eval_candidates) >= 5:
                    break
                if ev.card.id != cand1_ev.card.id:
                    raw_eval_candidates.append(ev)

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

            active_ids = {c.id for c in team_cards}
            shortlist = [ev for ev in eval_candidates if ev.card.id not in active_ids]
            for ev in solver_res.shortlist:
                if len(shortlist) >= 5:
                    break
                if ev.card.id not in active_ids and not any(
                    s.card.id == ev.card.id for s in shortlist
                ):
                    shortlist.append(ev)

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

    def build_team(
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
        """Synthesizes the optimal team for a challenge stage (contract method)."""
        return self.select_best_team_for_boss(
            candidate_pool=candidate_pool,
            boss_stage=boss_stage,
            forced_leader=forced_leader,
            language=language,
            failure_report=failure_report,
            ai_client=ai_client,
            use_ai_advisor=use_ai_advisor,
            generate_tactics=generate_tactics,
            mission_batch=mission_batch,
        )

    # =========================================================================
    # USER BOX LOADER HELPER
    # =========================================================================

    @staticmethod
    def load_user_box(
        box_path: str | None = None,
        dokkandb: DokkanDBClient | None = None,
    ) -> list[DokkanCard]:
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
                cards.append(DokkanCard.from_dict(c))
            except Exception:
                try:
                    cards.append(syncer.build_dokkan_card(c))
                except Exception as inner_e:
                    logger.debug(f"Failed parsing card {c.get('id')}: {inner_e}")

        logger.info(f"Loaded {len(cards)} cards from {box_path}")
        return cards


def build_team(*args: Any, **kwargs: Any) -> tuple[TeamRecommendation, list[CandidateEvaluation]]:
    """Synthesizes the optimal team for a challenge stage (module convenience function)."""
    return TeamBuilder().build_team(*args, **kwargs)


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
    "calculate_link_synergy",
    "consult_ollama_advisor",
    "recommend_candidate",
    "build_team",
    "optimize_rotations_for_team",
    "evaluate_rotation_pair",
    "select_best_friend_leader",
    "find_best_partners_for_card",
    "format_team_summary_table",
    "render_team_summary_table_rich",
    "format_stage_tactical_briefing",
    "render_stage_intel_rich",
    "format_card_for_strategy",
    "_get_global_category_map",
    "_resolve_category_name",
]
