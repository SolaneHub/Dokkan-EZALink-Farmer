from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

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

    def test_dokkandb_enrich_card_with_transformations(self):
        """Verifies that enrich_card extracts transformations (standby, active skill, transforms) into card metadata."""
        dokkandb = DokkanDBClient()
        dokkandb.get_card = MagicMock(
            return_value={
                "id": 1025551,
                "name": "Super Saiyan Goku & Super Saiyan Vegeta",
                "rarity": 5,
                "element": 12,
                "transformation_data": [
                    {
                        "id": 4025551,
                        "name": "Super Vegito",
                        "element": 12,
                        "link_ids": [1, 2],
                        "passive_skill_description": "Counters normal attacks with tremendous power",
                        "special_descriptions": ["Causes colossal damage to enemy"],
                        "min_turn": 4,
                    }
                ],
            }
        )
        dokkandb.get_links = MagicMock(return_value=[])

        raw_card = {"id": 1025551, "is_rainbow": True}
        enriched = dokkandb.enrich_card(raw_card)
        assert "transformations" in enriched
        assert len(enriched["transformations"]) == 1
        trans = enriched["transformations"][0]
        assert trans["form_id"] == 4025551
        assert trans["form_name"] == "Super Vegito"
        assert trans["min_turn"] == 4
        assert "Counters normal attacks" in trans["passive_skill_text"]

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

    def test_ensure_box_filters(self):
        """Tests checking in-game filters when tag_filter_on is already present."""
        adb = MagicMock()
        vision = MagicMock()
        vision.find_template.return_value = (500, 500)

        scanner = BoxScannerTask(adb=adb, vision=vision, config={})
        assert scanner.ensure_box_filters() is True
        # Since tag_filter_on is found, popup shouldn't need to be opened
        assert adb.tap.call_count == 0

    def test_ensure_box_filters_popup_activation(self):
        """Tests opening popup and activating UR/LR when tag_filter_on is not found."""
        adb = MagicMock()
        adb.get_screen_size.return_value = (1080, 2400)
        vision = MagicMock()

        # Simulate: tag_filter_on is None on grid, UR/LR unselected in popup, button_ok present
        def mock_find_template(_screen, template_name, **_kwargs):
            if "tag_filter_on" in template_name:
                return None
            if "tag_sort_released" in template_name:
                return (800, 200)
            if "btn_ur_selected" in template_name:
                return None
            if "btn_ur_unselected" in template_name:
                return (756, 1530)
            if "btn_lr_selected" in template_name:
                return None
            if "btn_lr_unselected" in template_name:
                return (907, 1530)
            if "button_ok" in template_name:
                return (540, 2040)
            return None

        vision.find_template.side_effect = mock_find_template

        scanner = BoxScannerTask(adb=adb, vision=vision, config={})
        res = scanner.ensure_box_filters()
        assert res is True
        # Tap calls: 1 to open filter popup, 1 for UR, 1 for LR, 1 for OK button = 4 taps
        assert adb.tap.call_count == 4

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
        """Tests that full box scan checks filters when filter_on tag is missing."""
        adb = MagicMock()
        vision = MagicMock()
        vision.find_template.side_effect = lambda _screen, tmpl, **_kw: (
            (500, 500) if "tag_filter_on" in tmpl or "tag_sort_released" in tmpl else None
        )
        vision.is_sort_released.return_value = True

        scanner = BoxScannerTask(adb=adb, vision=vision, config={"include_ssr": True})
        assert scanner.include_ssr is True
        assert scanner.ensure_box_filters() is True

    def test_default_box_scan_log_path(self):
        """Verifies default log path is ~/.dokkan-farmer/box_scan.log."""
        from dokkan_eza_link_farmer.automation.tasks.box_scanner import DEFAULT_BOX_SCAN_LOG_PATH

        assert DEFAULT_BOX_SCAN_LOG_PATH.endswith(os.path.join(".dokkan-farmer", "box_scan.log"))

        adb = MagicMock()
        vision = MagicMock()
        scanner = BoxScannerTask(adb=adb, vision=vision, config={})
        assert scanner.log_file == DEFAULT_BOX_SCAN_LOG_PATH
        scanner._close_file_logger()

    def test_box_scan_file_logging(self):
        """Verifies that debug and info logs during box scanning are written to the log file."""
        import logging

        adb = MagicMock()
        vision = MagicMock()
        with tempfile.TemporaryDirectory() as tmpdir:
            test_log = os.path.join(tmpdir, "test_box_scan.log")
            scanner = BoxScannerTask(
                adb=adb,
                vision=vision,
                config={},
                log_file=test_log,
            )

            scanner.log("Registration message for box scanner test")
            scanner_logger = logging.getLogger(
                "dokkan_eza_link_farmer.automation.tasks.box_scanner"
            )
            scanner_logger.debug("Detailed OCR debug trace information")

            scanner._close_file_logger()

            assert os.path.exists(test_log)
            with open(test_log, encoding="utf-8") as f:
                content = f.read()

            assert "Registration message for box scanner test" in content
            assert "Detailed OCR debug trace information" in content
            assert "[INFO   ]" in content
            assert "[DEBUG  ]" in content

    def test_box_scan_run_session_logging_and_cleanup(self):
        """Verifies session header and footer are recorded in log file during run()."""
        adb = MagicMock()
        adb.get_screen_size.return_value = (1080, 2400)
        adb.screencap.return_value = np.zeros((2400, 1080, 3), dtype=np.uint8)
        vision = MagicMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            test_log = os.path.join(tmpdir, "session_box_scan.log")
            test_box = os.path.join(tmpdir, "user_box.json")
            scanner = BoxScannerTask(
                adb=adb,
                vision=vision,
                config={},
                output_file=test_box,
                log_file=test_log,
                max_cards_to_scan=1,
            )
            scanner._init_catalog = MagicMock()
            scanner.ensure_box_filters = MagicMock(return_value=True)
            scanner._is_card_details_screen = MagicMock(return_value=True)
            scanner.scroll_to_top = MagicMock()
            scanner._save_box = MagicMock()

            # Execute run; should scan 1 card and stop cleanly
            with patch(
                "dokkan_eza_link_farmer.automation.tasks.box_scanner.scan_detail_screen"
            ) as mock_scan:
                mock_scan.return_value = (
                    {"id": 1001, "name": "Goku", "rarity": 4},
                    0.95,
                    False,
                    False,
                    0,
                )
                scanner.run()

            assert os.path.exists(test_log)
            with open(test_log, encoding="utf-8") as f:
                log_content = f.read()

            assert "Dokkan Box Scanner Session Started" in log_content
            assert "Dokkan Box Scanner Session Ended" in log_content
            assert scanner._file_handler is None

    def test_bot_engine_start_box_scanner_with_log_file(self):
        """Verifies BotEngine.start_box_scanner forwards log_file to BoxScannerTask."""
        from dokkan_eza_link_farmer.core.bot_engine import BotEngine

        engine = BotEngine()
        engine.adb = MagicMock()
        engine.adb.get_screen_size.return_value = (1080, 2400)
        engine.adb.screencap.return_value = np.zeros((2400, 1080, 3), dtype=np.uint8)
        custom_log = "custom_path/box_scan.log"
        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = os.path.join(tmpdir, "box.json")
            ok = engine.start_box_scanner(
                output_file=out_file,
                max_cards_to_scan=10,
                log_file=custom_log,
            )
            assert ok is True
            assert engine.current_task is not None
            assert getattr(engine.current_task, "log_file", None) == custom_log
            engine.stop_task()

    def test_cli_handle_box_scan_interactive_log_argument(self):
        """Verifies TerminalCLI.handle_box_scan_interactive parses --log-file parameter."""
        from dokkan_eza_link_farmer.core.bot_engine import BotEngine
        from dokkan_eza_link_farmer.ui.cli import TerminalCLI

        engine = BotEngine()
        engine.start_box_scanner = MagicMock()
        engine.dokkandb = MagicMock()
        engine.dokkandb.get_user_box_card_ids.return_value = []
        engine.adb = MagicMock()
        engine.adb.is_connected.return_value = True

        cli = TerminalCLI(engine)
        cli.handle_box_scan_interactive(["25", "--log-file", "my_debug.log"])

        engine.start_box_scanner.assert_called_once()
        _, kwargs = engine.start_box_scanner.call_args
        assert kwargs["max_cards_to_scan"] == 25
        assert kwargs["log_file"] == "my_debug.log"

    def test_register_card_eza_and_seza_flags(self):
        """Verifies real calculation of is_eza and is_seza based on DokkanDB catalog data."""
        adb = MagicMock()
        vision = MagicMock()
        scanner = BoxScannerTask(adb=adb, vision=vision, config={})
        crop = np.zeros((50, 50, 3), dtype=np.uint8)

        # 1. Base unit: no EZA data
        scanner._id_index[101] = {
            "id": 101,
            "name": "Base Card",
            "rarity": 4,
        }
        scanner._register_card(
            cand={"card_id": 101, "name": "Base Card"},
            score=0.9,
            crop=crop,
            cy=500.0,
            cx=200,
        )
        assert scanner.scanned_cards[101]["is_eza"] is False
        assert scanner.scanned_cards[101]["is_seza"] is False

        # 2. EZA unit: has eza_leader_skill or passive_skills_rows_eza
        scanner._id_index[102] = {
            "id": 102,
            "name": "EZA Card",
            "rarity": 4,
            "eza_leader_skill": "All Ki +3, Stats +120%",
        }
        scanner._register_card(
            cand={"card_id": 102, "name": "EZA Card"},
            score=0.9,
            crop=crop,
            cy=600.0,
            cx=200,
        )
        assert scanner.scanned_cards[102]["is_eza"] is True
        assert scanner.scanned_cards[102]["is_seza"] is False

        # 3. SEZA unit: has eza_leader_skill_set_id_pre or eza_passive_skill_description_pre
        scanner._id_index[103] = {
            "id": 103,
            "name": "SEZA Card",
            "rarity": 4,
            "eza_leader_skill": "All Ki +3, Stats +120%",
            "eza_passive_skill_description_pre": "Super EZA Passive",
        }
        scanner._register_card(
            cand={"card_id": 103, "name": "SEZA Card"},
            score=0.9,
            crop=crop,
            cy=700.0,
            cx=200,
        )
        assert scanner.scanned_cards[103]["is_eza"] is True
        assert scanner.scanned_cards[103]["is_seza"] is True

    def test_ocr_recognized_dupe_priority_in_register_card(self):
        """Verifies that duplicate cards recognized via OCR bypass the non-adjacent anti-collision rejection."""
        adb = MagicMock()
        vision = MagicMock()
        scanner = BoxScannerTask(adb=adb, vision=vision, config={})
        crop = np.zeros((100, 100, 3), dtype=np.uint8)

        card = {"card_id": 1017301, "name": "Sealas", "from_ocr": True}
        scanner.scanned_cards[1017301] = {
            "id": 1017301,
            "name": "Sealas",
            "copies": 1,
            "swipe_page": 0,
            "grid_slot": 0,
        }
        scanner._last_registered_card_id = 9999  # Different card (non-adjacent)

        # Non-adjacent dupe with from_ocr=True should be accepted and increment copies
        registered = scanner._register_card(card, score=1.0, crop=crop, cy=858.0, cx=325)
        assert registered is True
        assert scanner.scanned_cards[1017301]["copies"] == 2
        assert scanner._last_registered_card_id == 1017301

    def test_match_card_by_text_growth_button_cleanup(self):
        """Tests that text prefixed with 'Growth', 'owth', 'wth', etc. is cleanly stripped before matching."""
        adb = MagicMock()
        vision = MagicMock()
        scanner = BoxScannerTask(adb=adb, vision=vision, config={})
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

        # Match with 'Growth' prefix
        match1 = scanner._match_card_by_text("Growth Inescapable Justice")
        assert match1 is not None
        assert match1["id"] == 1020011

        # Match with 'owth' prefix and separator
        match2 = scanner._match_card_by_text("owth - Courage to Confront Evil")
        assert match2 is not None
        assert match2["id"] == 1029621

        # Match with 'wth'
        match3 = scanner._match_card_by_text("wth. Inescapable Justice")
        assert match3 is not None
        assert match3["id"] == 1020011

    def test_read_card_title_from_screen_crops_growth_button(self):
        """Tests that _read_card_title_from_screen crops out the first 28% of width of rotated crop."""
        adb = MagicMock()
        vision = MagicMock()
        scanner = BoxScannerTask(adb=adb, vision=vision, config={})

        passed_rot = []

        def mock_ocr(img):
            passed_rot.append(img.shape)
            return ([("box", "Courage to Confront Evil", 0.99)], None)

        scanner._ocr = mock_ocr  # type: ignore[assignment]
        dummy_screen = np.zeros((2400, 1080, 3), dtype=np.uint8)
        title = scanner._read_card_title_from_screen(dummy_screen)
        assert title == "Courage to Confront Evil"
        assert len(passed_rot) == 1
        # Original rotated width is TITLE_CROP_Y height = (0.375 - 0.058) * 2400 = 760
        # Cropping first 28% means 760 - int(760 * 0.28) = 760 - 212 = 548
        rot_shape = passed_rot[0]
        assert rot_shape[1] == 548
