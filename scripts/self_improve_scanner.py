"""
Live Box Self-Improvement Scanner Script
Connects via ADB to scan the first 30 cards of the user's Character Box,
measures confidence and accuracy, saves debug crops on low confidence or mismatch,
and logs metrics to console and JSON report.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any

import cv2
import numpy as np

from dokkan_eza_link_farmer.automation import scanner as scanner_module
from dokkan_eza_link_farmer.automation.scanner.banner_extractor import (
    BANNER_CROP_X,
    BANNER_CROP_Y,
    preprocess_text_banner,
)
from dokkan_eza_link_farmer.automation.scanner.detail_evaluator import (
    LEVEL_CROP_X,
    LEVEL_CROP_Y,
)
from dokkan_eza_link_farmer.automation.tasks.box_scanner import BoxScannerTask
from dokkan_eza_link_farmer.integrations.adb_client import ADBClient

# Ensure root directory is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("self_improve_scanner")

DEBUG_CROPS_DIR = os.path.join(BASE_DIR, "debug_crops")
REPORT_PATH = os.path.join(BASE_DIR, "reports", "self_improve_scanner_report.json")


def save_debug_crops(
    idx: int,
    screen_img: np.ndarray,
    _scanner: BoxScannerTask,
) -> None:
    """Saves full screen, banner, clean banner, and level crops for inspection."""
    os.makedirs(DEBUG_CROPS_DIR, exist_ok=True)
    h, w = screen_img.shape[:2]

    # Full screen
    full_path = os.path.join(DEBUG_CROPS_DIR, f"card_{idx:02d}_full.png")
    cv2.imwrite(full_path, screen_img)

    # Banner crop and rotated
    y1, y2 = int(h * BANNER_CROP_Y[0]), int(h * BANNER_CROP_Y[1])
    x1, x2 = int(w * BANNER_CROP_X[0]), int(w * BANNER_CROP_X[1])
    raw_banner = screen_img[y1:y2, x1:x2]
    if raw_banner.size > 0:
        banner_rot = cv2.rotate(raw_banner, cv2.ROTATE_90_CLOCKWISE)
        banner_path = os.path.join(DEBUG_CROPS_DIR, f"card_{idx:02d}_banner.png")
        cv2.imwrite(banner_path, banner_rot)

        clean_banner = preprocess_text_banner(banner_rot)
        clean_path = os.path.join(DEBUG_CROPS_DIR, f"card_{idx:02d}_clean.png")
        cv2.imwrite(clean_path, clean_banner)

    # Level crop
    ly1, ly2 = int(h * LEVEL_CROP_Y[0]), int(h * LEVEL_CROP_Y[1])
    lx1, lx2 = int(w * LEVEL_CROP_X[0]), int(w * LEVEL_CROP_X[1])
    level_crop = screen_img[ly1:ly2, lx1:lx2]
    if level_crop.size > 0:
        level_path = os.path.join(DEBUG_CROPS_DIR, f"card_{idx:02d}_level.png")
        cv2.imwrite(level_path, level_crop)


def run_scanner(serial: str = "RZCTB0ETG9L", total_cards: int = 30) -> dict[str, Any]:
    """Runs the 30-card scan loop, records metrics, and saves debug crops on failure."""
    logger.info(f"Connecting to ADB device (serial='{serial}')...")
    adb = ADBClient(serial=serial)
    devs = adb.list_devices()
    logger.info(f"Connected devices: {devs}")
    from dokkan_eza_link_farmer.automation.vision import Vision

    config: dict[str, Any] = {}
    scanner = BoxScannerTask(adb=adb, vision=Vision(), config=config)
    scanner._init_catalog()

    w, h = adb.get_screen_size()
    logger.info(f"Screen size: {w}x{h}")

    initial_screen = adb.screencap()
    is_details = scanner._is_card_details_screen(initial_screen)
    logger.info(f"Initial screen is_card_details: {is_details}")

    if not is_details:
        slot1_x = int(w * (110 / 1080.0))
        slot1_y = int(h * (604 / 2400.0))
        logger.info(f"Tapping Slot 1 at ({slot1_x}, {slot1_y}) to open Card #1...")
        adb.tap(slot1_x, slot1_y, delay_after=1.5)
        current_screen = adb.screencap()
        if not scanner._is_card_details_screen(current_screen):
            logger.info("Retrying tap on Slot 1...")
            adb.tap(slot1_x, slot1_y, delay_after=1.5)
            current_screen = adb.screencap()
    else:
        current_screen = initial_screen

    records: list[dict[str, Any]] = []
    elem_names_base = {0: "AGL", 1: "TEQ", 2: "INT", 3: "STR", 4: "PHY"}

    print("=" * 115, flush=True)
    print(
        f"{'#':<3} | {'CONF':<6} | {'CARD ID':<9} | {'ELEMENT':<7} | {'RARITY':<6} | {'EZA':<5} | {'LATENCY':<8} | {'DETECTED NAME / CATALOG NAME'}",
        flush=True,
    )
    print("=" * 115, flush=True)

    for idx in range(1, total_cards + 1):
        # Step 1: Extract multi-signal metadata
        detected_text = scanner_module.extract_banner_text(current_screen)
        detected_sub, detected_nm = scanner_module.extract_banner_tokens(current_screen)
        detected_class, detected_elem = scanner_module.extract_element_badge(current_screen)
        matcher = scanner_module.CatalogMatcher(scanner._catalog)
        cand, score = matcher.match_card_candidate(
            detected_text, detected_class=detected_class, detected_elem=detected_elem
        )

        # Adaptive 2-frame marquee stitch if score < 0.85
        if score < 0.85:
            logger.info(
                f"  [MARQUEE] Low confidence ({score:.2f} < 0.85) on card #{idx}. Stitched marquee check..."
            )
            time.sleep(1.0)
            frame2 = adb.screencap()
            text_f2 = scanner_module.extract_banner_text(frame2)
            stitched = scanner_module.stitch_marquee_text(detected_text, text_f2)
            cand2, score2 = matcher.match_card_candidate(
                stitched, detected_class=detected_class, detected_elem=detected_elem
            )
            if score2 > score:
                cand, score = cand2, score2
                detected_text = stitched
                sub2, nm2 = scanner_module.extract_banner_tokens(frame2)
                detected_sub = scanner_module.stitch_marquee_text(detected_sub, sub2)
                detected_nm = scanner_module.stitch_marquee_text(detected_nm, nm2)

        rarity = cand.get("rarity", 4) if cand else 4
        is_eza, is_seza, clv, mlv = scanner_module.extract_level_and_sa(
            current_screen, rarity=rarity
        )
        is_rainbow, pot_pct = scanner_module.extract_potential_and_rainbow(current_screen)

        # Catalog validation
        cat_card = scanner._id_index.get(int(cand.get("id") or 0)) if cand else None
        cat_name = cat_card.get("name") if cat_card else None
        cat_subname = cat_card.get("subname") if cat_card else None
        cat_elem_code = cat_card.get("element") if cat_card else None
        cat_elem = (
            elem_names_base.get(int(cat_elem_code) % 5) if cat_elem_code is not None else None
        )
        cat_rarity = (
            "LR"
            if cat_card and cat_card.get("rarity") == 5
            else ("UR" if cat_card and cat_card.get("rarity") == 4 else "SSR")
        )

        card_id = int(cand.get("id") or 0) if cand else None

        # Check failure conditions
        elem_mismatch = (
            cat_elem is not None and detected_elem is not None and cat_elem != detected_elem
        )
        needs_debug = (score < 0.85) or (cand is None) or elem_mismatch
        if needs_debug:
            save_debug_crops(idx, current_screen, scanner)

        # Register in scanner inventory
        scanner_module.register_card(
            scanner.session_ctx,
            cand,
            score=score,
            crop=None,
            swipe_page=idx // 25,
            grid_slot=idx % 25,
            is_rainbow=is_rainbow,
            is_eza=is_eza,
            potential_percent=pot_pct,
        )

        # Advance to next card via synchronized arrow tap
        t_swipe_start = time.time()
        if idx < total_cards:
            current_screen, _ = scanner_module.advance_to_next_card(
                scanner, current_screen, current_card_id=card_id
            )
        swipe_latency_ms = int((time.time() - t_swipe_start) * 1000)

        record = {
            "index": idx,
            "detected_name": detected_nm or detected_text,
            "detected_subname": detected_sub or detected_text,
            "detected_element": detected_elem,
            "detected_rarity": cat_rarity if cand else "UNKNOWN",
            "detected_eza": is_eza,
            "matched_card_id": card_id,
            "catalog_name": cat_name,
            "catalog_subname": cat_subname,
            "confidence_score": round(score, 3),
            "swipe_latency_ms": swipe_latency_ms,
        }
        records.append(record)

        # Print live table line
        cid_str = str(card_id) if card_id else "FAILED"
        elem_str = detected_elem or "?"
        eza_str = "YES" if is_eza else "NO"
        display_name = f"{cat_subname} - {cat_name}" if cat_card else detected_text
        print(
            f"{idx:<3} | {score:<6.2f} | {cid_str:<9} | {elem_str:<7} | {cat_rarity:<6} | {eza_str:<5} | {swipe_latency_ms:<5}ms | {display_name}",
            flush=True,
        )

    print("=" * 115, flush=True)

    # Compute Summary
    scores = [r["confidence_score"] for r in records]
    avg_score = float(np.mean(scores)) if scores else 0.0
    min_score = float(np.min(scores)) if scores else 0.0
    passed_90 = sum(1 for s in scores if s >= 0.90)
    passed_88 = sum(1 for s in scores if s >= 0.88)

    print(
        f"\nSUMMARY: {passed_90}/{total_cards} cards >= 0.90 conf | Avg Conf: {avg_score:.3f} | Min Conf: {min_score:.3f}",
        flush=True,
    )
    if passed_90 == total_cards and min_score >= 0.88:
        print(">>> [30/30 MATCH SUCCESS] ALL CARDS IDENTIFIED WITH CONFIDENCE >= 0.90! <<<")
    else:
        print(
            f">>> [SELF-IMPROVEMENT NEEDED] {total_cards - passed_90} cards below 0.90 threshold <<<"
        )

    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    report_data = {
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "total_cards": total_cards,
        "success_count_90": passed_90,
        "success_count_88": passed_88,
        "avg_confidence": round(avg_score, 3),
        "min_confidence": round(min_score, 3),
        "cards": records,
    }
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)
    logger.info(f"Saved full run report to {REPORT_PATH}")

    # Return to Character List screen
    back_x = int(w * (150 / 1080.0))
    back_y = int(h * (2060 / 2400.0))
    adb.tap(back_x, back_y, delay_after=1.0)

    return report_data


if __name__ == "__main__":
    serial = sys.argv[1] if len(sys.argv) > 1 else "RZCTB0ETG9L"
    run_scanner(serial=serial, total_cards=30)
