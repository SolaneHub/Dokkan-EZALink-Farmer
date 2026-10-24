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
from dokkan_eza_link_farmer.ai.client import DokkanAIClient
from dokkan_eza_link_farmer.ai.mission_solver import (
    ChallengeMission,
    MissionBatch,
    MissionBundler,
    MissionParser,
)
from dokkan_eza_link_farmer.ai.models import (
    AIConfig,
    AIModelFamily,
    BossEnemy,
    BossMechanic,
    BossPhase,
    BossStage,
    CardForm,
    DokkanCard,
    LeaderSkillSpec,
    PassiveTags,
    RotationPair,
    SATags,
    SupportedAIModel,
    TeamRecommendation,
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
from dokkan_eza_link_farmer.ai.team_builder import TeamBuilder
from dokkan_eza_link_farmer.automation.tasks.box_scanner import (
    DEFAULT_BOX_SCAN_LOG_PATH,
    BoxScannerTask,
)

BoxScanner = BoxScannerTask

if TYPE_CHECKING:
    import dokkan_eza_link_farmer.ai.endgame as endgame
    import dokkan_eza_link_farmer.ai.endgame_runner as endgame_runner
    import dokkan_eza_link_farmer.ai.telemetry as telemetry
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
        FailureReport,
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
    "FailureReport",
    "PostDefeatDecision",
    "TurnSnapshot",
    "apply_team_in_game",
    "attribute_culprit",
    "create_failure_report",
    "endgame",
    "endgame_runner",
    "is_debug_telemetry_enabled",
    "set_debug_telemetry",
    "telemetry",
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
            if name == "telemetry":
                mod = importlib.import_module("dokkan_eza_link_farmer.ai.telemetry")
                globals()[name] = mod
                return mod
            if name == "endgame_runner":
                mod = importlib.import_module("dokkan_eza_link_farmer.ai.endgame_runner")
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
    "TeamBuilder",
    "TeamRecommendation",
    "TurnSnapshot",
    "apply_team_in_game",
    "attribute_culprit",
    "create_failure_report",
    "endgame",
    "endgame_runner",
    "get_boss_catalog_path",
    "get_boss_stage",
    "is_debug_telemetry_enabled",
    "list_boss_stages",
    "load_boss_catalog",
    "parse_leader_spec",
    "parse_passive_tags",
    "parse_sa_tags",
    "set_debug_telemetry",
    "telemetry",
]
