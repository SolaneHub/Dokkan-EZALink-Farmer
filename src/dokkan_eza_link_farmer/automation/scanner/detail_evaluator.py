"""Visual detail evaluator for Dokkan cards (Rainbow star, Level, SA, and Element badge)."""

from __future__ import annotations

import logging
import re
from typing import Any

import cv2
import numpy as np

logger = logging.getLogger(__name__)

BADGE_CROP_Y: tuple[float, float] = (0.205, 0.255)
BADGE_CROP_X: tuple[float, float] = (0.02, 0.15)

LEVEL_CROP_Y: tuple[float, float] = (0.710, 0.755)
LEVEL_CROP_X: tuple[float, float] = (0.14, 0.44)

SA_CROP_Y: tuple[float, float] = (0.805, 0.840)
SA_CROP_X: tuple[float, float] = (0.02, 0.16)

POTENTIAL_CROP_Y: tuple[float, float] = (0.10, 0.17)
POTENTIAL_CROP_X: tuple[float, float] = (0.18, 0.35)


def detect_rainbow_star(screen_or_crop: np.ndarray | None) -> bool:
    """
    Detects if the card has 100% Hidden Potential rainbow star in thumbnail crop
    or full screen Character Details view.
    """
    if (
        screen_or_crop is None
        or not isinstance(screen_or_crop, np.ndarray)
        or screen_or_crop.size == 0
    ):
        return False
    h, w = screen_or_crop.shape[:2]
    if h > 500:
        y1, y2 = int(h * POTENTIAL_CROP_Y[0]), int(h * POTENTIAL_CROP_Y[1])
        x1, x2 = int(w * POTENTIAL_CROP_X[0]), int(w * POTENTIAL_CROP_X[1])
        crop = screen_or_crop[y1:y2, x1:x2]
    else:
        y1, y2 = int(h * 0.48), int(h * 0.88)
        x1, x2 = int(w * 0.60), int(w * 0.98)
        crop = screen_or_crop[y1:y2, x1:x2]

    if crop.size == 0:
        return False
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    cyan_mask = cv2.inRange(hsv, (80, 80, 120), (105, 255, 255))
    return bool(np.count_nonzero(cyan_mask) > 100)


