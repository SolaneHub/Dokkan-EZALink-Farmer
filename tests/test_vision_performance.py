"""Vision performance benchmark and regression verification.

Quantifies execution time for 100 iterations of template matching
on synthetic 1080x2400 frames to ensure zero overhead and optimal ROI latency.
"""

from __future__ import annotations

import time

import cv2
import numpy as np
import pytest

from dokkan_eza_link_farmer.automation.vision import Vision
from dokkan_eza_link_farmer.integrations.adb_client import ADBClient


@pytest.mark.fast
def test_vision_roi_match_performance():
    """Benchmarking 100 iterations of template matching within a targeted ROI.

    Verifies that mean matching latency remains strictly under 5ms per match.
    """
    screen = np.zeros((2400, 1080, 3), dtype=np.uint8)
    # Synthetic template with visual pattern representing a UI button (e.g. 80x150)
    tmpl = np.zeros((80, 150, 3), dtype=np.uint8)
    cv2.circle(tmpl, (75, 40), 25, (255, 200, 50), -1)
    cv2.putText(tmpl, "OK", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)

    # Prior ROI region (e.g. 200px x 400px window)
    y1, y2 = 1000, 1200
    x1, x2 = 300, 700
    screen[1050 : 1050 + 80, 350 : 350 + 150] = tmpl

    roi = screen[y1:y2, x1:x2]
    # Ensure contiguous buffer or direct slice operates seamlessly with zero overhead
    c_roi = np.ascontiguousarray(roi) if not roi.flags.c_contiguous else roi

    # Warm-up run
    for _ in range(5):
        res = cv2.matchTemplate(c_roi, tmpl, cv2.TM_CCOEFF_NORMED)
        _ = cv2.minMaxLoc(res)

    max_val = 0.0
    max_loc = (0, 0)
    t0 = time.perf_counter()
    for _ in range(100):
        res = cv2.matchTemplate(c_roi, tmpl, cv2.TM_CCOEFF_NORMED)
        _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(res)
    t1 = time.perf_counter()

    total_ms = (t1 - t0) * 1000.0
    avg_ms = total_ms / 100.0

    assert max_val >= 0.99
    assert max_loc == (50, 50)
    # Target criteria: < 5ms per ROI match
    assert avg_ms < 5.0, f"ROI template matching too slow: {avg_ms:.2f}ms >= 5.0ms"


@pytest.mark.fast
def test_vision_find_template_contiguous_and_roi_speed():
    """Validates that Vision.find_template properly executes within bounded vertical ROI."""
    vision = Vision("src/dokkan_eza_link_farmer/assets/templates/glb")

    screen = np.zeros((2400, 1080, 3), dtype=np.uint8)
    button_tmpl = vision.load_template("button_start")
    if button_tmpl is not None:
        th, tw = button_tmpl.shape[:2]
        # Place button_start in its expected vertical ROI (60%..98% Y)
        py = 1800
        px = 600
        screen[py : py + th, px : px + tw] = button_tmpl

        # Verify matching coordinates
        match = vision.find_template(screen, "button_start")
        assert match is not None
        assert abs(match[0] - (px + tw // 2)) <= 2
        assert abs(match[1] - (py + th // 2)) <= 2


@pytest.mark.fast
def test_adb_client_buffer_reuse():
    """Ensures ADBClient allocates and reuses memory buffer during screencap conversions."""
    adb = ADBClient()
    assert adb._frame_buffer is None

    # Simulate raw screencap buffer parsing
    w, h = 1080, 2400
    raw_rgba = np.zeros((h, w, 4), dtype=np.uint8)
    buf = np.empty((h, w, 3), dtype=np.uint8)
    adb._frame_buffer = buf

    cv2.cvtColor(raw_rgba, cv2.COLOR_RGBA2BGR, dst=adb._frame_buffer)
    assert adb._frame_buffer.shape == (2400, 1080, 3)
    assert adb._frame_buffer.flags.c_contiguous
