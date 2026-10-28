"""Fast in-memory unit tests for box scanner components.

Tests:
1. Card deduplication and anti-collision logic (adjacent vs non-adjacent copies).
2. Title and subname normalization, including Growth prefix stripping.
3. Rainbow star recognition via HSV facet detection.
4. DokkanSyncer caching, chunk processing, and lazy box detail syncing completely in-memory.
"""

from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import numpy as np
from tests.harness.fake_dokkandb import fake_dokkandb_requests_get

from dokkan_eza_link_farmer.ai.syncer import DokkanSyncer
from dokkan_eza_link_farmer.automation.tasks.box_scanner import (
    BoxScannerTask,
    _normalize_title,
)


class TestTitleNormalizationAndTextMatching:
    """Validates title normalization and OCR prefix stripping."""

    def test_normalize_title(self) -> None:
        assert _normalize_title("Risky Covering Fire") == "riskycoveringfire"
        assert _normalize_title("Time's Guidance!") == "timesguidance"
        assert _normalize_title("Power-Taken  From Others") == "powertakenfromothers"
        assert _normalize_title("Super Saiyan Goku (Angel)") == "supersaiyangokuangel"

    def test_growth_prefix_cleanup(self) -> None:
        scanner = BoxScannerTask(adb=MagicMock(), vision=MagicMock(), config={})
        scanner._subname_index = {
            _normalize_title("Inescapable Justice"): {
                "id": 1020011,
                "name": "Toppo",
                "subname": "Inescapable Justice",
            },
            _normalize_title("Courage to Confront Evil"): {
                "id": 1029621,
                "name": "Videl",
                "subname": "Courage to Confront Evil",
            },
        }

        # Stripping Growth variants
        m1 = scanner._match_card_by_text("Growth Inescapable Justice")
        assert m1 is not None and m1["id"] == 1020011

        m2 = scanner._match_card_by_text("owth - Courage to Confront Evil")
        assert m2 is not None and m2["id"] == 1029621

        m3 = scanner._match_card_by_text("wth. Inescapable Justice")
        assert m3 is not None and m3["id"] == 1020011


class TestRainbowStarDetection:
    """Validates HSV sparkling facet mask detection for rainbow 100% potential."""

    def test_rainbow_star_detection(self) -> None:
        scanner = BoxScannerTask(adb=MagicMock(), vision=MagicMock(), config={})

        # Blank non-rainbow crop
        black_crop = np.zeros((200, 200, 3), dtype=np.uint8)
        assert scanner._detect_rainbow_star(black_crop) is False

        # Cyan facets placed in bottom-right star corner (y: 100..160, x: 130..190)
        rainbow_crop = np.zeros((200, 200, 3), dtype=np.uint8)
        rainbow_crop[100:160, 130:190] = [255, 255, 0]  # Cyan in BGR
        assert scanner._detect_rainbow_star(rainbow_crop) is True


class TestCardDeduplicationAndAntiCollision:
    """Validates duplicate card registration and distance-based anti-collision."""

    def test_overlap_duplicate_protection(self) -> None:
        scanner = BoxScannerTask(adb=MagicMock(), vision=MagicMock(), config={})
        scanner._recently_scanned_positions = {}
        scanner.scanned_cards = {}

        cand = {"card_id": 1020281, "name": "Tien", "subname": "Risky Covering Fire", "rarity": 4}
        crop = np.zeros((100, 100, 3), dtype=np.uint8)

        # Initial scan at row cy=858
        scanner._register_card(cand, score=0.92, crop=crop, cy=858.0, cx=325)
        assert scanner.scanned_cards[1020281]["copies"] == 1

        # Re-scan at overlapping row cy=870 (distance < 180px) -> copies remain 1
        scanner._register_card(cand, score=0.91, crop=crop, cy=870.0, cx=325)
        assert scanner.scanned_cards[1020281]["copies"] == 1

        # Scan distinct separate copy at bottom row cy=1626 (distance > 180px) -> copies = 2
        scanner._register_card(cand, score=0.89, crop=crop, cy=1626.0, cx=325)
        assert scanner.scanned_cards[1020281]["copies"] == 2

    def test_anti_collision_dupe_mandatory_adjacency(self) -> None:
        scanner = BoxScannerTask(
            adb=MagicMock(), vision=MagicMock(), config={"pure_grid_mode": False}
        )
        crop = np.zeros((100, 100, 3), dtype=np.uint8)

        card_a = {"card_id": 1001, "name": "Goku A", "rarity": 4}
        card_b = {"card_id": 2002, "name": "Vegeta B", "rarity": 4}

        # Slot 1 registers Card A (New)
        assert scanner._register_card(card_a, score=0.90, crop=crop, cy=600.0, cx=110) is True
        assert scanner.scanned_cards[1001]["copies"] == 1

        # Slot 2 adjacent registers Card A (Dupe)
        assert scanner._register_card(card_a, score=0.88, crop=crop, cy=600.0, cx=325) is True
        assert scanner.scanned_cards[1001]["copies"] == 2

        # Slot 3 is Card B (New)
        assert scanner._register_card(card_b, score=0.91, crop=crop, cy=600.0, cx=540) is True
        assert scanner.scanned_cards[2002]["copies"] == 1

        # Slot 4 non-adjacent duplicate of Card A is rejected
        assert scanner._register_card(card_a, score=0.89, crop=crop, cy=600.0, cx=755) is False
        assert scanner.scanned_cards[1001]["copies"] == 2


