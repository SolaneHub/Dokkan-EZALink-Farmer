"""
Dokkan-EZALink-Farmer Core Package.

Provides core lifecycle management, configuration persistence, single-instance mutex,
system diagnostics, internationalization, and cryptographic updates.
"""

from typing import TYPE_CHECKING, Any

from dokkan_eza_link_farmer.core.i18n import (
    get_available_languages,
    get_language,
    set_language,
    t,
)
from dokkan_eza_link_farmer.core.system_tools import (
    SingleInstanceMutex,
    ToolLocator,
    get_config_path,
    get_resource_path,
)
from dokkan_eza_link_farmer.core.updater import (
    check_for_updates,
    compute_file_sha256,
    launch_detached_process,
    run_powershell_hidden,
    sanitize_process_env,
    verify_sha256,
)

if TYPE_CHECKING:
    from dokkan_eza_link_farmer.core.bot_engine import BotEngine

__all__ = [
    "BotEngine",
    "SingleInstanceMutex",
    "ToolLocator",
    "get_config_path",
    "get_resource_path",
    "get_available_languages",
    "get_language",
    "set_language",
    "t",
    "check_for_updates",
    "compute_file_sha256",
    "verify_sha256",
    "sanitize_process_env",
    "launch_detached_process",
    "run_powershell_hidden",
]


def __getattr__(name: str) -> Any:
    """Lazy imports to prevent circular initialization cycles when importing submodules."""
    if name == "BotEngine":
        from dokkan_eza_link_farmer.core.bot_engine import BotEngine

        return BotEngine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
