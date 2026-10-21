from __future__ import annotations

import difflib
import json
import logging
import os
import re
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import cv2
import numpy as np

from dokkan_eza_link_farmer.ai.syncer import DokkanSyncer
from dokkan_eza_link_farmer.automation.tasks.base_task import BaseTask
from dokkan_eza_link_farmer.automation.vision import Vision
from dokkan_eza_link_farmer.integrations.adb_client import ADBClient
from dokkan_eza_link_farmer.integrations.dokkandb_client import DokkanDBClient

logger = logging.getLogger(__name__)

CANONICAL_BOX_PATH = "config/box.json"
CACHE_BOX_PATH = os.path.join(os.path.expanduser("~"), ".dokkan-farmer", "cache", "user_box.json")
DEFAULT_USER_BOX_PATH = CACHE_BOX_PATH
DEFAULT_BOX_SCAN_LOG_PATH = os.path.join(os.path.expanduser("~"), ".dokkan-farmer", "box_scan.log")


def resolve_box_path(preferred_path: str | None = None) -> str:
    """Resolves canonical user box path.
    If preferred_path is an explicit custom path (not default cache/canonical), return it.
    Otherwise prefer canonical config/box.json if exists; then cache user_box.json if exists.
    """
    if preferred_path and preferred_path not in (
        DEFAULT_USER_BOX_PATH,
        CACHE_BOX_PATH,
        CANONICAL_BOX_PATH,
    ):
        return preferred_path
    if os.path.exists(CANONICAL_BOX_PATH):
        return CANONICAL_BOX_PATH
    if os.path.exists(CACHE_BOX_PATH):
        return CACHE_BOX_PATH
    return preferred_path or CANONICAL_BOX_PATH


def sync_box_cache(source_path: str, target_path: str | None = None) -> None:
    """Synchronizes source box file to target paths (keeping config/box.json and cache mirror in sync)."""
    import shutil

    if not source_path or not os.path.exists(source_path):
        return

    # Only sync if the source is one of the standard box paths or target is explicitly given
    if target_path:
        destinations = [target_path]
    elif os.path.abspath(source_path) == os.path.abspath(CANONICAL_BOX_PATH):
        destinations = [CACHE_BOX_PATH]
    elif os.path.abspath(source_path) == os.path.abspath(CACHE_BOX_PATH):
        destinations = [CANONICAL_BOX_PATH]
    else:
        return  # Custom test/isolated file; do not overwrite global config/cache

    source_real = os.path.abspath(source_path)
    for dest in destinations:
        if not dest:
            continue
        dest_real = os.path.abspath(dest)
        if source_real != dest_real:
            try:
                os.makedirs(os.path.dirname(dest_real), exist_ok=True)
                shutil.copy2(source_path, dest_real)
                logger.debug("Synchronized box file from %s to %s", source_path, dest_real)
            except Exception as exc:
                logger.debug("Failed to sync box from %s to %s: %s", source_path, dest_real, exc)


