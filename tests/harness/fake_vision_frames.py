"""Synthetic Dokkan Battle screen frame generator for in-memory testing.

Generates realistic 1080x2400 in-memory screenshot representations of Dokkan Battle
Character Details screen, including title banner, attribute badges, rainbow star,
level / SA counters, back button, and navigation arrows.
"""

from __future__ import annotations

import contextlib
from typing import Any

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


def paste_template_on_canvas(
    canvas: np.ndarray,
    template_name: str,
    cx: int,
    cy: int,
    vision: Any = None,
) -> tuple[int, int]:
    """Pastes an existing template centered at (cx, cy) onto the canvas.

    If vision is not provided, instantiates a default Vision().
    """
    if vision is None:
        from dokkan_eza_link_farmer.automation.vision import Vision

        vision = Vision()

    tmpl = vision.load_template(template_name)
    if tmpl is None:
        raise ValueError(f"Template '{template_name}' not found by Vision.")

    th, tw = tmpl.shape[:2]
    x1 = max(0, cx - tw // 2)
    y1 = max(0, cy - th // 2)
    x2 = min(canvas.shape[1], x1 + tw)
    y2 = min(canvas.shape[0], y1 + th)
    canvas[y1:y2, x1:x2] = tmpl[0 : y2 - y1, 0 : x2 - x1]
    return (cx, cy)


def create_synthetic_eza_select_frame(
    width: int = 1080,
    height: int = 2400,
    vision: Any = None,
) -> np.ndarray:
    """Creates a synthetic Extreme Z-Battle Level Select screen.

    Pastes button_eza_fight or text_eza_fight at standard EZA coordinates (Y ~ 0.69 - 0.75 H).
    """
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    # EZA fight button is located around center X and ~75% Y (within TEMPLATE_VERTICAL_ROIS 0.70..0.98)
    fight_x = int(width * 0.50)
    fight_y = int(height * 0.75)
    paste_template_on_canvas(frame, "button_eza_fight", fight_x, fight_y, vision=vision)
    return frame


def create_synthetic_battle_frame(
    width: int = 1080,
    height: int = 2400,
    auto_active: bool = True,
    vision: Any = None,
) -> np.ndarray:
    """Creates a synthetic Dokkan Battle active screen.

    Pastes battle_menu, auto_battle toggle (btn_auto_battle_on/off), and button_item.
    """
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    menu_x, menu_y = int(width * 0.15), int(height * 0.10)
    paste_template_on_canvas(frame, "button_battle_menu", menu_x, menu_y, vision=vision)

    auto_tmpl = "btn_auto_battle_on" if auto_active else "btn_auto_battle_off"
    auto_x, auto_y = int(width * 0.85), int(height * 0.10)
    paste_template_on_canvas(frame, auto_tmpl, auto_x, auto_y, vision=vision)

    # Item button at bottom right (ROI 0.75..1.0)
    item_x, item_y = int(width * 0.88), int(height * 0.88)
    paste_template_on_canvas(frame, "button_item", item_x, item_y, vision=vision)
    return frame


def create_synthetic_results_frame(
    width: int = 1080,
    height: int = 2400,
    has_attempt_again: bool = True,
    has_close_button: bool = False,
    vision: Any = None,
) -> np.ndarray:
    """Creates a synthetic victory / stage clear results screen.

    Pastes Attempt Again button (left) and OK button (right), centered OK button, or Close button.
    """
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    if has_close_button:
        close_x = int(width * 0.50)
        close_y = int(height * 0.85)
        paste_template_on_canvas(frame, "button_close", close_x, close_y, vision=vision)
    elif has_attempt_again:
        again_x = int(width * 0.28)
        again_y = int(height * 0.85)
        paste_template_on_canvas(frame, "button_attempt_again", again_x, again_y, vision=vision)
        ok_x = int(width * 0.72)
        ok_y = int(height * 0.85)
        paste_template_on_canvas(frame, "button_ok", ok_x, ok_y, vision=vision)
    else:
        ok_x = int(width * 0.50)
        ok_y = int(height * 0.85)
        paste_template_on_canvas(frame, "button_ok", ok_x, ok_y, vision=vision)
    return frame


def create_synthetic_quest_stage_frame(
    stage: str = "area_39_3",
    width: int = 1080,
    height: int = 2400,
    vision: Any = None,
) -> np.ndarray:
    """Creates a synthetic Quest stage selection screen (Area 39-3 or 35-1).

    Pastes the corresponding stage badge / card template within ROI (0.15..0.85 H).
    """
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    tmpl_name = "stage_area39_3" if stage == "area_39_3" else "stage_area35_1"
    stage_x = int(width * 0.50)
    stage_y = int(height * 0.35)
    paste_template_on_canvas(frame, tmpl_name, stage_x, stage_y, vision=vision)
    return frame


def create_synthetic_friend_select_frame(
    width: int = 1080,
    height: int = 2400,
    vision: Any = None,
) -> np.ndarray:
    """Creates a synthetic Friend Supporter Selection screen."""
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    # Friend refresh button at top right (ROI 0.10..0.35 H)
    rx, ry = int(width * 0.82), int(height * 0.18)
    paste_template_on_canvas(frame, "button_friend_refresh", rx, ry, vision=vision)
    return frame


def create_synthetic_team_confirm_frame(
    width: int = 1080,
    height: int = 2400,
    vision: Any = None,
) -> np.ndarray:
    """Creates a synthetic Team Confirmation screen (button_start and button_team_formation)."""
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    # Team formation button (ROI 0.30..0.55 H)
    fx, fy = int(width * 0.80), int(height * 0.49)
    paste_template_on_canvas(frame, "button_team_formation", fx, fy, vision=vision)

    # Start button at bottom right (ROI 0.60..0.98 H)
    sx, sy = int(width * 0.75), int(height * 0.88)
    paste_template_on_canvas(frame, "button_start", sx, sy, vision=vision)
    return frame


def create_synthetic_team_edit_frame(
    width: int = 1080,
    height: int = 2400,
    filled_slots: int = 6,
    vision: Any = None,
) -> np.ndarray:
    """Creates a synthetic Team Edit / Formation screen."""
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    # Confirm formation button at bottom right (ROI 0.50..0.98 H)
    cx, cy = int(width * 0.88), int(height * 0.88)
    paste_template_on_canvas(frame, "button_confirm_formation", cx, cy, vision=vision)

    # Deck remove all button (ROI 0.15..0.45 H)
    rx, ry = int(width * 0.91), int(height * 0.30)
    paste_template_on_canvas(frame, "button_deck_remove_all", rx, ry, vision=vision)

    # Paste team slot badges
    for slot in range(1, filled_slots + 1):
        with contextlib.suppress(Exception):
            paste_template_on_canvas(
                frame, f"badge_team_slot_{slot}", 100 + slot * 120, 500, vision=vision
            )
    return frame


def create_synthetic_stamina_empty_frame(
    width: int = 1080,
    height: int = 2400,
    vision: Any = None,
) -> np.ndarray:
    """Creates a synthetic Stamina Empty / Restore STA popup screen.

    Pastes header_restore_sta and button_cancel within their vertical ROIs.
    """
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    header_x = int(width * 0.50)
    header_y = int(height * 0.38)
    paste_template_on_canvas(frame, "header_restore_sta", header_x, header_y, vision=vision)

    cancel_x = int(width * 0.50)
    cancel_y = int(height * 0.70)
    paste_template_on_canvas(frame, "button_cancel", cancel_x, cancel_y, vision=vision)
    return frame


def create_synthetic_difficulty_frame(
    width: int = 1080,
    height: int = 2400,
    vision: Any = None,
) -> np.ndarray:
    """Creates a synthetic Difficulty Selection screen (diff_super and diff_z_hard)."""
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    # diff_super (ROI 0.25..0.65 H)
    sx, sy = int(width * 0.50), int(height * 0.40)
    paste_template_on_canvas(frame, "diff_super", sx, sy, vision=vision)

    # diff_z_hard (ROI 0.30..0.70 H)
    zx, zy = int(width * 0.50), int(height * 0.55)
    paste_template_on_canvas(frame, "diff_z_hard", zx, zy, vision=vision)
    return frame
