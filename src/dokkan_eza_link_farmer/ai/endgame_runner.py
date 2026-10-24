"""Backward compatibility alias for dokkan_eza_link_farmer.ai.endgame.runner."""

from __future__ import annotations

from dokkan_eza_link_farmer.ai.endgame.runner import *  # noqa: F403
from dokkan_eza_link_farmer.ai.endgame.runner import (
    BattleSimulatorFn,
    EndgameResult,
    EndgameRunner,
    EndgameRunnerState,
    EndgameStageOutcome,
    apply_team_in_game,
)

__all__ = [
    "BattleSimulatorFn",
    "EndgameResult",
    "EndgameRunner",
    "EndgameRunnerState",
    "EndgameStageOutcome",
    "apply_team_in_game",
]