class DetailEvaluator:
    """Evaluates card visual properties including rainbow star, element badge, level, and SA."""

    def __init__(self, ocr: Any = None) -> None:
        self.ocr = ocr

    def detect_rainbow_star(self, screen_or_crop: np.ndarray | None) -> bool:
        """Detects if thumbnail crop contains the rainbow star."""
        return detect_rainbow_star(screen_or_crop)

    def extract_element_badge(self, screen_img: np.ndarray | None) -> tuple[str | None, str | None]:
        """
        Extracts Class ('SUPER' / 'EXTREME') and Element ('AGL' / 'TEQ' / 'INT' / 'STR' / 'PHY')
        from the badge ROI in upper left.
        """
        if (
            self.ocr is None
            or screen_img is None
            or not isinstance(screen_img, np.ndarray)
            or screen_img.size == 0
        ):
            return None, None

        h, w = screen_img.shape[:2]
        y1, y2 = int(h * BADGE_CROP_Y[0]), int(h * BADGE_CROP_Y[1])
        x1, x2 = int(w * BADGE_CROP_X[0]), int(w * BADGE_CROP_X[1])

        crop = screen_img[y1:y2, x1:x2]
        if crop.size == 0:
            return None, None

        card_class = None
        card_elem = None
        try:
            results, _ = self.ocr(crop)
            if results:
                text = " ".join(
                    [str(item[1]) for item in results if item and len(item) > 1]
                ).upper()
                if "EXTREME" in text or "EXT" in text:
                    card_class = "EXTREME"
                elif "SUPER" in text or "SUP" in text:
                    card_class = "SUPER"

                for elem in ("AGL", "TEQ", "INT", "STR", "PHY"):
                    if elem in text:
                        card_elem = elem
                        break
        except Exception as exc:
            logger.debug(f"Badge OCR error: {exc}")

        return card_class, card_elem

    def extract_level_and_sa(
        self, screen_img: np.ndarray | None, rarity: int = 4
    ) -> tuple[bool, bool, int, int]:
        """
        Extracts Level and SA Level from character details screen.
        Returns: (is_eza, is_seza, current_level, max_level)
        """
        if (
            self.ocr is None
            or screen_img is None
            or not isinstance(screen_img, np.ndarray)
            or screen_img.size == 0
        ):
            return False, False, 0, 0

        h, w = screen_img.shape[:2]
        is_eza = False
        is_seza = False
        curr_lv, max_lv = 0, 0

        # 1. Level ROI
        ly1, ly2 = int(h * LEVEL_CROP_Y[0]), int(h * LEVEL_CROP_Y[1])
        lx1, lx2 = int(w * LEVEL_CROP_X[0]), int(w * LEVEL_CROP_X[1])
        lcrop = screen_img[ly1:ly2, lx1:lx2]
        if lcrop.size > 0:
            try:
                res_l, _ = self.ocr(lcrop)
                if res_l:
                    l_text = " ".join([str(it[1]) for it in res_l if it and len(it) > 1])
                    m = re.search(r"(\d+)\s*/\s*(\d+)", l_text)
                    if m:
                        curr_lv = int(m.group(1))
                        max_lv = int(m.group(2))
                        if max_lv == 140:
                            is_eza = True
                        elif max_lv == 150 and rarity == 4:
                            is_eza = True
                            is_seza = True
            except Exception as exc:
                logger.debug(f"Level OCR error: {exc}")

        # 2. Super Attack ROI
        sy1, sy2 = int(h * SA_CROP_Y[0]), int(h * SA_CROP_Y[1])
        sx1, sx2 = int(w * SA_CROP_X[0]), int(w * SA_CROP_X[1])
        scrop = screen_img[sy1:sy2, sx1:sx2]
        if scrop.size > 0:
            try:
                res_sa, _ = self.ocr(scrop)
                if res_sa:
                    sa_text = " ".join([str(it[1]) for it in res_sa if it and len(it) > 1])
                    m = re.search(r"(\d+)\s*/\s*(\d+)", sa_text)
                    if m:
                        sa_max = int(m.group(2))
                        if sa_max in (15, 25):
                            is_eza = True
            except Exception as exc:
                logger.debug(f"SA OCR error: {exc}")

        return is_eza, is_seza, curr_lv, max_lv

    def extract_potential_and_rainbow(
        self, screen_img: np.ndarray | None, curr_sa: int = 10, max_sa: int = 10
    ) -> tuple[bool, int]:
        """
        Verifies if Rainbow star is present or if RapidOCR reads '100%' in the Hidden Potential ROI.
        Prevents false triggers on card art auras.
        """
        if screen_img is None or not isinstance(screen_img, np.ndarray) or screen_img.size == 0:
            return False, 0

        # Cards with SA < 10 cannot legally be 100% rainbow (bottom-right path requires SA 10)
        if curr_sa < 10 and max_sa <= 10:
            return False, 0

        h, w = screen_img.shape[:2]
        is_rainbow = self.detect_rainbow_star(screen_img)
        pot_percent = 100 if is_rainbow else 0

        if not is_rainbow and self.ocr is not None:
            y1, y2 = int(h * POTENTIAL_CROP_Y[0]), int(h * POTENTIAL_CROP_Y[1])
            x1, x2 = int(w * POTENTIAL_CROP_X[0]), int(w * POTENTIAL_CROP_X[1])
            crop = screen_img[y1:y2, x1:x2]
            if crop.size > 0:
                try:
                    results, _ = self.ocr(crop)
                    if results:
                        text = " ".join([str(it[1]) for it in results if it and len(it) > 1])
                        m = re.search(r"(\d{1,3})%", text)
                        if m:
                            pot_percent = int(m.group(1))
                            if pot_percent == 100:
                                is_rainbow = True
                except Exception as exc:
                    logger.debug(f"Potential OCR error: {exc}")

        return is_rainbow, pot_percent

    _detect_rainbow_star = detect_rainbow_star
    _extract_element_badge = extract_element_badge
    _extract_level_and_sa = extract_level_and_sa
    _extract_potential_and_rainbow = extract_potential_and_rainbow


def extract_element_badge(
    screen_img: np.ndarray | None, ocr: Any = None
) -> tuple[str | None, str | None]:
    return DetailEvaluator(ocr=ocr).extract_element_badge(screen_img)


def extract_level_and_sa(
    screen_img: np.ndarray | None, ocr: Any = None, rarity: int = 4
) -> tuple[bool, bool, int, int]:
    return DetailEvaluator(ocr=ocr).extract_level_and_sa(screen_img, rarity=rarity)


def extract_potential_and_rainbow(
    screen_img: np.ndarray | None, ocr: Any = None, curr_sa: int = 10, max_sa: int = 10
) -> tuple[bool, int]:
    return DetailEvaluator(ocr=ocr).extract_potential_and_rainbow(
        screen_img, curr_sa=curr_sa, max_sa=max_sa
    )


