"""
DokkanBattleBot Core Package.

Exposes fundamental automation modules: ADB communication, computer vision,
game state detection, DokkanDB integration, and the central BotEngine.
"""

from core.adb_client import ADBClient
from core.vision import Vision
from core.game_state import StateDetector, GameState
from core.dokkandb_client import DokkanDBClient
from core.i18n import t, set_language, get_language, get_available_languages
from core.system_tools import ToolLocator, get_resource_path, get_config_path
from core.bot_engine import BotEngine

__all__ = [
    "ADBClient",
    "Vision",
    "StateDetector",
    "GameState",
    "DokkanDBClient",
    "BotEngine",
    "t",
    "set_language",
    "get_language",
    "get_available_languages",
    "ToolLocator",
    "get_resource_path",
    "get_config_path",
]
