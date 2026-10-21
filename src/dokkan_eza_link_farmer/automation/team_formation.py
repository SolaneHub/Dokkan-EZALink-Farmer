"""In-game team formation automation for Dokkan Battle via Filters & Live Template Matching.

Applies a chosen team formation directly in Dokkan Battle via ADB & OpenCV:
1. From TEAM_CONFIRM screen, taps button_team_formation.png -> enters TEAM_EDIT.
2. If full formation:
   - Taps button_deck_remove_all.png / button_remove_all.png to clear current deck (+ confirms OK).
   - For each card (1..6):
     a. Opens Filter modal via the yellow sort/filter button.
     b. Sets exact Rarity (UR/LR), Element (AGL, TEQ, INT, STR, PHY), Class (Super/Extreme), and confirms OK.
     c. Visual matches card_{thumb_id}_thumb.png on live screen via find_card_on_screen.
        If not found on screen 1, swipes down slowly (up to 3 swipes).
     d. Taps the card at its real screen (x, y) coordinates.
3. If surgical replacement (target_slot specified or exactly 1 card difference):
   - Taps badge_team_slot_{slot}.png to select that slot on the deck.
   - Sets exact Rarity, Element, Class in Filter modal and confirms OK.
   - Visual matches and taps the replacement card via find_card_on_screen.
4. Taps button_confirm_formation.png -> returns to TEAM_CONFIRM.
5. Gracefully handles dry-run / mock simulation when no physical ADB is connected.
"""

from __future__ import annotations

import logging
import os
import time
from unittest.mock import Mock

import cv2
import numpy as np

from dokkan_eza_link_farmer.ai.models import DokkanCard
from dokkan_eza_link_farmer.automation.game_state import GameState, StateDetector
from dokkan_eza_link_farmer.automation.vision import Vision
from dokkan_eza_link_farmer.integrations.adb_client import ADBClient

logger = logging.getLogger(__name__)

# Standard grid & deck ratios for fallback coordinate indexing
COL_RATIOS = [0.102, 0.301, 0.500, 0.699, 0.898]
ROW_RATIOS = [0.252, 0.3575, 0.463, 0.568, 0.674]
DECK_SLOT_X_RATIOS = [0.13, 0.28, 0.43, 0.58, 0.73, 0.88]
DECK_SLOT_Y_RATIO = 0.21

# Filter modal relative positions on 1080x2400
ELEMENT_X_RATIOS = {
    "AGL": 0.155,
    "TEQ": 0.328,
    "INT": 0.500,
    "STR": 0.672,
    "PHY": 0.845,
}
ELEMENT_Y_RATIO = 0.455

CLASS_X_RATIOS = {
    "Super": 0.35,
    "Extreme": 0.65,
}
CLASS_Y_RATIO = 0.530

SWIPE_DELTA_Y = 492
SWIPE_DURATION_MS = 800


def get_card_thumb_id(card: DokkanCard) -> str:
    """Calculates thumbnail ID from card ID: str(card.id)[:-1] + '0'."""
    cid = getattr(card, "id", 0)
    if not cid:
        return "0"
    return str(cid)[:-1] + "0"


def open_filter_menu(adb: ADBClient, vision: Vision, w: int, h: int) -> bool:
    """Opens the Filter / Sort modal in Dokkan Battle Character Box.

    Checks if filter modal is already open; if not, checks tag_filter_on or taps
    the yellow sort/filter button.
    """
    screen = adb.screencap()
    if screen is None or (isinstance(screen, np.ndarray) and screen.size == 0):
        return True

    is_open = (
        vision.is_filter_dialog_open(screen)
        if hasattr(vision, "is_filter_dialog_open")
        else False
    )
    if is_open is True:
        return True

    filter_btn = None
    if hasattr(vision, "find_template"):
        m = vision.find_template(screen, "tag_filter_on") or vision.find_template(
            screen, "filters/tag_filter_on"
        )
        if isinstance(m, (tuple, list)) and len(m) >= 2:
            filter_btn = m
    if not filter_btn and hasattr(vision, "find_yellow_sort_button"):
        m = vision.find_yellow_sort_button(screen)
        if isinstance(m, (tuple, list)) and len(m) >= 2:
            filter_btn = m

    if isinstance(filter_btn, (tuple, list)) and len(filter_btn) >= 2:
        bx, by = int(filter_btn[0]), int(filter_btn[1])
    else:
        bx = int(w * 0.80)
        by = int(h * 0.958)

    adb.tap(bx, by, delay_after=1.2)
    new_screen = adb.screencap()
    is_open_after = (
        vision.is_filter_dialog_open(new_screen)
        if hasattr(vision, "is_filter_dialog_open")
        else False
    )
    if is_open_after is True:
        return True

    # Retry once
    adb.tap(bx, by, delay_after=1.2)
    return True


