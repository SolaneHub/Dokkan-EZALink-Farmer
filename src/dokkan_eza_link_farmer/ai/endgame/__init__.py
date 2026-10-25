"""Dokkan AI Endgame Challenge & Combat Telemetry Subsystem.

Provides:
- EndgameRunner: Autonomous state machine for Red Zone / Blue Zone challenge events.
- CombatTelemetryTracker & CombatRingBuffer: Pre-KO FIFO frame telemetry and action observation.
- Culprit attribution: Slot 7 immunity, direct attribution, and vulnerability sharing.
- EpisodicMemory & EpisodicMemoryManager: Persistent post-defeat decision tree and tactical retry memory.
"""

from __future__ import annotations

from dokkan_eza_link_farmer.ai.endgame import runner, telemetry
from dokkan_eza_link_farmer.ai.endgame.runner import (
    BattleSimulatorFn,
    EndgameResult,
    EndgameRunner,
    EndgameRunnerState,
    EndgameStageOutcome,
    apply_team_in_game,
)
from dokkan_eza_link_farmer.ai.endgame.telemetry import (
    DEFAULT_MEMORY_CACHE_PATH,
    CombatFrame,
    CombatRingBuffer,
    CombatTelemetryTracker,
    CulpritAttribution,
    EpisodicMemory,
    EpisodicMemoryManager,
    FailureReport,
    PostDefeatDecision,
    TurnSnapshot,
    attribute_culprit,
    create_failure_report,
    is_debug_telemetry_enabled,
    set_debug_telemetry,
)

__all__ = [
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
    "is_debug_telemetry_enabled",
    "runner",
    "set_debug_telemetry",
    "telemetry",
]
