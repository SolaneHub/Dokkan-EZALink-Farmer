"""Banner extraction and OCR preprocessing module for Dokkan Character Details screen."""

from __future__ import annotations

import logging
import re
from typing import Any, overload

import cv2
import numpy as np

logger = logging.getLogger(__name__)

BANNER_CROP_Y: tuple[float, float] = (0.005, 0.508)
BANNER_CROP_X: tuple[float, float] = (0.740, 0.985)


@overload
def preprocess_text_banner(banner_bgr: None) -> None: ...


@overload
def preprocess_text_banner(banner_bgr: np.ndarray) -> np.ndarray: ...


def preprocess_text_banner(banner_bgr: np.ndarray | None) -> np.ndarray | None:
    """
    Isolates white text pixels (S < 45, V > 205) with dark outline (V < 50),
    eliminating animated background effects (SFX, aura, and sparkles).
    """
    if (
        banner_bgr is None
        or not isinstance(banner_bgr, np.ndarray)
        or banner_bgr.size == 0
        or len(banner_bgr.shape) != 3
        or banner_bgr.shape[2] != 3
    ):
        return banner_bgr
    hsv = cv2.cvtColor(banner_bgr, cv2.COLOR_BGR2HSV)
    _, s_ch, v_ch = cv2.split(hsv)
    white_mask = (s_ch < 45) & (v_ch > 205)
    gray = cv2.cvtColor(banner_bgr, cv2.COLOR_BGR2GRAY)
    border_mask = gray < 50
    dilated_border = cv2.dilate(border_mask.astype(np.uint8), np.ones((3, 3), np.uint8))
    combined = white_mask & (dilated_border > 0)
    cleaned = np.zeros_like(banner_bgr)
    cleaned[combined] = [255, 255, 255]
    return cleaned


def stitch_marquee_text(text_f1: str | None, text_f2: str | None) -> str:
    """
    Merges unique text tokens from frame 1 and frame 2 to reconstruct marquee text.
    """
    if not text_f1 and not text_f2:
        return ""
    str1 = str(text_f1 or "").strip()
    str2 = str(text_f2 or "").strip()
    tokens_f1 = [t for t in re.split(r"\s+", str1) if t]
    tokens_f2 = [t for t in re.split(r"\s+", str2) if t]

    merged_tokens: list[str] = list(tokens_f1)
    seen_lower = {t.lower() for t in tokens_f1}
    for t in tokens_f2:
        if t.lower() not in seen_lower:
            merged_tokens.append(t)
            seen_lower.add(t.lower())

    return " ".join(merged_tokens)


class BannerExtractor:
    """Extracts and cleans subname and name text tokens from the character details banner."""

    def __init__(
        self,
        ocr: Any = None,
        crop_y: tuple[float, float] = BANNER_CROP_Y,
        crop_x: tuple[float, float] = BANNER_CROP_X,
    ) -> None:
        self.ocr = ocr
        self.crop_y = crop_y
        self.crop_x = crop_x

    def _extract_tokens_by_position(
        self, screen_img: np.ndarray | None
    ) -> tuple[list[tuple[float, str]], list[tuple[float, str]]]:
        if (
            self.ocr is None
            or screen_img is None
            or not hasattr(screen_img, "shape")
            or len(screen_img.shape) < 2
        ):
            return [], []

        h, w = screen_img.shape[:2]
        y1, y2 = int(h * self.crop_y[0]), int(h * self.crop_y[1])
        x1, x2 = int(w * self.crop_x[0]), int(w * self.crop_x[1])

        crop = screen_img[y1:y2, x1:x2]
        if crop.size == 0:
            return [], []

        banner = cv2.rotate(crop, cv2.ROTATE_90_CLOCKWISE)
        cleaned = preprocess_text_banner(banner)

        try:
            results, _ = self.ocr(banner)
            if not results and cleaned is not None:
                results, _ = self.ocr(cleaned)
            if not results:
                return [], []

            sub_tokens: list[tuple[float, str]] = []
            name_tokens: list[tuple[float, str]] = []
            for item in results:
                if not item or len(item) < 2:
                    continue
                box, txt = item[0], str(item[1]).strip()
                if not txt:
                    continue
                if re.match(r"^(?:growth|grow|5)$", txt, flags=re.IGNORECASE):
                    continue
                if isinstance(box, (list, tuple)) and len(box) >= 4:
                    min_y = min(float(pt[1]) for pt in box)
                    max_y = max(float(pt[1]) for pt in box)
                    min_x = min(float(pt[0]) for pt in box)
                    center_y = sum(float(pt[1]) for pt in box) / float(len(box))
                    if min_y < 110 and max_y < 115 and "growth" in txt.lower():
                        continue
                else:
                    min_x = 0.0
                    center_y = 150.0

                cleaned_tok = re.sub(r"^(?:growth|grow|5)\s*", "", txt, flags=re.IGNORECASE).strip()
                if cleaned_tok:
                    if center_y < 172.0:
                        sub_tokens.append((min_x, cleaned_tok))
                    else:
                        name_tokens.append((min_x, cleaned_tok))

            sub_tokens.sort(key=lambda t: t[0])
            name_tokens.sort(key=lambda t: t[0])
            return sub_tokens, name_tokens
        except Exception as exc:
            logger.debug(f"Banner OCR error: {exc}")
            return [], []

    def extract_banner_text(self, screen_img: np.ndarray | None) -> str:
        """Crops rotated text banner, strips growth button, runs OCR and returns full title string."""
        sub_tokens, name_tokens = self._extract_tokens_by_position(screen_img)
        ordered_tokens = [t[1] for t in sub_tokens] + [t[1] for t in name_tokens]
        return " ".join(ordered_tokens).strip()

    def extract_banner_tokens(self, screen_img: np.ndarray | None) -> tuple[str, str]:
        """Extracts subname and name as separate strings using spatial Y-splitting on rotated banner."""
        sub_tokens, name_tokens = self._extract_tokens_by_position(screen_img)
        sub_str = " ".join(t[1] for t in sub_tokens).strip()
        name_str = " ".join(t[1] for t in name_tokens).strip()
        return sub_str, name_str

    preprocess_text_banner = staticmethod(preprocess_text_banner)
    stitch_marquee_text = staticmethod(stitch_marquee_text)
    _extract_banner_text = extract_banner_text
    _extract_banner_tokens = extract_banner_tokens
    _stitch_marquee_text = staticmethod(stitch_marquee_text)