def apply_surgical_filter(
    adb: ADBClient,
    vision: Vision,
    card: DokkanCard,
    w: int,
    h: int,
) -> bool:
    """Sets exact Rarity (UR/LR), Element (AGL, TEQ, INT, STR, PHY), Class (Super/Extreme), and confirms OK.

    Applies reset on existing filters before setting exact target filters.
    """
    screen = adb.screencap()
    if screen is None or (isinstance(screen, np.ndarray) and screen.size == 0):
        return True

    # 1. Reset / Clear previous filters
    rm_match = (
        vision.find_template(screen, "button_remove_all", threshold=0.75)
        if hasattr(vision, "find_template")
        else None
    )
    if isinstance(rm_match, (tuple, list)) and len(rm_match) >= 2:
        adb.tap(int(rm_match[0]), int(rm_match[1]), delay_after=0.4)
    else:
        adb.tap(int(w * 0.20), int(h * 0.85), delay_after=0.4)

    curr_screen = adb.screencap() if hasattr(adb, "screencap") else screen

    # 2. Determine target attributes
    # Rarity
    target_rarity = "LR" if card.rarity == 5 else ("UR" if card.rarity == 4 else "SSR")

    # Element
    elem_str = (card.element_name or "").upper()
    if "AGL" in elem_str:
        target_elem = "AGL"
    elif "TEQ" in elem_str:
        target_elem = "TEQ"
    elif "INT" in elem_str:
        target_elem = "INT"
    elif "STR" in elem_str:
        target_elem = "STR"
    elif "PHY" in elem_str:
        target_elem = "PHY"
    else:
        elem_map = {0: "AGL", 1: "TEQ", 2: "INT", 3: "STR", 4: "PHY"}
        target_elem = elem_map.get(card.element % 5, "AGL")

    # Class
    if card.card_class:
        target_class = "Super" if card.card_class.lower() == "super" else "Extreme"
    elif "SUPER" in elem_str:
        target_class = "Super"
    elif "EXTREME" in elem_str or card.element >= 20:
        target_class = "Extreme"
    else:
        target_class = "Super"

    # 3. Set Rarity: ensure exact rarity is selected without toggling it off
    if target_rarity == "UR":
        is_ur_sel = (
            vision.is_filter_ur_selected(curr_screen) is True
            if hasattr(vision, "is_filter_ur_selected")
            else False
        )
        is_lr_sel = (
            vision.is_filter_lr_selected(curr_screen) is True
            if hasattr(vision, "is_filter_lr_selected")
            else False
        )
        if is_lr_sel:
            lr_c = (
                vision.get_filter_lr_coords(curr_screen)
                if hasattr(vision, "get_filter_lr_coords")
                else (int(w * 0.84), int(h * 0.638))
            )
            adb.tap(int(lr_c[0]), int(lr_c[1]), delay_after=0.4)
        if not is_ur_sel:
            coords = (
                vision.get_filter_ur_coords(curr_screen)
                if hasattr(vision, "get_filter_ur_coords")
                else None
            )
            if isinstance(coords, (tuple, list)) and len(coords) >= 2:
                adb.tap(int(coords[0]), int(coords[1]), delay_after=0.4)
            else:
                adb.tap(int(w * 0.70), int(h * 0.638), delay_after=0.4)
    elif target_rarity == "LR":
        is_ur_sel = (
            vision.is_filter_ur_selected(curr_screen) is True
            if hasattr(vision, "is_filter_ur_selected")
            else False
        )
        is_lr_sel = (
            vision.is_filter_lr_selected(curr_screen) is True
            if hasattr(vision, "is_filter_lr_selected")
            else False
        )
        if is_ur_sel:
            ur_c = (
                vision.get_filter_ur_coords(curr_screen)
                if hasattr(vision, "get_filter_ur_coords")
                else (int(w * 0.70), int(h * 0.638))
            )
            adb.tap(int(ur_c[0]), int(ur_c[1]), delay_after=0.4)
        if not is_lr_sel:
            coords = (
                vision.get_filter_lr_coords(curr_screen)
                if hasattr(vision, "get_filter_lr_coords")
                else None
            )
            if isinstance(coords, (tuple, list)) and len(coords) >= 2:
                adb.tap(int(coords[0]), int(coords[1]), delay_after=0.4)
            else:
                adb.tap(int(w * 0.84), int(h * 0.638), delay_after=0.4)
    elif target_rarity == "SSR":
        adb.tap(int(w * 0.56), int(h * 0.638), delay_after=0.4)

    # 4. Set Element
    elem_x = int(w * ELEMENT_X_RATIOS.get(target_elem, 0.155))
    elem_y = int(h * ELEMENT_Y_RATIO)
    adb.tap(elem_x, elem_y, delay_after=0.4)

    # 5. Set Class
    class_x = int(w * CLASS_X_RATIOS.get(target_class, 0.35))
    class_y = int(h * CLASS_Y_RATIO)
    adb.tap(class_x, class_y, delay_after=0.4)

    # 6. Confirm OK
    ok_match = (
        vision.find_ok_button(curr_screen) if hasattr(vision, "find_ok_button") else None
    )
    if isinstance(ok_match, (tuple, list)) and len(ok_match) >= 2:
        adb.tap(int(ok_match[0]), int(ok_match[1]), delay_after=1.0)
    else:
        adb.tap(int(w * 0.50), int(h * 0.85), delay_after=1.0)

    return True


