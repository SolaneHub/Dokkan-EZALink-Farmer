from __future__ import annotations

import logging
import os
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import numpy as np

from dokkan_eza_link_farmer.ai.syncer import DokkanSyncer
from dokkan_eza_link_farmer.automation.scanner import (
    _DEFAULT_IMPORT_CACHE_BOX,
    CACHE_BOX_PATH,
    CANONICAL_BOX_PATH,
    DEFAULT_USER_BOX_PATH,
    ScanSessionContext,
    advance_to_next_card,
    compute_screen_diff,
    detect_rainbow_star,
    extract_banner_text,
    extract_element_badge,
    extract_level_and_sa,
    extract_potential_and_rainbow,
    is_card_details_screen,
    load_existing_box,
    match_card_by_text,
    match_card_candidate,
    normalize_title,
    preprocess_text_banner,
    read_card_title_from_screen,
    read_counter_total_cards,
    register_card,
    resolve_box_path,
    save_box,
    scan_detail_screen,
    scroll_to_top,
    stitch_marquee_text,
    sync_box_cache,
    verify_and_enforce_filters,
)
from dokkan_eza_link_farmer.automation.scanner.catalog_matcher import CatalogMatcher
from dokkan_eza_link_farmer.automation.tasks.base_task import BaseTask
from dokkan_eza_link_farmer.automation.vision import Vision
from dokkan_eza_link_farmer.core.system_tools import AppPaths
from dokkan_eza_link_farmer.integrations.adb_client import ADBClient
from dokkan_eza_link_farmer.integrations.dokkandb_client import DokkanDBClient

logger = logging.getLogger(__name__)

DEFAULT_BOX_SCAN_LOG_PATH = AppPaths.get_box_scan_log_path()
_DEFAULT_IMPORT_LOG_PATH = DEFAULT_BOX_SCAN_LOG_PATH
_normalize_title = normalize_title
_SHARED_OCR: Any = None


