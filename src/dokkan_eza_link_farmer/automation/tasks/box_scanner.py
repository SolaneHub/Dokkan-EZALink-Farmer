from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any

import numpy as np

from dokkan_eza_link_farmer.ai.syncer import DokkanSyncer
from dokkan_eza_link_farmer.automation.scanner import (
    CACHE_BOX_PATH,
    CANONICAL_BOX_PATH,
    DEFAULT_USER_BOX_PATH,
    advance_to_next_card,
    compute_screen_diff,
    detect_rainbow_star,
    execute_ocr_fallback,
    extract_banner_text,
    extract_element_badge,
    extract_level_and_sa,
    extract_potential_and_rainbow,
    is_card_details_screen,
    load_existing_box,
    match_card_by_text,
    match_card_candidate,
    match_row_with_alignment,
    normalize_title,
    preprocess_text_banner,
    read_card_title_from_screen,
    register_card,
    resolve_box_path,
    save_box,
    scroll_to_top,
    stitch_marquee_text,
    sync_box_cache,
    track_vertical_shift,
    verify_and_enforce_filters,
)
from dokkan_eza_link_farmer.automation.scanner.catalog_matcher import CatalogMatcher
from dokkan_eza_link_farmer.automation.scanner.legacy_grid import (
    get_second_candidate,
    init_thumbnails,
    match_slot_thumbnail_with_delta,
)
from dokkan_eza_link_farmer.automation.tasks.base_task import BaseTask
from dokkan_eza_link_farmer.automation.vision import Vision
from dokkan_eza_link_farmer.integrations.adb_client import ADBClient
from dokkan_eza_link_farmer.integrations.dokkandb_client import DokkanDBClient

logger = logging.getLogger(__name__)

DEFAULT_BOX_SCAN_LOG_PATH = os.path.join(os.path.expanduser("~"), ".dokkan-farmer", "box_scan.log")
_normalize_title = normalize_title


