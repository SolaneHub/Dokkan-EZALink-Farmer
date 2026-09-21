"""
DokkanBattleBot User Interfaces Package.

Provides interactive and headless user interfaces:
- TerminalCLI: Interactive Rich-based terminal UI and command prompt
- run_discord_bot: Headless Discord bot interface with slash commands
"""

from interfaces.cli import TerminalCLI
from interfaces.discord_bot import run_discord_bot, setup_discord_interactive

__all__ = [
    "TerminalCLI",
    "run_discord_bot",
    "setup_discord_interactive",
]
