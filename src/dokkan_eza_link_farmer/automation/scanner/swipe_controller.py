"""Swipe, navigation, and screen diff utilities for sequential 1-to-1 card details scanning."""

from __future__ import annotations

import logging
import re
import time
from typing import Any

import cv2
import numpy as np

logger = logging.getLogger(__name__)

COUNTER_CROP_Y: tuple[float, float] = (0.74, 0.79)
COUNTER_CROP_X: tuple[float, float] = (0.35, 0.65)


def compute_screen_diff(
    img1: np.ndarray | None,
    img2: np.ndarray | None,
    roi: tuple[int, int, int, int] | None = None,
) -> float:
    """Computes mean absolute pixel difference between two screens to detect lack of motion."""
    if (
        img1 is None
        or img2 is None
        or not isinstance(img1, np.ndarray)
        or not isinstance(img2, np.ndarray)
        or img1.shape != img2.shape
        or img1.size == 0
        or img2.size == 0
    ):
        return 999.0
    if roi:
        y1, y2, x1, x2 = roi
        g1, g2 = img1[y1:y2, x1:x2], img2[y1:y2, x1:x2]
    else:
        h = img1.shape[0]
        g1, g2 = img1[int(h * 0.22) : int(h * 0.75), :], img2[int(h * 0.22) : int(h * 0.75), :]
    return float(np.mean(cv2.absdiff(g1, g2)))


def read_counter_total_cards(screen_img: np.ndarray | None, ocr: Any = None) -> int | None:
    """OCR extracts target total card count from Character List counter ROI (e.g. '895/2000' -> 895)."""
    if (
        ocr is None
        or screen_img is None
        or not isinstance(screen_img, np.ndarray)
        or screen_img.size == 0
    ):
        return None
    h, w = screen_img.shape[:2]
    crop = screen_img[
        int(h * COUNTER_CROP_Y[0]) : int(h * COUNTER_CROP_Y[1]),
        int(w * COUNTER_CROP_X[0]) : int(w * COUNTER_CROP_X[1]),
    ]
    if crop.size == 0:
        return None
    try:
        results, _ = ocr(crop)
        if results:
            full_text = " ".join([str(item[1]) for item in results if item and len(item) > 1])
            m = re.search(r"(\d{1,4})\s*/\s*(\d{1,4})", full_text)
            if m:
                return int(m.group(1))
    except Exception as exc:
        logger.debug(f"Counter OCR error: {exc}")
    return None


def is_card_details_screen(screen_img: np.ndarray | None, ocr: Any = None) -> bool:
    """Determines if the device is showing a Character Details view."""
    if screen_img is None or not isinstance(screen_img, np.ndarray) or screen_img.size == 0:
        return False
    h, w = screen_img.shape[:2]
    if ocr:
        top_crop = screen_img[int(h * 0.08) : int(h * 0.18), :]
        try:
            results, _ = ocr(top_crop)
            if results:
                texts = [str(r[1]).lower() for r in results if r and len(r) > 1]
                for t in texts:
                    if "growth" in t:
                        return True
                    if "character" in t or "can add" in t or "cannot add" in t:
                        return False
        except Exception as exc:
            logger.debug(f"OCR details check error: {exc}")

    back_crop = screen_img[int(h * 0.84) : int(h * 0.88), int(w * 0.05) : int(w * 0.22)]
    back_green = np.count_nonzero((back_crop[:, :, 1] > 100) & (back_crop[:, :, 2] < 120))
    stat_crop = screen_img[int(h * 0.64) : int(h * 0.68), int(w * 0.35) : int(w * 0.65)]
    orange_px = np.count_nonzero(
        (stat_crop[:, :, 0] < 60) & (stat_crop[:, :, 1] > 60) & (stat_crop[:, :, 2] > 180)
    )
    return bool(back_green > 200 and orange_px > 300)


def is_right_arrow_visible(screen_img: np.ndarray | None) -> bool:
    """Checks if the right navigation chevron (>) is currently visible on the right edge."""
    if screen_img is None or not isinstance(screen_img, np.ndarray) or screen_img.size == 0:
        return False
    h, w = screen_img.shape[:2]
    roi = screen_img[
        int(h * (1010 / 2400.0)) : int(h * (1120 / 2400.0)),
        int(w * (1010 / 1080.0)) : int(w * (1075 / 1080.0)),
    ]
    if roi.size == 0:
        return False
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    return bool(np.count_nonzero(gray > 220) > 1500 or np.mean(gray) > 175.0)


def advance_to_next_card(
    task: Any,
    current_screen: np.ndarray,
    current_card_id: int | None = None,
    max_wait: float = 6.0,
) -> tuple[np.ndarray, bool]:
    """Advances to the next card in Character Details via arrow tap and verification."""
    w, h = task.adb.get_screen_size()
    arrow_x, arrow_y = int(w * (1040 / 1080.0)), int(h * (1050 / 2400.0))
    stat_roi = (int(h * 0.64), int(h * 0.70), int(w * 0.05), int(w * 0.90))
    start_t = time.time()
    sc = current_screen
    for _ in range(5):
        if time.time() - start_t >= max_wait:
            break
        pulse_wait = 0.0
        while not is_right_arrow_visible(sc) and pulse_wait < 1.8:
            time.sleep(0.25)
            pulse_wait += 0.25
            sc = task.adb.screencap()
        task.adb.tap(arrow_x, arrow_y, delay_after=1.1)
        next_screen = task.adb.screencap()
        if current_card_id is not None:
            t_next = task._extract_banner_text(next_screen)
            c_next, e_next = task._extract_element_badge(next_screen)
            cand_next, _ = task._match_card_candidate(
                t_next, detected_class=c_next, detected_elem=e_next
            )
            next_cid = int(cand_next.get("id") or 0) if cand_next else None
            if next_cid is not None and next_cid != current_card_id:
                return next_screen, True
        else:
            if compute_screen_diff(sc, next_screen, roi=stat_roi) >= 7.0:
                return next_screen, True
        time.sleep(0.3)
        sc = next_screen
    return sc, False


def scroll_to_top(task: Any) -> None:
    """Scrolls Character List all the way to the top before beginning scan."""
    w, h = task.adb.get_screen_size()
    task.log("Ensuring Character List is scrolled to the top...")
    consecutive_top = 0
    for _ in range(35):
        if task.is_stopped():
            break
        before = task.adb.screencap()
        task.adb.swipe(
            int(w * 0.50),
            int(h * 0.25),
            int(w * 0.50),
            int(h * 0.85),
            duration_ms=200,
            delay_after=0.4,
        )
        after = task.adb.screencap()
        if is_card_details_screen(after, ocr=task._ocr):
            task.adb.tap(
                int(w * task.BACK_BUTTON_RATIO[0]),
                int(h * task.BACK_BUTTON_RATIO[1]),
                delay_after=0.5,
            )
            after = task.adb.screencap()
        diff = compute_screen_diff(before, after, roi=(int(h * 0.25), int(h * 0.70), 0, int(w)))
        if diff < 10.0:
            consecutive_top += 1
            if consecutive_top >= 3:
                break
        else:
            consecutive_top = 0
    task.log("Character List is positioned at the top.")


__all__ = [
    "COUNTER_CROP_X",
    "COUNTER_CROP_Y",
    "advance_to_next_card",
    "compute_screen_diff",
    "is_card_details_screen",
    "is_right_arrow_visible",
    "read_counter_total_cards",
    "scroll_to_top",
]
