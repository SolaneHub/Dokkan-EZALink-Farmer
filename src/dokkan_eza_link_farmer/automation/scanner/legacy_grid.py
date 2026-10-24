"""Backward-compatibility helpers for legacy grid matching and vertical tracking."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

import cv2
import numpy as np

logger = logging.getLogger(__name__)


def init_thumbnails(
    scanner: Any,
    catalog: list[dict[str, Any]],
    cache_dir: str,
    include_ssr: bool = False,
    syncer: Any = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Loads and prepares character thumbnails for fast grid pattern matching."""
    _ = include_ssr
    thumbs_dir = os.path.join(cache_dir, "thumbs")
    os.makedirs(thumbs_dir, exist_ok=True)
    char_json_path = os.path.join(cache_dir, "dokkan_characters.json")
    char_map: dict[int, dict[str, Any]] = {}
    allowed_rarities = (3, 4, 5)

    for c in catalog:
        cid = c.get("id")
        rarity = c.get("rarity")
        if rarity in allowed_rarities and cid:
            char_map[int(str(cid)[:-1] + "0")] = {
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

    if os.path.exists(char_json_path):
        try:
            import json

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
        f for f in os.listdir(thumbs_dir) if f.startswith("card_") and f.endswith("_thumb.png")
    ]
    if len(thumb_files) < 10 and syncer and catalog:
        scanner.log("Downloading character thumbnails from Supabase mirror...")
        try:
            syncer.sync_thumbnails(cards=catalog)
            thumb_files = [
                f
                for f in os.listdir(thumbs_dir)
                if f.startswith("card_") and f.endswith("_thumb.png")
            ]
        except Exception as e:
            logger.warning(f"Could not auto-download thumbnails from Supabase: {e}")

    loaded_thumbs: list[dict[str, Any]] = []
    type_map = {"AGI": "AGL", "TEC": "TEQ", "INT": "INT", "PUI": "STR", "END": "PHY"}
    blacklisted = {1002910, 1024090, 1002300}
    valid_rarities = ("SSR", "UR", "LR")

    for f in thumb_files:
        fp = os.path.join(thumbs_dir, f)
        parts = f.replace("card_", "").replace("_thumb.png", "")
        tid = int(parts) if parts.isdigit() else None
        if not tid or tid in blacklisted:
            continue
        info = char_map.get(tid)
        if not info or (info.get("rarity") and info["rarity"] not in valid_rarities):
            continue

        im = cv2.imread(fp, cv2.IMREAD_UNCHANGED)
        if im is not None and len(im.shape) == 3 and im.shape[2] == 4 and im.shape[0] >= 200:
            alpha = im[:, :, 3]
            pts = np.argwhere(alpha > 80)
            if pts.size == 0:
                continue
            y1, x1 = pts.min(axis=0)
            y2, x2 = pts.max(axis=0)
            p_cy, p_cx = int(np.mean(pts[:, 0])), int(np.mean(pts[:, 1]))
            crop = im[
                max(0, p_cy - 55) : min(im.shape[0], p_cy + 55),
                max(0, p_cx - 55) : min(im.shape[1], p_cx + 55),
                :3,
            ]
            face_patch = cv2.resize(crop, (int(crop.shape[1] * 0.84), int(crop.shape[0] * 0.84)))
            char_bgr = im[y1:y2, x1:x2, :3]
            char_mask = (alpha[y1:y2, x1:x2] > 80).astype(np.uint8) * 255
            card_id = int(info.get("id") or (tid + 1))
            elem_norm = type_map.get(str(info.get("type", "")), str(info.get("type", "")))
            loaded_thumbs.append(
                {
                    "thumb_id": tid,
                    "card_id": card_id,
                    "name": info.get("name") or f"Card_{card_id}",
                    "subname": info.get("subname") or "",
                    "rarity": 5
                    if info.get("rarity") == "LR"
                    else (4 if info.get("rarity") == "UR" else 3),
                    "type": elem_norm,
                    "has_survival_passive": bool(info.get("has_survival_passive", False)),
                    "face_patch": face_patch,
                    "masked_bgr": cv2.resize(char_bgr, (0, 0), fx=0.84, fy=0.84),
                    "masked_mask": cv2.resize(
                        char_mask, (0, 0), fx=0.84, fy=0.84, interpolation=cv2.INTER_NEAREST
                    ),
                }
            )

    lr_thumbs = [t for t in loaded_thumbs if t.get("rarity") == 5]
    return loaded_thumbs, lr_thumbs


