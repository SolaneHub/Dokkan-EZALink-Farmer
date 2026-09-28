"""Dokkan Battle automation tasks package."""

from dokkan_eza_link_farmer.automation.tasks.base_task import BaseTask
from dokkan_eza_link_farmer.automation.tasks.eza_farm import EZAFarmTask
from dokkan_eza_link_farmer.automation.tasks.link_level_farm import LinkLevelFarmTask

__all__ = ["BaseTask", "EZAFarmTask", "LinkLevelFarmTask"]
