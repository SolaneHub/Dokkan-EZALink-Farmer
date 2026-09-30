"""
Dokkan-EZALink-Farmer: Automated EZA Climbing & Link Level Grinder.

Specialized endgame automation for DBZ Dokkan Battle:
- Extreme Z-Battle (EZA 999 Zeni Farming)
- Chamber of Spirit and Time (Link Leveling Deck Rotation)
"""

from dokkan_eza_link_farmer.automation.game_state import GameState, StateDetector
from dokkan_eza_link_farmer.automation.vision import Vision
from dokkan_eza_link_farmer.core.bot_engine import BotEngine
from dokkan_eza_link_farmer.core.system_tools import SingleInstanceMutex, ToolLocator
from dokkan_eza_link_farmer.integrations.adb_client import ADBClient
from dokkan_eza_link_farmer.integrations.dokkandb_client import DokkanDBClient
from dokkan_eza_link_farmer.ui.cli import TerminalCLI

__version__ = "1.0.5"
__author__ = "SolaneHub"

__all__ = [
    "BotEngine",
    "TerminalCLI",
    "ADBClient",
    "DokkanDBClient",
    "Vision",
    "StateDetector",
    "GameState",
    "ToolLocator",
    "SingleInstanceMutex",
    "__version__",
]