def match_slot_thumbnail_with_delta(
    loaded_thumbs: list[dict[str, Any]], crop: np.ndarray
) -> tuple[dict[str, Any] | None, float, float]:
    """Matches a single grid slot crop, returning (best_candidate, best_score, delta)."""
    if not loaded_thumbs or crop is None or crop.size == 0:
        return None, 0.0, 0.0

    scores: list[tuple[float, dict[str, Any]]] = []
    for t in loaded_thumbs:
        res = cv2.matchTemplate(crop, t["face_patch"], cv2.TM_CCOEFF_NORMED)
        score = float(cv2.minMaxLoc(res)[1])
        if score >= 0.25:
            scores.append((score, t))

    if not scores:
        return None, 0.0, 0.0

    scores.sort(key=lambda x: x[0], reverse=True)
    best_cand, best_s = scores[0][1], scores[0][0]
    second_s = scores[1][0] if len(scores) > 1 else 0.0
    delta = best_s - second_s
    if best_s >= 0.85 and delta >= 0.08:
        return best_cand, best_s, delta

    eval_set = {t["thumb_id"]: t for _, t in scores[:35]}
    ch, cw = crop.shape[:2]
    masked_scores: list[tuple[float, dict[str, Any]]] = []
    for t in eval_set.values():
        mbgr, mmask = t.get("masked_bgr"), t.get("masked_mask")
        if mbgr is not None and mmask is not None and mbgr.shape[0] <= ch and mbgr.shape[1] <= cw:
            res = cv2.matchTemplate(crop, mbgr, cv2.TM_CCORR_NORMED, mask=mmask)
            masked_scores.append((float(cv2.minMaxLoc(res)[1]), t))

    if masked_scores:
        masked_scores.sort(key=lambda x: x[0], reverse=True)
        if masked_scores[0][0] > best_s:
            best_s = masked_scores[0][0]
            best_cand = masked_scores[0][1]
            second_ms = masked_scores[1][0] if len(masked_scores) > 1 else 0.0
            delta = best_s - second_ms

    if best_s < 0.75 and delta < 0.06:
        cand_name = best_cand.get("name") if best_cand else "None"
        cand_id = best_cand.get("card_id") if best_cand else "None"
        logger.debug(
            "[TRANSPARENCY] Rejecting ambiguous thumbnail match: best candidate [%s] '%s' score %.3f < 0.75, delta %.3f < 0.06",
            cand_id,
            cand_name,
            best_s,
            delta,
        )
        return None, best_s, delta

    return best_cand, best_s, delta


def get_second_candidate(
    loaded_thumbs: list[dict[str, Any]], crop: np.ndarray
) -> tuple[dict[str, Any] | None, float]:
    """Returns the second best thumbnail match candidate and its score."""
    if not loaded_thumbs or crop is None or crop.size == 0:
        return None, 0.0
    scores: list[tuple[float, dict[str, Any]]] = []
    for t in loaded_thumbs:
        res = cv2.matchTemplate(crop, t["face_patch"], cv2.TM_CCOEFF_NORMED)
        score = float(cv2.minMaxLoc(res)[1])
        if score >= 0.25:
            scores.append((score, t))
    if len(scores) < 2:
        return None, 0.0
    scores.sort(key=lambda x: x[0], reverse=True)
    return scores[1][1], scores[1][0]


def track_vertical_shift(
    prev_img: np.ndarray,
    curr_img: np.ndarray,
    last_cy: float,
    col_ratios: list[float] | None = None,
) -> float | None:
    """Calculates exact pixel shift between consecutive screens using horizontal strip matching."""
    _ = col_ratios
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

    strip_candidates = [1111.0, 1363.0, 858.0]
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


