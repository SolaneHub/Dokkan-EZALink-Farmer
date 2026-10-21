"""Dokkan Battle automation tasks package."""

from dokkan_eza_link_farmer.automation.tasks.base_task import BaseTask
from dokkan_eza_link_farmer.automation.tasks.box_scanner import (
    DEFAULT_BOX_SCAN_LOG_PATH,
    BoxScannerTask,
)
from dokkan_eza_link_farmer.automation.tasks.challenge_task import ChallengeTask
from dokkan_eza_link_farmer.automation.tasks.eza_farm import EZAFarmTask
from dokkan_eza_link_farmer.automation.tasks.link_level_farm import LinkLevelFarmTask
from dokkan_eza_link_farmer.automation.tasks.stage_farm import StageFarmTask

__all__ = [
    "BaseTask",
    "BoxScannerTask",
    "ChallengeTask",
    "DEFAULT_BOX_SCAN_LOG_PATH",
    "EZAFarmTask",
    "LinkLevelFarmTask",
    "StageFarmTask",
]
