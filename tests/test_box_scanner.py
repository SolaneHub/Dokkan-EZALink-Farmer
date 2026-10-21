from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import MagicMock

import numpy as np

from dokkan_eza_link_farmer.automation.tasks.box_scanner import (
    BoxScannerTask,
    _normalize_title,
)
from dokkan_eza_link_farmer.integrations.dokkandb_client import DokkanDBClient


class TestBoxScanner:
    """Unified test suite for the autonomous Character Box Scanner and DokkanDB integration."""

    def test_normalize_title(self):
        """Tests text normalization for card subnames."""
        assert _normalize_title("Risky Covering Fire") == "riskycoveringfire"
        assert _normalize_title("Time's Guidance!") == "timesguidance"
        assert _normalize_title("Power-Taken  From Others") == "powertakenfromothers"
        assert _normalize_title("Super Saiyan Goku (Angel)") == "supersaiyangokuangel"

    def test_box_save_and_load(self):
        """Tests saving and incremental loading of scanned card data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = os.path.join(tmpdir, "box.json")
            adb = MagicMock()
            vision = MagicMock()
            config = {}
            dokkandb = MagicMock()
            dokkandb.get_cards_catalog.return_value = [
                {
                    "id": 1020281,
                    "name": "Tien",
                    "subname": "Risky Covering Fire",
                    "rarity": 4,
                    "element": 14,
                },
                {
                    "id": 1020531,
                    "name": "Majin Buu",
                    "subname": "Power Taken From Others",
                    "rarity": 4,
                    "element": 20,
                },
            ]

            scanner = BoxScannerTask(
                adb=adb,
                vision=vision,
                config=config,
                dokkandb=dokkandb,
                output_file=out_file,
            )
            scanner._init_catalog()

            # Test text matching
            match1 = scanner._match_card_by_text("Risky Covering Fire")
            assert match1 is not None
            assert match1["id"] == 1020281

            # Fuzzy match
            match2 = scanner._match_card_by_text("Taken From Others")
            assert match2 is not None
            assert match2["id"] == 1020531

            # Test save
            scanner.scanned_cards[1020281] = {
                "id": 1020281,
                "name": "Tien",
                "subname": "Risky Covering Fire",
                "rarity": 4,
                "is_rainbow": True,
                "copies": 1,
            }
            scanner._save_box()

            # Test load into a new scanner instance
            scanner2 = BoxScannerTask(
                adb=adb,
                vision=vision,
                config=config,
                dokkandb=dokkandb,
                output_file=out_file,
            )
            assert 1020281 in scanner2.scanned_cards
            assert scanner2.scanned_cards[1020281]["name"] == "Tien"
            assert scanner2.scanned_cards[1020281]["is_rainbow"] is True

    def test_rainbow_star_detection(self):
        """Tests 100% Hidden Potential rainbow star recognition via HSV sparkling facet detection."""
        adb = MagicMock()
        vision = MagicMock()
        with tempfile.TemporaryDirectory() as tmpdir:
            scanner = BoxScannerTask(
                adb=adb,
                vision=vision,
                config={},
                output_file=os.path.join(tmpdir, "box.json"),
            )

            # Blank non-rainbow crop
            black_crop = np.zeros((200, 200, 3), dtype=np.uint8)
            assert scanner._detect_rainbow_star(black_crop) is False

            # Synthetic rainbow crop with cyan facets placed in bottom-right star corner (y: 100..160, x: 130..190)
            rainbow_crop = np.zeros((200, 200, 3), dtype=np.uint8)
            # Pure cyan in BGR: B=255, G=255, R=0
            rainbow_crop[100:160, 130:190] = [255, 255, 0]
            assert scanner._detect_rainbow_star(rainbow_crop) is True

    def test_vertical_shift_tracking(self):
        """Tests multi-anchor visual vertical shift calculation between consecutive frames."""
        adb = MagicMock()
        vision = MagicMock()
        with tempfile.TemporaryDirectory() as tmpdir:
            scanner = BoxScannerTask(
                adb=adb,
                vision=vision,
                config={},
                output_file=os.path.join(tmpdir, "box.json"),
            )

            # Create two 2400x1080 frames with a known vertical shift of 759px (3 rows)
            h, w = 2400, 1080
            prev_img = np.zeros((h, w, 3), dtype=np.uint8)
            # Draw distinctive visual patterns at row centers
            col_xs = [int(w * r) for r in scanner.COL_RATIOS]
            for r_y in [605, 858, 1111, 1364, 1617]:
                for cx in col_xs:
                    prev_img[r_y - 30 : r_y + 30, cx - 30 : cx + 30] = np.random.randint(
                        50, 250, (60, 60, 3), dtype=np.uint8
                    )

            shift_true = 759
            curr_img = np.zeros_like(prev_img)
            curr_img[: h - shift_true, :] = prev_img[shift_true:, :]

            shift_detected = scanner._track_vertical_shift(prev_img, curr_img, last_cy=1617.0)
            assert shift_detected is not None
            assert abs(shift_detected - shift_true) <= 5.0

    def test_overlap_duplicate_protection(self):
        """Tests that scanning an overlapping row does not artificially increment copies."""
        adb = MagicMock()
        vision = MagicMock()
        with tempfile.TemporaryDirectory() as tmpdir:
            scanner = BoxScannerTask(
                adb=adb,
                vision=vision,
                config={},
                output_file=os.path.join(tmpdir, "box.json"),
            )
            scanner._recently_scanned_positions = {}
            scanner.scanned_cards = {}

            cand = {
                "card_id": 1020281,
                "name": "Tien",
                "subname": "Risky Covering Fire",
                "rarity": 4,
            }
            dummy_crop = np.zeros((100, 100, 3), dtype=np.uint8)

            # First scan at row cy=858
            scanner._register_card(cand, score=0.92, crop=dummy_crop, cy=858.0, cx=325)
            assert 1020281 in scanner.scanned_cards
            assert scanner.scanned_cards[1020281]["copies"] == 1

            # Re-scan at overlapping row cy=870 (distance < 180px)
            scanner._register_card(cand, score=0.91, crop=dummy_crop, cy=870.0, cx=325)
            assert scanner.scanned_cards[1020281]["copies"] == 1  # Copies MUST remain 1

            # Scan distinct separate copy at bottom row cy=1626 (distance > 180px)
            scanner._register_card(cand, score=0.89, crop=dummy_crop, cy=1626.0, cx=325)
            assert scanner.scanned_cards[1020281]["copies"] == 2  # Genuine dupe incremented

    def test_dokkandb_linking_partners(self):
        """Tests algorithmic calculation of optimal in-box linking partners from DokkanDB data."""
        dokkandb = DokkanDBClient()
        dokkandb.get_cards_catalog = MagicMock(
            return_value=[
                {
                    "id": 1001,
                    "name": "Goku",
                    "subname": "Hero",
                    "link_ids": [1, 2, 3],
                    "category_ids": [10, 20],
                },
                {
                    "id": 1002,
                    "name": "Vegeta",
                    "subname": "Rival",
                    "link_ids": [1, 2, 4],
                    "category_ids": [10, 30],
                },
                {
                    "id": 1003,
                    "name": "Frieza",
                    "subname": "Emperor",
                    "link_ids": [5, 6, 7],
                    "category_ids": [40],
                },
            ]
        )
        dokkandb.get_links = MagicMock(
            return_value=[
                {"id": 1, "name": "Super Saiyan"},
                {"id": 2, "name": "Prepared for Battle"},
                {"id": 3, "name": "Kamehameha"},
                {"id": 4, "name": "Royal Lineage"},
            ]
        )

        partners = dokkandb.get_best_linking_partners(1001, pool_card_ids=[1001, 1002, 1003])
        assert len(partners) >= 1
        best = partners[0]
        assert best["card_id"] == 1002
        assert best["shared_links_count"] == 2
        assert "Super Saiyan" in best["shared_links"]
        assert "Prepared for Battle" in best["shared_links"]
        assert best["shared_categories_count"] == 1

    def test_dokkandb_enrich_card_and_box(self):
        """Tests full metadata enrichment of scanned cards with categories, leader/passive skills, and best partners."""
        dokkandb = DokkanDBClient()
        dokkandb.get_card = MagicMock(
            return_value={
                "id": 1001,
                "name": "Goku",
                "subname": "Hero",
                "rarity": 4,
                "element": 12,
                "link_ids": [1, 2],
                "category_names": ["Pure Saiyans", "Goku's Family"],
                "eza_leader_skill": "All Types Ki +3, Stats +120%",
                "eza_passive_skill_description": "ATK & DEF +150%",
            }
        )
        dokkandb.get_links = MagicMock(
            return_value=[
                {"id": 1, "name": "Super Saiyan"},
                {"id": 2, "name": "Prepared for Battle"},
            ]
        )
        dokkandb.get_best_linking_partners = MagicMock(
            return_value=[{"card_id": 1002, "name": "Vegeta", "shared_links_count": 2}]
        )

        raw_card = {"id": 1001, "is_rainbow": True}
        enriched = dokkandb.enrich_card(raw_card)
        assert enriched["name"] == "Goku"
        assert enriched["links"] == ["Super Saiyan", "Prepared for Battle"]
        assert enriched["categories"] == ["Pure Saiyans", "Goku's Family"]
        assert "All Types" in enriched["leader_skill"]
        assert "ATK & DEF" in enriched["passive_skill"]

        box = dokkandb.enrich_box([raw_card])
        assert len(box) == 1
        assert "best_in_box_partners" in box[0]

    def test_default_user_box_path_and_coordinates(self):
        """Tests that BoxScanner defaults to ~/.dokkan-farmer/cache/user_box.json and tracks swipe_page + grid_slot."""
        from dokkan_eza_link_farmer.automation.tasks.box_scanner import DEFAULT_USER_BOX_PATH

        assert DEFAULT_USER_BOX_PATH.endswith(
            os.path.join(".dokkan-farmer", "cache", "user_box.json")
        )

        adb = MagicMock()
        vision = MagicMock()
        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = os.path.join(tmpdir, "user_box.json")
            scanner = BoxScannerTask(adb=adb, vision=vision, config={}, output_file=out_file)

            cand = {"card_id": 1028731, "name": "LR Beast Gohan", "rarity": 5, "element": 13}
            crop = np.zeros((100, 100, 3), dtype=np.uint8)

            # Register with swipe_page=2, grid_slot=14 (3rd row, 5th column)
            scanner._register_card(
                cand, score=0.95, crop=crop, cy=1111.0, cx=970, swipe_page=2, grid_slot=14
            )

            assert 1028731 in scanner.scanned_cards
            saved_entry = scanner.scanned_cards[1028731]
            assert saved_entry["swipe_page"] == 2
            assert saved_entry["grid_slot"] == 14

            # Save and verify JSON contents
            scanner._save_box(enrich=False)
            with open(out_file, encoding="utf-8") as f:
                data = json.load(f)

            assert "cards" in data
            assert len(data["cards"]) == 1
            card_data = data["cards"][0]
            assert card_data["id"] == 1028731
            assert card_data["swipe_page"] == 2
            assert card_data["grid_slot"] == 14

    def test_match_slot_thumbnail_with_delta_and_ocr_fallback(self):
        """Tests thumbnail matching with delta margin and RapidOCR fallback when score < 0.72 or delta < 0.05."""
        adb = MagicMock()
        adb.get_screen_size.return_value = (1080, 2400)
        adb.screencap.return_value = np.zeros((2400, 1080, 3), dtype=np.uint8)
        vision = MagicMock()
        scanner = BoxScannerTask(adb=adb, vision=vision, config={"pure_grid_mode": False})

        # Mock fallback OCR
        scanner._read_card_title_from_screen = MagicMock(return_value="Subname From OCR")
        scanner._match_card_by_text = MagicMock(
            return_value={"id": 1025551, "name": "Goku", "subname": "Subname From OCR", "rarity": 5}
        )

        res = scanner._execute_ocr_fallback(cx=325, cy=858)
        assert res is not None
        assert res["card_id"] == 1025551
        assert res["name"] == "Goku"

    def test_ensure_box_filters(self):
        """Tests checking in-game filters (UR, LR, Sort: Released) via vision templates."""
        adb = MagicMock()
        vision = MagicMock()
        vision.find_template.return_value = (500, 500)

        scanner = BoxScannerTask(adb=adb, vision=vision, config={})
        assert scanner.ensure_box_filters() is True

    def test_box_scanner_uses_syncer_and_downloads_thumbs(self):
        """Verifies that BoxScanner uses DokkanSyncer to sync the 2-chunk catalog and download thumbnails."""
        adb = MagicMock()
        vision = MagicMock()
        syncer = MagicMock()
        syncer.sync_catalog.return_value = [
            {"id": 1012901, "name": "LR Gogeta", "subname": "Fusion", "rarity": 5, "element": 14}
        ]
        syncer.sync_thumbnails.return_value = 1

        with tempfile.TemporaryDirectory() as tmpdir:
            syncer.cache_dir = os.path.join(tmpdir, "cache")
            scanner = BoxScannerTask(
                adb=adb,
                vision=vision,
                config={},
                syncer=syncer,
                output_file=os.path.join(tmpdir, "user_box.json"),
            )
            scanner._init_catalog()
            assert syncer.sync_catalog.called
            assert len(scanner._catalog) == 1
            assert 1012901 in scanner._id_index

    def test_anti_collision_dupe_mandatory_adjacency(self):
        """Verifies that non-adjacent duplicates are rejected as false collisions."""
        adb = MagicMock()
        vision = MagicMock()
        scanner = BoxScannerTask(adb=adb, vision=vision, config={"pure_grid_mode": False})
        dummy_crop = np.zeros((100, 100, 3), dtype=np.uint8)

        card_a = {"card_id": 1001, "name": "Goku A", "rarity": 4}
        card_b = {"card_id": 2002, "name": "Vegeta B", "rarity": 4}
        card_c = {"card_id": 3003, "name": "Trunks C", "rarity": 4}

        # 1. Slot 1 registers Card A (New)
        ok1 = scanner._register_card(card_a, score=0.90, crop=dummy_crop, cy=600.0, cx=110)
        assert ok1 is True
        assert scanner.scanned_cards[1001]["copies"] == 1
        assert scanner._last_registered_card_id == 1001

        # 2. Slot 2 is adjacent: registers Card A (Dupe)
        ok2 = scanner._register_card(card_a, score=0.88, crop=dummy_crop, cy=600.0, cx=325)
        assert ok2 is True
        assert scanner.scanned_cards[1001]["copies"] == 2
        assert scanner._last_registered_card_id == 1001

        # 3. Slot 3 is Card B (New)
        ok3 = scanner._register_card(card_b, score=0.91, crop=dummy_crop, cy=600.0, cx=540)
        assert ok3 is True
        assert scanner.scanned_cards[2002]["copies"] == 1
        assert scanner._last_registered_card_id == 2002

        # 4. Direct non-adjacent DUPE registration of Card A is rejected
        ok4 = scanner._register_card(card_a, score=0.89, crop=dummy_crop, cy=600.0, cx=755)
        assert ok4 is False
        assert scanner.scanned_cards[1001]["copies"] == 2  # Copies NOT incremented

        # 5. Test _match_row_with_alignment anti-collision with candidate 2 selection
        grid_frame = np.zeros((2400, 1080, 3), dtype=np.uint8)
        # Mock slot matcher to return Card A (seen non-adjacent) as cand1
        scanner._match_slot_thumbnail_with_delta = MagicMock(
            return_value=(card_a, 0.85, 0.10)
        )
        # Mock second candidate to return Card C (not seen)
        scanner._get_second_candidate = MagicMock(return_value=(card_c, 0.78))

        _, row_res = scanner._match_row_with_alignment(
            grid_frame, cy=600.0, col_xs=[755], half_w=95, half_h=125
        )
        matched_cand, matched_score, _, _, _ = row_res[0]
        assert matched_cand["card_id"] == 3003  # Candidate 2 selected!
        assert matched_score == 0.78

    def test_screen_diff_computation(self):
        """Tests pixel difference MSE / MAE calculation for fine-scroll stop detection."""
        img1 = np.ones((2400, 1080, 3), dtype=np.uint8) * 100
        img2 = np.ones((2400, 1080, 3), dtype=np.uint8) * 100
        assert BoxScannerTask._compute_screen_diff(img1, img2) == 0.0

        img3 = np.ones((2400, 1080, 3), dtype=np.uint8) * 150
        diff = BoxScannerTask._compute_screen_diff(img1, img3)
        assert abs(diff - 50.0) < 1.0

        assert BoxScannerTask._compute_screen_diff(None, img2) == 999.0

    def test_ensure_box_filters_include_ssr(self):
        """Tests that full box scan (include_ssr=True) requires only Sort: Released."""
        adb = MagicMock()
        vision = MagicMock()
        vision.find_template.side_effect = lambda _screen, tmpl, **_kw: (
            (500, 500) if "tag_sort_released" in tmpl else None
        )
        vision.is_sort_released.return_value = True

        scanner = BoxScannerTask(adb=adb, vision=vision, config={"include_ssr": True})
        assert scanner.include_ssr is True
        assert scanner.ensure_box_filters() is True
