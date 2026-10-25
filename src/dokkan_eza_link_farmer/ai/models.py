"""Backward-compatible facade module re-exporting Dokkan AI domain models."""

from __future__ import annotations

from dokkan_eza_link_farmer.ai.boss_models import (
    BossEnemy,
    BossMechanic,
    BossPhase,
    BossStage,
    ChallengeStageInfo,
    infer_boss_categories_from_name,
)
from dokkan_eza_link_farmer.ai.card_models import (
    TYPE_NAMES,
    CardForm,
    DokkanCard,
    LeaderSkillSpec,
    PassiveTags,
    RotationPair,
    SATags,
    TeamRecommendation,
    parse_dodge_percentage_from_text,
)
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
    "PassiveTags",
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
    "FailureReport",
    "TYPE_NAMES",
    "parse_dodge_percentage_from_text",
    "infer_boss_categories_from_name",
]
