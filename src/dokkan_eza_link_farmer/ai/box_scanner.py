from __future__ import annotations

from dokkan_eza_link_farmer.automation.tasks.box_scanner import (
    CACHE_BOX_PATH,
    CANONICAL_BOX_PATH,
    DEFAULT_BOX_SCAN_LOG_PATH,
    DEFAULT_USER_BOX_PATH,
    BoxScannerTask,
    _normalize_title,
    resolve_box_path,
    sync_box_cache,
)


class BoxScanner(BoxScannerTask):
    """
    Autonomous in-game Character Box Scanner for the AI Teambuilder subsystem.
    Thin backward-compatible adapter that inherits directly from BoxScannerTask
    (located in dokkan_eza_link_farmer.automation.tasks.box_scanner).
    Do NOT reimplement scanning logic here; all scanning mechanics and ADB routines
    belong in BoxScannerTask to prevent redundant code duplication.

    Scans 5x5 character grid, extracts rainbow/EZA status, swipe_page, and grid_slot coordinates,
    persisting the structured inventory to config/box.json (with synchronized cache).
    """

    pass


__all__ = [
    "CANONICAL_BOX_PATH",
    "CACHE_BOX_PATH",
    "DEFAULT_BOX_SCAN_LOG_PATH",
    "DEFAULT_USER_BOX_PATH",
    "BoxScanner",
    "BoxScannerTask",
    "_normalize_title",
    "resolve_box_path",
    "sync_box_cache",
]
