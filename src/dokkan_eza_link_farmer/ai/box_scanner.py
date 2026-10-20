from __future__ import annotations

from dokkan_eza_link_farmer.automation.tasks.box_scanner import (
    DEFAULT_USER_BOX_PATH,
    BoxScannerTask,
    _normalize_title,
)


class BoxScanner(BoxScannerTask):
    """
    Autonomous in-game Character Box Scanner for the AI Teambuilder subsystem.
    Scans 5x5 character grid, extracts rainbow/EZA status, swipe_page, and grid_slot coordinates,
    persisting the structured inventory to ~/.dokkan-farmer/cache/user_box.json.
    """

    pass


__all__ = [
    "DEFAULT_USER_BOX_PATH",
    "BoxScanner",
    "BoxScannerTask",
    "_normalize_title",
]
