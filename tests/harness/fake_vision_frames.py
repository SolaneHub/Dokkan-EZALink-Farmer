"""Synthetic Dokkan Battle screen frame generator for in-memory testing.

Generates realistic 1080x2400 in-memory screenshot representations of Dokkan Battle
Character Details screen, including title banner, attribute badges, rainbow star,
level / SA counters, back button, and navigation arrows.
"""

from __future__ import annotations

import cv2
import numpy as np


def draw_rainbow_star(
    img: np.ndarray,
    center: tuple[int, int] = (280, 320),
    size: int = 25,
    is_rainbow: bool = True,
) -> None:
    """Draws a 5-pointed star.

    If is_rainbow is True, draws with cyan color (BGR: 255, 255, 0)
    matching the HSV mask range (80..105, 80..255, 120..255).
    If False, draws with gold/yellow color (BGR: 0, 200, 255).
    """
    pts: list[list[int]] = []
    for i in range(10):
        r = size if i % 2 == 0 else size / 2.0
        angle = i * np.pi / 5.0 - np.pi / 2.0
        pts.append([int(center[0] + r * np.cos(angle)), int(center[1] + r * np.sin(angle))])
    poly = np.array(pts, np.int32)
    color = (255, 255, 0) if is_rainbow else (0, 200, 255)
    cv2.fillPoly(img, [poly], color)


def draw_element_badge(
    img: np.ndarray,
    card_class: str = "SUPER",
    card_element: str = "AGL",
) -> None:
    """Draws the character attribute badge in upper-left ROI (BADGE_CROP_Y / BADGE_CROP_X)."""
    cv2.putText(
        img,
        card_class.upper(),
        (30, 530),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        img,
        card_element.upper(),
        (30, 580),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )


def draw_title_banner(
    img: np.ndarray,
    subname: str,
    name: str,
) -> None:
    """Draws rotated character title banner (BANNER_CROP_Y: 0.005..0.508, BANNER_CROP_X: 0.740..0.985).

    The banner is drawn horizontally on a temporary canvas, where subname is placed at
    center_y < 172 and name at center_y >= 172, then rotated 90 deg counter-clockwise and
    spliced into the main 1080x2400 portrait canvas.
    """
    rot = np.zeros((264, 1207, 3), dtype=np.uint8)
    cv2.putText(
        rot,
        subname,
        (50, 120),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.2,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        rot,
        name,
        (50, 220),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.5,
        (255, 255, 255),
        3,
        cv2.LINE_AA,
    )

    unrot = cv2.rotate(rot, cv2.ROTATE_90_COUNTERCLOCKWISE)
    h_crop, w_crop = unrot.shape[:2]
    img[12 : 12 + h_crop, 799 : 799 + w_crop] = unrot


def draw_navigation_controls(
    img: np.ndarray,
    has_right_arrow: bool = True,
    has_back_button: bool = True,
) -> None:
    """Draws navigation arrow chevron (>) and character details bottom back button."""
    h, w = img.shape[:2]

    # Right arrow: roi around y: 1010..1120, x: 1010..1075
    if has_right_arrow:
        img[1010:1120, 1010:1075] = 255

    # Back button green area: y: 0.84..0.88 (2016..2112), x: 0.05..0.22 (54..237)
    if has_back_button:
        img[int(h * 0.84) : int(h * 0.88), int(w * 0.05) : int(w * 0.22)] = [30, 180, 40]

    # Orange stat crop marker required by is_card_details_screen
    img[int(h * 0.64) : int(h * 0.68), int(w * 0.35) : int(w * 0.65)] = [20, 100, 220]

    # Optional GROWTH button in top crop to satisfy OCR check if enabled
    cv2.putText(img, "GROWTH", (100, 260), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)


def draw_level_and_sa(
    img: np.ndarray,
    curr_level: int = 150,
    max_level: int = 150,
    curr_sa: int = 20,
    max_sa: int = 20,
) -> None:
    """Draws level and SA ratios in their respective character detail ROIs."""
    cv2.putText(
        img,
        f"{curr_level}/{max_level}",
        (160, 1770),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.2,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        img,
        f"{curr_sa}/{max_sa}",
        (30, 1980),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.2,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )


def create_synthetic_card_detail_frame(
    subname: str,
    name: str,
    card_class: str = "SUPER",
    card_element: str = "AGL",
    is_rainbow: bool = True,
    curr_level: int = 150,
    max_level: int = 150,
    curr_sa: int = 20,
    max_sa: int = 20,
    has_right_arrow: bool = True,
    has_back_button: bool = True,
    width: int = 1080,
    height: int = 2400,
) -> np.ndarray:
    """Creates a complete synthetic Dokkan Battle 1080x2400 Character Details screen."""
    frame = np.zeros((height, width, 3), dtype=np.uint8)

    draw_navigation_controls(
        frame,
        has_right_arrow=has_right_arrow,
        has_back_button=has_back_button,
    )
    draw_title_banner(frame, subname=subname, name=name)
    draw_element_badge(frame, card_class=card_class, card_element=card_element)
    draw_rainbow_star(frame, is_rainbow=is_rainbow)
    draw_level_and_sa(
        frame,
        curr_level=curr_level,
        max_level=max_level,
        curr_sa=curr_sa,
        max_sa=max_sa,
    )

    return frame