class TestDokkanSyncerInMemory:
    """Validates in-memory DokkanSyncer synchronization and caching."""

    def test_syncer_catalog_and_lazy_box_details(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            syncer = DokkanSyncer(cache_dir=tmpdir)

            with patch("requests.get", side_effect=fake_dokkandb_requests_get):
                catalog = syncer.sync_catalog(force=True)
                assert len(catalog) == 4
                ids = [c["id"] for c in catalog]
                assert 1001 in ids
                assert 1002 in ids

                # Lazy details fetching for box
                box_file = os.path.join(tmpdir, "user_box.json")
                with open(box_file, "w", encoding="utf-8") as f:
                    json.dump({"cards": [{"id": 1001, "is_rainbow": True, "is_eza": True}]}, f)

                cards = syncer.sync_user_box_details(user_box_file=box_file, concurrency=1)
                assert len(cards) == 1
                assert cards[0].id == 1001
                assert cards[0].is_rainbow is True
                assert cards[0].is_eza is True

    def test_syncer_429_retry_and_backoff(self) -> None:
        """Validates that HTTP 429 rate-limiting triggers exponential backoff and retries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            syncer = DokkanSyncer(cache_dir=tmpdir)
            call_count = 0

            def mock_get(_url: str, **_kwargs):
                nonlocal call_count
                call_count += 1
                mock_resp = MagicMock()
                if call_count < 3:
                    mock_resp.status_code = 429
                    mock_resp.headers = {"Retry-After": "0"}
                    return mock_resp
                else:
                    mock_resp.status_code = 200
                    mock_resp.json.return_value = [
                        {"id": 5001, "name": "Recovered Goku", "element": 1}
                    ]
                    return mock_resp

            with patch("requests.get", side_effect=mock_get), patch("time.sleep") as mock_sleep:
                card = syncer.fetch_card_detail_sync(5001, force=True)
                assert card is not None
                assert card["id"] == 5001
                assert call_count == 3
                assert mock_sleep.call_count >= 2

    def test_syncer_429_exhausted_falls_back_to_cache(self) -> None:
        """Validates that if retries are exhausted on 429, it gracefully falls back to existing cache."""
        with tempfile.TemporaryDirectory() as tmpdir:
            syncer = DokkanSyncer(cache_dir=tmpdir)
            cache_file = os.path.join(syncer.cards_dir, "card_5002_glb.json")
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump({"id": 5002, "name": "Cached Vegeta", "element": 2}, f)

            def mock_get_429(_url: str, **_kwargs):
                mock_resp = MagicMock()
                mock_resp.status_code = 429
                mock_resp.headers = {"Retry-After": "0"}
                return mock_resp

            with patch("requests.get", side_effect=mock_get_429), patch("time.sleep"):
                # force=True would normally try network, but should smoothly fallback to cache on 429
                card = syncer.fetch_card_detail_sync(5002, force=True)
                assert card is not None
                assert card["id"] == 5002
                assert card["name"] == "Cached Vegeta"


class TestBoxFilterVerification:
    """Validates Character Box filter enforcement and safe modal interaction."""

    def test_filters_already_active_skips_click(self) -> None:
        from dokkan_eza_link_farmer.automation.scanner.filter_manager import (
            verify_and_enforce_filters,
        )

        task = MagicMock()
        task.adb.screencap.return_value = np.zeros((2400, 1080, 3), dtype=np.uint8)
        task.adb.get_screen_size.return_value = (1080, 2400)
        task.vision.find_template.side_effect = lambda _s, t, **_kw: (
            (850, 1825, 0.99) if "tag_" in t else None
        )

        res = verify_and_enforce_filters(task)
        assert res is True
        task.adb.tap.assert_not_called()

    def test_filter_popup_fails_to_open_aborts_without_misclick(self) -> None:
        from dokkan_eza_link_farmer.automation.scanner.filter_manager import (
            verify_and_enforce_filters,
        )

        task = MagicMock()
        task.adb.screencap.return_value = np.zeros((2400, 1080, 3), dtype=np.uint8)
        task.adb.get_screen_size.return_value = (1080, 2400)
        task.vision.find_template.return_value = None
        task.vision.find_yellow_sort_button.return_value = (850, 1825)
        task.vision.is_filter_dialog_open.return_value = False

        res = verify_and_enforce_filters(task)
        assert res is False
        for call_args in task.adb.tap.call_args_list:
            x, y = call_args[0][0], call_args[0][1]
            assert (x, y) == (850, 1825)

    def test_filter_popup_opens_and_enforces_ur_lr(self) -> None:
        from dokkan_eza_link_farmer.automation.scanner.filter_manager import (
            verify_and_enforce_filters,
        )

        task = MagicMock()
        task.adb.screencap.return_value = np.zeros((2400, 1080, 3), dtype=np.uint8)
        task.adb.get_screen_size.return_value = (1080, 2400)
        task.vision.find_yellow_sort_button.return_value = (850, 1825)
        task.vision.is_filter_dialog_open.return_value = True

        def mock_find_template(_s, name, **_kw):
            if "button_ok" in name:
                return (540, 2020, 0.95)
            if "btn_ur_unselected" in name:
                return (755, 1530, 0.95)
            if "btn_lr_unselected" in name:
                return (910, 1530, 0.95)
            return None

        task.vision.find_template.side_effect = mock_find_template
        task.vision.is_filter_ur_selected.return_value = False
        task.vision.is_filter_lr_selected.return_value = False
        task.vision.is_filter_released_selected.return_value = True
        task.vision.get_filter_ur_coords.return_value = (755, 1530)
        task.vision.get_filter_lr_coords.return_value = (910, 1530)

        res = verify_and_enforce_filters(task)
        assert res is True
        tapped_coords = [(c[0][0], c[0][1]) for c in task.adb.tap.call_args_list]
        assert (850, 1825) in tapped_coords
        assert (755, 1530) in tapped_coords
        assert (910, 1530) in tapped_coords
        assert (540, 2020) in tapped_coords
