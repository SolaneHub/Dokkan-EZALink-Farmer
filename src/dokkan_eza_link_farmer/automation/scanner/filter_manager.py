"""In-game Character Box filter verification and enforcement."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def verify_and_enforce_filters(task: Any) -> bool:
    """
    Verifies that Character Box filters are set appropriately and sorted by Released.
    1. Checks Sort by Released on main grid.
    2. Checks tag_filter_on.png on main grid.
    3. If UR+LR filters are not confirmed active, opens filter popup, ensures UR and LR buttons
       are selected (clicking unselected if needed), and confirms with button_ok.png.
    """
    if not task.vision or not getattr(task, "adb", None):
        return True

    screen = task.adb.screencap() if task.adb else None
    if screen is None or (hasattr(screen, "size") and screen.size == 0):
        return True

    size = task.adb.get_screen_size() if task.adb else (1080, 2400)
    w, h = size if isinstance(size, (tuple, list)) and len(size) >= 2 else (1080, 2400)

    sort_ok = bool(
        task.vision.find_template(screen, "filters/tag_sort_released.png", threshold=0.70)
        or task.vision.find_template(screen, "tag_sort_released", threshold=0.70)
        or (hasattr(task.vision, "is_sort_released") and task.vision.is_sort_released(screen))
    )
    filter_on = bool(
        task.vision.find_template(screen, "filters/tag_filter_on.png", threshold=0.70)
        or task.vision.find_template(screen, "tag_filter_on", threshold=0.70)
    )

    if sort_ok and filter_on:
        task.log(
            f"In-game box filters already active: FilterOn={filter_on}, SortReleased={sort_ok}"
        )
        return True

    task.log(
        f"In-game box filters status: FilterOn={filter_on}, SortReleased={sort_ok}. Opening filter popup..."
    )

    # 1. Locate sort/filter button
    filter_btn_loc = None
    if hasattr(task.vision, "find_yellow_sort_button"):
        filter_btn_loc = task.vision.find_yellow_sort_button(screen)

    if not filter_btn_loc:
        m = (
            task.vision.find_template(screen, "tag_sort_released", threshold=0.70)
            or task.vision.find_template(screen, "filters/tag_sort_released.png", threshold=0.70)
            or task.vision.find_template(screen, "tag_filter_on", threshold=0.70)
            or task.vision.find_template(screen, "filters/tag_filter_on.png", threshold=0.70)
        )
        if m:
            filter_btn_loc = (m[0], m[1])

    if not filter_btn_loc:
        back_btn = task.vision.find_template(screen, "button_back_green", threshold=0.70)
        if back_btn:
            filter_btn_loc = (int(w * 0.79), int(back_btn[1]))
        elif (h / float(w)) >= 1.85:
            filter_btn_loc = (int(w * 0.79), int(h * 0.760))
        else:
            filter_btn_loc = (int(w * 0.80), int(h * 0.958))

    task.adb.tap(filter_btn_loc[0], filter_btn_loc[1], delay_after=1.5)
    popup_screen = task.adb.screencap()

    # 2. Verify filter modal is actually open
    is_open = (
        task.vision.is_filter_dialog_open(popup_screen)
        if hasattr(task.vision, "is_filter_dialog_open")
        else False
    )

    if not is_open:
        # Retry opening once
        task.log("Filter modal not detected after tap. Retrying...")
        task.adb.tap(filter_btn_loc[0], filter_btn_loc[1], delay_after=2.0)
        popup_screen = task.adb.screencap()
        is_open = (
            task.vision.is_filter_dialog_open(popup_screen)
            if hasattr(task.vision, "is_filter_dialog_open")
            else False
        )

    if not is_open:
        task.log(
            "⚠️ Could not open filter modal. Skipping filter configuration to prevent misclicks."
        )
        return False

    # 3. Ensure 'Released' sort is selected if not confirmed
    if not sort_ok:
        rel_selected = bool(
            task.vision.find_template(
                popup_screen, "filters/btn_released_selected.png", threshold=0.75
            )
            or task.vision.find_template(popup_screen, "btn_released_selected", threshold=0.75)
            or (
                hasattr(task.vision, "is_filter_released_selected")
                and task.vision.is_filter_released_selected(popup_screen)
            )
        )
        if not rel_selected:
            rel_loc = (int(w * 0.46), int(h * 0.422))
            task.adb.tap(rel_loc[0], rel_loc[1], delay_after=0.5)
            popup_screen = task.adb.screencap()

    # 4. Ensure UR is selected
    if hasattr(task.vision, "is_filter_ur_selected"):
        ur_selected = bool(task.vision.is_filter_ur_selected(popup_screen))
    else:
        x_min, x_max = int(w * 0.58), int(w * 0.78)
        ur_selected = bool(
            task.vision.find_template(
                popup_screen[:, x_min:x_max], "btn_ur_selected", threshold=0.85
            )
        )

    if not ur_selected:
        ur_coords = None
        if hasattr(task.vision, "get_filter_ur_coords"):
            ur_coords = task.vision.get_filter_ur_coords(popup_screen)
        if not ur_coords:
            x_min, x_max = int(w * 0.58), int(w * 0.78)
            ur_unsel_loc = task.vision.find_template(
                popup_screen[:, x_min:x_max], "btn_ur_unselected", threshold=0.75
            )
            if ur_unsel_loc:
                ur_coords = (ur_unsel_loc[0] + x_min, ur_unsel_loc[1])
            else:
                ur_coords = (int(w * 0.70), int(h * 0.638))
        task.adb.tap(ur_coords[0], ur_coords[1], delay_after=0.6)
        popup_screen = task.adb.screencap()

    # 5. Ensure LR is selected (must check column-scoped ROI so selected UR doesn't falsely trigger LR)
    if hasattr(task.vision, "is_filter_lr_selected"):
        lr_selected = bool(task.vision.is_filter_lr_selected(popup_screen))
    else:
        x_min, x_max = int(w * 0.77), int(w * 0.99)
        lr_selected = bool(
            task.vision.find_template(
                popup_screen[:, x_min:x_max], "btn_lr_selected", threshold=0.85
            )
        )

    if not lr_selected:
        lr_coords = None
        if hasattr(task.vision, "get_filter_lr_coords"):
            lr_coords = task.vision.get_filter_lr_coords(popup_screen)
        if not lr_coords:
            x_min, x_max = int(w * 0.77), int(w * 0.99)
            lr_unsel_loc = task.vision.find_template(
                popup_screen[:, x_min:x_max], "btn_lr_unselected", threshold=0.75
            )
            if lr_unsel_loc:
                lr_coords = (lr_unsel_loc[0] + x_min, lr_unsel_loc[1])
            else:
                lr_coords = (int(w * 0.84), int(h * 0.638))
        task.adb.tap(lr_coords[0], lr_coords[1], delay_after=0.6)
        popup_screen = task.adb.screencap()

        # Double check LR became selected; if not, retry once directly
        if hasattr(task.vision, "is_filter_lr_selected") and not task.vision.is_filter_lr_selected(
            popup_screen
        ):
            task.adb.tap(int(w * 0.842), int(h * 0.638), delay_after=0.6)
            popup_screen = task.adb.screencap()

    # Ensure UR is still selected (in case of unexpected toggle)
    if hasattr(task.vision, "is_filter_ur_selected") and not task.vision.is_filter_ur_selected(
        popup_screen
    ):
        ur_coords = (
            task.vision.get_filter_ur_coords(popup_screen)
            if hasattr(task.vision, "get_filter_ur_coords")
            else (int(w * 0.70), int(h * 0.638))
        )
        task.adb.tap(ur_coords[0], ur_coords[1], delay_after=0.6)
        popup_screen = task.adb.screencap()

    # 6. Confirm OK
    ok_loc = task.vision.find_template(
        popup_screen, "buttons/button_ok.png", threshold=0.75
    ) or task.vision.find_template(popup_screen, "button_ok", threshold=0.75)
    if ok_loc:
        task.adb.tap(ok_loc[0], ok_loc[1], delay_after=1.5)
    else:
        task.adb.tap(int(w * 0.50), int(h * 0.843), delay_after=1.5)

    task.log("In-game box filters configured (UR+LR, Released).")
    return True


__all__ = ["verify_and_enforce_filters"]
