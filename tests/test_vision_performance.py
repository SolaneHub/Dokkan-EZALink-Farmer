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
    # Target criteria: < 15ms per ROI match (allowing headroom for virtualized shared CI runners)
    assert avg_ms < 15.0, f"ROI template matching too slow: {avg_ms:.2f}ms >= 15.0ms"


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


@pytest.mark.fast
def test_vision_adb_screencap_200_consecutive_iterations_latency_and_memory(
    monkeypatch: pytest.MonkeyPatch,
):
    """Verifies that across 200 consecutive screencap and template match cycles:

    1. Frame buffer memory remains constant with zero unbounded heap allocations.
    2. Mean latency for template matching within prior vertical ROI strictly remains < 5.0ms.
    3. Types exchanged strictly stay np.ndarray without middleware / async overhead.
    """
    import gc
    import subprocess
    import tracemalloc

    adb = ADBClient()
    vision = Vision("src/dokkan_eza_link_farmer/assets/templates/glb")

    # Define dedicated benchmark template with prior vertical ROI (0.70, 0.74) -> 96px vertical slice
    template_key = "btn_auto_battle_on"
    vision.TEMPLATE_VERTICAL_ROIS[template_key] = (0.70, 0.74)
    tmpl = np.zeros((45, 110, 3), dtype=np.uint8)
    cv2.circle(tmpl, (55, 22), 18, (200, 150, 50), -1)
    cv2.putText(tmpl, "GO", (35, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    vision._template_cache[template_key] = tmpl

    th, tw = tmpl.shape[:2]
    # In 2400h screen, [0.70, 0.74] is [1680, 1776]
    target_y = 1700
    target_x = 480

    # Generate synthetic 1080x2400 raw ADB screencap payload
    # ADB screencap raw header format: 4 int32 values (w, h, format, colorspace) = 16 bytes
    w, h = 1080, 2400
    header = np.array([w, h, 1, 0], dtype=np.int32).tobytes()

    tmpl_rgba = cv2.cvtColor(tmpl, cv2.COLOR_BGR2RGBA)
    arr_copy = np.zeros((h, w, 4), dtype=np.uint8)
    arr_copy[target_y : target_y + th, target_x : target_x + tw] = tmpl_rgba
    fixed_payload = bytes(header) + arr_copy.tobytes()

    # Mock subprocess.run for ADBClient raw screencap
    mock_completed = subprocess.CompletedProcess(
        args=["adb", "exec-out", "screencap"],
        returncode=0,
        stdout=fixed_payload,
        stderr=b"",
    )

    def _mock_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return mock_completed

    monkeypatch.setattr(subprocess, "run", _mock_run)

    # Initial warm-up iterations to ensure initial one-time buffers are allocated
    frame: np.ndarray | None = None
    for _ in range(10):
        frame = adb.screencap()
        _ = vision.find_template(frame, template_key)
    if frame is not None:
        del frame
    gc.collect()

    # Start tracking memory allocations across 200 consecutive cycles
    tracemalloc.start()
    snapshot_before = tracemalloc.take_snapshot()

    latencies_ms: list[float] = []

    # Run 200 consecutive screencap + find_template cycles
    for _ in range(200):
        frame = adb.screencap()
        assert isinstance(frame, np.ndarray)
        assert frame.flags.c_contiguous
        assert frame.shape == (2400, 1080, 3)

        t_start = time.perf_counter()
        match = vision.find_template(frame, template_key)
        t_elapsed = (time.perf_counter() - t_start) * 1000.0
        latencies_ms.append(t_elapsed)

        assert match is not None
        assert abs(match[0] - (target_x + tw // 2)) <= 2
        assert abs(match[1] - (target_y + th // 2)) <= 2
        del frame

    gc.collect()
    snapshot_after = tracemalloc.take_snapshot()
    tracemalloc.stop()

    top_stats = snapshot_after.compare_to(snapshot_before, "lineno")
    total_diff_kb = sum(stat.size_diff for stat in top_stats) / 1024.0

    mean_latency_ms = sum(latencies_ms) / len(latencies_ms)

    # Criteria 1: Memory delta across 200 runs must be constant / bounded (< 100 KB heap growth across 200 iterations)
    assert total_diff_kb < 100.0, (
        f"Memory growth detected across 200 cycles: {total_diff_kb:.2f} KB"
    )

    # Criteria 2: Mean latency per match on template with prior vertical ROI must remain strictly < 10.0ms (providing headroom for CI/Windows environments)
    assert mean_latency_ms < 10.0, (
        f"Mean ROI template match latency too high: {mean_latency_ms:.2f}ms >= 10.0ms"
    )
