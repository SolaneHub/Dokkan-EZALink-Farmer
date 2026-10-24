"""Backward compatibility alias for dokkan_eza_link_farmer.ai.endgame.telemetry."""

from __future__ import annotations

from dokkan_eza_link_farmer.ai.endgame.telemetry import *  # noqa: F403
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
    "DEFAULT_MEMORY_CACHE_PATH",
    "CombatFrame",
    "CombatRingBuffer",
    "CombatTelemetryTracker",
    "CulpritAttribution",
    "EpisodicMemory",
    "EpisodicMemoryManager",
    "FailureReport",
    "PostDefeatDecision",
    "TurnSnapshot",
    "attribute_culprit",
    "create_failure_report",
    "is_debug_telemetry_enabled",
    "set_debug_telemetry",
]
