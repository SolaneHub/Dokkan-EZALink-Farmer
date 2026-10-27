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
from pathlib import Path
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


_CACHED_TACTICAL_MATRIX: dict[str, Any] | None = None
_CACHED_DAMAGE_BENCHMARKS: dict[str, Any] | None = None


def _get_project_data_path(filename: str) -> Path | None:
    """Resolves project-relative path to a data file, checking parent directories and CWD."""
    current = Path(__file__).resolve().parent
    for _ in range(5):
        candidate = current / "data" / filename
        if candidate.is_file():
            return candidate
        if (current / "pyproject.toml").is_file() or (current / ".git").is_dir():
            candidate = current / "data" / filename
            if candidate.is_file():
                return candidate
        current = current.parent

    cwd_candidate = Path.cwd() / "data" / filename
    if cwd_candidate.is_file():
        return cwd_candidate

    direct_cwd = Path.cwd() / filename
    if direct_cwd.is_file():
        return direct_cwd

    return None


def load_cards_tactical_matrix(reload: bool = False) -> dict[str, Any]:
    """Loads and caches the Dokkan cards tactical matrix from data/cards_tactical_matrix.json.

    Returns the parsed dictionary. If missing or invalid, returns an empty dictionary gracefully.
    """
    global _CACHED_TACTICAL_MATRIX
    if _CACHED_TACTICAL_MATRIX is not None and not reload:
        return _CACHED_TACTICAL_MATRIX

    path = _get_project_data_path("cards_tactical_matrix.json")
    if path and path.is_file():
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    _CACHED_TACTICAL_MATRIX = data
                    return _CACHED_TACTICAL_MATRIX
        except Exception as exc:
            logger.warning("Failed to load cards tactical matrix from %s: %s", path, exc)

    _CACHED_TACTICAL_MATRIX = {}
    return _CACHED_TACTICAL_MATRIX


def load_damage_simulation_benchmarks(reload: bool = False) -> dict[str, Any]:
    """Loads and caches endgame damage simulation benchmarks from data/damage_simulation_benchmarks.json.

    Returns the parsed dictionary. If missing or invalid, returns an empty dictionary gracefully.
    """
    global _CACHED_DAMAGE_BENCHMARKS
    if _CACHED_DAMAGE_BENCHMARKS is not None and not reload:
        return _CACHED_DAMAGE_BENCHMARKS

    path = _get_project_data_path("damage_simulation_benchmarks.json")
    if path and path.is_file():
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    _CACHED_DAMAGE_BENCHMARKS = data
                    return _CACHED_DAMAGE_BENCHMARKS
        except Exception as exc:
            logger.warning("Failed to load damage simulation benchmarks from %s: %s", path, exc)

    _CACHED_DAMAGE_BENCHMARKS = {}
    return _CACHED_DAMAGE_BENCHMARKS


def _lookup_tactical_matrix_entry(card_id: int) -> dict[str, Any] | None:
    """Helper to look up a card's tactical entry in cards_tactical_matrix.json."""
    matrix = load_cards_tactical_matrix()
    if not matrix:
        return None
    by_id = matrix.get("cards_by_id")
    if isinstance(by_id, dict):
        entry = by_id.get(str(card_id)) or by_id.get(card_id)
        if entry and isinstance(entry, dict):
            return entry
    cards = matrix.get("cards")
    if isinstance(cards, list):
        for c in cards:
            if isinstance(c, dict) and c.get("card_id") == card_id:
                return c
    return None


