"""Character Box scanner sub-modules for banner extraction, detail evaluation, and catalog matching."""

from __future__ import annotations

from dokkan_eza_link_farmer.automation.scanner.banner_extractor import (
    BannerExtractor,
    extract_banner_text,
    extract_banner_tokens,
    preprocess_text_banner,
    read_card_title_from_screen,
    stitch_marquee_text,
)
from dokkan_eza_link_farmer.automation.scanner.box_storage import (
    _DEFAULT_IMPORT_CACHE_BOX,
    _DEFAULT_IMPORT_USER_BOX,
    CACHE_BOX_PATH,
    CANONICAL_BOX_PATH,
    DEFAULT_USER_BOX_PATH,
    load_existing_box,
    resolve_box_path,
    save_box,
    sync_box_cache,
)
from dokkan_eza_link_farmer.automation.scanner.card_registry import register_card
from dokkan_eza_link_farmer.automation.scanner.catalog_matcher import (
    CatalogMatcher,
    index_single_card,
    match_card_by_text,
    match_card_candidate,
    normalize_title,
)
from dokkan_eza_link_farmer.automation.scanner.detail_evaluator import (
    DetailEvaluator,
    detect_rainbow_star,
    extract_element_badge,
    extract_level_and_sa,
    extract_potential_and_rainbow,
    save_diagnostic_crops,
    scan_detail_screen,
)
from dokkan_eza_link_farmer.automation.scanner.filter_manager import (
    verify_and_enforce_filters,
)
from dokkan_eza_link_farmer.automation.scanner.session_context import ScanSessionContext
from dokkan_eza_link_farmer.automation.scanner.swipe_controller import (
    advance_to_next_card,
    compute_screen_diff,
    is_card_details_screen,
    is_right_arrow_visible,
    read_counter_total_cards,
    scroll_to_top,
)

__all__ = [
    "CACHE_BOX_PATH",
    "CANONICAL_BOX_PATH",
    "DEFAULT_USER_BOX_PATH",
    "_DEFAULT_IMPORT_CACHE_BOX",
    "_DEFAULT_IMPORT_USER_BOX",
    "BannerExtractor",
    "CatalogMatcher",
    "DetailEvaluator",
    "ScanSessionContext",
    "advance_to_next_card",
    "compute_screen_diff",
    "detect_rainbow_star",
    "extract_banner_text",
    "extract_banner_tokens",
    "extract_element_badge",
    "extract_level_and_sa",
    "extract_potential_and_rainbow",
    "index_single_card",
    "is_card_details_screen",
    "is_right_arrow_visible",
    "load_existing_box",
    "match_card_by_text",
    "match_card_candidate",
    "normalize_title",
    "preprocess_text_banner",
    "read_card_title_from_screen",
    "read_counter_total_cards",
    "register_card",
    "resolve_box_path",
    "save_box",
    "save_diagnostic_crops",
    "scan_detail_screen",
    "scroll_to_top",
    "stitch_marquee_text",
    "sync_box_cache",
    "verify_and_enforce_filters",
]
