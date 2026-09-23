"""
DokkanBattleBot Core Package.

Exposes fundamental automation modules: ADB communication, computer vision,
game state detection, DokkanDB integration, and the central BotEngine.
"""

from core.adb_client import ADBClient
from core.bot_engine import BotEngine
from core.dokkandb_client import DokkanDBClient
from core.game_state import GameState, StateDetector
from core.i18n import get_available_languages, get_language, set_language, t
from core.system_tools import ToolLocator, get_config_path, get_resource_path
from core.vision import Vision

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
