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
    if not task.vision:
        return True

    screen = task.adb.screencap() if task.adb else None
    size = task.adb.get_screen_size() if task.adb else (1080, 2400)
    w, h = size if isinstance(size, (tuple, list)) and len(size) >= 2 else (1080, 2400)

    sort_ok = bool(
        task.vision.find_template(screen, "filters/tag_sort_released.png", threshold=0.75)
        or (hasattr(task.vision, "is_sort_released") and task.vision.is_sort_released(screen))
    )
    filter_on = bool(task.vision.find_template(screen, "filters/tag_filter_on.png", threshold=0.75))

    if not filter_on:
        task.log("Filters not active on grid. Opening filter popup to configure UR+LR...")
        filter_btn_loc = task.vision.find_template(
            screen, "filters/tag_filter_on.png", threshold=0.75
        )
        if filter_btn_loc:
            task.adb.tap(filter_btn_loc[0], filter_btn_loc[1], delay_after=1.0)
        else:
            task.adb.tap(int(w * 0.90), int(h * 0.95), delay_after=1.0)

        popup_screen = task.adb.screencap()

        ur_selected = bool(
            task.vision.find_template(popup_screen, "filters/btn_ur_selected.png", threshold=0.75)
        )
        if not ur_selected:
            ur_unsel_loc = task.vision.find_template(
                popup_screen, "filters/btn_ur_unselected.png", threshold=0.75
            )
            if ur_unsel_loc:
                task.adb.tap(ur_unsel_loc[0], ur_unsel_loc[1], delay_after=0.5)
            else:
                task.adb.tap(int(w * 0.70), int(h * 0.638), delay_after=0.5)
            popup_screen = task.adb.screencap()

        lr_selected = bool(
            task.vision.find_template(popup_screen, "filters/btn_lr_selected.png", threshold=0.75)
        )
        if not lr_selected:
            lr_unsel_loc = task.vision.find_template(
                popup_screen, "filters/btn_lr_unselected.png", threshold=0.75
            )
            if lr_unsel_loc:
                task.adb.tap(lr_unsel_loc[0], lr_unsel_loc[1], delay_after=0.5)
            else:
                task.adb.tap(int(w * 0.84), int(h * 0.638), delay_after=0.5)
            popup_screen = task.adb.screencap()

        ok_loc = task.vision.find_template(popup_screen, "buttons/button_ok.png", threshold=0.75)
        if ok_loc:
            task.adb.tap(ok_loc[0], ok_loc[1], delay_after=1.0)
        else:
            task.adb.tap(int(w * 0.50), int(h * 0.85), delay_after=1.0)

        task.log(f"In-game box filters configured. SortReleased={sort_ok}")
        return True

    task.log(f"In-game box filters status: FilterOn={filter_on}, SortReleased={sort_ok}")
    return True


__all__ = ["verify_and_enforce_filters"]