def extract_banner_text(
    screen_img: np.ndarray | None,
    ocr: Any = None,
    crop_y: tuple[float, float] = BANNER_CROP_Y,
    crop_x: tuple[float, float] = BANNER_CROP_X,
) -> str:
    """Functional interface for extracting banner text."""
    return BannerExtractor(ocr=ocr, crop_y=crop_y, crop_x=crop_x).extract_banner_text(screen_img)


def extract_banner_tokens(
    screen_img: np.ndarray | None,
    ocr: Any = None,
    crop_y: tuple[float, float] = BANNER_CROP_Y,
    crop_x: tuple[float, float] = BANNER_CROP_X,
) -> tuple[str, str]:
    """Functional interface for extracting subname and name tokens."""
    return BannerExtractor(ocr=ocr, crop_y=crop_y, crop_x=crop_x).extract_banner_tokens(screen_img)


def read_card_title_from_screen(
    screen_img: np.ndarray | None,
    ocr: Any = None,
    crop_y: tuple[float, float] = (0.058, 0.375),
    crop_x: tuple[float, float] = (0.777, 0.926),
) -> str | None:
    """Crops, rotates, and performs OCR on the card title region, cropping out Growth button."""
    if ocr is None or screen_img is None or not hasattr(screen_img, "shape"):
        return None

    h, w = screen_img.shape[:2]
    y1, y2 = int(h * crop_y[0]), int(h * crop_y[1])
    x1, x2 = int(w * crop_x[0]), int(w * crop_x[1])

    crop = screen_img[y1:y2, x1:x2]
    if getattr(crop, "size", 0) == 0:
        return None

    rot = cv2.rotate(crop, cv2.ROTATE_90_CLOCKWISE)
    if rot.shape[1] > 0:
        rot = rot[:, int(rot.shape[1] * 0.28) :]

    try:
        results, _ = ocr(rot)
        if not results:
            return None
        words = [str(item[1]) for item in results if item and len(item) > 1]
        return " ".join(words).strip() or None
    except Exception as exc:
        logger.debug(f"OCR error: {exc}")
        return None


_stitch_marquee_text = stitch_marquee_text
_extract_banner_text = extract_banner_text
_extract_banner_tokens = extract_banner_tokens

__all__ = [
    "BANNER_CROP_X",
    "BANNER_CROP_Y",
    "BannerExtractor",
    "_extract_banner_text",
    "_extract_banner_tokens",
    "_stitch_marquee_text",
    "extract_banner_text",
    "extract_banner_tokens",
    "preprocess_text_banner",
    "read_card_title_from_screen",
    "stitch_marquee_text",
]
