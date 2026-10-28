"""Backward-compatible facade module re-exporting Dokkan AI domain models."""

from __future__ import annotations

from dokkan_eza_link_farmer.ai.boss_models import (
    DIFFICULTY_CODES,
    DIFFICULTY_NAMES,
    BossEnemy,
    BossMechanic,
    BossPhase,
    BossStage,
    ChallengeStageInfo,
    infer_boss_categories_from_name,
    parse_difficulty_code,
)
from dokkan_eza_link_farmer.ai.card_models import (
    TYPE_NAMES,
    CardForm,
    DokkanCard,
    LeaderSkillSpec,
    PassiveTags,
    RotationPair,
    SATags,
    TeamConditionalBuff,
    TeamRecommendation,
    parse_dodge_percentage_from_text,
)
from dokkan_eza_link_farmer.ai.damage_engine import calculate_damage_taken
from dokkan_eza_link_farmer.ai.llm_advisor import (
    AIConfig,
    AIModelFamily,
    FailureReport,
    SupportedAIModel,
)

__all__ = [
    "AIModelFamily",
    "SupportedAIModel",
    "AIConfig",
    "calculate_damage_taken",
    "PassiveTags",
    "TeamConditionalBuff",
    "SATags",
    "LeaderSkillSpec",
    "CardForm",
    "DokkanCard",
    "RotationPair",
    "TeamRecommendation",
    "BossMechanic",
    "BossEnemy",
    "BossPhase",
    "BossStage",
    "ChallengeStageInfo",
    "DIFFICULTY_CODES",
    "DIFFICULTY_NAMES",
    "parse_difficulty_code",
    "FailureReport",
    "TYPE_NAMES",
    "parse_dodge_percentage_from_text",
    "infer_boss_categories_from_name",
]
