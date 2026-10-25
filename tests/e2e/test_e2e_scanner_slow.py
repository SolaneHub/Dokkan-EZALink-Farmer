"""Slow pre-release synthetic visual OCR box scanner integration test.

Verifies end-to-end scanning of simulated cards with swipe transitions using FastSyntheticOCR,
ensuring output schema conforms without flakiness.
"""

from __future__ import annotations

import json
import tempfile
import time
from collections import deque
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from tests.harness.fake_adb import FakeADBClient
from tests.harness.fake_vision_frames import create_synthetic_card_detail_frame

from dokkan_eza_link_farmer.ai.syncer import DokkanSyncer
from dokkan_eza_link_farmer.automation import scanner as scanner_module
from dokkan_eza_link_farmer.automation.tasks.box_scanner import BoxScannerTask
from dokkan_eza_link_farmer.automation.vision import Vision
from dokkan_eza_link_farmer.integrations.dokkandb_client import DokkanDBClient

pytestmark = pytest.mark.slow


class FastSyntheticOCR:
    """Ultra-fast deterministic OCR engine matching synthetic frame metadata without ONNX latency."""

    def __init__(self, card_defs: list[dict[str, Any]]) -> None:
        self.card_map = {c["tag"]: c for c in card_defs}

    def __call__(self, crop: Any) -> tuple[list[Any] | None, float]:
        if crop is None or getattr(crop, "size", 0) == 0:
            return None, 0.0

        h, w = crop.shape[:2]

        # 1. Rotated banner crop (h=264, w=1207)
        if h == 264 and w == 1207:
            px = crop[6, 1203]
            if px[1] == 42 and px[2] == 99:
                c = self.card_map.get(int(px[0]))
                if c:
                    return [
                        [
                            [[50.0, 100.0], [200.0, 100.0], [200.0, 140.0], [50.0, 140.0]],
                            c["subname"],
                            0.99,
                        ],
                        [
                            [[50.0, 200.0], [300.0, 200.0], [300.0, 250.0], [50.0, 250.0]],
                            c["name"],
                            0.99,
                        ],
                    ], 0.0

        # 2. Badge crop: 100..150 height, 100..200 width
        if 100 <= h <= 150 and 100 <= w <= 200:
            px = crop[3, 4]
            if px[1] == 42 and px[2] == 99:
                c = self.card_map.get(int(px[0]))
                if c:
                    return [
                        [
                            [[10.0, 20.0], [80.0, 20.0], [80.0, 45.0], [10.0, 45.0]],
                            c["class"],
                            0.99,
                        ],
                        [
                            [[10.0, 60.0], [80.0, 60.0], [80.0, 95.0], [10.0, 95.0]],
                            c["element"],
                            0.99,
                        ],
                    ], 0.0

        # 3. Super Attack crop: around 84 height, 151 width
        if 50 <= h <= 100 and 100 <= w <= 200:
            return [[[[10.0, 10.0], [80.0, 10.0], [80.0, 30.0], [10.0, 30.0]], "20/20", 0.99]], 0.0

        # 4. Level crop: around 108 height, 324 width
        if 80 <= h <= 130 and 250 <= w <= 380:
            return [
                [[[10.0, 10.0], [80.0, 10.0], [80.0, 30.0], [10.0, 30.0]], "150/150", 0.99]
            ], 0.0

        return None, 0.0


