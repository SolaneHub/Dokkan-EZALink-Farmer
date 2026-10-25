"""Ollama AI Advisor and zero-crash deterministic fallback engine.

Provides prompt formatting for local LLM inference (DeepSeek-R1 / Qwen),
<think> tag stripping, structured JSON parsing, and zero-grade deterministic fallback
to Candidate #1 upon server offline, timeouts (>75s), malformed responses, or hallucinated IDs.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

import requests

if TYPE_CHECKING:
    from dokkan_eza_link_farmer.ai.client import DokkanAIClient
    from dokkan_eza_link_farmer.ai.models import (
        BossStage,
        DokkanCard,
    )
    from dokkan_eza_link_farmer.ai.solver import CandidateEvaluation

logger = logging.getLogger(__name__)


class AIModelFamily(str, Enum):
    """Supported AI model architectures."""

    QWEN = "qwen"


class SupportedAIModel(str, Enum):
    """The single officially supported universal model for local AI inference (RTX 3060 Ti / 8GB VRAM)."""

    QWEN_3_5_4B = "qwen3.5:4b"

    @classmethod
    def list_models(cls) -> list[str]:
        return [m.value for m in cls]

    @classmethod
    def normalize(cls, _raw: str = "") -> str:
        """Strictly validates and maps input to the supported qwen3.5:4b model."""
        return cls.QWEN_3_5_4B.value


@dataclass
class AIConfig:
    """Settings for local Ollama AI inference engine."""

    enabled: bool = False
    provider: str = "ollama"
    base_url: str = "http://localhost:11434/v1"
    model_family: AIModelFamily = AIModelFamily.QWEN
    model_name: str = SupportedAIModel.QWEN_3_5_4B.value
    api_key: str = "ollama"
    temperature: float = 0.6
    timeout_seconds: float = 75.0
    max_attempts: int = 10
    confidence_threshold: float = 0.72

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "provider": self.provider,
            "base_url": self.base_url,
            "model_family": self.model_family.value,
            "model_name": self.model_name,
            "api_key": self.api_key,
            "temperature": self.temperature,
            "timeout_seconds": self.timeout_seconds,
            "max_attempts": self.max_attempts,
            "confidence_threshold": self.confidence_threshold,
            "ollama_url": self.base_url.replace("/v1", ""),
            "ollama_model": self.model_name,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> AIConfig:
        if not data:
            return cls()

        raw_model = str(
            data.get("ollama_model") or data.get("model_name") or SupportedAIModel.QWEN_3_5_4B.value
        )
        model_name = SupportedAIModel.normalize(raw_model)
        family = AIModelFamily.QWEN

        raw_url = str(data.get("ollama_url") or data.get("base_url") or "http://localhost:11434/v1")
        if raw_url and not raw_url.endswith("/v1") and not raw_url.endswith("/v1/"):
            base_url = f"{raw_url.rstrip('/')}/v1"
        else:
            base_url = raw_url

        return cls(
            enabled=bool(data.get("enabled", False)),
            provider=str(data.get("provider", "ollama")),
            base_url=base_url,
            model_family=family,
            model_name=model_name,
            api_key=str(data.get("api_key", "ollama")),
            temperature=float(data.get("temperature", 0.6)),
            timeout_seconds=float(data.get("timeout_seconds", 75.0)),
            max_attempts=int(data.get("max_attempts", 10)),
            confidence_threshold=float(data.get("confidence_threshold", 0.72)),
        )


@dataclass
class FailureReport:
    """Structured report of combat defeat for AI telemetry and Advisor."""

    defeat_turn: int = 1
    phase_index: int = 1
    boss_element: int = 0
    boss_hp_percent: float = 100.0
    culprit_card_id: int | None = None
    classification: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "defeat_turn": self.defeat_turn,
            "phase_index": self.phase_index,
            "boss_element": self.boss_element,
            "boss_hp_percent": self.boss_hp_percent,
            "culprit_card_id": self.culprit_card_id,
            "classification": self.classification,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> FailureReport:
        if not data:
            return cls()
        return cls(
            defeat_turn=int(data.get("defeat_turn", 1)),
            phase_index=int(data.get("phase_index", 1)),
            boss_element=int(data.get("boss_element", 0)),
            boss_hp_percent=float(data.get("boss_hp_percent", 100.0)),
            culprit_card_id=int(data["culprit_card_id"])
            if data.get("culprit_card_id") is not None
            else None,
            classification=str(data.get("classification", "")),
            reason=str(data.get("reason", "")),
        )


def strip_think_tags(text: str) -> str:
    """Strips <think>...</think> reasoning tags from LLM output (DeepSeek-R1 / Qwen)."""
    if not text:
        return ""
    # Iteratively remove innermost balanced <think>...</think> blocks (case-insensitive, handles nested tags)
    prev = None
    while prev != text:
        prev = text
        text = re.sub(r"(?is)<\s*think\b[^>]*>(?:(?!<\s*think\b).)*?<\s*/\s*think\s*>", "", text)
    # Remove unclosed <think> tag to the end of string
    text = re.sub(r"(?is)<\s*think\b[^>]*>.*$", "", text)
    # Remove any leftover stray </think> tags
    text = re.sub(r"(?is)<\s*/\s*think\s*>", "", text)
    return text.strip()


def is_ai_advisor_enabled(
    ai_client: Any | None = None,
    settings_path: str = "config/settings.yaml",
) -> bool:
    """Checks whether the Ollama AI Advisor is enabled in ai_client config or settings.yaml."""
    if ai_client and hasattr(ai_client, "config") and ai_client.config is not None:
        return bool(getattr(ai_client.config, "enabled", False))

    if os.path.exists(settings_path):
        try:
            import yaml

            with open(settings_path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            ai_section = data.get("ai", {})
            if isinstance(ai_section, dict):
                return bool(ai_section.get("enabled", False))
        except Exception as e:
            logger.debug(f"Could not read settings from {settings_path}: {e}")
    return False


def build_advisor_payload(
    boss_stage: BossStage,
    current_team: list[DokkanCard],
    top_candidates: list[CandidateEvaluation],
    failure_report: FailureReport | None = None,
    mission_batch: Any | None = None,
) -> dict[str, Any]:
    """Constructs the compact JSON payload sent to Ollama AI Advisor."""
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
                else (
                    "Slot 2 Specialist (On-Hit Buildup / Stacker - Attacks First, Post-SA Tank)"
                    if getattr(c, "has_on_hit_defense", False)
                    else (
                        "Slot 2 Stacker"
                        if getattr(c, "has_stacking_def", False)
                        else "Damage/Support"
                    )
                )
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


def build_advisor_messages(
    boss_stage: BossStage,
    current_team: list[DokkanCard],
    payload: dict[str, Any],
    failure_report: FailureReport | None = None,
    mission_batch: Any | None = None,
) -> list[dict[str, str]]:
    """Constructs system and user prompt messages for Ollama LLM inference."""
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
        desc += (
            f" (Cancels Dodge: {p.cancels_dodge}, AoE: {p.has_aoe}, Locks Slots: {p.locks_slots})"
        )
        phases_desc.append(desc)

    mission_constraint_rules = ""
    mission_user_section = ""
    if mission_batch is not None:
        summary = getattr(mission_batch, "summary", "")
        req_cats = getattr(mission_batch, "required_categories", [])
        req_cats_str = ", ".join(f"{cnt}x '{cat}'" for cnt, cat in req_cats) if req_cats else "None"
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
        "CRITICAL MANDATORY REQUIREMENT: You MUST evaluate unit survivability and effectiveness across ALL battles and ALL phases of the stage "
        "(from Phase 1 / Turn 1 to the final phase). A candidate that is strong against the final boss but has severe type disadvantage "
        "or dies in Phase 1 (especially against initial multi-enemy attack barrages) is UNACCEPTABLE. Favor candidates that guarantee survival across the entire gauntlet. "
        "CRITICAL SLOT 1 SURVIVABILITY: Units whose Guard, Damage Reduction, or DEF only activate 'when receiving an attack', 'after receiving an attack', 'for every attack received', or are '(once only)' are NOT true Slot 1 tanks and will get oneshotted by an initial enemy Super Attack. Never select or recommend them as Slot 1 anchors. True Slot 1 anchors must possess unconditional pre-attack Guard, high pre-attack Damage Reduction (>= 50%), or high Dodge (>= 70%). "
        "CRITICAL SLOT 2 OPTIMIZATION: Units with on-hit defense mechanics or defense stacking on Super Attack are PRIME SLOT 2 SPECIALISTS. In Slot 2, they launch their Super Attack first (raising/stacking DEF and activating post-super passives), and only then receive attacks to safely trigger their on-hit build-up. Keep them in main rotation (Slot 2) paired with a true Slot 1 tank so they stack every 2 turns; do NOT place them in Slot 1, and avoid floating them to Slot 3 (which delays their stacking). "
        "CRITICAL ENEMY-CONDITIONAL PASSIVE RESTRICTION: Units whose Damage Reduction, Guard, or Dodge depend on specific enemy categories or classes (e.g. TEQ SSG Goku with 77% DR against 'Movie Bosses' or 'Pure Saiyans') LOSE their defense entirely if ANY phase of the stage does not feature that enemy category (e.g. Toppo, Goku Black, Cell, Buu). If a stage contains ANY non-matching phase, NEVER select or place such units in rotation as they will take catastrophic fatal damage. "
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

    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_content},
    ]


def extract_advisor_candidate(
    content: str,
    reasoning: str | None,
    top_candidates: list[CandidateEvaluation],
) -> tuple[int | None, str, str | None]:
    """Extracts candidate ID and reasoning from LLM advisor output.

    Returns:
        (selected_card_id, reasoning_str, error_type)
        where error_type is None on success, or:
        - "malformed" if parsing failed or no ID was identified
        - "hallucinated" if extracted ID is outside top_candidates shortlist
    """
    clean_json = strip_think_tags(content)

    # 1. Strip markdown code blocks if returned
    if "```" in clean_json:
        match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", clean_json)
        if match:
            clean_json = match.group(1).strip()

    # 2. Extract JSON object containing selected_card_id or first valid JSON object
    candidate_json = None
    if "{" in clean_json and "}" in clean_json:
        match = re.search(r"\{[^{}]*\"selected_card_id\"[^{}]*\}", clean_json, re.DOTALL)
        if match:
            candidate_json = match.group(0).strip()
        else:
            for m in re.finditer(r"(\{[\s\S]*?\})", clean_json):
                try:
                    candidate = m.group(1).strip()
                    parsed_test = json.loads(candidate)
                    if isinstance(parsed_test, dict):
                        candidate_json = candidate
                        break
                except Exception:
                    continue
        if not candidate_json:
            match = re.search(r"(\{[\s\S]*\})", clean_json)
            if match:
                candidate_json = match.group(1).strip()
    if candidate_json:
        clean_json = candidate_json

    # 3. Fallback: If clean_json has no '{', try extracting JSON from reasoning if available
    if (not clean_json or "{" not in clean_json) and reasoning:
        clean_reasoning = strip_think_tags(reasoning)
        match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", clean_reasoning)
        if match:
            clean_json = match.group(1).strip()
        else:
            match = re.search(r"\{[^{}]*\"selected_card_id\"[^{}]*\}", clean_reasoning, re.DOTALL)
            if match:
                clean_json = match.group(0).strip()
            else:
                match = re.search(r"(\{[\s\S]*\})", clean_reasoning)
                if match:
                    clean_json = match.group(1).strip()

    sel_id: int | None = None
    advisor_reason = ""
    try:
        parsed = json.loads(clean_json)
        if isinstance(parsed, dict):
            raw_id = None
            for key in (
                "selected_card_id",
                "card_id",
                "candidate_id",
                "selected_id",
                "recommendation",
                "recommended_card",
                "recommended_card_id",
                "choice",
                "card",
                "id",
            ):
                if parsed.get(key) is not None:
                    raw_id = parsed[key]
                    break

            if raw_id is None:
                for subval in parsed.values():
                    if isinstance(subval, dict):
                        for key in ("selected_card_id", "card_id", "candidate_id", "id"):
                            if subval.get(key) is not None:
                                raw_id = subval[key]
                                break
                        if raw_id is not None:
                            break

            if raw_id is not None:
                try:
                    sel_id = int(raw_id)
                except (ValueError, TypeError):
                    sel_id = None

            advisor_reason = str(
                parsed.get("reasoning")
                or parsed.get("reason")
                or parsed.get("explanation")
                or parsed.get("message")
                or ""
            )
    except Exception:
        pass

    if sel_id is None:
        # Fallback A: Extract candidate ID via regex matching optional quotes, spaces, colon/equals
        reg_match = re.search(
            r"(?:selected_card_id|card_id|candidate_id|selected_id|choice|recommended_card)[\"'\s]*[:=][\"'\s]*(\d+)",
            clean_json,
            re.IGNORECASE,
        )
        if reg_match:
            sel_id = int(reg_match.group(1))
            reason_match = re.search(
                r"reasoning[\"'\s]*[:=][\"'\s]*\"?([^\"}\r\n]+)",
                clean_json,
                re.IGNORECASE,
            )
            if not advisor_reason:
                advisor_reason = (
                    reason_match.group(1).strip() if reason_match else clean_json.strip()
                )
        else:
            # Fallback B: Scan if any candidate ID in the top shortlist is mentioned as a full token
            for ev in top_candidates[:5]:
                if re.search(rf"\b{re.escape(str(ev.card.id))}\b", clean_json):
                    sel_id = ev.card.id
                    if not advisor_reason:
                        advisor_reason = clean_json.strip()
                    break

    if not sel_id:
        return None, "", "malformed"

    # Verify that the selected ID is among the top candidates shortlist
    shortlist_ids = {ev.card.id for ev in top_candidates[:5]}
    if sel_id not in shortlist_ids:
        return sel_id, advisor_reason, "hallucinated"

    return sel_id, advisor_reason, None


def parse_advisor_response(
    content: str,
    reasoning: str | None,
    top_candidates: list[CandidateEvaluation],
) -> tuple[int, str] | None:
    """Parses candidate ID and reasoning from LLM advisor output.

    Strips <think> tags, extracts JSON or markdown blocks, and validates against shortlist.
    Returns (selected_card_id, reasoning_str) or None if parsing fails.
    """
    sel_id, advisor_reason, error_type = extract_advisor_candidate(
        content=content,
        reasoning=reasoning,
        top_candidates=top_candidates,
    )
    if error_type is not None or sel_id is None:
        return None
    return sel_id, advisor_reason


def consult_ollama_advisor(
    top_candidates: list[CandidateEvaluation],
    current_team: list[DokkanCard],
    boss_stage: BossStage,
    ai_client: DokkanAIClient | None = None,
    failure_report: FailureReport | None = None,
    mission_batch: Any | None = None,
    settings_path: str = "config/settings.yaml",
) -> tuple[DokkanCard, str]:
    """Consults local Ollama LLM (DeepSeek-R1 / Qwen) to evaluate subtle semantic conditions

    in passive skills across the Top 5 candidates, acting as a semantic tie-breaker.
    Gracefully falls back to Candidate #1 if Ollama is disabled, offline, times out (>75s),
    returns malformed output, or returns an ID outside the Top 5 shortlist.
    """
    if not top_candidates:
        raise ValueError("No candidates provided for Ollama Advisor.")

    fallback_choice = top_candidates[0].card

    # 1. Check if explicitly disabled in config
    if ai_client and hasattr(ai_client, "config") and ai_client.config is not None:
        if getattr(ai_client.config, "enabled", True) is False:
            logger.debug("Ollama AI Advisor disabled in client config.")
            return (
                fallback_choice,
                "Algorithmic Solver Top-Ranked Choice (AI Advisor Disabled in Settings)",
            )
    elif (
        not is_ai_advisor_enabled(ai_client=ai_client, settings_path=settings_path)
        and ai_client is None
    ):
        logger.debug("Ollama AI Advisor disabled in settings.")
        return (
            fallback_choice,
            "Algorithmic Solver Top-Ranked Choice (AI Advisor Disabled in Settings)",
        )

    # 2. Server availability check (Offline)
    if not ai_client or not ai_client.is_available():
        logger.info("Ollama AI server not responding; using Algorithmic Solver Candidate #1.")
        return (
            fallback_choice,
            "Algorithmic Solver Top-Ranked Choice (Offline / Graceful Fallback)",
        )

    try:
        # 3. Construct structured payload
        payload = build_advisor_payload(
            boss_stage=boss_stage,
            current_team=current_team,
            top_candidates=top_candidates,
            failure_report=failure_report,
            mission_batch=mission_batch,
        )

        messages = build_advisor_messages(
            boss_stage=boss_stage,
            current_team=current_team,
            payload=payload,
            failure_report=failure_report,
            mission_batch=mission_batch,
        )

        logger.info("Querying local Ollama AI Advisor for semantic tie-break...")
        content, reasoning = ai_client.chat_completion(
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

    # Clean and parse response
    sel_id, advisor_reason, error_type = extract_advisor_candidate(
        content=content,
        reasoning=reasoning,
        top_candidates=top_candidates,
    )

    if error_type == "malformed" or sel_id is None:
        logger.warning("Ollama Advisor returned malformed response. Falling back smoothly.")
        return (
            fallback_choice,
            "Algorithmic Solver Top-Ranked Choice (Malformed Response Fallback)",
        )

    if error_type == "hallucinated":
        shortlist_ids = {ev.card.id for ev in top_candidates[:5]}
        logger.warning(
            f"Ollama returned ID {sel_id} not in candidates shortlist ({shortlist_ids}); falling back to Solver #1."
        )
        return (
            fallback_choice,
            "Algorithmic Solver Top-Ranked Choice (Invalid / Hallucinated ID Fallback)",
        )

    for ev in top_candidates[:5]:
        if ev.card.id == sel_id:
            full_reason = (
                f"Qwen Advisor: {advisor_reason}"
                if advisor_reason
                else f"Qwen Advisor selected card {sel_id}"
            )
            logger.info(f"Qwen Advisor selected card {sel_id} ({ev.card.name})")
            return ev.card, full_reason

    return fallback_choice, "Algorithmic Solver Top-Ranked Choice (Offline / Graceful Fallback)"


def recommend_candidate(
    top_candidates: list[CandidateEvaluation],
    current_team: list[DokkanCard],
    boss_stage: BossStage,
    ai_client: DokkanAIClient | None = None,
    failure_report: FailureReport | None = None,
    mission_batch: Any | None = None,
    settings_path: str = "config/settings.yaml",
) -> tuple[DokkanCard, str]:
    """Recommends candidate using Ollama Advisor with zero-grade fallback (contract function)."""
    return consult_ollama_advisor(
        top_candidates=top_candidates,
        current_team=current_team,
        boss_stage=boss_stage,
        ai_client=ai_client,
        failure_report=failure_report,
        mission_batch=mission_batch,
        settings_path=settings_path,
    )


__all__ = [
    "AIModelFamily",
    "SupportedAIModel",
    "AIConfig",
    "FailureReport",
    "strip_think_tags",
    "is_ai_advisor_enabled",
    "build_advisor_payload",
    "build_advisor_messages",
    "extract_advisor_candidate",
    "parse_advisor_response",
    "consult_ollama_advisor",
    "recommend_candidate",
]