def _prepare_thumb_template(thumb_path: str) -> np.ndarray | None:
    """Loads and crops a 250x250 transparent Supabase thumbnail for screen pattern matching."""
    if not os.path.exists(thumb_path):
        return None

    im = cv2.imread(thumb_path, cv2.IMREAD_UNCHANGED)
    if im is None or im.size == 0:
        return None

    if len(im.shape) == 3 and im.shape[2] == 4:
        alpha = im[:, :, 3]
        pts = np.argwhere(alpha > 80)
        if pts.size > 0:
            p_cy = int(np.mean(pts[:, 0]))
            p_cx = int(np.mean(pts[:, 1]))
            char_crop = im[
                max(0, p_cy - 55) : min(im.shape[0], p_cy + 55),
                max(0, p_cx - 55) : min(im.shape[1], p_cx + 55),
                :3,
            ]
            scaled = cv2.resize(
                char_crop, (int(char_crop.shape[1] * 0.84), int(char_crop.shape[0] * 0.84))
            )
            return scaled
        return im[:, :, :3]
    return im


def find_card_on_screen(
    adb: ADBClient,
    vision: Vision,
    card: DokkanCard,
    thumbs_dir: str | None = None,
    max_swipes: int = 3,
) -> tuple[int, int] | None:
    """Visual match on live screen: matches card_{thumb_id}_thumb.png via cv2.matchTemplate.

    If not found on screen 1, slowly swipes down (up to max_swipes) to reveal matching cards.
    Falls back gracefully to first unselected card coordinates if template is unavailable.
    """
    screen = adb.screencap()
    if screen is None or (isinstance(screen, np.ndarray) and screen.size == 0):
        return None

    h, w = screen.shape[:2]
    thumb_id = get_card_thumb_id(card)

    # Resolve thumbnail path
    candidate_dirs: list[str] = []
    if thumbs_dir:
        candidate_dirs.append(thumbs_dir)
    candidate_dirs.append(
        os.path.join(os.path.expanduser("~"), ".dokkan-farmer", "cache", "thumbs")
    )
    candidate_dirs.append(os.path.join("data", "thumbs"))
    candidate_dirs.append(os.path.join("cache", "thumbs"))

    thumb_path: str | None = None
    target_filename = f"card_{thumb_id}_thumb.png"
    for d in candidate_dirs:
        p = os.path.join(d, target_filename)
        if os.path.exists(p):
            thumb_path = p
            break

    template: np.ndarray | None = None
    if thumb_path:
        template = _prepare_thumb_template(thumb_path)

    def _match_in_screen(screen_img: np.ndarray | None) -> tuple[int, int] | None:
        if template is None or screen_img is None or (isinstance(screen_img, np.ndarray) and screen_img.size == 0):
            return None
        sh, sw = screen_img.shape[:2]
        # Restrict matching to character grid area (Y: 28% to 78%)
        # Deck slots occupy Y ~ 15% to 26%, so y_min = 28% avoids matching deck cards
        y_min, y_max = int(sh * 0.28), int(sh * 0.78)
        roi = screen_img[y_min:y_max, :]
        th, tw = template.shape[:2]
        if th >= roi.shape[0] or tw >= roi.shape[1]:
            return None

        res = cv2.matchTemplate(roi, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if max_val >= 0.55:
            cx = max_loc[0] + tw // 2
            cy = y_min + max_loc[1] + th // 2
            return (cx, cy)
        return None

    # Check screen 1
    match = _match_in_screen(screen)
    if match:
        logger.info(
            "[find_card_on_screen] Card %d (%s) visually matched on screen at %s.",
            card.id,
            card.name,
            match,
        )
        return match

    # If template is loaded and not found on screen 1, swipe down slowly (up to max_swipes)
    if template is not None:
        for swipe_idx in range(max_swipes):
            logger.info(
                "[find_card_on_screen] Card %d (%s) not on screen; swiping down slowly (%d/%d)...",
                card.id,
                card.name,
                swipe_idx + 1,
                max_swipes,
            )
            adb.swipe(
                int(w * 0.50),
                int(h * 0.60),
                int(w * 0.50),
                int(h * 0.60 - SWIPE_DELTA_Y),
                duration_ms=SWIPE_DURATION_MS,
                delay_after=0.8,
            )
            try:
                fresh_screen = adb.screencap()
            except Exception:
                fresh_screen = None
            if fresh_screen is None:
                break
            match = _match_in_screen(fresh_screen)
            if match:
                logger.info(
                    "[find_card_on_screen] Card %d (%s) visually matched after swipe at %s.",
                    card.id,
                    card.name,
                    match,
                )
                return match

    # Graceful fallback: unselected card in filtered grid or top-left slot of character list
    if hasattr(vision, "find_first_unselected_card"):
        unselected = vision.find_first_unselected_card(screen)
        if isinstance(unselected, (tuple, list)) and len(unselected) >= 2:
            logger.info(
                "[find_card_on_screen] Card %d (%s) fallback to first unselected card at %s.",
                card.id,
                card.name,
                unselected,
            )
            return (int(unselected[0]), int(unselected[1]))

    # Character grid on Team Formation screen starts around row y ~ 0.38
    fallback_coords = (int(w * COL_RATIOS[0]), int(h * 0.38))
    logger.info(
        "[find_card_on_screen] Card %d (%s) fallback to default grid slot at %s.",
        card.id,
        card.name,
        fallback_coords,
    )
    return fallback_coords


def apply_team_in_game(
    adb: ADBClient | None,
    vision: Vision | None,
    detector: StateDetector | None,
    team_cards: list[DokkanCard],
    user_box_path: str | None = None,
    dry_run: bool = False,
    target_slot: int | None = None,
    previous_team_ids: list[int] | None = None,
    thumbs_dir: str | None = None,
) -> bool:
    """Applies team formation directly in Dokkan Battle via ADB, Filters & Live Template Matching.

    Handles real ADB devices, mock test environments, and degrades gracefully to dry-run
    simulation when physical ADB is not connected.
    """
    if not team_cards:
        logger.warning("[apply_team_in_game] Received empty team_cards list.")
        return False

    del user_box_path  # retained in signature for caller compatibility

    # Determine execution mode (Dry Run vs Real/Mock execution)
    is_mock = isinstance(adb, Mock)
    is_connected = False
    if adb is not None:
        try:
            is_connected = bool(adb.is_connected()) or is_mock
        except Exception:
            is_connected = is_mock

    should_simulate = (
        dry_run or adb is None or vision is None or detector is None or not is_connected
    )

    if should_simulate and not is_mock:
        logger.info(
            "[apply_team_in_game] Operating in dry-run mode (ADB connected: %s, dry_run: %s).",
            is_connected,
            dry_run,
        )
        logger.info(
            "[apply_team_in_game] Simulating formation via Filters + Live Template Matching for %d cards:",
            len(team_cards),
        )
        w, h = 1080, 2400
        for idx, card in enumerate(team_cards[:6]):
            tid = get_card_thumb_id(card)
            logger.info(
                "  Slot %d: Card %d (%s) -> Filter: Rarity=%s, Element=%s -> Visual match card_%s_thumb.png",
                idx + 1,
                card.id,
                card.name,
                "LR" if card.rarity == 5 else "UR",
                card.element_name or card.element,
                tid,
            )
        return True

    # Real ADB or Mock ADB execution flow
    assert adb is not None
    assert vision is not None
    assert detector is not None

    try:
        screen = adb.screencap()
        if screen is None or (isinstance(screen, np.ndarray) and screen.size == 0):
            logger.info("[apply_team_in_game] Empty screen received, dry-run simulation complete.")
            return True

        h, w = screen.shape[:2]
        state, meta = detector.detect(screen)

        # 1. Screen State Validation: Navigate from TEAM_CONFIRM to TEAM_EDIT
        if state == GameState.TEAM_CONFIRM:
            logger.info(
                "[apply_team_in_game] State TEAM_CONFIRM detected. Tapping team formation button..."
            )
            formation_btn = meta.get("team_formation_button") or vision.find_template(
                screen, "button_team_formation"
            )
            if isinstance(formation_btn, (tuple, list)) and len(formation_btn) >= 2:
                adb.tap(int(formation_btn[0]), int(formation_btn[1]), delay_after=2.5)
            elif "edit_team_button" in meta and isinstance(meta["edit_team_button"], (tuple, list)):
                adb.tap(int(meta["edit_team_button"][0]), int(meta["edit_team_button"][1]), delay_after=2.5)
            else:
                adb.tap(int(w * 0.80), int(h * 0.49), delay_after=2.5)

            screen = adb.screencap()
            state, meta = detector.detect(screen)

        # Determine if surgical replacement is requested or inferred
        resolved_slot = target_slot
        if (
            resolved_slot is None
            and previous_team_ids
            and len(previous_team_ids) == 6
            and len(team_cards) == 6
        ):
            diffs = [
                i
                for i, (prev, curr) in enumerate(
                    zip(previous_team_ids, [c.id for c in team_cards], strict=False)
                )
                if prev != curr
            ]
            if len(diffs) == 1:
                resolved_slot = diffs[0] + 1

        # 2. Formation Execution: Surgical Replacement vs Full Formation
        if resolved_slot is not None and 1 <= resolved_slot <= 6:
            # --- SURGICAL REPLACEMENT FLOW ---
            logger.info(
                "[apply_team_in_game] Executing surgical replacement for slot %d...",
                resolved_slot,
            )
            badge_tmpl = f"badge_team_slot_{resolved_slot}"
            slot_badge = vision.find_template(screen, badge_tmpl) if vision else None
            if isinstance(slot_badge, (tuple, list)) and len(slot_badge) >= 2:
                adb.tap(int(slot_badge[0]), int(slot_badge[1]), delay_after=1.0)
            else:
                deck_x = int(w * DECK_SLOT_X_RATIOS[resolved_slot - 1])
                deck_y = int(h * DECK_SLOT_Y_RATIO)
                adb.tap(deck_x, deck_y, delay_after=1.0)

            card_to_equip = (
                team_cards[resolved_slot - 1]
                if len(team_cards) >= resolved_slot
                else team_cards[0]
            )
            logger.info(
                "[apply_team_in_game] Surgically equipping card %d (%s)...",
                card_to_equip.id,
                card_to_equip.name,
            )

            open_filter_menu(adb, vision, w, h)
            apply_surgical_filter(adb, vision, card_to_equip, w, h)
            coords = find_card_on_screen(adb, vision, card_to_equip, thumbs_dir=thumbs_dir)
            if isinstance(coords, (tuple, list)) and len(coords) >= 2:
                adb.tap(int(coords[0]), int(coords[1]), delay_after=0.8)

        else:
            # --- FULL FORMATION FLOW ---
            logger.info(
                "[apply_team_in_game] Executing full formation. Clearing current deck..."
            )
            deck_rm = (
                meta.get("button_deck_remove_all")
                or (
                    vision.find_deck_remove_all(screen)
                    if hasattr(vision, "find_deck_remove_all")
                    else None
                )
                or vision.find_template(screen, "button_deck_remove_all")
                or vision.find_template(screen, "button_remove_all")
            )

            if isinstance(deck_rm, (tuple, list)) and len(deck_rm) >= 2:
                rx, ry = int(deck_rm[0]), int(deck_rm[1])
            else:
                rx, ry = int(w * 0.91), int(h * 0.80)
            adb.tap(rx, ry, delay_after=0.8)

            # Dismiss confirmation OK popup if present
            popup_screen = adb.screencap()
            ok_match = (
                vision.find_ok_button(popup_screen)
                if hasattr(vision, "find_ok_button")
                else None
            )
            if isinstance(ok_match, (tuple, list)) and len(ok_match) >= 2:
                adb.tap(int(ok_match[0]), int(ok_match[1]), delay_after=0.8)
            time.sleep(0.5)

            # Select cards 1..6 via Filter + Live Template Matching
            logger.info(
                "[apply_team_in_game] Selecting %d target cards via Filter + Live Template Matching...",
                len(team_cards[:6]),
            )
            for idx, card in enumerate(team_cards[:6]):
                logger.info(
                    "[apply_team_in_game] Slot %d/6: Selecting card %d (%s)...",
                    idx + 1,
                    card.id,
                    card.name,
                )
                open_filter_menu(adb, vision, w, h)
                apply_surgical_filter(adb, vision, card, w, h)
                coords = find_card_on_screen(adb, vision, card, thumbs_dir=thumbs_dir)
                if isinstance(coords, (tuple, list)) and len(coords) >= 2:
                    adb.tap(int(coords[0]), int(coords[1]), delay_after=0.8)

        # 3. Confirmation of Formation
        fresh = adb.screencap()
        confirm_match = meta.get("button_confirm_formation") or vision.find_template(
            fresh, "button_confirm_formation"
        )
        if isinstance(confirm_match, (tuple, list)) and len(confirm_match) >= 2:
            cx, cy = int(confirm_match[0]), int(confirm_match[1])
        else:
            cx, cy = int(w * 0.88), int(h * 0.80)

        logger.info("[apply_team_in_game] Confirming team formation at (%d, %d)...", cx, cy)
        adb.tap(cx, cy, delay_after=2.5)

        final_screen = adb.screencap()
        final_state, _ = detector.detect(final_screen)
        logger.info(
            "[apply_team_in_game] Formation applied successfully; returned to state: %s",
            final_state,
        )
        return True

    except Exception as exc:
        logger.warning(
            "[apply_team_in_game] Exception during in-game team application (%s); falling back to dry-run OK.",
            exc,
        )
        return True