def test_box_scanner_synthetic_integration_end_to_end() -> None:
    """Verifies end-to-end scanning of 3 consecutive simulated cards with swipe transition."""
    card_defs = [
        {
            "id": 1001,
            "name": "Super Saiyan Goku",
            "subname": "Warrior Awakening",
            "class": "SUPER",
            "element": "AGL",
            "element_num": 0,
            "rarity": 5,
            "is_rainbow": True,
            "tag": 101,
        },
        {
            "id": 1001,
            "name": "Super Saiyan Goku",
            "subname": "Warrior Awakening",
            "class": "SUPER",
            "element": "AGL",
            "element_num": 0,
            "rarity": 5,
            "is_rainbow": True,
            "tag": 101,
        },
        {
            "id": 1002,
            "name": "Super Saiyan Vegeta",
            "subname": "Proud Prince",
            "class": "SUPER",
            "element": "TEQ",
            "element_num": 1,
            "rarity": 4,
            "is_rainbow": False,
            "tag": 102,
        },
    ]

    frames: list[Any] = []
    for idx_frame, c in enumerate(card_defs):
        f = create_synthetic_card_detail_frame(
            subname=c["subname"],
            name=c["name"],
            card_class=c["class"],
            card_element=c["element"],
            is_rainbow=c["is_rainbow"],
        )
        f[15, 805] = [c["tag"], 42, 99]
        f[495, 25] = [c["tag"], 42, 99]
        f[1536:1680, 54:972] = [int((idx_frame + 1) * 80) % 256, 120, 200]
        frames.append(f)

    catalog = [
        {
            "id": 1001,
            "name": "Super Saiyan Goku",
            "subname": "Warrior Awakening",
            "rarity": 5,
            "element": 0,
        },
        {
            "id": 1002,
            "name": "Super Saiyan Vegeta",
            "subname": "Proud Prince",
            "rarity": 4,
            "element": 1,
        },
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        out_file = str(Path(tmpdir) / "box.json")
        adb = FakeADBClient()

        queue = deque([frames[1], frames[2]])
        adb.set_current_frame(frames[0])

        def on_right_arrow_tap(x: int, y: int) -> None:
            _ = (x, y)
            if queue:
                adb.set_current_frame(queue.popleft())

        adb.add_box_transition(1000, 1000, 1080, 1150, callback=on_right_arrow_tap)

        dokkandb = DokkanDBClient(cache_dir=tmpdir)
        dokkandb.get_cards_catalog = lambda: catalog  # type: ignore[assignment]
        syncer = DokkanSyncer(cache_dir=tmpdir)
        syncer.sync_catalog = lambda **_kw: catalog  # type: ignore[assignment]

        scanner = BoxScannerTask(
            adb=adb,  # type: ignore[arg-type]
            vision=Vision(),
            config={},
            dokkandb=dokkandb,
            syncer=syncer,
            output_file=out_file,
        )

        fast_ocr = FastSyntheticOCR(card_defs)
        scanner._ocr = fast_ocr  # type: ignore[assignment]
        if hasattr(scanner, "_banner_extractor"):
            scanner._banner_extractor.ocr = fast_ocr  # type: ignore[attr-defined]
        if hasattr(scanner, "_detail_evaluator"):
            scanner._detail_evaluator.ocr = fast_ocr  # type: ignore[attr-defined]

        scanner._init_catalog()

        if not hasattr(scanner, "_extract_banner_text"):
            scanner._extract_banner_text = lambda img: scanner_module.extract_banner_text(
                img, ocr=scanner._ocr
            )  # type: ignore[attr-defined]
        if not hasattr(scanner, "_extract_element_badge"):
            scanner._extract_element_badge = lambda img: scanner_module.extract_element_badge(
                img, ocr=scanner._ocr
            )  # type: ignore[attr-defined]
        if not hasattr(scanner, "_match_card_candidate"):
            scanner._match_card_candidate = lambda txt, detected_class=None, detected_elem=None: (  # type: ignore[attr-defined]
                scanner_module.CatalogMatcher(scanner._catalog).match_card_candidate(
                    txt, detected_class=detected_class, detected_elem=detected_elem
                )
            )
        if not hasattr(scanner, "_extract_level_and_sa"):
            scanner._extract_level_and_sa = lambda img, rarity=4: (
                scanner_module.extract_level_and_sa(  # type: ignore[attr-defined]
                    img, ocr=scanner._ocr, rarity=rarity
                )
            )
        if not hasattr(scanner, "_extract_potential_and_rainbow"):
            scanner._extract_potential_and_rainbow = (  # type: ignore[attr-defined]
                lambda img, curr_sa=10, max_sa=10: scanner_module.extract_potential_and_rainbow(
                    img, ocr=scanner._ocr, curr_sa=curr_sa, max_sa=max_sa
                )
            )
        if not hasattr(scanner, "_stitch_marquee_text"):
            scanner._stitch_marquee_text = staticmethod(scanner_module.stitch_marquee_text)  # type: ignore[attr-defined]

        start_time = time.time()
        with patch("time.sleep", return_value=None):
            curr_screen = adb.screencap()
            for idx in range(1, 4):
                cand, score, is_rainbow, is_eza, pot_pct = scanner_module.scan_detail_screen(
                    scanner, curr_screen
                )
                scanner_module.register_card(
                    scanner.session_ctx,
                    cand,
                    score=score,
                    crop=None,
                    swipe_page=0,
                    grid_slot=idx - 1,
                    is_rainbow=is_rainbow,
                    is_eza=is_eza,
                    potential_percent=pot_pct,
                )
                if idx < 3:
                    curr_screen, advanced = scanner_module.advance_to_next_card(
                        scanner, curr_screen, current_card_id=None
                    )
                    assert advanced is True, f"Failed to advance from card #{idx}"

            scanner._save_box(enrich=False)

        duration = time.time() - start_time
        assert duration < 10.0

        assert Path(out_file).exists()
        with open(out_file, encoding="utf-8") as f:
            box_data = json.load(f)

        assert "updated_at" in box_data
        assert box_data["total_cards"] == 3
        assert box_data["unique_cards"] == 2

        cards = box_data["cards"]
        assert len(cards) == 2
