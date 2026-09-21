"""
DokkanBattleBot Automation Tasks Package.

Defines base task structures and concrete task routines:
- EZAFarmTask: Extreme Z-Battle auto climbing (up to Lv. 999)
- LinkLevelFarmTask: Auto link-skill leveling on Chamber of Spirit and Time
"""

from tasks.base_task import BaseTask
from tasks.eza_farm import EZAFarmTask
from tasks.link_level_farm import LinkLevelFarmTask

__all__ = [
    "BaseTask",
    "EZAFarmTask",
    "LinkLevelFarmTask",
]