def _lookup_damage_benchmark_entry(card_id: int) -> dict[str, Any] | None:
    """Helper to look up a card's damage benchmark entry in damage_simulation_benchmarks.json."""
    benchmarks_data = load_damage_simulation_benchmarks()
    if not benchmarks_data:
        return None
    benchmarks = benchmarks_data.get("benchmarks")
    if isinstance(benchmarks, dict):
        entry = benchmarks.get(str(card_id)) or benchmarks.get(card_id)
        if entry and isinstance(entry, dict):
            return entry
    return None


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
        card_id = getattr(card, "id", None) or getattr(card, "card_id", 0)
        has_s23_guard = getattr(card, "has_slot_2_3_guard", False)
        has_s1_guard = getattr(card, "has_slot_1_only_guard", False)
        intro_turns = getattr(card, "guard_turns_limit", None) or getattr(
            card, "dr_turns_limit", None
        )
        guard_type = getattr(ev, "guard_type", "none")
        tactical_guard_type = (
            "unconditional" if getattr(card, "is_guard_unconditional", False) else guard_type
        )
        if has_s23_guard:
            tactical_guard_type = "slot_2_3_locked"
        elif has_s1_guard:
            tactical_guard_type = "slot_1_only"
        elif intro_turns:
            tactical_guard_type = f"turn_limited_{intro_turns}T"

        matrix_entry = _lookup_tactical_matrix_entry(card_id)
        bench_entry = _lookup_damage_benchmark_entry(card_id)

        # Intro cliff detection
        if matrix_entry is not None and "has_intro_cliff" in matrix_entry:
            has_intro_cliff = bool(matrix_entry.get("has_intro_cliff", False))
            cliff_turn = matrix_entry.get("cliff_turn")
        else:
            has_intro_cliff = bool(intro_turns is not None and intro_turns > 0)
            cliff_turn = intro_turns

        # Slot scoring (0.0 - 10.0 scale)
        if card_id == 1030481:
            slot1_score = 0.0
            slot2_score = float(matrix_entry.get("slot2_score", 9.5)) if matrix_entry else 9.5
            slot3_score = float(matrix_entry.get("slot3_score", 8.5)) if matrix_entry else 8.5
            has_intro_cliff = True
            cliff_turn = 3
        elif card_id == 1015201:
            slot1_score = 0.0
            slot2_score = float(matrix_entry.get("slot2_score", 3.0)) if matrix_entry else 3.0
            slot3_score = float(matrix_entry.get("slot3_score", 5.0)) if matrix_entry else 5.0
            has_intro_cliff = False
            cliff_turn = None
        elif matrix_entry is not None:
            slot1_score = float(matrix_entry.get("slot1_score", 0.0))
            slot2_score = float(matrix_entry.get("slot2_score", 0.0))
            slot3_score = float(matrix_entry.get("slot3_score", 0.0))
        else:
            if has_s23_guard or not ev.base_slot1_viable:
                slot1_score = 0.0
            else:
                slot1_score = 7.5 if getattr(card, "is_slot1_tank", False) else 5.0
            slot2_score = 8.0
            slot3_score = 7.0

        # Team-conditional bypass check (e.g. Majin Vegeta 1033061 in 5+ Extreme team)
        team_def = (
            card.calculate_team_conditional_defense(current_team)
            if hasattr(card, "calculate_team_conditional_defense")
            else {}
        )
        bypasses_orbs = team_def.get("bypasses_orb_requirement", False)

        # Slot 1 status: str ("LETHAL", "SURVIVED", or "VIABLE")
        if bypasses_orbs:
            slot1_score = 9.8
            slot1_status = "VIABLE"
        elif card_id in (1030481, 1015201) or slot1_score == 0.0 or has_s23_guard:
            slot1_score = 0.0
            slot1_status = "LETHAL"
        elif matrix_entry is not None and "slot1_status" in matrix_entry:
            raw_status = str(matrix_entry["slot1_status"])
            if raw_status in ("LETHAL", "VIABLE"):
                slot1_status = raw_status
            elif raw_status == "UNSTABLE":
                bench_status = (
                    bench_entry.get("slot_evaluations", {}).get("slot_1", {}).get("status")
                    if isinstance(bench_entry, dict)
                    else None
                )
                if bench_status == "LETHAL":
                    slot1_status = "LETHAL"
                elif bench_status in ("SURVIVES", "SURVIVED"):
                    slot1_status = "SURVIVED"
                elif bench_status in ("SAFE", "IMMUNE"):
                    slot1_status = "VIABLE"
                else:
                    slot1_status = "LETHAL" if slot1_score < 4.0 else "SURVIVED"
            elif raw_status in ("SURVIVES", "SURVIVED"):
                slot1_status = "SURVIVED"
            else:
                slot1_status = "VIABLE" if ev.base_slot1_viable else "LETHAL"
        elif bench_entry is not None:
            bench_status = (
                bench_entry.get("slot_evaluations", {}).get("slot_1", {}).get("status", "")
            )
            if bench_status == "LETHAL":
                slot1_status = "LETHAL"
            elif bench_status in ("SURVIVES", "SURVIVED"):
                slot1_status = "SURVIVED"
            elif bench_status in ("SAFE", "IMMUNE"):
                slot1_status = "VIABLE"
            else:
                slot1_status = "VIABLE" if ev.base_slot1_viable else "LETHAL"
        else:
            slot1_status = "VIABLE" if ev.base_slot1_viable else "LETHAL"

        # Damage simulation benchmarks mapping 2.5M, 3.5M, 4.2M boss SA
        damage_simulations: dict[str, dict[str, Any]] = {}
        slot1_sims: dict[str, Any] = {}
        if bench_entry and isinstance(bench_entry, dict):
            slot1_eval = bench_entry.get("slot_evaluations", {}).get("slot_1", {})
            if isinstance(slot1_eval, dict):
                slot1_sims = slot1_eval.get("simulations", {})

        threshold_map = [
            ("2.5M", "boss_2_5m", 2_500_000),
            ("3.5M", "boss_3_5m", 3_500_000),
            ("4.2M", "boss_4_2m", 4_200_000),
        ]

        for label, bench_key, atk_val in threshold_map:
            sim_item = slot1_sims.get(bench_key) or slot1_sims.get(label)
            if sim_item and isinstance(sim_item, dict):
                dmg_taken = int(sim_item.get("damage_taken", sim_item.get("damage", 0)))
                status_raw = str(
                    sim_item.get("status", "LETHAL" if dmg_taken >= 700_000 else "SURVIVED")
                )
                damage_simulations[label] = {
                    "damage_taken": dmg_taken,
                    "damage": dmg_taken,
                    "status": status_raw,
                    "survived": status_raw != "LETHAL",
                }
            else:
                if card_id == 1030481:
                    default_dmgs = {"2.5M": 2_575_000, "3.5M": 3_724_999, "4.2M": 4_530_000}
                    d_val = default_dmgs[label]
                    damage_simulations[label] = {
                        "damage_taken": d_val,
                        "damage": d_val,
                        "status": "LETHAL",
                        "survived": False,
                    }
                elif card_id == 1015201:
                    default_dmgs = {"2.5M": 875_000, "3.5M": 1_275_000, "4.2M": 1_555_000}
                    d_val = default_dmgs[label]
                    damage_simulations[label] = {
                        "damage_taken": d_val,
                        "damage": d_val,
                        "status": "LETHAL",
                        "survived": False,
                    }
                elif slot1_status == "LETHAL":
                    damage_simulations[label] = {
                        "damage_taken": atk_val,
                        "damage": atk_val,
                        "status": "LETHAL",
                        "survived": False,
                    }
                else:
                    dr = getattr(card, "damage_reduction_percent", 0) or 0
                    has_guard = getattr(card, "has_guard", False)
                    def_stat = getattr(card, "defense", 250_000) or 250_000
                    type_mod = 0.8 if has_guard else 1.0
                    guard_red = 0.5 if has_guard else 1.0
                    dmg_before_def = atk_val * type_mod * (1.0 - (dr / 100.0))
                    dmg_after_def = max(0.0, dmg_before_def - def_stat)
                    calc_dmg = int(dmg_after_def * guard_red)
                    calc_status = (
                        "LETHAL"
                        if calc_dmg >= 700_000
                        else ("SURVIVES" if calc_dmg < 500_000 else "VULNERABLE")
                    )
                    damage_simulations[label] = {
                        "damage_taken": calc_dmg,
                        "damage": calc_dmg,
                        "status": calc_status,
                        "survived": calc_status != "LETHAL",
                    }

        # Numeric Slot 1 Penalty determination
        slot_1_penalty = None
        if slot1_score == 0.0 or slot1_status == "LETHAL":
            if has_s23_guard or card_id == 1030481:
                slot_1_penalty = (
                    "-45.0: Slot 2/3 restricted guard - Fatal Slot 1 trap, do NOT place in Slot 1"
                )
            elif has_s1_guard or card_id == 1015201:
                slot_1_penalty = "-50.0: Slot-1 restricted naked guard without DR/Dodge against lethal boss SA - Fatal Slot 1 trap, do NOT place in Slot 1"
            else:
                slot_1_penalty = "-50.0: Fatal Slot 1 vulnerability - Catastrophic lethal damage against endgame boss SA, do NOT place in Slot 1"
        elif has_s23_guard:
            slot_1_penalty = (
                "-45.0: Slot 2/3 restricted guard - Fatal Slot 1 trap, do NOT place in Slot 1"
            )
        elif has_s1_guard and not ev.base_slot1_viable:
            slot_1_penalty = (
                "-20.0: Slot-1 restricted naked guard without DR/Dodge against lethal boss SA"
            )
        elif (
            getattr(card, "has_orb_conditional_defense", False)
            and not bypasses_orbs
            and not getattr(card, "pre_hit_guard", False)
            and getattr(card, "pre_hit_dr_percent", 0) < 50
        ):
            slot_1_penalty = (
                "-25.0: Relies on Ki Spheres for defense - inactive pre-attack in Slot 1"
            )

        # Determine slot_restrictions tag
        from dokkan_eza_link_farmer.ai.tactical_dictionary import SLOT_2_3_LOCKED_IDS

        if bypasses_orbs:
            slot_restrictions = "SLOT_1_SAFE"
        elif has_s23_guard or card_id in SLOT_2_3_LOCKED_IDS:
            slot_restrictions = "SLOT_2_LOCKED"
        elif has_intro_cliff and cliff_turn is not None and cliff_turn <= 5:
            slot_restrictions = "INTRO_CLIFF_TURN_5"
        elif (
            getattr(card, "has_orb_conditional_defense", False)
            and not getattr(card, "pre_hit_guard", False)
            and getattr(card, "pre_hit_dr_percent", 0) < 50
        ):
            slot_restrictions = "SLOT_2_LOCKED"
        elif (
            ev.base_slot1_viable
            and slot1_score >= 5.0
            and slot1_status != "LETHAL"
            or has_s1_guard
            and ev.base_slot1_viable
        ):
            slot_restrictions = "SLOT_1_SAFE"
        else:
            slot_restrictions = "SLOT_2_LOCKED"

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
                "guard_type": guard_type,
                "tactical_guard_type": tactical_guard_type,
                "defensive_tier": getattr(ev, "defensive_tier", ""),
                "estimated_sa_damage_taken": getattr(ev, "estimated_damage_taken", None),
                "dr_percent": int(team_def.get("dr", getattr(card, "damage_reduction_percent", 0)))
                if bypasses_orbs
                else getattr(card, "damage_reduction_percent", 0),
                "has_slot_1_only_guard": has_s1_guard,
                "has_slot_2_3_guard": has_s23_guard,
                "intro_turns": intro_turns,
                "slot_1_penalty": slot_1_penalty,
                "slot1_score": slot1_score,
                "slot2_score": slot2_score,
                "slot3_score": slot3_score,
                "has_intro_cliff": has_intro_cliff,
                "cliff_turn": cliff_turn,
                "slot1_status": slot1_status,
                "slot_restrictions": slot_restrictions,
                "damage_simulations": damage_simulations,
                "tactical_timeline": card.get_tactical_form_timeline()
                if hasattr(card, "get_tactical_form_timeline")
                else [],
                "transformations": [
                    {
                        "form_id": t.form_id,
                        "form_name": t.form_name,
                        "min_turn": t.min_turn,
                        "passive_summary": t.passive_skill_text[:200]
                        if t.passive_skill_text
                        else "",
                    }
                    for t in getattr(card, "transformations", [])
                ],
                "active_skill": (
                    {
                        "name": card.active_skill_name,
                        "effect": card.active_skill_effect,
                        "condition": card.active_skill_condition,
                    }
                    if getattr(card, "active_skill_name", "")
                    else None
                ),
                "standby_skill": (
                    {
                        "name": card.standby_skill_name,
                        "effect": card.standby_skill_effect,
                        "condition": card.standby_skill_condition,
                    }
                    if getattr(card, "standby_skill_name", "")
                    else None
                ),
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
        "CRITICAL DOKKAN DAMAGE FORMULA & ORDER OF OPERATIONS: "
        "Damage Taken = {[(Enemy ATK * Variance * Type Modifier) * (1 - DR%)] - Ally DEF} * Guard Reduction. "
        "1. Damage Reduction (DR%) multiplies BEFORE Ally DEF subtraction, shrinking huge boss attacks so DEF can absorb the remainder. "
        "2. Guard applies AFTER DEF subtraction (halving damage by 0.5), while setting Type Modifier to 0.8. "
        "3. NEVER equate Guard to 50% DR! Units with 'Naked Guard' (Guard without DR and with low pre-super DEF) suffer fatal ONESHOT damage (>1M) from 2.5M+ Super Attacks in Slot 1. "
        "4. Natural Guard vs Passive Guard: Units with Natural Type Advantage (e.g. INT vs TEQ boss) ALREADY have Natural Guard (50% Guard Reduction + ~0.9x Type Mod). Passive guard on them is mostly redundant; prioritize DR, DEF stacking, or dodge. "
        "5. True Slot 1 God Tanks possess BOTH Guard and DR (e.g. Beast Gohan), heavy DR (>= 60-70%), or high Dodge (>= 70%). Units with Naked Guard, on-hit buildup, or post-super DEF belong in Slot 2 to super first. "
        "CRITICAL POST-10TH ANNIVERSARY TACTICAL MATRIX & DAMAGE BENCHMARKS (2.5M, 3.5M, 4.2M SA): "
        "Candidates with slot1_score == 0.0 or slot1_status == 'LETHAL' in Slot 1 (such as LR Gogeta 1030481 or Supreme Kai 1015201) "
        "suffer catastrophic one-shots (>1.5M damage) and MUST NEVER be selected or advised for Slot 1. "
        "Always inspect slot1_score, slot1_status, slot_restrictions, and damage_simulations (2.5M, 3.5M, 4.2M) in candidate data. "
        "Strictly adhere to slot_restrictions: "
        "'SLOT_1_SAFE' can anchor Slot 1; 'SLOT_2_LOCKED' MUST NEVER be put in Slot 1; 'INTRO_CLIFF_TURN_5' loses its guard/DR after entry turn 5 and must rotate out. "
        "CRITICAL SLOT 1 SURVIVABILITY: Units whose Guard, Damage Reduction, or DEF only activate 'when receiving an attack', 'after receiving an attack', 'for every attack received', "
        "or are '(once only)', or are restricted to 'As the 2nd or 3rd attacker in a turn' (has_slot_2_3_guard) are NOT true Slot 1 tanks and will get oneshotted by an initial enemy Super Attack. "
        "NEVER select, assign, or recommend them as Slot 1 anchors. "
        "CRITICAL INTRO CLIFF EFFECT: Units with 'For X turns from character's entry turn' temporary guard or DR (e.g. 3-turn intro) experience a massive defensive cliff after Turn 4 (Turn 5 onwards). In long fights (>= 3 phases), they must be transitioned to Slot 2 or Slot 3 once their intro expiration approaches. "
        "CRITICAL SLOT 2 OPTIMIZATION: Units with on-hit defense mechanics, Naked Guard, defense stacking on Super Attack, or Slot 2/3 conditional guard (e.g. LR Gogeta 1030481) are PRIME SLOT 2 SPECIALISTS. In Slot 2, they launch their Super Attack first (raising/stacking DEF, activating post-super passives and enabling their Slot 2/3 Guard), and only then receive attacks to safely trigger their on-hit build-up. Keep them in main rotation (Slot 2) paired with a true Slot 1 tank so they stack every 2 turns; do NOT place them in Slot 1, and avoid floating them to Slot 3 (which delays their stacking). "
        "CRITICAL ENEMY-CONDITIONAL PASSIVE RESTRICTION: Units whose Damage Reduction, Guard, or Dodge depend on specific enemy categories or classes (e.g. TEQ SSG Goku with 77% DR against 'Movie Bosses' or 'Pure Saiyans') LOSE their defense entirely if ANY phase of the stage does not feature that enemy category (e.g. Toppo, Goku Black, Cell, Buu). If a stage contains ANY non-matching phase, NEVER select or place such units in rotation as they will take catastrophic fatal damage. "
        "CRITICAL SLOT 1-RESTRICTED DEFENSE: Units whose Guard or Damage Reduction is restricted to 'As the 1st attacker in a turn' (has_slot_1_only_guard) have ZERO guard and ZERO DR in Slot 2 or Slot 3. If floated to Slot 3, their defense is completely disabled and they will get oneshotted by normal attacks. If they lack base stats/DR to survive Slot 1 against a 2M+ SA boss, they are unplayable in high-difficulty events and MUST NOT be selected or floated. "
        "CRITICAL KI SPHERE CONDITIONAL DEFENSE & ORB-CHANGER SYNERGY: Units whose Damage Reduction, Guard, or Dodge requires Ki Spheres (e.g. 'with 3 or more Ki Spheres obtained', 'per Ki Sphere obtained', or 'with Rainbow Ki Spheres obtained') DO NOT have that defense active pre-attack in Slot 1 because Ki Spheres are collected when the unit takes its turn to attack! Never assign an orb-dependent unit as an unshielded Slot 1 anchor against pre-attack enemy hits. Furthermore, orb-hungry units MUST be paired with Orb Changers (especially Rainbow Ki Sphere Changers) or placed in Slot 2/3 to guarantee consistent orb acquisition and prevent fatal orb starvation. "
        "CRITICAL DUAL CONDITIONAL PASSIVES (OR-CONDITIONS): Units like Majin Vegeta (1033061) or SSJ2 Goku Angel (4033071) feature dual activation paths: [X Ki Spheres obtained] OR [when Y or more Extreme/Super Class allies are on the team]. When deployed in an Extreme-centric team (>= 5 Extreme allies), Majin Vegeta achieves up to 72% Damage Reduction and Guard BEFORE ATTACKING from start of turn without needing any Ki Spheres, making him a prime Slot 1 God-Wall. Conversely, in Super-centric teams (< 3 Extreme allies), he is forced into the Ki Sphere path (needing 7 spheres for full DR), shifting his optimal position to Slot 2/3. "
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