def get_shared_ocr() -> Any:
    """Returns a shared, cached RapidOCR engine instance to prevent thread pool leaks."""
    global _SHARED_OCR
    if _SHARED_OCR is None:
        try:
            from rapidocr_onnxruntime import RapidOCR

            _SHARED_OCR = RapidOCR()
            logger.info("RapidOCR engine initialized successfully.")
        except Exception as e:
            logger.error("Failed to initialize RapidOCR engine: %s", e)
    return _SHARED_OCR


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
        log_file: str | None = None,
    ):
        super().__init__(adb, vision, config, on_status, on_run_complete)
        self.dokkandb = dokkandb or DokkanDBClient()
        db_cache = getattr(self.dokkandb, "cache_dir", None)
        syncer_cache = db_cache if isinstance(db_cache, str) else None
        self.syncer = syncer or DokkanSyncer(cache_dir=syncer_cache)
        self.output_file = (
            output_file
            if (output_file is not None and output_file != _DEFAULT_IMPORT_CACHE_BOX)
            else (
                DEFAULT_USER_BOX_PATH
                if DEFAULT_USER_BOX_PATH != _DEFAULT_IMPORT_CACHE_BOX
                else AppPaths.get_user_box_path()
            )
        )
        self.max_cards_to_scan = max_cards_to_scan
        self.pure_grid_mode = config.get("pure_grid_mode", False)
        self.include_ssr = bool(config.get("include_ssr", False))
        self.log_file = (
            log_file
            if (log_file is not None and log_file != _DEFAULT_IMPORT_LOG_PATH)
            else (
                DEFAULT_BOX_SCAN_LOG_PATH
                if DEFAULT_BOX_SCAN_LOG_PATH != _DEFAULT_IMPORT_LOG_PATH
                else AppPaths.get_box_scan_log_path()
            )
        )
        self._file_handler: logging.Handler | None = None
        self._setup_file_logger()

        self._ocr = get_shared_ocr()

        self._catalog: list[dict[str, Any]] = []
        self._subname_index: dict[str, Any] = {}
        self.session_ctx = ScanSessionContext()
        self._load_existing_box()

    @property
    def _id_index(self) -> dict[int, dict[str, Any]]:
        return self.session_ctx.catalog_index

    @_id_index.setter
    def _id_index(self, val: dict[int, dict[str, Any]]) -> None:
        self.session_ctx.catalog_index = val if val is not None else {}

    @property
    def scanned_cards(self) -> dict[int, dict[str, Any]]:
        return self.session_ctx.scanned_cards

    @scanned_cards.setter
    def scanned_cards(self, val: dict[int, dict[str, Any]]) -> None:
        self.session_ctx.scanned_cards = val if val is not None else {}

    @property
    def _session_seen_ids(self) -> set[int]:
        return self.session_ctx.seen_ids

    @_session_seen_ids.setter
    def _session_seen_ids(self, val: set[int]) -> None:
        self.session_ctx.seen_ids = val if val is not None else set()

    @property
    def _recently_scanned_positions(self) -> dict[int, tuple[float, float]]:
        return self.session_ctx.recently_scanned_positions

    @_recently_scanned_positions.setter
    def _recently_scanned_positions(self, val: dict[int, tuple[float, float]]) -> None:
        self.session_ctx.recently_scanned_positions = val if val is not None else {}

    @property
    def _last_registered_card_id(self) -> int | None:
        return self.session_ctx.last_registered_card_id

    @_last_registered_card_id.setter
    def _last_registered_card_id(self, val: int | None) -> None:
        self.session_ctx.last_registered_card_id = val

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
        self.session_ctx.catalog_index = self._id_index
        for norm, cands in matcher._subname_index.items():
            if cands:
                self._subname_index[norm] = cands[0]

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

    def _register_card(
        self,
        cand: dict[str, Any] | None,
        score: float,
        crop: np.ndarray | None = None,
        cy: float = 0.0,
        cx: int = 0,
        swipe_page: int = 0,
        grid_slot: int = 0,
        is_rainbow: bool | None = None,
        is_eza: bool | None = None,
        potential_percent: int | None = None,
    ) -> bool:
        return register_card(
            self.session_ctx,
            cand,
            score,
            crop=crop,
            cy=cy,
            cx=cx,
            swipe_page=swipe_page,
            grid_slot=grid_slot,
            is_rainbow=is_rainbow,
            is_eza=is_eza,
            potential_percent=potential_percent,
            log_fn=self.log,
        )

    def run(self) -> None:
        """Main automated scanning loop using OCR detail evaluation and swipe progression."""
        self._setup_file_logger()
        start_time = datetime.now(timezone.utc)
        logger.info("=" * 70)
        logger.info(
            f"=== Dokkan Box Scanner Session Started: {start_time.strftime('%Y-%m-%d %H:%M:%S UTC')} ==="
        )
        logger.info(f"Log destination: {self.log_file}")
        logger.info(f"Box output target: {self.output_file}")
        logger.info(
            f"Max cards to scan: {self.max_cards_to_scan if self.max_cards_to_scan else 'unlimited'}"
        )
        logger.info(f"Include SSR: {self.include_ssr}")
        logger.info("=" * 70)

        self.is_running = True
        try:
            self.log(
                "🚀 Starting Autonomous Character Box Scanner (Detail Evaluator & Swipe Controller)..."
            )

            self._init_catalog()
            self.ensure_box_filters()

            w, h = self.adb.get_screen_size()
            self.log(f"Device resolution: {w}x{h}. Initializing detail scanning pipeline...")

            initial_screen = self.adb.screencap()
            if not self._is_card_details_screen(initial_screen):
                self.scroll_to_top()
                slot1_x = int(w * (110 / 1080.0))
                slot1_y = int(h * (604 / 2400.0))
                self.log(f"Opening first card details at ({slot1_x}, {slot1_y})...")
                self.adb.tap(slot1_x, slot1_y, delay_after=1.5)
                current_screen = self.adb.screencap()
                if not self._is_card_details_screen(current_screen):
                    self.log("Retrying opening card details...")
                    self.adb.tap(slot1_x, slot1_y, delay_after=1.5)
                    current_screen = self.adb.screencap()
            else:
                current_screen = initial_screen

            if self.session_ctx.scanned_cards is None:
                self.session_ctx.scanned_cards = {}
            self.session_ctx.recently_scanned_positions.clear()
            self.session_ctx.last_registered_card_id = None

            total_detected = read_counter_total_cards(current_screen, ocr=self._ocr)
            if total_detected:
                self.log(f"Detected total cards to scan from counter: {total_detected}")

            target_limit = self.max_cards_to_scan or total_detected or 9999
            scanned_count = 0

            while not self.is_stopped() and scanned_count < target_limit:
                cand, score, is_rainbow, is_eza, pot_pct = scan_detail_screen(self, current_screen)
                card_id = int(cand.get("id") or cand.get("card_id") or 0) if cand else None

                registered = self._register_card(
                    cand,
                    score=score,
                    crop=None,
                    swipe_page=scanned_count // 25,
                    grid_slot=scanned_count % 25,
                    is_rainbow=is_rainbow,
                    is_eza=is_eza,
                    potential_percent=pot_pct,
                )
                if registered:
                    scanned_count += 1

                total_instances = sum(int(c.get("copies", 1)) for c in self.scanned_cards.values())
                if self.max_cards_to_scan and total_instances >= self.max_cards_to_scan:
                    self.log(f"Reached target scan limit of {self.max_cards_to_scan} cards.")
                    break

                if scanned_count >= target_limit:
                    break

                current_screen, advanced = advance_to_next_card(
                    self, current_screen, current_card_id=card_id
                )
                if not advanced:
                    self.log("No further card advancement detected. End of character box reached.")
                    break

                if scanned_count % 5 == 0:
                    self._save_box(enrich=False)

            self.log("Enriching owned cards with DokkanDB links and optimal linking partners...")
            self._save_box(enrich=True)
            total_instances = sum(int(c.get("copies", 1)) for c in self.scanned_cards.values())
            self.log(
                f"✅ Box Scan Completed! Stored {total_instances} total cards ({len(self.scanned_cards)} unique) in '{self.output_file}'."
            )
        except Exception as exc:
            logger.exception(f"Unhandled exception during box scanning: {exc}")
            self.log(f"❌ Box scan interrupted by error: {exc}")
            raise
        finally:
            end_time = datetime.now(timezone.utc)
            duration = end_time - start_time
            total_cards = (
                sum(int(c.get("copies", 1)) for c in self.scanned_cards.values())
                if hasattr(self, "scanned_cards") and self.scanned_cards
                else 0
            )
            unique_cards = (
                len(self.scanned_cards)
                if hasattr(self, "scanned_cards") and self.scanned_cards
                else 0
            )
            logger.info("=" * 70)
            logger.info(
                f"=== Dokkan Box Scanner Session Ended: {end_time.strftime('%Y-%m-%d %H:%M:%S UTC')} (Duration: {duration}) ==="
            )
            logger.info(
                f"Final Count: {total_cards} total cards ({unique_cards} unique) in '{self.output_file}'"
            )
            logger.info("=" * 70)
            self.is_running = False
            self._close_file_logger()


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
    "extract_banner_text",
    "extract_element_badge",
    "extract_level_and_sa",
    "extract_potential_and_rainbow",
    "is_card_details_screen",
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
    "scan_detail_screen",
    "scroll_to_top",
    "stitch_marquee_text",
    "sync_box_cache",
    "verify_and_enforce_filters",
]