def _normalize_title(text: str) -> str:
    """Removes non-alphanumeric characters and lowercases text for robust matching."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


class BoxScannerTask(BaseTask):
    """
    Autonomously scans the player's personal in-game Character Box via ADB,
    extracts card titles using OCR and template matching against DokkanDB catalog,
    and builds ~/.dokkan-farmer/cache/user_box.json with swipe_page and grid_slot coordinates.
    """

    # 5 columns x 5 rows grid coordinates for standard 1080x2400 resolution
    COL_RATIOS = [0.102, 0.301, 0.500, 0.699, 0.898]  # ~110, 325, 540, 755, 970
    ROW_RATIOS = [0.252, 0.3575, 0.463, 0.568, 0.674]  # ~605, 858, 1111, 1364, 1617

    # Back button in Character Details screen
    BACK_BUTTON_RATIO = (0.139, 0.858)  # (150, 2060)

    # Subname text bounding box on Character Details screen (rotated 90 deg counter-clockwise)
    TITLE_CROP_Y = (0.058, 0.375)  # 140..900
    TITLE_CROP_X = (0.777, 0.926)  # 840..1000

    @staticmethod
    def _compute_screen_diff(
        img1: np.ndarray | None,
        img2: np.ndarray | None,
        roi: tuple[int, int, int, int] | None = None,
    ) -> float:
        """Computes mean absolute pixel difference between two screens to detect lack of motion.
        Returns 0.0 for identical frames.
        """
        if img1 is None or img2 is None:
            return 999.0
        if not isinstance(img1, np.ndarray) or not isinstance(img2, np.ndarray):
            return 999.0
        if img1.shape != img2.shape or img1.size == 0 or img2.size == 0:
            return 999.0
        if roi:
            y1, y2, x1, x2 = roi
            g1 = img1[y1:y2, x1:x2]
            g2 = img2[y1:y2, x1:x2]
        else:
            h, w = img1.shape[:2]
            g1 = img1[int(h * 0.22) : int(h * 0.75), :]
            g2 = img2[int(h * 0.22) : int(h * 0.75), :]
        diff = cv2.absdiff(g1, g2)
        return float(np.mean(diff))

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

        # Initialize OCR engine
        self._ocr = None
        try:
            from rapidocr_onnxruntime import RapidOCR

            self._ocr = RapidOCR()
            logger.info("RapidOCR engine initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize RapidOCR engine: {e}")

        # Catalog lookup structures
        self._catalog: list[dict[str, Any]] = []
        self._subname_index: dict[str, dict[str, Any]] = {}
        self._id_index: dict[int, dict[str, Any]] = {}
        self._loaded_thumbs: list[dict[str, Any]] = []
        self._lr_thumbs: list[dict[str, Any]] = []

        # Owned cards map: {card_id: card_dict}
        self.scanned_cards: dict[int, dict[str, Any]] = {}
        self._load_existing_box()

    def _setup_file_logger(self) -> None:
        """Sets up a debug file handler saving all box scanner events to ~/.dokkan-farmer/box_scan.log."""
        if not self.log_file:
            return

        try:
            target_path = os.path.abspath(self.log_file)
            os.makedirs(os.path.dirname(target_path), exist_ok=True)

            pkg_logger = logging.getLogger("dokkan_eza_link_farmer")

            # Check if this exact handler is already attached
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
        """Emits a log message to the registered status callback and debug file logger."""
        logger.info(message)
        super().log(message)

    def _load_existing_box(self) -> None:
        """Loads previously scanned cards so scans are incremental and resumeable."""
        target_path = resolve_box_path(self.output_file)

        if os.path.exists(target_path):
            try:
                with open(target_path, encoding="utf-8") as f:
                    data = json.load(f)
                card_list = data if isinstance(data, list) else data.get("cards", [])
                for item in card_list:
                    if isinstance(item, dict) and "id" in item:
                        self.scanned_cards[int(item["id"])] = item
                    elif isinstance(item, int):
                        self.scanned_cards[item] = {"id": item, "copies": 1}
                logger.info(f"Loaded {len(self.scanned_cards)} existing cards from {target_path}")
            except Exception as e:
                logger.warning(f"Could not load existing box from {target_path}: {e}")

    def _save_box(self, enrich: bool = True) -> None:
        """Persists discovered cards to output_file, optionally enriching with DokkanDB details and best linking partners."""
        os.makedirs(os.path.dirname(os.path.abspath(self.output_file)), exist_ok=True)
        card_list = list(self.scanned_cards.values())
        if enrich and self.dokkandb:
            try:
                enriched = self.dokkandb.enrich_box(card_list)
                if isinstance(enriched, list):
                    card_list = enriched
                    for ec in card_list:
                        if isinstance(ec, dict):
                            cid = int(ec.get("id") or 0)
                            if cid and cid in self.scanned_cards:
                                orig = self.scanned_cards[cid]
                                ec["copies"] = orig.get("copies", 1)
                                ec["swipe_page"] = orig.get("swipe_page", 0)
                                ec["grid_slot"] = orig.get("grid_slot", 0)
                                ec["is_eza"] = orig.get("is_eza", False)
                                ec["is_seza"] = orig.get("is_seza", False)
                                ec["potential_percent"] = orig.get("potential_percent", 0)
                                self.scanned_cards[cid] = ec
            except Exception as e:
                logger.warning(f"Error enriching box with DokkanDB: {e}")

        total_instances = sum(int(c.get("copies", 1)) for c in self.scanned_cards.values())
        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "total_cards": total_instances,
            "unique_cards": len(self.scanned_cards),
            "cards": card_list,
        }
        with open(self.output_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        # Synchronize with canonical config/box.json or cache mirror
        sync_box_cache(self.output_file)

    def ensure_box_filters(self) -> bool:
        """
        Verifies that Character Box filters are set appropriately and sorted by Released.
        1. Checks Sort by Released on main grid.
        2. Checks tag_filter_on.png on main grid.
        3. If UR+LR filters are not confirmed active, opens filter popup, ensures UR and LR buttons
           are selected (clicking unselected if needed), and confirms with button_ok.png.
        """
        if not self.vision:
            return True

        screen = self.adb.screencap()
        size = self.adb.get_screen_size() if self.adb else (1080, 2400)
        w, h = size if isinstance(size, (tuple, list)) and len(size) >= 2 else (1080, 2400)

        sort_ok = bool(
            self.vision.find_template(screen, "filters/tag_sort_released.png", threshold=0.75)
            or (hasattr(self.vision, "is_sort_released") and self.vision.is_sort_released(screen))
        )
        filter_on = bool(
            self.vision.find_template(screen, "filters/tag_filter_on.png", threshold=0.75)
        )

        if not filter_on:
            self.log("Filters not active on grid. Opening filter popup to configure UR+LR...")
            # Open filter popup: click filter button or tag_filter_on / fallback at (0.90 * w, 0.95 * h)
            filter_btn_loc = self.vision.find_template(
                screen, "filters/tag_filter_on.png", threshold=0.75
            )
            if filter_btn_loc:
                self.adb.tap(filter_btn_loc[0], filter_btn_loc[1], delay_after=1.0)
            else:
                self.adb.tap(int(w * 0.90), int(h * 0.95), delay_after=1.0)

            popup_screen = self.adb.screencap()

            # Check UR filter
            ur_selected = bool(
                self.vision.find_template(
                    popup_screen, "filters/btn_ur_selected.png", threshold=0.75
                )
            )
            if not ur_selected:
                ur_unsel_loc = self.vision.find_template(
                    popup_screen, "filters/btn_ur_unselected.png", threshold=0.75
                )
                if ur_unsel_loc:
                    self.adb.tap(ur_unsel_loc[0], ur_unsel_loc[1], delay_after=0.5)
                else:
                    self.adb.tap(int(w * 0.70), int(h * 0.638), delay_after=0.5)
                popup_screen = self.adb.screencap()

            # Check LR filter
            lr_selected = bool(
                self.vision.find_template(
                    popup_screen, "filters/btn_lr_selected.png", threshold=0.75
                )
            )
            if not lr_selected:
                lr_unsel_loc = self.vision.find_template(
                    popup_screen, "filters/btn_lr_unselected.png", threshold=0.75
                )
                if lr_unsel_loc:
                    self.adb.tap(lr_unsel_loc[0], lr_unsel_loc[1], delay_after=0.5)
                else:
                    self.adb.tap(int(w * 0.84), int(h * 0.638), delay_after=0.5)
                popup_screen = self.adb.screencap()

            # Confirm and close popup
            ok_loc = self.vision.find_template(
                popup_screen, "buttons/button_ok.png", threshold=0.75
            )
            if ok_loc:
                self.adb.tap(ok_loc[0], ok_loc[1], delay_after=1.0)
            else:
                self.adb.tap(int(w * 0.50), int(h * 0.85), delay_after=1.0)

            self.log(f"In-game box filters configured. SortReleased={sort_ok}")
            return True

        self.log(f"In-game box filters status: FilterOn={filter_on}, SortReleased={sort_ok}")
        return True

    def _init_catalog(self) -> None:
        """Loads and indexes DokkanDB cards catalog by subname and ID."""
        self.log("Fetching card database catalog from DokkanDB...")
        if self.syncer:
            try:
                self._catalog = self.syncer.sync_catalog(include_ssr=self.include_ssr)
            except Exception as e:
                logger.warning(f"Error syncing catalog via DokkanSyncer: {e}")
        if not self._catalog:
            self._catalog = self.dokkandb.get_cards_catalog()
        self.log(f"Indexed {len(self._catalog)} cards from DokkanDB catalog.")

        for card in self._catalog:
            cid = card.get("id")
            if cid:
                self._id_index[int(cid)] = card

            sub = card.get("subname")
            if sub:
                norm = _normalize_title(sub)
                if norm not in self._subname_index:
                    self._subname_index[norm] = card

            # Index awakening data forms as well
            awakening_list = card.get("awakening_data") or []
            for awk in awakening_list:
                awk_id = awk.get("id")
                if awk_id:
                    self._id_index[int(awk_id)] = awk
                awk_sub = awk.get("subname")
                if awk_sub:
                    awk_norm = _normalize_title(awk_sub)
                    if awk_norm not in self._subname_index:
                        self._subname_index[awk_norm] = awk

    def _init_thumbnails(self) -> None:
        """Loads and prepares character thumbnails for fast grid pattern matching."""
        cache_dir = os.path.join(self.dokkandb.cache_dir, "thumbs")
        os.makedirs(cache_dir, exist_ok=True)

        char_json_path = os.path.join(self.dokkandb.cache_dir, "dokkan_characters.json")
        char_map: dict[int, dict[str, Any]] = {}
        allowed_rarities = (3, 4, 5)

        # 1. Index cards from DokkanDB catalog (and their awakening forms)
        for c in self._catalog:
            cid = c.get("id")
            rarity = c.get("rarity")
            if rarity in allowed_rarities and cid:
                tid = int(str(cid)[:-1] + "0")
                char_map[tid] = {
                    "id": int(cid),
                    "name": c.get("name"),
                    "subname": c.get("subname"),
                    "rarity": "LR" if rarity == 5 else ("UR" if rarity == 4 else "SSR"),
                    "type": c.get("element"),
                    "has_survival_passive": bool(c.get("has_survival_passive")),
                }
            for awk in c.get("awakening_data") or []:
                aid = awk.get("id")
                arar = awk.get("rarity")
                if arar in allowed_rarities and aid:
                    atid = int(str(aid)[:-1] + "0")
                    if atid not in char_map:
                        char_map[atid] = {
                            "id": int(aid),
                            "name": awk.get("name"),
                            "subname": awk.get("subname"),
                            "rarity": "LR" if arar == 5 else ("UR" if arar == 4 else "SSR"),
                            "type": awk.get("element"),
                            "has_survival_passive": bool(awk.get("has_survival_passive")),
                        }

        # 2. Also incorporate dokkan_characters.json if present
        if os.path.exists(char_json_path):
            try:
                with open(char_json_path, encoding="utf-8") as f:
                    data = json.load(f)
                    for c in data:
                        tid = c.get("thumbId")
                        if tid and int(tid) not in char_map:
                            rar = c.get("rarity")
                            if rar in ("SSR", "UR", "LR"):
                                char_map[int(tid)] = c
            except Exception as e:
                logger.warning(f"Error reading dokkan_characters.json: {e}")

        thumb_files = [
            f for f in os.listdir(cache_dir) if f.startswith("card_") and f.endswith("_thumb.png")
        ]
        if len(thumb_files) < 10 and self.syncer and self._catalog:
            self.log("Downloading character thumbnails from Supabase mirror...")
            try:
                self.syncer.sync_thumbnails(cards=self._catalog)
                thumb_files = [
                    f
                    for f in os.listdir(cache_dir)
                    if f.startswith("card_") and f.endswith("_thumb.png")
                ]
            except Exception as e:
                logger.warning(f"Could not auto-download thumbnails from Supabase: {e}")

        self._loaded_thumbs = []

        type_map = {"AGI": "AGL", "TEC": "TEQ", "INT": "INT", "PUI": "STR", "END": "PHY"}
        blacklisted_thumbs = {1002910, 1024090, 1002300}

        valid_rarities = ("SSR", "UR", "LR")

        for f in thumb_files:
            fp = os.path.join(cache_dir, f)
            parts = f.replace("card_", "").replace("_thumb.png", "")
            tid = int(parts) if parts.isdigit() else None
            if not tid or tid in blacklisted_thumbs:
                continue

            info = char_map.get(tid)
            if not info:
                continue

            char_rarity = info.get("rarity")
            if char_rarity and char_rarity not in valid_rarities:
                continue

            im = cv2.imread(fp, cv2.IMREAD_UNCHANGED)
            if im is not None and len(im.shape) == 3 and im.shape[2] == 4 and im.shape[0] >= 200:
                alpha = im[:, :, 3]
                pts = np.argwhere(alpha > 80)
                if pts.size == 0:
                    continue

                y1, x1 = pts.min(axis=0)
                y2, x2 = pts.max(axis=0)
                p_cy = int(np.mean(pts[:, 0]))
                p_cx = int(np.mean(pts[:, 1]))

                char_crop = im[
                    max(0, p_cy - 55) : min(im.shape[0], p_cy + 55),
                    max(0, p_cx - 55) : min(im.shape[1], p_cx + 55),
                    :3,
                ]
                face_patch = cv2.resize(
                    char_crop, (int(char_crop.shape[1] * 0.84), int(char_crop.shape[0] * 0.84))
                )

                char_bgr = im[y1:y2, x1:x2, :3]
                char_mask = (alpha[y1:y2, x1:x2] > 80).astype(np.uint8) * 255
                scaled_bgr = cv2.resize(char_bgr, (0, 0), fx=0.84, fy=0.84)
                scaled_mask = cv2.resize(
                    char_mask, (0, 0), fx=0.84, fy=0.84, interpolation=cv2.INTER_NEAREST
                )

                card_id = int(info.get("id") or (tid + 1))
                elem_raw = info.get("type", "")
                elem_norm = type_map.get(elem_raw, elem_raw)
                has_surv = bool(info.get("has_survival_passive", False))
                self._loaded_thumbs.append(
                    {
                        "thumb_id": tid,
                        "card_id": card_id,
                        "name": info.get("name") or f"Card_{card_id}",
                        "subname": info.get("subname") or "",
                        "rarity": 5 if char_rarity == "LR" else (4 if char_rarity == "UR" else 3),
                        "type": elem_norm,
                        "has_survival_passive": has_surv,
                        "face_patch": face_patch,
                        "masked_bgr": scaled_bgr,
                        "masked_mask": scaled_mask,
                    }
                )

        self._lr_thumbs = [t for t in self._loaded_thumbs if t.get("rarity") == 5]
        self._special_thumbs = [
            t
            for t in self._loaded_thumbs
            if t.get("rarity") == 5
            or t.get("has_survival_passive")
            or " & " in t.get("name", "")
            or "/" in t.get("name", "")
            or " + " in t.get("name", "")
            or "(Giant Ape)" in t.get("name", "")
        ]
        self.log(
            f"Pre-loaded {len(self._loaded_thumbs)} character thumbnails ({len(self._lr_thumbs)} LRs, "
            f"{len(self._special_thumbs)} special effect/duo/LRs) for visual pattern matching."
        )

    def _match_slot_thumbnail(self, crop: np.ndarray) -> tuple[dict[str, Any] | None, float]:
        """Matches a single grid slot crop against pre-loaded thumbnails using two-pass matching."""
        cand, score, _ = self._match_slot_thumbnail_with_delta(crop)
        return cand, score

    def _match_slot_thumbnail_with_delta(
        self, crop: np.ndarray
    ) -> tuple[dict[str, Any] | None, float, float]:
        """
        Matches a single grid slot crop, returning (best_candidate, best_score, delta).
        Delta is the confidence margin between candidate #1 and #2.
        Crops central 65% to exclude rarity border and typing badge.
        """
        if not self._loaded_thumbs or crop is None or crop.size == 0:
            return None, 0.0, 0.0

        # Crop central 65% to exclude rarity frame and type badge
        ch, cw = crop.shape[:2]
        pad_h = int(ch * 0.175)
        pad_w = int(cw * 0.175)
        eval_crop = crop[pad_h : ch - pad_h, pad_w : cw - pad_w]
        if eval_crop.size == 0 or eval_crop.shape[0] < 20 or eval_crop.shape[1] < 20:
            eval_crop = crop

        scores: list[tuple[float, dict[str, Any]]] = []

        # Pass 1: Fast correlation over centered face patches
        for t in self._loaded_thumbs:
            patch = t["face_patch"]
            # Ensure patch fits inside eval_crop
            target = (
                eval_crop
                if eval_crop.shape[0] >= patch.shape[0] and eval_crop.shape[1] >= patch.shape[1]
                else crop
            )
            res = cv2.matchTemplate(target, patch, cv2.TM_CCOEFF_NORMED)
            score = float(cv2.minMaxLoc(res)[1])
            if score >= 0.25:
                scores.append((score, t))

        if not scores:
            return None, 0.0, 0.0

        scores.sort(key=lambda x: x[0], reverse=True)
        best_cand = scores[0][1]
        best_s = scores[0][0]
        second_s = scores[1][0] if len(scores) > 1 else 0.0
        delta = best_s - second_s

        if best_s >= 0.85 and delta >= 0.08:
            return best_cand, best_s, delta

        # Pass 2: High-accuracy masked correlation for shiny / holo LR cards or ambiguous matches
        eval_set: dict[int, dict[str, Any]] = {t["thumb_id"]: t for _, t in scores[:35]}
        ech, ecw = eval_crop.shape[:2]
        masked_scores: list[tuple[float, dict[str, Any]]] = []

        for t in eval_set.values():
            mbgr = t.get("masked_bgr")
            mmask = t.get("masked_mask")
            if mbgr is not None and mmask is not None:
                target = eval_crop if mbgr.shape[0] <= ech and mbgr.shape[1] <= ecw else crop
                if mbgr.shape[0] <= target.shape[0] and mbgr.shape[1] <= target.shape[1]:
                    res = cv2.matchTemplate(target, mbgr, cv2.TM_CCORR_NORMED, mask=mmask)
                    ms = float(cv2.minMaxLoc(res)[1])
                    masked_scores.append((ms, t))

        if masked_scores:
            masked_scores.sort(key=lambda x: x[0], reverse=True)
            if masked_scores[0][0] > best_s:
                best_s = masked_scores[0][0]
                best_cand = masked_scores[0][1]
                second_ms = masked_scores[1][0] if len(masked_scores) > 1 else 0.0
                delta = best_s - second_ms

        if best_s < 0.75 and delta < 0.06:
            return None, best_s, delta

        return best_cand, best_s, delta

    def _get_second_candidate(self, crop: np.ndarray) -> tuple[dict[str, Any] | None, float]:
        """Returns the second best thumbnail match candidate and its score for anti-collision evaluation."""
        if not self._loaded_thumbs or crop is None or crop.size == 0:
            return None, 0.0

        ch, cw = crop.shape[:2]
        pad_h = int(ch * 0.175)
        pad_w = int(cw * 0.175)
        eval_crop = crop[pad_h : ch - pad_h, pad_w : cw - pad_w]
        if eval_crop.size == 0 or eval_crop.shape[0] < 20 or eval_crop.shape[1] < 20:
            eval_crop = crop

        scores: list[tuple[float, dict[str, Any]]] = []
        for t in self._loaded_thumbs:
            patch = t["face_patch"]
            target = (
                eval_crop
                if eval_crop.shape[0] >= patch.shape[0] and eval_crop.shape[1] >= patch.shape[1]
                else crop
            )
            res = cv2.matchTemplate(target, patch, cv2.TM_CCOEFF_NORMED)
            score = float(cv2.minMaxLoc(res)[1])
            if score >= 0.25:
                scores.append((score, t))

        if len(scores) < 2:
            return None, 0.0

        scores.sort(key=lambda x: x[0], reverse=True)
        return scores[1][1], scores[1][0]

    def _execute_ocr_fallback(self, cx: int, cy: int) -> dict[str, Any] | None:
        """
        Fallback OCR: Taps the slot at (cx, cy) to open Character Details,
        extracts subname via RapidOCR, matches against indexed catalog,
        and taps the green back button (button_back_green.png) to return to the grid.
        """
        size = self.adb.get_screen_size() if self.adb else (1080, 2400)
        w, h = size if isinstance(size, (tuple, list)) and len(size) >= 2 else (1080, 2400)
        self.log(f"  [FALLBACK_OCR] Opening slot ({cx}, {cy}) for subname text verification...")
        self.adb.tap(cx, cy, delay_after=1.0)
        screen = self.adb.screencap()

        subname = self._read_card_title_from_screen(screen)
        matched = self._match_card_by_text(subname) if subname else None

        # Tap green back button
        back_loc = None
        if self.vision:
            back_loc = self.vision.find_template(
                screen, "buttons/button_back_green.png", threshold=0.70
            )
        if back_loc:
            self.adb.tap(back_loc[0], back_loc[1], delay_after=0.8)
        else:
            self.adb.tap(
                int(w * self.BACK_BUTTON_RATIO[0]),
                int(h * self.BACK_BUTTON_RATIO[1]),
                delay_after=0.8,
            )

        if matched:
            cid = int(matched.get("id") or 0)
            self.log(
                f"  [FALLBACK_OCR_MATCH] Identified: '{subname}' -> [{cid}] {matched.get('name')}"
            )
            return {
                "card_id": cid,
                "name": matched.get("name"),
                "subname": matched.get("subname"),
                "rarity": matched.get("rarity", 4),
                "element": matched.get("element"),
            }
        return None

    def _match_card_by_text(self, recognized_text: str) -> dict[str, Any] | None:
        """Matches recognized OCR text against indexed subnames."""
        if not recognized_text:
            return None

        clean_text = re.sub(
            r"^(?:growth|owth|wth|vth|uth|nth|rth|th)\b[\s\-\.$$\|]*",
            "",
            recognized_text,
            flags=re.IGNORECASE,
        ).strip()

        norm_query = _normalize_title(clean_text)
        if len(norm_query) < 3:
            return None

        # 1. Exact or substring match
        for norm_sub, card in self._subname_index.items():
            if norm_query in norm_sub or norm_sub in norm_query:
                return card

        # 2. Fuzzy sequence match
        best_card = None
        best_score = 0.0
        for norm_sub, card in self._subname_index.items():
            score = difflib.SequenceMatcher(None, norm_query, norm_sub).ratio()
            if score > best_score and score >= 0.68:
                best_score = score
                best_card = card

        return best_card

    def _read_card_title_from_screen(self, screen_img: np.ndarray) -> str | None:
        """Crops, rotates, and performs OCR on the card title region."""
        if self._ocr is None or screen_img is None:
            return None

        h, w = screen_img.shape[:2]
        y1, y2 = int(h * self.TITLE_CROP_Y[0]), int(h * self.TITLE_CROP_Y[1])
        x1, x2 = int(w * self.TITLE_CROP_X[0]), int(w * self.TITLE_CROP_X[1])

        crop = screen_img[y1:y2, x1:x2]
        if crop.size == 0:
            return None

        # Dokkan vertical banner has letters rotated 90 deg counter-clockwise
        rot = cv2.rotate(crop, cv2.ROTATE_90_CLOCKWISE)

        # Crop out the first 28% width of rot to exclude the Growth button
        if rot.shape[1] > 0:
            rot = rot[:, int(rot.shape[1] * 0.28) :]

        try:
            results, _ = self._ocr(rot)
            if not results:
                return None

            words = [str(item[1]) for item in results if item and len(item) > 1]
            return " ".join(words).strip()
        except Exception as e:
            logger.debug(f"OCR error: {e}")
            return None

    def _is_card_details_screen(self, screen_img: np.ndarray) -> bool:
        """Determines if the device is showing a Character Details view."""
        if screen_img is None:
            return False
        h, w = screen_img.shape[:2]

        # 1. On grid screen, the green 'Character' header banner is present at top
        grid_crop = screen_img[int(h * 0.11) : int(h * 0.13), int(w * 0.10) : int(w * 0.75)]
        green_header = np.count_nonzero(
            (grid_crop[:, :, 1] > 140) & (grid_crop[:, :, 2] < 70) & (grid_crop[:, :, 0] < 70)
        )
        if green_header > 500:
            return False

        # 2. Check green '<<<' back button at bottom-left: y: 0.84..0.88, x: 0.05..0.22
        back_crop = screen_img[int(h * 0.84) : int(h * 0.88), int(w * 0.05) : int(w * 0.22)]
        back_green = np.count_nonzero((back_crop[:, :, 1] > 100) & (back_crop[:, :, 2] < 120))

        # 3. Check orange ATK badge region: y: 0.64..0.68, x: 0.35..0.65
        stat_crop = screen_img[int(h * 0.64) : int(h * 0.68), int(w * 0.35) : int(w * 0.65)]
        orange_px = np.count_nonzero(
            (stat_crop[:, :, 0] < 60) & (stat_crop[:, :, 1] > 60) & (stat_crop[:, :, 2] > 180)
        )

        return bool(back_green > 200 and orange_px > 50)

    def _detect_rainbow_star(self, screen_or_crop: np.ndarray) -> bool:
        """Detects if the card has 100% Hidden Potential rainbow star."""
        if screen_or_crop is None or screen_or_crop.size == 0:
            return False
        h, w = screen_or_crop.shape[:2]
        if h > 500:
            # Full screen Character Details view
            y1, y2 = int(h * 0.10), int(h * 0.17)
            x1, x2 = int(w * 0.18), int(w * 0.35)
            crop = screen_or_crop[y1:y2, x1:x2]
        else:
            # 190x190 grid slot crop (star is in bottom-right corner)
            y1, y2 = int(h * 0.48), int(h * 0.88)
            x1, x2 = int(w * 0.60), int(w * 0.98)
            crop = screen_or_crop[y1:y2, x1:x2]

        if crop.size == 0:
            return False
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        # Sparkling facets (cyan facets: Hue 80..105, Sat > 80, Val > 120)
        cyan_mask = cv2.inRange(hsv, (80, 80, 120), (105, 255, 255))
        return bool(np.count_nonzero(cyan_mask) > 100)

    def scroll_to_top(self) -> None:
        """Scrolls Character List all the way to the top before beginning scan."""
        w, h = self.adb.get_screen_size()
        self.log("Ensuring Character List is scrolled to the top...")
        consecutive_top = 0
        for _ in range(35):
            if self.is_stopped():
                break
            before = self.adb.screencap()
            self.adb.swipe(
                int(w * 0.50),
                int(h * 0.25),
                int(w * 0.50),
                int(h * 0.85),
                duration_ms=200,
                delay_after=0.4,
            )
            after = self.adb.screencap()
            if self._is_card_details_screen(after):
                self.adb.tap(
                    int(w * self.BACK_BUTTON_RATIO[0]),
                    int(h * self.BACK_BUTTON_RATIO[1]),
                    delay_after=0.5,
                )
                after = self.adb.screencap()

            crop_b = before[int(h * 0.25) : int(h * 0.70), :]
            crop_a = after[int(h * 0.25) : int(h * 0.70), :]
            diff = float(np.mean(cv2.absdiff(crop_b, crop_a)))
            if diff < 10.0:
                consecutive_top += 1
                if consecutive_top >= 3:
                    break
            else:
                consecutive_top = 0
        self.log("Character List is positioned at the top.")

    def _track_vertical_shift(
        self, prev_img: np.ndarray, curr_img: np.ndarray, last_cy: float
    ) -> float | None:
        """Calculates exact pixel shift between consecutive screens using horizontal strip matching."""
        if prev_img is None or curr_img is None:
            return None
        h, w = prev_img.shape[:2]
        if curr_img.shape[:2] != (h, w) or h == 0 or w == 0:
            return None

        roi_y_start = int(h * 0.18)
        roi_y_end = int(h * 0.75)
        if roi_y_end <= roi_y_start:
            return None
        curr_img_roi = curr_img[roi_y_start:roi_y_end, :]

        # Primary attempt: Row 3 (strip_cy = 1111) or Row 4 (strip_cy = 1363). Fallback: Row 2 (strip_cy = 858).
        strip_candidates = [1111.0, 1363.0, 858.0]
        # If last_cy is valid and not already close to candidates, consider it as well
        if 550.0 <= last_cy <= 1650.0 and not any(abs(last_cy - c) < 40 for c in strip_candidates):
            strip_candidates.insert(0, last_cy)

        for strip_cy in strip_candidates:
            y1 = max(0, int(strip_cy - 40))
            y2 = min(h, int(strip_cy + 40))
            x1 = int(w * 0.10)
            x2 = int(w * 0.90)
            strip = prev_img[y1:y2, x1:x2]

            if strip.shape[0] < 20 or strip.shape[1] < 50:
                continue
            if curr_img_roi.shape[0] < strip.shape[0] or curr_img_roi.shape[1] < strip.shape[1]:
                continue

            res = cv2.matchTemplate(curr_img_roi, strip, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)

            if max_val >= 0.68:
                new_strip_cy = (roi_y_start + max_loc[1]) + (strip.shape[0] // 2)
                shift = strip_cy - new_strip_cy
                if shift > 30.0:
                    return float(shift)

        return None

    def _register_card(
        self,
        cand: dict[str, Any] | None,
        score: float,
        crop: np.ndarray,
        cy: float,
        cx: int,
        swipe_page: int = 0,
        grid_slot: int = 0,
    ) -> bool:
        """Registers a recognized card into self.scanned_cards with swipe_page and grid_slot coordinates."""
        if cand and score >= 0.72:
            cid = int(cand["card_id"])
            is_rainbow = self._detect_rainbow_star(crop)
            cat_card = self._id_index.get(cid) or {}
            cname = cat_card.get("name") or cand.get("name", "Unknown")
            csub = cat_card.get("subname") or ""
            rarity = cat_card.get("rarity") or cand.get("rarity", 4)
            elem = cat_card.get("element") or cand.get("element")
            has_eza_data = bool(
                cat_card.get("eza_leader_skill")
                or cat_card.get("passive_skills_rows_eza")
                or cat_card.get("eza_leader_skill_set_id")
                or cand.get("has_eza")
            )
            has_seza_data = bool(
                cat_card.get("eza_passive_skill_description_pre")
                or cat_card.get("passive_skills_rows_eza_pre")
                or cat_card.get("eza_leader_skill_set_id_pre")
            )
            is_seza = has_seza_data
            is_eza = has_eza_data or is_seza
            pot_pct = 100 if is_rainbow else 0

            # Check if this card was already scanned at nearly the same position (overlap re-scan)
            if not hasattr(self, "_recently_scanned_positions"):
                self._recently_scanned_positions = {}
            prev_pos = self._recently_scanned_positions.get(cid)
            if prev_pos is not None:
                if isinstance(prev_pos, (tuple, list)) and len(prev_pos) >= 2:
                    p_cy, p_cx = float(prev_pos[0]), float(prev_pos[1])
                elif isinstance(prev_pos, (int, float)):
                    p_cy, p_cx = float(prev_pos), float(cx)
                else:
                    p_cy, p_cx = float(cy), float(cx)
                if abs(p_cx - cx) < 60.0 and abs(p_cy - cy) < 180.0:
                    self._recently_scanned_positions[cid] = (cy, cx)
                    return True

            if cid not in self.scanned_cards:
                self.scanned_cards[cid] = {
                    "id": cid,
                    "name": cname,
                    "subname": csub,
                    "rarity": rarity,
                    "element": elem,
                    "is_rainbow": is_rainbow,
                    "is_eza": is_eza,
                    "is_seza": is_seza,
                    "potential_percent": pot_pct,
                    "copies": 1,
                    "swipe_page": swipe_page,
                    "grid_slot": grid_slot,
                    "scanned_at": datetime.now(timezone.utc).isoformat(),
                }
                self._last_registered_card_id = cid
                self._recently_scanned_positions[cid] = (cy, cx)
                rarity_str = "LR" if rarity == 5 else ("UR" if rarity == 4 else "SSR")
                star_str = "★ Rainbow" if is_rainbow else "★"
                self.log(
                    f"  [NEW] [{score:.2f}] #{len(self.scanned_cards)}: "
                    f"[{cid}] {cname} - '{csub}' ({rarity_str} {star_str}) [p:{swipe_page}, s:{grid_slot}]"
                )
            else:
                from_ocr = bool(cand.get("from_ocr"))
                # Mandatory Adjacency validation for DUPE increment (unless verified via OCR)
                if (
                    not from_ocr
                    and self._last_registered_card_id is not None
                    and self._last_registered_card_id != cid
                ):
                    self.log(
                        f"  [ANTI-COLLISION] Skipping non-adjacent DUPE registration for [{cid}] "
                        f"(last registered: {self._last_registered_card_id})."
                    )
                    return False
                self.scanned_cards[cid]["copies"] = self.scanned_cards[cid].get("copies", 1) + 1
                self._last_registered_card_id = cid
                self._recently_scanned_positions[cid] = (cy, cx)
                self.log(
                    f"  [DUPE] [{score:.2f}] Card [{cid}] {cname}: copy #{self.scanned_cards[cid]['copies']}"
                )
            return True
        elif cand and score >= 0.55:
            self.log(
                f"  [LOW_CONF] Slot ({int(cy)}, {cx}) candidate [{cand['card_id']}] {cand['name']} score {score:.2f} < 0.72"
            )
        return False

    def _match_row_with_alignment(
        self, grid_img: np.ndarray, cy: float, col_xs: list[int], half_w: int, half_h: int
    ) -> tuple[float, list[tuple[dict[str, Any] | None, float, np.ndarray, int, int]]]:
        """
        Matches a 5-card row with dynamic vertical micro-alignment (-50px to +50px).
        Evaluates delta and executes RapidOCR fallback when score < 0.72 or delta < 0.05.
        Applies Mandatory Adjacency Anti-Collision rule to eliminate false duplicates.
        """
        h, w = grid_img.shape[:2]

        test_cands: list[float] = []
        for c_idx in [0, 2]:
            if c_idx < len(col_xs):
                cx = col_xs[c_idx]
                crop = grid_img[
                    max(0, int(cy - half_h)) : min(h, int(cy + half_h)),
                    max(0, cx - half_w) : min(w, cx + half_w),
                ]
                _, s, _ = self._match_slot_thumbnail_with_delta(crop)
                test_cands.append(s)

        base_metric = max(test_cands) if test_cands else 0.0
        best_dy = 0.0
        best_metric = base_metric

        if base_metric < 0.80:
            for dy in [-50, -35, -20, 20, 35, 50]:
                adj_cy = cy + dy
                if adj_cy < 450 or adj_cy > 1750:
                    continue
                test_ys: list[float] = []
                for c_idx in [0, 2]:
                    if c_idx < len(col_xs):
                        cx = col_xs[c_idx]
                        crop = grid_img[
                            max(0, int(adj_cy - half_h)) : min(h, int(adj_cy + half_h)),
                            max(0, cx - half_w) : min(w, cx + half_w),
                        ]
                        _, s, _ = self._match_slot_thumbnail_with_delta(crop)
                        test_ys.append(s)
                cand_metric = max(test_ys) if test_ys else 0.0
                if cand_metric > best_metric:
                    best_metric = cand_metric
                    best_dy = float(dy)
                    if best_metric >= 0.88:
                        break

        final_cy = cy + best_dy

        row_results: list[tuple[dict[str, Any] | None, float, np.ndarray, int, int]] = []
        for c_idx, cx in enumerate(col_xs):
            crop = grid_img[
                max(0, int(final_cy - half_h)) : min(h, int(final_cy + half_h)),
                max(0, cx - half_w) : min(w, cx + half_w),
            ]
            cand, score, delta = self._match_slot_thumbnail_with_delta(crop)
            ocr_executed_for_slot = False

            # Check if this card was already scanned at nearly the same position (overlap re-scan)
            prev_pos = getattr(self, "_recently_scanned_positions", {}).get(
                int(cand["card_id"]) if cand else -1
            )
            is_overlap_rescan = False
            if prev_pos is not None:
                if isinstance(prev_pos, (tuple, list)) and len(prev_pos) >= 2:
                    p_cy, p_cx = float(prev_pos[0]), float(prev_pos[1])
                elif isinstance(prev_pos, (int, float)):
                    p_cy, p_cx = float(prev_pos), float(cx)
                else:
                    p_cy, p_cx = float(final_cy), float(cx)
                is_overlap_rescan = abs(p_cx - cx) < 60.0 and abs(p_cy - final_cy) < 180.0

            # Requirement 2.1: Anti-Collision Rule on [DUPE] (Mandatory Adjacency)
            # Under fixed in-game sorting (Sort: Released or Rarity), true duplicates
            # of the same card are strictly adjacent.
            if cand and int(cand["card_id"]) in self.scanned_cards and not is_overlap_rescan:
                cid = int(cand["card_id"])
                is_adjacent = (
                    self._last_registered_card_id is not None
                    and self._last_registered_card_id == cid
                )
                if not is_adjacent:
                    self.log(
                        f"  [ANTI-COLLISION] Slot ({int(final_cy)}, {cx}) candidate [{cid}] {cand.get('name')} "
                        f"already seen non-adjacently (last registered: {self._last_registered_card_id}). Rejecting false DUPE!"
                    )
                    cand2, s2 = self._get_second_candidate(crop)
                    if (
                        cand2
                        and s2 >= 0.70
                        and (
                            int(cand2["card_id"]) not in self.scanned_cards
                            or int(cand2["card_id"]) == self._last_registered_card_id
                        )
                    ):
                        self.log(
                            f"  [ANTI-COLLISION] Selected 2nd candidate [{cand2['card_id']}] {cand2.get('name')} (score: {s2:.2f})"
                        )
                        cand = cand2
                        score = s2
                    elif not self.pure_grid_mode:
                        ocr_executed_for_slot = True
                        delta = 1.0
                        fallback_cand = self._execute_ocr_fallback(cx, int(final_cy))
                        if fallback_cand:
                            cand = fallback_cand
                            cand["from_ocr"] = True
                            score = 1.0
                        else:
                            cand = None
                            score = 0.0
                    else:
                        cand = None
                        score = 0.0

            # Fallback OCR triggered when confidence < 0.72 or delta margin < 0.05
            if (
                (cand is None or score < 0.72 or delta < 0.05)
                and not self.pure_grid_mode
                and not ocr_executed_for_slot
                and score > 0.0
            ):
                fallback_cand = self._execute_ocr_fallback(cx, int(final_cy))
                if fallback_cand:
                    cand = fallback_cand
                    cand["from_ocr"] = True
                    score = 1.0

            # Synchronize last registered card id per slot so subsequent slots in row know adjacency
            if cand and score >= 0.72 and not is_overlap_rescan:
                self._last_registered_card_id = int(cand["card_id"])
            elif not is_overlap_rescan and (cand is None or score < 0.55):
                self._last_registered_card_id = None

            row_results.append((cand, score, crop, cx, c_idx))

        return final_cy, row_results

    def run(self) -> None:
        """Main automated scanning loop with visual tracking, filter verification, and position logging."""
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
        logger.info(f"Include SSR: {self.include_ssr}, Pure Grid Mode: {self.pure_grid_mode}")
        logger.info("=" * 70)

        self.is_running = True
        try:
            self.log(
                "🚀 Starting Autonomous Character Box Scanner (Visual Shift & Position Tracking)..."
            )

            self._init_catalog()
            self._init_thumbnails()

            # Check and ensure filters: UR + LR, Sort: Released
            self.ensure_box_filters()

            w, h = self.adb.get_screen_size()
            self.log(f"Device resolution: {w}x{h}. Initializing grid scanning...")

            initial_screen = self.adb.screencap()
            if self._is_card_details_screen(initial_screen):
                self.log("Detected open card detail view. Returning to grid...")
                self.adb.tap(
                    int(w * self.BACK_BUTTON_RATIO[0]),
                    int(h * self.BACK_BUTTON_RATIO[1]),
                    delay_after=1.0,
                )

            self.scroll_to_top()

            if not hasattr(self, "scanned_cards") or self.scanned_cards is None:
                self.scanned_cards = {}
            self._recently_scanned_positions = {}
            self._last_registered_card_id = None
            ROW_PITCH = 253.0
            half_w = int(w * 0.088)  # 95px
            half_h = 125
            col_xs = [int(w * r) for r in self.COL_RATIOS]
            max_visible_y = 1680.0

            curr_grid = self.adb.screencap()

            # Step 0: Scan all 5 rows of top screen (swipe_page = 0)
            top_row_ys = [int(h * r) for r in self.ROW_RATIOS]
            self.log(f"Scanning initial top screen (5 rows at y={top_row_ys})...")

            last_scanned_cy = float(top_row_ys[-1])
            for r_idx, cy in enumerate(top_row_ys):
                aligned_cy, row_results = self._match_row_with_alignment(
                    curr_grid, cy, col_xs, half_w, half_h
                )
                for cand, score, crop, cx, c_idx in row_results:
                    grid_slot = r_idx * 5 + c_idx
                    self._register_card(
                        cand, score, crop, aligned_cy, cx, swipe_page=0, grid_slot=grid_slot
                    )
                last_scanned_cy = float(aligned_cy)

            # Requirement 2.3: 3-row slow anti-inertia swipe with 2 rows guaranteed overlap
            SWIPE_ROWS = 3
            SWIPE_DELTA_Y = int(SWIPE_ROWS * ROW_PITCH)  # ~759px
            start_y = int(h * 0.65)
            end_y = start_y - SWIPE_DELTA_Y

            consecutive_stationary_swipes = 0
            swipe_count = 0

            while not self.is_stopped():
                swipe_count += 1

                total_instances = sum(int(c.get("copies", 1)) for c in self.scanned_cards.values())
                if self.max_cards_to_scan and total_instances >= self.max_cards_to_scan:
                    self.log(f"Reached target scan limit of {self.max_cards_to_scan} cards.")
                    break

                pre_swipe = curr_grid
                self.adb.swipe(
                    int(w * 0.50), start_y, int(w * 0.50), end_y, duration_ms=800, delay_after=1.0
                )

                next_grid = self.adb.screencap()
                if self._is_card_details_screen(next_grid):
                    self.adb.tap(
                        int(w * self.BACK_BUTTON_RATIO[0]),
                        int(h * self.BACK_BUTTON_RATIO[1]),
                        delay_after=0.5,
                    )
                    next_grid = self.adb.screencap()

                # Requirement 2.2: Fine-scroll termination based strictly on direct pixel diff.
                # Never stop for '0 new IDs' (screen could contain only duplicates or re-scanned rows).
                screen_diff = self._compute_screen_diff(pre_swipe, next_grid)
                logger.debug(f"Swipe #{swipe_count}: pixel diff = {screen_diff:.2f}")

                if screen_diff < 7.5:
                    consecutive_stationary_swipes += 1
                    self.log(
                        f"No vertical scroll detected via pixel diff ({screen_diff:.2f} < 7.5, "
                        f"{consecutive_stationary_swipes}/2 stationary swipes)..."
                    )
                    if consecutive_stationary_swipes >= 2:
                        remaining_rows = []
                        next_cy = last_scanned_cy + ROW_PITCH
                        while next_cy <= max_visible_y:
                            remaining_rows.append(next_cy)
                            next_cy += ROW_PITCH

                        if remaining_rows:
                            self.log(
                                f"Scanning final bottom rows: {[int(y) for y in remaining_rows]}"
                            )
                            for r_offset, cy in enumerate(remaining_rows):
                                aligned_cy, row_results = self._match_row_with_alignment(
                                    next_grid, cy, col_xs, half_w, half_h
                                )
                                for cand, score, crop, cx, c_idx in row_results:
                                    slot = (
                                        (len(top_row_ys) - len(remaining_rows) + r_offset) % 5
                                    ) * 5 + c_idx
                                    self._register_card(
                                        cand,
                                        score,
                                        crop,
                                        aligned_cy,
                                        cx,
                                        swipe_page=swipe_count,
                                        grid_slot=slot,
                                    )

                        self.log(
                            "✅ Reached bottom of Character List (pixel diff verified). Full Box scan completed!"
                        )
                        break

                    curr_grid = next_grid
                    continue
                shift = self._track_vertical_shift(curr_grid, next_grid, last_scanned_cy)
                if shift is None or shift < 50.0:
                    if screen_diff < 12.0:
                        self.log(
                            f"Low motion detected (diff: {screen_diff:.2f}, shift: {shift}). Treating as bottom boundary."
                        )
                        consecutive_stationary_swipes += 1
                        if consecutive_stationary_swipes >= 2:
                            break
                        curr_grid = next_grid
                        continue
                    shift = float(SWIPE_DELTA_Y)

                consecutive_stationary_swipes = 0

                new_anchor_cy = last_scanned_cy - shift
                new_rows = []
                k = 1
                while True:
                    next_cy = new_anchor_cy + k * ROW_PITCH
                    if next_cy > max_visible_y:
                        break
                    if next_cy >= 550.0:
                        new_rows.append(next_cy)
                    k += 1

                self.log(
                    f"Swipe #{swipe_count}: shift {shift:.0f}px ({(shift / ROW_PITCH):.2f} rows). "
                    f"Scanning {len(new_rows)} newly revealed rows: {[int(y) for y in new_rows]}"
                )

                if new_rows:
                    last_aligned = float(new_rows[-1])
                    for r_offset, cy in enumerate(new_rows):
                        aligned_cy, row_results = self._match_row_with_alignment(
                            next_grid, cy, col_xs, half_w, half_h
                        )
                        for cand, score, crop, cx, c_idx in row_results:
                            slot = ((r_offset + 3) % 5) * 5 + c_idx
                            self._register_card(
                                cand,
                                score,
                                crop,
                                aligned_cy,
                                cx,
                                swipe_page=swipe_count,
                                grid_slot=slot,
                            )
                        last_aligned = float(aligned_cy)
                    last_scanned_cy = last_aligned
                else:
                    last_scanned_cy = float(new_anchor_cy)

                curr_grid = next_grid

                if swipe_count % 3 == 0:
                    self._save_box(enrich=False)

            # Final DokkanDB enrichment with optimal linking partners
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