class BoxScannerTask(BaseTask):
    """
    Autonomously scans the player's personal in-game Character Box via ADB,
    extracts card titles using OCR and template matching against DokkanDB catalog,
    and builds config/box.json with swipe_page and grid_slot coordinates.
    """

    COL_RATIOS = [0.102, 0.301, 0.500, 0.699, 0.898]
    ROW_RATIOS = [0.252, 0.3575, 0.463, 0.568, 0.674]
    BACK_BUTTON_RATIO = (0.139, 0.858)
    TITLE_CROP_Y = (0.058, 0.375)
    TITLE_CROP_X = (0.777, 0.926)

    @staticmethod
    def _compute_screen_diff(
        img1: np.ndarray | None,
        img2: np.ndarray | None,
        roi: tuple[int, int, int, int] | None = None,
    ) -> float:
        return compute_screen_diff(img1, img2, roi=roi)

    def __init__(
        self,
        adb: ADBClient,
        vision: Vision,
        config: dict[str, Any],
        dokkandb: DokkanDBClient | None = None,
        syncer: DokkanSyncer | None = None,
        on_status: Callable[[str], None] | None = None,
        on_run_complete: Callable[[int, int], None] | None = None,
        output_file: str | None = None,
        max_cards_to_scan: int | None = None,
        log_file: str | None = DEFAULT_BOX_SCAN_LOG_PATH,
    ):
        super().__init__(adb, vision, config, on_status, on_run_complete)
        self.dokkandb = dokkandb or DokkanDBClient()
        db_cache = getattr(self.dokkandb, "cache_dir", None)
        syncer_cache = db_cache if isinstance(db_cache, str) else None
        self.syncer = syncer or DokkanSyncer(cache_dir=syncer_cache)
        self.output_file = output_file if output_file is not None else DEFAULT_USER_BOX_PATH
        self.max_cards_to_scan = max_cards_to_scan
        self.pure_grid_mode = config.get("pure_grid_mode", False)
        self.include_ssr = bool(config.get("include_ssr", False))
        self.log_file = log_file if log_file is not None else DEFAULT_BOX_SCAN_LOG_PATH
        self._file_handler: logging.Handler | None = None
        self._setup_file_logger()
        self._last_registered_card_id: int | None = None
        self._session_seen_ids: set[int] = set()
        self._recently_scanned_positions: dict[int, tuple[float, float]] = {}

        self._ocr = None
        try:
            from rapidocr_onnxruntime import RapidOCR

            self._ocr = RapidOCR()
            logger.info("RapidOCR engine initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize RapidOCR engine: {e}")

        self._catalog: list[dict[str, Any]] = []
        self._subname_index: dict[str, Any] = {}
        self._id_index: dict[int, dict[str, Any]] = {}
        self._loaded_thumbs: list[dict[str, Any]] = []
        self._lr_thumbs: list[dict[str, Any]] = []
        self._special_thumbs: list[dict[str, Any]] = []

        self.scanned_cards: dict[int, dict[str, Any]] = {}
        self._load_existing_box()

    def _setup_file_logger(self) -> None:
        """Sets up a debug file handler saving all box scanner events to log_file."""
        if not self.log_file:
            return
        try:
            target_path = os.path.abspath(self.log_file)
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            pkg_logger = logging.getLogger("dokkan_eza_link_farmer")
            for h in pkg_logger.handlers:
                if (
                    isinstance(h, logging.FileHandler)
                    and os.path.abspath(getattr(h, "baseFilename", "")) == target_path
                ):
                    self._file_handler = h
                    return

            handler = logging.FileHandler(target_path, mode="a", encoding="utf-8")
            formatter = logging.Formatter(
                "%(asctime)s [%(levelname)-7s] [%(name)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
            handler.setFormatter(formatter)
            handler.setLevel(logging.DEBUG)
            pkg_logger.addHandler(handler)
            if pkg_logger.level == logging.NOTSET or pkg_logger.level > logging.DEBUG:
                pkg_logger.setLevel(logging.DEBUG)
            self._file_handler = handler
        except Exception as e:
            logger.warning(
                f"Could not initialize box scanner debug log file at {self.log_file}: {e}"
            )

    def _close_file_logger(self) -> None:
        """Flushes and detaches file handler for box scan logging."""
        if self._file_handler:
            try:
                pkg_logger = logging.getLogger("dokkan_eza_link_farmer")
                self._file_handler.flush()
                pkg_logger.removeHandler(self._file_handler)
                self._file_handler.close()
            except Exception:
                pass
            finally:
                self._file_handler = None

    def __del__(self) -> None:
        self._close_file_logger()

    def log(self, message: str) -> None:
        logger.info(message)
        super().log(message)

    # Delegated scanner sub-components
    def _load_existing_box(self) -> None:
        self.scanned_cards = load_existing_box(self.output_file)

    def _save_box(self, enrich: bool = True) -> None:
        save_box(self.output_file, self.scanned_cards, dokkandb=self.dokkandb, enrich=enrich)

    def ensure_box_filters(self) -> bool:
        return verify_and_enforce_filters(self)

    def _init_catalog(self) -> None:
        self.log("Fetching card database catalog from DokkanDB...")
        if self.syncer:
            try:
                self._catalog = self.syncer.sync_catalog(include_ssr=self.include_ssr)
            except Exception as e:
                logger.warning(f"Error syncing catalog via DokkanSyncer: {e}")
        if not self._catalog:
            self._catalog = self.dokkandb.get_cards_catalog()
        self.log(f"Indexed {len(self._catalog)} cards from DokkanDB catalog.")
        matcher = CatalogMatcher(self._catalog)
        self._id_index = matcher._id_index
        for norm, cands in matcher._subname_index.items():
            if cands:
                self._subname_index[norm] = cands[0]

    def _init_thumbnails(self) -> None:
        loaded, lrs = init_thumbnails(
            self,
            self._catalog,
            self.dokkandb.cache_dir,
            include_ssr=self.include_ssr,
            syncer=self.syncer,
        )
        self._loaded_thumbs = loaded
        self._lr_thumbs = lrs
        self._special_thumbs = [
            t
            for t in self._loaded_thumbs
            if t.get("rarity") == 5
            or t.get("has_survival_passive")
            or any(s in t.get("name", "") for s in (" & ", "/", " + ", "(Giant Ape)"))
        ]
        self.log(
            f"Pre-loaded {len(self._loaded_thumbs)} character thumbnails ({len(self._lr_thumbs)} LRs, "
            f"{len(self._special_thumbs)} special effect/duo/LRs) for visual pattern matching."
        )

    def _match_slot_thumbnail(self, crop: np.ndarray) -> tuple[dict[str, Any] | None, float]:
        cand, score, _ = self._match_slot_thumbnail_with_delta(crop)
        return cand, score

    def _match_slot_thumbnail_with_delta(
        self, crop: np.ndarray
    ) -> tuple[dict[str, Any] | None, float, float]:
        return match_slot_thumbnail_with_delta(self._loaded_thumbs, crop)

    def _get_second_candidate(self, crop: np.ndarray) -> tuple[dict[str, Any] | None, float]:
        return get_second_candidate(self._loaded_thumbs, crop)

    def _execute_ocr_fallback(self, cx: int, cy: int) -> dict[str, Any] | None:
        return execute_ocr_fallback(self, cx, cy)

    def _match_card_by_text(self, recognized_text: str) -> dict[str, Any] | None:
        matcher = CatalogMatcher()
        matcher._subname_index = {
            k: [v] if isinstance(v, dict) else v for k, v in self._subname_index.items()
        }
        matcher._id_index = self._id_index
        return matcher.match_card_by_text(recognized_text)

    def _match_card_candidate(
        self,
        recognized_text: str,
        detected_class: str | None = None,
        detected_elem: str | None = None,
        detected_rarity: int | None = None,
    ) -> tuple[dict[str, Any] | None, float]:
        matcher = CatalogMatcher()
        matcher._subname_index = {
            k: [v] if isinstance(v, dict) else v for k, v in self._subname_index.items()
        }
        matcher._id_index = self._id_index
        return match_card_candidate(
            matcher,
            recognized_text,
            detected_class=detected_class,
            detected_elem=detected_elem,
            detected_rarity=detected_rarity,
            session_seen_ids=self._session_seen_ids,
            last_registered_card_id=self._last_registered_card_id,
        )

    def _read_card_title_from_screen(self, screen_img: np.ndarray) -> str | None:
        return read_card_title_from_screen(
            screen_img, ocr=self._ocr, crop_y=self.TITLE_CROP_Y, crop_x=self.TITLE_CROP_X
        )

    def _is_card_details_screen(self, screen_img: np.ndarray) -> bool:
        return is_card_details_screen(screen_img, ocr=self._ocr)

    def _detect_rainbow_star(self, screen_or_crop: np.ndarray) -> bool:
        return detect_rainbow_star(screen_or_crop)

    def _extract_banner_text(self, screen_img: np.ndarray | None) -> str:
        return extract_banner_text(screen_img, ocr=self._ocr)

    def _extract_element_badge(
        self, screen_img: np.ndarray | None
    ) -> tuple[str | None, str | None]:
        return extract_element_badge(screen_img, ocr=self._ocr)

    def _extract_level_and_sa(
        self, screen_img: np.ndarray | None, rarity: int = 4
    ) -> tuple[bool, bool, int, int]:
        return extract_level_and_sa(screen_img, ocr=self._ocr, rarity=rarity)

    def _extract_potential_and_rainbow(
        self, screen_img: np.ndarray | None, curr_sa: int = 10, max_sa: int = 10
    ) -> tuple[bool, int]:
        return extract_potential_and_rainbow(
            screen_img, ocr=self._ocr, curr_sa=curr_sa, max_sa=max_sa
        )

    @staticmethod
    def _stitch_marquee_text(text_f1: str | None, text_f2: str | None) -> str:
        return stitch_marquee_text(text_f1, text_f2)

    def scroll_to_top(self) -> None:
        scroll_to_top(self)

    def _advance_to_next_card(
        self, current_screen: np.ndarray, current_card_id: int | None = None
    ) -> tuple[np.ndarray, bool]:
        return advance_to_next_card(self, current_screen, current_card_id=current_card_id)

    def _track_vertical_shift(
        self, prev_img: np.ndarray, curr_img: np.ndarray, last_cy: float
    ) -> float | None:
        return track_vertical_shift(prev_img, curr_img, last_cy, col_ratios=self.COL_RATIOS)

    def _register_card(
        self,
        cand: dict[str, Any] | None,
        score: float,
        crop: np.ndarray | None = None,
        cy: float = 0.0,
        cx: int = 0,
        swipe_page: int = 0,
        grid_slot: int = 0,
    ) -> bool:
        return register_card(
            self,
            cand,
            score,
            crop=crop,
            cy=cy,
            cx=cx,
            swipe_page=swipe_page,
            grid_slot=grid_slot,
        )

    def _match_row_with_alignment(
        self, grid_img: np.ndarray, cy: float, col_xs: list[int], half_w: int, half_h: int
    ) -> tuple[float, list[tuple[dict[str, Any] | None, float, np.ndarray, int, int]]]:
        return match_row_with_alignment(self, grid_img, cy, col_xs, half_w, half_h)

    def run(self) -> None:
        """Main automated scanning loop with visual tracking, filter verification, and position logging."""
        from dokkan_eza_link_farmer.automation.scanner.legacy_grid import run_grid_scan

        run_grid_scan(self)


__all__ = [
    "CACHE_BOX_PATH",
    "CANONICAL_BOX_PATH",
    "DEFAULT_BOX_SCAN_LOG_PATH",
    "DEFAULT_USER_BOX_PATH",
    "BoxScannerTask",
    "_normalize_title",
    "advance_to_next_card",
    "compute_screen_diff",
    "detect_rainbow_star",
    "execute_ocr_fallback",
    "extract_banner_text",
    "extract_element_badge",
    "extract_level_and_sa",
    "extract_potential_and_rainbow",
    "is_card_details_screen",
    "load_existing_box",
    "match_card_by_text",
    "match_card_candidate",
    "match_row_with_alignment",
    "normalize_title",
    "preprocess_text_banner",
    "read_card_title_from_screen",
    "register_card",
    "resolve_box_path",
    "save_box",
    "scroll_to_top",
    "stitch_marquee_text",
    "sync_box_cache",
    "track_vertical_shift",
    "verify_and_enforce_filters",
]