def save_diagnostic_crops(
    screen_img: np.ndarray | None,
    output_dir: str | None = None,
    prefix: str = "card",
) -> None:
    """Saves full screen, banner, and level crops to disk for post-mortem debugging."""
    if screen_img is None or not isinstance(screen_img, np.ndarray) or screen_img.size == 0:
        return
    import os
    import time

    target_dir = output_dir or os.path.join(
        os.path.expanduser("~"), ".dokkan-farmer", "debug_crops"
    )
    try:
        os.makedirs(target_dir, exist_ok=True)
        h, w = screen_img.shape[:2]
        ts = int(time.time() * 1000)

        # 1. Full Screen
        full_path = os.path.join(target_dir, f"{prefix}_{ts}_full.png")
        cv2.imwrite(full_path, screen_img)

        # 2. Banner Crop
        from dokkan_eza_link_farmer.automation.scanner.banner_extractor import (
            BANNER_CROP_X,
            BANNER_CROP_Y,
        )

        by1, by2 = int(h * BANNER_CROP_Y[0]), int(h * BANNER_CROP_Y[1])
        bx1, bx2 = int(w * BANNER_CROP_X[0]), int(w * BANNER_CROP_X[1])
        banner = screen_img[by1:by2, bx1:bx2]
        if banner.size > 0:
            banner_rot = cv2.rotate(banner, cv2.ROTATE_90_CLOCKWISE)
            cv2.imwrite(os.path.join(target_dir, f"{prefix}_{ts}_banner.png"), banner_rot)

        # 3. Level Crop
        ly1, ly2 = int(h * LEVEL_CROP_Y[0]), int(h * LEVEL_CROP_Y[1])
        lx1, lx2 = int(w * LEVEL_CROP_X[0]), int(w * LEVEL_CROP_X[1])
        level_crop = screen_img[ly1:ly2, lx1:lx2]
        if level_crop.size > 0:
            cv2.imwrite(os.path.join(target_dir, f"{prefix}_{ts}_level.png"), level_crop)

        logger.debug("[TRANSPARENCY] Saved diagnostic crops to %s", target_dir)
    except Exception as exc:
        logger.debug("[TRANSPARENCY] Could not save diagnostic crop: %s", exc)


def scan_detail_screen(
    task: Any, screen_img: np.ndarray
) -> tuple[dict[str, Any] | None, float, bool, bool, int]:
    """Scans a single Character Details screen with anti-SFX and adaptive 2-frame marquee stitch."""
    import time

    text_f1 = task._extract_banner_text(screen_img)
    card_class, card_elem = task._extract_element_badge(screen_img)
    cand, score = task._match_card_candidate(
        text_f1, detected_class=card_class, detected_elem=card_elem
    )
    if score < 0.85:
        task.log(
            f"  [MARQUEE] Low confidence ({score:.2f} < 0.85) on '{text_f1}' (class: {card_class}, elem: {card_elem}). "
            f"Triggering 2-frame marquee stitch..."
        )
        time.sleep(1.0)
        frame2 = task.adb.screencap() if task.adb else None
        text_f2 = task._extract_banner_text(frame2) if frame2 is not None else ""
        stitched_text = task._stitch_marquee_text(text_f1, text_f2)
        cand2, score2 = task._match_card_candidate(
            stitched_text, detected_class=card_class, detected_elem=card_elem
        )
        if score2 > score:
            cand, score = cand2, score2
            task.log(
                f"  [MARQUEE] Stitched text: '{stitched_text}' -> [{cand.get('id') if cand else '?'}] conf {score:.2f}"
            )
        else:
            task.log(
                f"  [MARQUEE] Stitched matching did not improve score ({score2:.2f} <= {score:.2f}). Retaining initial candidate."
            )

        # Save diagnostic crops when confidence remains low or no candidate could be identified
        if score < 0.85:
            diag_dir = getattr(task, "debug_crops_dir", None)
            save_diagnostic_crops(screen_img, output_dir=diag_dir, prefix=f"low_conf_{score:.2f}")

    rarity = cand.get("rarity", 4) if cand else 4
    is_eza, is_seza, curr_lv, max_lv = task._extract_level_and_sa(screen_img, rarity=rarity)

    curr_sa, max_sa = 1, 10
    if screen_img is not None and getattr(screen_img, "size", 0) > 0 and task._ocr is not None:
        h_s, w_s = screen_img.shape[:2]
        scrop = screen_img[
            int(h_s * SA_CROP_Y[0]) : int(h_s * SA_CROP_Y[1]),
            int(w_s * SA_CROP_X[0]) : int(w_s * SA_CROP_X[1]),
        ]
        if scrop.size > 0:
            try:
                res_sa, _ = task._ocr(scrop)
                if res_sa:
                    sa_text = " ".join([str(it[1]) for it in res_sa if it and len(it) > 1])
                    m = re.search(r"(\d+)\s*/\s*(\d+)", sa_text)
                    if m:
                        curr_sa, max_sa = int(m.group(1)), int(m.group(2))
            except Exception:
                pass

    is_rainbow, pot_pct = task._extract_potential_and_rainbow(
        screen_img, curr_sa=curr_sa, max_sa=max_sa
    )
    return cand, score, is_rainbow, is_eza, pot_pct


_detect_rainbow_star = detect_rainbow_star
_extract_element_badge = extract_element_badge
_extract_level_and_sa = extract_level_and_sa
_extract_potential_and_rainbow = extract_potential_and_rainbow

__all__ = [
    "BADGE_CROP_X",
    "BADGE_CROP_Y",
    "DetailEvaluator",
    "LEVEL_CROP_X",
    "LEVEL_CROP_Y",
    "POTENTIAL_CROP_X",
    "POTENTIAL_CROP_Y",
    "SA_CROP_X",
    "SA_CROP_Y",
    "_detect_rainbow_star",
    "_extract_element_badge",
    "_extract_level_and_sa",
    "_extract_potential_and_rainbow",
    "detect_rainbow_star",
    "extract_element_badge",
    "extract_level_and_sa",
    "extract_potential_and_rainbow",
    "save_diagnostic_crops",
    "scan_detail_screen",
]