def _parse_candidate_dict(
    parsed: dict[str, Any], top_candidates: list[CandidateEvaluation]
) -> tuple[int | None, str]:
    """Extracts card ID and reasoning from a parsed JSON dictionary."""
    primary_keys = (
        "selected_card_id",
        "best_candidate_id",
        "recommended_card_id",
        "recommended_id",
        "choice_id",
        "target_id",
        "choice",
    )
    secondary_keys = (
        "candidate_id",
        "card_id",
        "card",
        "id",
    )

    sel_id = None
    advisor_reason = ""

    # 1. Top-level key scan for primary keys
    for k in primary_keys:
        val = parsed.get(k)
        if val is not None:
            if isinstance(val, int):
                sel_id = val
                break
            elif isinstance(val, str) and val.strip().isdigit():
                sel_id = int(val.strip())
                break
            elif isinstance(val, dict) and "id" in val:
                try:
                    sel_id = int(val["id"])
                    break
                except (ValueError, TypeError):
                    pass

    # 2. Check nested dicts for primary keys
    if sel_id is None:
        for subval in parsed.values():
            if isinstance(subval, dict):
                for k in primary_keys:
                    if subval.get(k) is not None:
                        val = subval[k]
                        if isinstance(val, int):
                            sel_id = val
                            break
                        elif isinstance(val, str) and val.strip().isdigit():
                            sel_id = int(val.strip())
                            break
                if sel_id is not None:
                    break

    # 3. Secondary keys top-level
    if sel_id is None:
        for k in secondary_keys:
            val = parsed.get(k)
            if val is not None:
                if isinstance(val, int):
                    sel_id = val
                    break
                elif isinstance(val, str) and val.strip().isdigit():
                    sel_id = int(val.strip())
                    break
                elif isinstance(val, dict) and "id" in val:
                    try:
                        sel_id = int(val["id"])
                        break
                    except (ValueError, TypeError):
                        pass

    # 4. Check nested dicts for secondary keys
    if sel_id is None:
        for subval in parsed.values():
            if isinstance(subval, dict):
                for k in secondary_keys:
                    if subval.get(k) is not None:
                        val = subval[k]
                        if isinstance(val, int):
                            sel_id = val
                            break
                        elif isinstance(val, str) and val.strip().isdigit():
                            sel_id = int(val.strip())
                            break
                if sel_id is not None:
                    break

    # 5. Check "recommendation" field if integer or string mentioning a candidate
    if sel_id is None and "recommendation" in parsed:
        rec_val = parsed["recommendation"]
        if isinstance(rec_val, int):
            sel_id = rec_val
        elif isinstance(rec_val, str):
            for ev in top_candidates[:5]:
                if re.search(rf"\b{re.escape(str(ev.card.id))}\b", rec_val):
                    sel_id = ev.card.id
                    break

    # 6. Check "message" field if mentioning candidate ID
    if sel_id is None and "message" in parsed:
        msg_val = str(parsed["message"])
        for ev in top_candidates[:5]:
            if re.search(rf"\b{re.escape(str(ev.card.id))}\b", msg_val):
                sel_id = ev.card.id
                break

    # Extract reasoning
    expl = (
        parsed.get("reasoning")
        or parsed.get("reason")
        or parsed.get("explanation")
        or parsed.get("message")
        or parsed.get("recommendation")
    )
    if isinstance(expl, dict):
        advisor_reason = str(
            expl.get("matchup_analysis")
            or expl.get("summary")
            or expl.get("text")
            or expl.get("reason")
            or list(expl.values())[0]
        )
    elif expl:
        advisor_reason = str(expl).strip()

    return sel_id, advisor_reason


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
    clean_content = strip_think_tags(content)
    clean_reasoning = strip_think_tags(reasoning) if reasoning else ""
    combined_raw = f"{clean_content}\n{clean_reasoning}".strip()

    sel_id: int | None = None
    advisor_reason = ""

    # Strategy 1: If clean_content itself is valid JSON, parse directly!
    json_candidate = clean_content
    if "```" in json_candidate:
        m = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", json_candidate)
        if m:
            json_candidate = m.group(1).strip()

    if json_candidate.startswith("{") and json_candidate.endswith("}"):
        try:
            parsed = json.loads(json_candidate)
            if isinstance(parsed, dict):
                sel_id, advisor_reason = _parse_candidate_dict(parsed, top_candidates)
        except Exception:
            pass

    # Strategy 2: If multiple JSON blocks or text wrapping, look for block with selected_card_id / best_candidate_id
    if sel_id is None and "{" in clean_content:
        m = re.search(
            r"\{[^{}]*(?:selected_card_id|best_candidate_id|recommended_card_id)[^{}]*\}",
            clean_content,
        )
        if m:
            try:
                parsed = json.loads(m.group(0).strip())
                if isinstance(parsed, dict):
                    sel_id, advisor_reason = _parse_candidate_dict(parsed, top_candidates)
            except Exception:
                pass

    # Strategy 3: Try outer-most {...} block in clean_content
    if sel_id is None and "{" in clean_content:
        m = re.search(r"(\{[\s\S]*\})", clean_content)
        if m:
            try:
                parsed = json.loads(m.group(1).strip())
                if isinstance(parsed, dict):
                    sel_id, advisor_reason = _parse_candidate_dict(parsed, top_candidates)
            except Exception:
                pass

    # Strategy 4: If still no sel_id, try reasoning text
    if sel_id is None and clean_reasoning:
        r_candidate = clean_reasoning
        if "```" in r_candidate:
            m = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", r_candidate)
            if m:
                r_candidate = m.group(1).strip()
        if r_candidate.startswith("{") and r_candidate.endswith("}"):
            try:
                parsed = json.loads(r_candidate)
                if isinstance(parsed, dict):
                    sel_id, advisor_reason = _parse_candidate_dict(parsed, top_candidates)
            except Exception:
                pass
        if sel_id is None and "{" in clean_reasoning:
            m = re.search(
                r"\{[^{}]*(?:selected_card_id|best_candidate_id|recommended_card_id)[^{}]*\}",
                clean_reasoning,
            )
            if m:
                try:
                    parsed = json.loads(m.group(0).strip())
                    if isinstance(parsed, dict):
                        sel_id, advisor_reason = _parse_candidate_dict(parsed, top_candidates)
                except Exception:
                    pass
            if sel_id is None:
                m = re.search(r"(\{[\s\S]*\})", clean_reasoning)
                if m:
                    try:
                        parsed = json.loads(m.group(1).strip())
                        if isinstance(parsed, dict):
                            sel_id, advisor_reason = _parse_candidate_dict(parsed, top_candidates)
                    except Exception:
                        pass

    # Strategy 5 (Fallback A): Regex matching key-value pairs in combined raw text
    if sel_id is None:
        reg_match = re.search(
            r"(?:selected_card_id|best_candidate_id|recommended_card_id|recommended_id|choice_id|card_id|candidate_id|selected_id|choice)[\"'\s]*[:=][\"'\s]*(\d+)",
            combined_raw,
            re.IGNORECASE,
        )
        if reg_match:
            sel_id = int(reg_match.group(1))
            reason_match = re.search(
                r"reasoning[\"'\s]*[:=][\"'\s]*\"?([^\"}\r\n]+)",
                combined_raw,
                re.IGNORECASE,
            )
            if not advisor_reason:
                advisor_reason = (
                    reason_match.group(1).strip() if reason_match else combined_raw.strip()
                )

    # Strategy 6 (Fallback B): Scan if any candidate ID in the top shortlist is mentioned as a full token
    if sel_id is None:
        for ev in top_candidates[:5]:
            if re.search(rf"\b{re.escape(str(ev.card.id))}\b", combined_raw):
                sel_id = ev.card.id
                if not advisor_reason:
                    advisor_reason = combined_raw.strip()
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
        logger.warning(
            f"Ollama Advisor returned malformed response (content: {content[:200]!r}, reasoning: {(reasoning or '')[:200]!r}). Falling back smoothly."
        )
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
    "load_cards_tactical_matrix",
    "load_damage_simulation_benchmarks",
    "build_advisor_payload",
    "build_advisor_messages",
    "extract_advisor_candidate",
    "parse_advisor_response",
    "consult_ollama_advisor",
    "recommend_candidate",
]
