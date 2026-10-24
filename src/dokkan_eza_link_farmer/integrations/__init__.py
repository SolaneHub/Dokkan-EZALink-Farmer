"""External integrations package (ADB, DokkanDB, Discord Bot)."""

from dokkan_eza_link_farmer.integrations.adb_client import ADBClient
from dokkan_eza_link_farmer.integrations.dokkandb_client import DokkanDBClient


def run_discord_bot(*args, **kwargs):
    """Lazy loader for run_discord_bot to isolate discord dependency."""
    from dokkan_eza_link_farmer.integrations.discord_bot import run_discord_bot as _run

    return _run(*args, **kwargs)


__all__ = ["ADBClient", "DokkanDBClient", "run_discord_bot"]
