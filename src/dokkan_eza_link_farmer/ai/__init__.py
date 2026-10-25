from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from dokkan_eza_link_farmer.ai.boss_catalog import (
    DEFAULT_BOSS_CATALOG_PATH,
    get_boss_catalog_path,
    get_boss_stage,
    list_boss_stages,
    load_boss_catalog,
)
from dokkan_eza_link_farmer.ai.boss_models import (
    TYPE_NAMES,
    BossEnemy,
    BossMechanic,
    BossPhase,
    BossStage,
    ChallengeStageInfo,
    infer_boss_categories_from_name,
)
from dokkan_eza_link_farmer.ai.card_models import (
    CardForm,
    DokkanCard,
    LeaderSkillSpec,
    PassiveTags,
    SATags,
    TeamRecommendation,
    parse_dodge_percentage_from_text,
)
from dokkan_eza_link_farmer.ai.client import DokkanAIClient
from dokkan_eza_link_farmer.ai.llm_advisor import (
    AIConfig,
    AIModelFamily,
    FailureReport,
    SupportedAIModel,
)
from dokkan_eza_link_farmer.ai.mission_solver import (
    ChallengeMission,
    MissionBatch,
    MissionBundler,
    MissionParser,
)
from dokkan_eza_link_farmer.ai.solver import (
    CandidateEvaluation,
    ConstraintSolverResult,
    DokkanConstraintSolver,
)
from dokkan_eza_link_farmer.ai.syncer import (
    DokkanSyncer,
    parse_leader_spec,
    parse_passive_tags,
    parse_sa_tags,
)
from dokkan_eza_link_farmer.ai.synergy import RotationPair
from dokkan_eza_link_farmer.ai.team_builder import TeamBuilder
from dokkan_eza_link_farmer.automation.tasks.box_scanner import (
    DEFAULT_BOX_SCAN_LOG_PATH,
    BoxScannerTask,
)

BoxScanner = BoxScannerTask

if TYPE_CHECKING:
    import dokkan_eza_link_farmer.ai.endgame as endgame
    from dokkan_eza_link_farmer.ai.endgame import (
        DEFAULT_MEMORY_CACHE_PATH,
        BattleSimulatorFn,
        CombatFrame,
        CombatRingBuffer,
        CombatTelemetryTracker,
        CulpritAttribution,
        EndgameResult,
        EndgameRunner,
        EndgameRunnerState,
        EndgameStageOutcome,
        EpisodicMemory,
        EpisodicMemoryManager,
        PostDefeatDecision,
        TurnSnapshot,
        apply_team_in_game,
        attribute_culprit,
        create_failure_report,
        is_debug_telemetry_enabled,
        set_debug_telemetry,
    )

_LAZY_LOCK = threading.Lock()

_LAZY_ENDGAME_EXPORTS = {
    "BattleSimulatorFn",
    "CombatFrame",
    "CombatRingBuffer",
    "CombatTelemetryTracker",
    "CulpritAttribution",
    "DEFAULT_MEMORY_CACHE_PATH",
    "EndgameResult",
    "EndgameRunner",
    "EndgameRunnerState",
    "EndgameStageOutcome",
    "EpisodicMemory",
    "EpisodicMemoryManager",
    "PostDefeatDecision",
    "TurnSnapshot",
    "apply_team_in_game",
    "attribute_culprit",
    "create_failure_report",
    "endgame",
    "is_debug_telemetry_enabled",
    "set_debug_telemetry",
}


def __getattr__(name: str) -> Any:
    if name in _LAZY_ENDGAME_EXPORTS:
        with _LAZY_LOCK:
            if name in globals():
                return globals()[name]
            import importlib

            if name == "endgame":
                mod = importlib.import_module("dokkan_eza_link_farmer.ai.endgame")
                globals()[name] = mod
                return mod

            mod = importlib.import_module("dokkan_eza_link_farmer.ai.endgame")
            val = getattr(mod, name)
            globals()[name] = val
            return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals().keys()) | _LAZY_ENDGAME_EXPORTS)


__all__ = [
    "AIConfig",
    "AIModelFamily",
    "BattleSimulatorFn",
    "BossEnemy",
    "BossMechanic",
    "BossPhase",
    "BossStage",
    "BoxScanner",
    "BoxScannerTask",
    "CandidateEvaluation",
    "CardForm",
    "ChallengeMission",
    "ChallengeStageInfo",
    "CombatFrame",
    "CombatRingBuffer",
    "CombatTelemetryTracker",
    "ConstraintSolverResult",
    "CulpritAttribution",
    "DEFAULT_BOSS_CATALOG_PATH",
    "DEFAULT_BOX_SCAN_LOG_PATH",
    "DEFAULT_MEMORY_CACHE_PATH",
    "DokkanAIClient",
    "DokkanCard",
    "DokkanConstraintSolver",
    "DokkanSyncer",
    "EndgameResult",
    "EndgameRunner",
    "EndgameRunnerState",
    "EndgameStageOutcome",
    "EpisodicMemory",
    "EpisodicMemoryManager",
    "FailureReport",
    "LeaderSkillSpec",
    "MissionBatch",
    "MissionBundler",
    "MissionParser",
    "PassiveTags",
    "PostDefeatDecision",
    "RotationPair",
    "SATags",
    "SupportedAIModel",
    "TYPE_NAMES",
    "TeamBuilder",
    "TeamRecommendation",
    "TurnSnapshot",
    "apply_team_in_game",
    "attribute_culprit",
    "create_failure_report",
    "endgame",
    "get_boss_catalog_path",
    "get_boss_stage",
    "infer_boss_categories_from_name",
    "is_debug_telemetry_enabled",
    "list_boss_stages",
    "load_boss_catalog",
    "parse_dodge_percentage_from_text",
    "parse_leader_spec",
    "parse_passive_tags",
    "parse_sa_tags",
    "set_debug_telemetry",
]