def match_row_with_alignment(
    scanner: Any, grid_img: np.ndarray, cy: float, col_xs: list[int], half_w: int, half_h: int
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
            _, s, _ = scanner._match_slot_thumbnail_with_delta(crop)
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
                    _, s, _ = scanner._match_slot_thumbnail_with_delta(crop)
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
        cand, score, delta = scanner._match_slot_thumbnail_with_delta(crop)
        ocr_executed_for_slot = False

        prev_pos = getattr(scanner, "_recently_scanned_positions", {}).get(
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

        if cand and int(cand["card_id"]) in scanner.scanned_cards and not is_overlap_rescan:
            cid = int(cand["card_id"])
            is_adjacent = (
                scanner._last_registered_card_id is not None
                and scanner._last_registered_card_id == cid
            )
            if not is_adjacent:
                scanner.log(
                    f"  [ANTI-COLLISION] Slot ({int(final_cy)}, {cx}) candidate [{cid}] {cand.get('name')} "
                    f"already seen non-adjacently (last registered: {scanner._last_registered_card_id}). Rejecting false DUPE!"
                )
                cand2, s2 = scanner._get_second_candidate(crop)
                if (
                    cand2
                    and s2 >= 0.70
                    and (
                        int(cand2["card_id"]) not in scanner.scanned_cards
                        or int(cand2["card_id"]) == scanner._last_registered_card_id
                    )
                ):
                    scanner.log(
                        f"  [ANTI-COLLISION] Selected 2nd candidate [{cand2['card_id']}] {cand2.get('name')} (score: {s2:.2f})"
                    )
                    cand = cand2
                    score = s2
                elif not scanner.pure_grid_mode:
                    ocr_executed_for_slot = True
                    delta = 1.0
                    fallback_cand = scanner._execute_ocr_fallback(cx, int(final_cy))
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

        if (
            (cand is None or score < 0.72 or delta < 0.05)
            and not scanner.pure_grid_mode
            and not ocr_executed_for_slot
            and score > 0.0
        ):
            fallback_cand = scanner._execute_ocr_fallback(cx, int(final_cy))
            if fallback_cand:
                cand = fallback_cand
                cand["from_ocr"] = True
                score = 1.0

        if cand and score >= 0.72 and not is_overlap_rescan:
            scanner._last_registered_card_id = int(cand["card_id"])
        elif not is_overlap_rescan and (cand is None or score < 0.55):
            scanner._last_registered_card_id = None

        row_results.append((cand, score, crop, cx, c_idx))

    return final_cy, row_results


def execute_ocr_fallback(scanner: Any, cx: int, cy: int) -> dict[str, Any] | None:
    """Compatibility fallback for thumbnail OCR tests."""
    size = scanner.adb.get_screen_size() if scanner.adb else (1080, 2400)
    w, h = size if isinstance(size, (tuple, list)) and len(size) >= 2 else (1080, 2400)
    scanner.adb.tap(cx, cy, delay_after=1.0)
    screen = scanner.adb.screencap()
    subname = scanner._read_card_title_from_screen(screen)
    matched = scanner._match_card_by_text(subname) if subname else None

    back_loc = (
        scanner.vision.find_template(screen, "buttons/button_back_green.png", threshold=0.70)
        if scanner.vision and screen is not None
        else None
    )
    if back_loc:
        scanner.adb.tap(back_loc[0], back_loc[1], delay_after=0.8)
    else:
        scanner.adb.tap(
            int(w * scanner.BACK_BUTTON_RATIO[0]),
            int(h * scanner.BACK_BUTTON_RATIO[1]),
            delay_after=0.8,
        )

    if matched:
        return {
            "card_id": int(matched.get("id") or 0),
            "name": matched.get("name"),
            "subname": matched.get("subname"),
            "rarity": matched.get("rarity", 4),
            "element": matched.get("element"),
        }
    return None


def run_grid_scan(scanner: Any) -> None:
    """Main automated scanning loop with visual tracking, filter verification, and position logging."""
    scanner._setup_file_logger()
    start_time = datetime.now(timezone.utc)
    logger.info("=" * 70)
    logger.info(
        f"=== Dokkan Box Scanner Session Started: {start_time.strftime('%Y-%m-%d %H:%M:%S UTC')} ==="
    )
    logger.info(f"Log destination: {scanner.log_file}")
    logger.info(f"Box output target: {scanner.output_file}")
    logger.info(
        f"Max cards to scan: {scanner.max_cards_to_scan if scanner.max_cards_to_scan else 'unlimited'}"
    )
    logger.info(f"Include SSR: {scanner.include_ssr}, Pure Grid Mode: {scanner.pure_grid_mode}")
    logger.info("=" * 70)

    scanner.is_running = True
    try:
        scanner.log(
            "🚀 Starting Autonomous Character Box Scanner (Visual Shift & Position Tracking)..."
        )

        scanner._init_catalog()
        scanner._init_thumbnails()
        scanner.ensure_box_filters()

        w, h = scanner.adb.get_screen_size()
        scanner.log(f"Device resolution: {w}x{h}. Initializing grid scanning...")

        initial_screen = scanner.adb.screencap()
        if scanner._is_card_details_screen(initial_screen):
            scanner.log("Detected open card detail view. Returning to grid...")
            scanner.adb.tap(
                int(w * scanner.BACK_BUTTON_RATIO[0]),
                int(h * scanner.BACK_BUTTON_RATIO[1]),
                delay_after=1.0,
            )

        scanner.scroll_to_top()

        if not hasattr(scanner, "scanned_cards") or scanner.scanned_cards is None:
            scanner.scanned_cards = {}
        scanner._recently_scanned_positions = {}
        scanner._last_registered_card_id = None
        row_pitch = 253.0
        half_w = int(w * 0.088)
        half_h = 125
        col_xs = [int(w * r) for r in scanner.COL_RATIOS]
        max_visible_y = 1680.0

        curr_grid = scanner.adb.screencap()

        top_row_ys = [int(h * r) for r in scanner.ROW_RATIOS]
        scanner.log(f"Scanning initial top screen (5 rows at y={top_row_ys})...")

        last_scanned_cy = float(top_row_ys[-1])
        for r_idx, cy in enumerate(top_row_ys):
            aligned_cy, row_results = scanner._match_row_with_alignment(
                curr_grid, cy, col_xs, half_w, half_h
            )
            for cand, score, crop, cx, c_idx in row_results:
                grid_slot = r_idx * 5 + c_idx
                scanner._register_card(
                    cand, score, crop, aligned_cy, cx, swipe_page=0, grid_slot=grid_slot
                )
            last_scanned_cy = float(aligned_cy)

        swipe_rows = 3
        swipe_delta_y = int(swipe_rows * row_pitch)
        start_y = int(h * 0.65)
        end_y = start_y - swipe_delta_y

        consecutive_stationary_swipes = 0
        swipe_count = 0

        while not scanner.is_stopped():
            swipe_count += 1
            total_instances = sum(int(c.get("copies", 1)) for c in scanner.scanned_cards.values())
            if scanner.max_cards_to_scan and total_instances >= scanner.max_cards_to_scan:
                scanner.log(f"Reached target scan limit of {scanner.max_cards_to_scan} cards.")
                break

            pre_swipe = curr_grid
            scanner.adb.swipe(
                int(w * 0.50), start_y, int(w * 0.50), end_y, duration_ms=800, delay_after=1.0
            )

            next_grid = scanner.adb.screencap()
            if scanner._is_card_details_screen(next_grid):
                scanner.adb.tap(
                    int(w * scanner.BACK_BUTTON_RATIO[0]),
                    int(h * scanner.BACK_BUTTON_RATIO[1]),
                    delay_after=0.5,
                )
                next_grid = scanner.adb.screencap()

            screen_diff = scanner._compute_screen_diff(pre_swipe, next_grid)
            logger.debug(f"Swipe #{swipe_count}: pixel diff = {screen_diff:.2f}")

            if screen_diff < 7.5:
                consecutive_stationary_swipes += 1
                scanner.log(
                    f"No vertical scroll detected via pixel diff ({screen_diff:.2f} < 7.5, "
                    f"{consecutive_stationary_swipes}/2 stationary swipes)..."
                )
                if consecutive_stationary_swipes >= 2:
                    remaining_rows = []
                    next_cy = last_scanned_cy + row_pitch
                    while next_cy <= max_visible_y:
                        remaining_rows.append(next_cy)
                        next_cy += row_pitch

                    if remaining_rows:
                        scanner.log(
                            f"Scanning final bottom rows: {[int(y) for y in remaining_rows]}"
                        )
                        for r_offset, cy in enumerate(remaining_rows):
                            aligned_cy, row_results = scanner._match_row_with_alignment(
                                next_grid, cy, col_xs, half_w, half_h
                            )
                            for cand, score, crop, cx, c_idx in row_results:
                                slot = (
                                    (len(top_row_ys) - len(remaining_rows) + r_offset) % 5
                                ) * 5 + c_idx
                                scanner._register_card(
                                    cand,
                                    score,
                                    crop,
                                    aligned_cy,
                                    cx,
                                    swipe_page=swipe_count,
                                    grid_slot=slot,
                                )

                    scanner.log(
                        "✅ Reached bottom of Character List (pixel diff verified). Full Box scan completed!"
                    )
                    break

                curr_grid = next_grid
                continue

            shift = scanner._track_vertical_shift(curr_grid, next_grid, last_scanned_cy)
            if shift is None or shift < 50.0:
                if screen_diff < 12.0:
                    scanner.log(
                        f"Low motion detected (diff: {screen_diff:.2f}, shift: {shift}). Treating as bottom boundary."
                    )
                    consecutive_stationary_swipes += 1
                    if consecutive_stationary_swipes >= 2:
                        break
                    curr_grid = next_grid
                    continue
                shift = float(swipe_delta_y)

            consecutive_stationary_swipes = 0
            new_anchor_cy = last_scanned_cy - shift
            new_rows = []
            k = 1
            while True:
                next_cy = new_anchor_cy + k * row_pitch
                if next_cy > max_visible_y:
                    break
                if next_cy >= 550.0:
                    new_rows.append(next_cy)
                k += 1

            scanner.log(
                f"Swipe #{swipe_count}: shift {shift:.0f}px ({(shift / row_pitch):.2f} rows). "
                f"Scanning {len(new_rows)} newly revealed rows: {[int(y) for y in new_rows]}"
            )

            if new_rows:
                last_aligned = float(new_rows[-1])
                for r_offset, cy in enumerate(new_rows):
                    aligned_cy, row_results = scanner._match_row_with_alignment(
                        next_grid, cy, col_xs, half_w, half_h
                    )
                    for cand, score, crop, cx, c_idx in row_results:
                        slot = ((r_offset + 3) % 5) * 5 + c_idx
                        scanner._register_card(
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
                scanner._save_box(enrich=False)

        scanner.log("Enriching owned cards with DokkanDB links and optimal linking partners...")
        scanner._save_box(enrich=True)
        total_instances = sum(int(c.get("copies", 1)) for c in scanner.scanned_cards.values())
        scanner.log(
            f"✅ Box Scan Completed! Stored {total_instances} total cards ({len(scanner.scanned_cards)} unique) in '{scanner.output_file}'."
        )
    except Exception as exc:
        logger.exception(f"Unhandled exception during box scanning: {exc}")
        scanner.log(f"❌ Box scan interrupted by error: {exc}")
        raise
    finally:
        end_time = datetime.now(timezone.utc)
        duration = end_time - start_time
        total_cards = (
            sum(int(c.get("copies", 1)) for c in scanner.scanned_cards.values())
            if hasattr(scanner, "scanned_cards") and scanner.scanned_cards
            else 0
        )
        unique_cards = (
            len(scanner.scanned_cards)
            if hasattr(scanner, "scanned_cards") and scanner.scanned_cards
            else 0
        )
        logger.info("=" * 70)
        logger.info(
            f"=== Dokkan Box Scanner Session Ended: {end_time.strftime('%Y-%m-%d %H:%M:%S UTC')} (Duration: {duration}) ==="
        )
        logger.info(
            f"Final Count: {total_cards} total cards ({unique_cards} unique) in '{scanner.output_file}'"
        )
        logger.info("=" * 70)
        scanner.is_running = False
        scanner._close_file_logger()


__all__ = [
    "execute_ocr_fallback",
    "get_second_candidate",
    "init_thumbnails",
    "match_row_with_alignment",
    "match_slot_thumbnail_with_delta",
    "run_grid_scan",
    "track_vertical_shift",
]
