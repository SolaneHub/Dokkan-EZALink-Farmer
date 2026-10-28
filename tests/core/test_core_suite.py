from __future__ import annotations

import os
import sys
import unittest.mock
from pathlib import Path

import pytest
from tests.harness.fake_dokkandb import (
    FakeDokkanDBClient,
    fake_dokkandb_requests_get,
)

from dokkan_eza_link_farmer.core.i18n import get_available_languages, get_language, set_language, t
from dokkan_eza_link_farmer.core.system_tools import (
    AppPaths,
    ToolLocator,
    get_config_path,
    get_resource_path,
)


class TestI18n:
    @pytest.fixture(autouse=True)
    def reset_language(self):
        set_language("en")
        yield
        set_language("en")

    def test_available_languages(self):
        langs = get_available_languages()
        assert "en" in langs
        assert "it" in langs

    def test_set_and_get_language(self):
        assert set_language("it")
        assert get_language() == "it"

        assert set_language("en")
        assert get_language() == "en"

    def test_invalid_language_fallback(self):
        res = set_language("nonexistent_lang_code")
        assert not res
        assert get_language() == "en"

    def test_translation_lookup(self):
        set_language("en")
        en_val = t("cli.banner_subtitle")
        assert "CLI & Discord" in en_val
        assert "Chamber of Spirit and Time" in en_val

        set_language("it")
        it_val = t("cli.banner_subtitle")
        assert "CLI & Discord" in it_val
        assert "Stanza dello Spirito e del Tempo" in it_val
        assert en_val != it_val

    def test_parameter_interpolation(self):
        set_language("en")
        interpolated = t("tasks.device_connected", serial="TEST_DEVICE", res="1080x1920")
        assert "TEST_DEVICE" in interpolated
        assert "1080x1920" in interpolated

    def test_missing_key_fallback_to_raw_key(self):
        unknown_key = "some.completely.unknown.nested.key"
        result = t(unknown_key)
        assert result == unknown_key


class TestFakeDokkanDBHarness:
    """Verifies that FakeDokkanDBClient satisfies all interface and catalog requirements in-memory."""

    def test_zbattles_in_memory(self, fake_dokkandb: FakeDokkanDBClient):
        zbattles = fake_dokkandb.get_zbattles()
        assert len(zbattles) > 0
        assert all("name" in z for z in zbattles)
        assert all(z.get("is_currently_open") for z in zbattles)

    def test_events_and_growth_chamber(self, fake_dokkandb: FakeDokkanDBClient):
        events = fake_dokkandb.get_events()
        assert len(events) > 0
        chamber = fake_dokkandb.get_chamber_of_spirit_and_time()
        assert chamber is not None
        assert "chamber of spirit and time" in chamber.get("name", "").lower()
        assert chamber.get("banner_local_path") is not None

    def test_categories_and_links(self, fake_dokkandb: FakeDokkanDBClient):
        cats = fake_dokkandb.get_categories()
        links = fake_dokkandb.get_links()
        assert len(cats) > 0
        assert len(links) > 0
        pure_saiyans = next((c for c in cats if c.get("id") == 1), None)
        assert pure_saiyans is not None

    def test_cards_catalog_and_card_details(self, fake_dokkandb: FakeDokkanDBClient):
        catalog = fake_dokkandb.get_cards_catalog()
        assert len(catalog) > 0
        card_1001 = fake_dokkandb.get_card(1001)
        assert card_1001 is not None
        assert card_1001["id"] == 1001
        assert "Guards" in card_1001.get("passive_skill_description", "")

    def test_search_and_linking_partners(self, fake_dokkandb: FakeDokkanDBClient):
        goku_cards = fake_dokkandb.search_cards("Goku")
        assert len(goku_cards) > 0
        partners = fake_dokkandb.get_best_linking_partners(1001)
        assert isinstance(partners, list)

    def test_http_request_interceptor(self):
        resp_chunk1 = fake_dokkandb_requests_get(
            "https://api.dokkandb.com/api/cards-catalog-with-transformations?chunk=1"
        )
        assert resp_chunk1.status_code == 200
        assert len(resp_chunk1.json()) > 0

        resp_card = fake_dokkandb_requests_get("https://api.dokkandb.com/api/card?code=1001")
        assert resp_card.status_code == 200
        assert resp_card.json()[0]["id"] == 1001

        resp_img = fake_dokkandb_requests_get(
            "https://enaskhebnjtktdfszdcb.supabase.co/storage/v1/object/public/assets/mirror/thumb.png"
        )
        assert resp_img.status_code == 200
        assert len(resp_img.content) > 50

        resp_cat_lead = fake_dokkandb_requests_get(
            "https://api.dokkandb.com/api/category-leaders?code=1"
        )
        assert resp_cat_lead.status_code == 200
        assert len(resp_cat_lead.json()) > 0

    def test_category_leaders_in_memory(self, fake_dokkandb: FakeDokkanDBClient):
        leaders = fake_dokkandb.get_category_leaders(1)
        assert len(leaders) > 0
        leader_map = fake_dokkandb.get_category_leaders_map(1)
        assert 1001 in leader_map
        parsed = leader_map[1001]
        assert parsed["base_boost_pct"] == 170.0
        assert parsed["ki"] == 3
        assert parsed["is_main_leader"] is True

    def test_offline_dokkandb_resilience_fuzz_50_iterations(self):
        """Fast Test Loop: verifies 50 offline fuzz stress iterations for DokkanDB resilience."""
        from tools.fuzz_dokkandb_offline import run_dokkandb_fuzzer

        passed, failed, elapsed = run_dokkandb_fuzzer(num_runs=50, seed=1337, verbose=False)
        assert failed == 0, f"Offline fuzzer detected {failed} failures"
        assert passed == 50
        assert elapsed < 10.0, f"Fuzzing took too long: {elapsed:.2f}s"


class TestSystemTools:
    def test_get_resource_path(self):
        res_path = get_resource_path("templates")
        assert os.path.isdir(res_path), (
            f"Resource path '{res_path}' should be an existing directory"
        )

        locales_path = get_resource_path("locales")
        assert os.path.isdir(locales_path), (
            f"Locales path '{locales_path}' should be an existing directory"
        )

    def test_get_config_path(self):
        cfg_path = get_config_path("config/settings.yaml")
        assert os.path.isfile(cfg_path), (
            f"Config path '{cfg_path}' should resolve to an existing file"
        )

    def test_diagnose_system_structure(self):
        diag = ToolLocator.diagnose_system()
        assert "os" in diag
        assert "platform" in diag
        assert "python_version" in diag
        assert "scrcpy" in diag
        assert "adb" in diag
        assert "found" in diag["adb"]
        assert "found" in diag["scrcpy"]
        assert "install_help" in diag


class TestAppPaths:
    """Verifies AppPaths single source of truth, fallbacks, and env overrides."""

    @pytest.fixture(autouse=True)
    def clean_canonical_box(self):
        canonical = Path("config/box.json")
        if canonical.exists():
            canonical.unlink()
        yield
        if canonical.exists():
            canonical.unlink()

    def test_default_paths(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("DOKKAN_FARMER_HOME", raising=False)
        expected_base = os.path.join(os.path.expanduser("~"), ".dokkan-farmer")

        assert AppPaths.get_base_dir() == expected_base
        assert AppPaths.get_user_box_path() == os.path.join(expected_base, "user_box.json")
        assert AppPaths.get_box_scan_log_path() == os.path.join(expected_base, "box_scan.log")
        assert AppPaths.get_ai_memory_path() == os.path.join(expected_base, "ai_memory.json")
        assert AppPaths.get_cache_dir() == os.path.join(expected_base, "cache")
        assert AppPaths.get_thumbnails_cache_dir() == os.path.join(expected_base, "cache", "thumbs")

    def test_custom_dokkan_farmer_home_override(self, monkeypatch: pytest.MonkeyPatch, tmp_path):
        custom_home = tmp_path / "custom_farmer"
        monkeypatch.setenv("DOKKAN_FARMER_HOME", str(custom_home))

        expected_base = os.path.abspath(str(custom_home))
        assert AppPaths.get_base_dir() == expected_base
        assert AppPaths.get_user_box_path() == os.path.join(expected_base, "user_box.json")
        assert AppPaths.get_box_scan_log_path() == os.path.join(expected_base, "box_scan.log")
        assert AppPaths.get_ai_memory_path() == os.path.join(expected_base, "ai_memory.json")

        expected_cache = os.path.join(expected_base, "cache")
        assert AppPaths.get_cache_dir() == expected_cache
        assert os.path.isdir(expected_cache)

        expected_thumbs = os.path.join(expected_cache, "thumbs")
        assert AppPaths.get_thumbnails_cache_dir() == expected_thumbs
        assert os.path.isdir(expected_thumbs)

    def test_whitespace_dokkan_farmer_home_fallback(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("DOKKAN_FARMER_HOME", "   ")
        expected_base = os.path.join(os.path.expanduser("~"), ".dokkan-farmer")
        assert AppPaths.get_base_dir() == expected_base

    def test_automatic_directory_creation(self, monkeypatch: pytest.MonkeyPatch, tmp_path):
        nested_home = tmp_path / "deep" / "nested" / "farmer_home"
        monkeypatch.setenv("DOKKAN_FARMER_HOME", str(nested_home))

        assert not nested_home.exists()
        cache_dir = AppPaths.get_cache_dir()
        assert os.path.isdir(cache_dir)
        thumbs_dir = AppPaths.get_thumbnails_cache_dir()
        assert os.path.isdir(thumbs_dir)

    def test_trailing_slash_handling(self, monkeypatch: pytest.MonkeyPatch, tmp_path):
        home_with_slash = str(tmp_path / "trailing_slash") + os.sep
        monkeypatch.setenv("DOKKAN_FARMER_HOME", home_with_slash)
        assert AppPaths.get_base_dir() == os.path.abspath(home_with_slash)

    def test_legacy_cache_box_compatibility(self, monkeypatch: pytest.MonkeyPatch, tmp_path):
        from dokkan_eza_link_farmer.automation.scanner.box_storage import resolve_box_path

        monkeypatch.setenv("DOKKAN_FARMER_HOME", str(tmp_path))
        legacy_cache_box = tmp_path / "cache" / "user_box.json"
        legacy_cache_box.parent.mkdir(parents=True, exist_ok=True)
        legacy_cache_box.write_text("{}", encoding="utf-8")

        resolved = resolve_box_path()
        assert resolved == str(legacy_cache_box)

    def test_legacy_ai_memory_compatibility(self, monkeypatch: pytest.MonkeyPatch, tmp_path):
        import json

        from dokkan_eza_link_farmer.ai.endgame.telemetry import EpisodicMemory

        monkeypatch.setenv("DOKKAN_FARMER_HOME", str(tmp_path))
        legacy_mem = tmp_path / "cache" / "ai_memory.json"
        legacy_mem.parent.mkdir(parents=True, exist_ok=True)
        legacy_mem.write_text(json.dumps({"updated_at": "legacy", "stages": {}}), encoding="utf-8")

        memory = EpisodicMemory()
        assert memory.cache_path == legacy_mem
        assert memory._data.get("updated_at") == "legacy"

    def test_env_var_quotes_stripping(self, monkeypatch: pytest.MonkeyPatch, tmp_path):
        target_dir = str(tmp_path / "quoted_dir")
        monkeypatch.setenv("DOKKAN_FARMER_HOME", f'"{target_dir}"')
        assert AppPaths.get_base_dir() == os.path.abspath(target_dir)

        monkeypatch.setenv("DOKKAN_FARMER_HOME", f"'{target_dir}'")
        assert AppPaths.get_base_dir() == os.path.abspath(target_dir)

        monkeypatch.setenv("DOKKAN_FARMER_HOME", f'  "{target_dir}"  ')
        assert AppPaths.get_base_dir() == os.path.abspath(target_dir)

    def test_env_var_tilde_expansion(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("DOKKAN_FARMER_HOME", "~/custom_dokkan_farm")
        expected = os.path.abspath(os.path.join(os.path.expanduser("~"), "custom_dokkan_farm"))
        assert AppPaths.get_base_dir() == expected

    def test_oserror_directory_creation_resilience(self, monkeypatch: pytest.MonkeyPatch, tmp_path):
        monkeypatch.setenv("DOKKAN_FARMER_HOME", str(tmp_path))
        with unittest.mock.patch(
            "os.makedirs", side_effect=PermissionError("Read-only filesystem")
        ):
            cache_dir = AppPaths.get_cache_dir()
            assert cache_dir == os.path.join(str(tmp_path), "cache")
            thumbs_dir = AppPaths.get_thumbnails_cache_dir()
            assert thumbs_dir == os.path.join(str(tmp_path), "cache", "thumbs")

    def test_canonical_user_box_resolution_with_runtime_home_override(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ):
        from dokkan_eza_link_farmer.automation.scanner.box_storage import resolve_box_path

        monkeypatch.setenv("DOKKAN_FARMER_HOME", str(tmp_path))
        canonical_user_box = tmp_path / "user_box.json"
        canonical_user_box.write_text("{}", encoding="utf-8")

        resolved = resolve_box_path()
        assert resolved == str(canonical_user_box)

    def test_sync_box_cache_runtime_override(self, monkeypatch: pytest.MonkeyPatch, tmp_path):
        from dokkan_eza_link_farmer.automation.scanner.box_storage import (
            CANONICAL_BOX_PATH,
            sync_box_cache,
        )

        monkeypatch.setenv("DOKKAN_FARMER_HOME", str(tmp_path))
        os.makedirs("config", exist_ok=True)
        canonical_file = Path(CANONICAL_BOX_PATH)
        canonical_file.write_text('{"cards": []}', encoding="utf-8")
        try:
            sync_box_cache(CANONICAL_BOX_PATH)
            target = tmp_path / "user_box.json"
            assert target.exists()
        finally:
            if canonical_file.exists():
                canonical_file.unlink()

    def test_episodic_memory_runtime_override(self, monkeypatch: pytest.MonkeyPatch, tmp_path):
        from dokkan_eza_link_farmer.ai.endgame.telemetry import EpisodicMemory

        monkeypatch.setenv("DOKKAN_FARMER_HOME", str(tmp_path))
        mem = EpisodicMemory()
        assert str(mem.cache_path) == str(tmp_path / "ai_memory.json")

    def test_box_scanner_task_runtime_override(self, monkeypatch: pytest.MonkeyPatch, tmp_path):
        from dokkan_eza_link_farmer.automation.tasks.box_scanner import BoxScannerTask

        monkeypatch.setenv("DOKKAN_FARMER_HOME", str(tmp_path))
        task = BoxScannerTask(unittest.mock.MagicMock(), unittest.mock.MagicMock(), {})
        assert task.output_file == str(tmp_path / "user_box.json")
        assert task.log_file == str(tmp_path / "box_scan.log")

    def test_endgame_runner_runtime_override(self, monkeypatch: pytest.MonkeyPatch, tmp_path):
        from dokkan_eza_link_farmer.ai.endgame.runner import EndgameRunner

        monkeypatch.setenv("DOKKAN_FARMER_HOME", str(tmp_path))
        runner = EndgameRunner(
            adb=unittest.mock.MagicMock(),
            vision=unittest.mock.MagicMock(),
            detector=unittest.mock.MagicMock(),
        )
        assert str(runner.user_box_path) == str(tmp_path / "user_box.json")
        assert str(runner.memory_path) == str(tmp_path / "ai_memory.json")

    def test_dokkandb_client_candidate_paths_honors_apppaths(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ):
        from dokkan_eza_link_farmer.integrations.dokkandb_client import DokkanDBClient

        monkeypatch.setenv("DOKKAN_FARMER_HOME", str(tmp_path))
        box_file = tmp_path / "user_box.json"
        box_file.write_text('[{"id": 9999999}]', encoding="utf-8")

        client = DokkanDBClient()
        ids = client.get_user_box_card_ids()
        assert 9999999 in ids

    def test_non_ascii_dokkan_farmer_home(self, monkeypatch: pytest.MonkeyPatch, tmp_path):
        non_ascii_dir = tmp_path / "farmer_test_é_日本語"
        monkeypatch.setenv("DOKKAN_FARMER_HOME", str(non_ascii_dir))

        cache_dir = AppPaths.get_cache_dir()
        assert os.path.isdir(cache_dir)
        thumbs_dir = AppPaths.get_thumbnails_cache_dir()
        assert os.path.isdir(thumbs_dir)
        assert AppPaths.get_user_box_path() == str(non_ascii_dir / "user_box.json")

    def test_env_var_nested_expansion(self, monkeypatch: pytest.MonkeyPatch, tmp_path):
        monkeypatch.setenv("MOCK_BASE_DIR", str(tmp_path))
        var_syntax = (
            "%MOCK_BASE_DIR%/sub_farmer" if sys.platform == "win32" else "$MOCK_BASE_DIR/sub_farmer"
        )
        monkeypatch.setenv("DOKKAN_FARMER_HOME", var_syntax)

        expected = os.path.abspath(str(tmp_path / "sub_farmer"))
        assert AppPaths.get_base_dir() == expected

    def test_endgame_runner_legacy_memory_fallback(self, monkeypatch: pytest.MonkeyPatch, tmp_path):
        import json

        from dokkan_eza_link_farmer.ai.endgame.runner import EndgameRunner

        monkeypatch.setenv("DOKKAN_FARMER_HOME", str(tmp_path))
        legacy_mem = tmp_path / "cache" / "ai_memory.json"
        legacy_mem.parent.mkdir(parents=True, exist_ok=True)
        legacy_mem.write_text(
            json.dumps({"updated_at": "legacy_runner_test", "stages": {"101": {}}}),
            encoding="utf-8",
        )

        runner = EndgameRunner(
            adb=unittest.mock.MagicMock(),
            vision=unittest.mock.MagicMock(),
            detector=unittest.mock.MagicMock(),
        )
        assert runner.memory_path == legacy_mem
        assert runner.memory.cache_path == legacy_mem
        assert runner.memory._data.get("updated_at") == "legacy_runner_test"

    def test_endgame_runner_enrichment_uses_cache_dir(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ):
        import json

        from dokkan_eza_link_farmer.ai.endgame.runner import EndgameRunner

        monkeypatch.setenv("DOKKAN_FARMER_HOME", str(tmp_path))
        box_file = tmp_path / "user_box.json"
        box_file.write_text(json.dumps([{"id": 1025551, "name": "Goku"}]), encoding="utf-8")

        runner = EndgameRunner(
            adb=unittest.mock.MagicMock(),
            vision=unittest.mock.MagicMock(),
            detector=unittest.mock.MagicMock(),
            user_box_path=str(box_file),
        )

        with unittest.mock.patch(
            "dokkan_eza_link_farmer.ai.syncer.DokkanSyncer"
        ) as mock_syncer_cls:
            mock_inst = unittest.mock.MagicMock()
            mock_inst.sync_box_details.return_value = []
            mock_syncer_cls.return_value = mock_inst

            runner.load_user_box()

            mock_syncer_cls.assert_called_once_with(cache_dir=AppPaths.get_cache_dir())

    def test_dokkan_syncer_legacy_box_fallback(self, monkeypatch: pytest.MonkeyPatch, tmp_path):
        import json

        from dokkan_eza_link_farmer.ai.syncer import DokkanSyncer

        monkeypatch.setenv("DOKKAN_FARMER_HOME", str(tmp_path))
        legacy_box = tmp_path / "cache" / "user_box.json"
        legacy_box.parent.mkdir(parents=True, exist_ok=True)
        legacy_box.write_text(
            json.dumps([{"id": 1025551, "name": "Goku", "category_ids": [1]}]), encoding="utf-8"
        )

        syncer = DokkanSyncer()
        assert not os.path.exists(AppPaths.get_user_box_path())

        cards = syncer.sync_user_box_details()
        assert len(cards) == 1
        assert cards[0].id == 1025551

    def test_box_scanner_task_respects_monkeypatched_defaults(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ):
        import dokkan_eza_link_farmer.automation.tasks.box_scanner as bs_module
        from dokkan_eza_link_farmer.automation.tasks.box_scanner import BoxScannerTask

        monkeypatch.setenv("DOKKAN_FARMER_HOME", str(tmp_path / "env_home"))
        custom_box = str(tmp_path / "custom_monkeypatched_box.json")
        custom_log = str(tmp_path / "custom_monkeypatched_log.log")

        monkeypatch.setattr(bs_module, "DEFAULT_USER_BOX_PATH", custom_box)
        monkeypatch.setattr(bs_module, "DEFAULT_BOX_SCAN_LOG_PATH", custom_log)

        task = BoxScannerTask(unittest.mock.MagicMock(), unittest.mock.MagicMock(), {})
        assert task.output_file == custom_box
        assert task.log_file == custom_log

    def test_telemetry_respects_monkeypatched_default_memory_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ):
        import dokkan_eza_link_farmer.ai.endgame.telemetry as tel_module
        from dokkan_eza_link_farmer.ai.endgame.telemetry import EpisodicMemory

        monkeypatch.setenv("DOKKAN_FARMER_HOME", str(tmp_path / "env_home"))
        custom_mem = str(tmp_path / "custom_monkeypatched_memory.json")
        monkeypatch.setattr(tel_module, "DEFAULT_MEMORY_CACHE_PATH", custom_mem)

        mem = EpisodicMemory()
        assert str(mem.cache_path) == custom_mem

    def test_support_catalog_respects_monkeypatch_and_env_home(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ):
        import json

        import dokkan_eza_link_farmer.ai.support_catalog as sc_module
        from dokkan_eza_link_farmer.ai.support_catalog import fetch_all_support_memories

        home_dir = tmp_path / "env_home"
        monkeypatch.setenv("DOKKAN_FARMER_HOME", str(home_dir))

        env_cache_file = home_dir / "cache" / "dokkandb_support_memories.json"
        env_cache_file.parent.mkdir(parents=True, exist_ok=True)
        env_cache_file.write_text(json.dumps([{"id": 1, "name": "EnvMemory"}]), encoding="utf-8")

        data = fetch_all_support_memories()
        assert len(data) == 1
        assert data[0]["name"] == "EnvMemory"

        custom_sc = str(tmp_path / "custom_support.json")
        Path(custom_sc).write_text(
            json.dumps([{"id": 2, "name": "MonkeyMemory"}]), encoding="utf-8"
        )
        monkeypatch.setattr(sc_module, "MEMORIES_CACHE_FILE", custom_sc)

        data_monkey = fetch_all_support_memories()
        assert len(data_monkey) == 1
        assert data_monkey[0]["name"] == "MonkeyMemory"

    def test_sync_box_cache_migrates_legacy_box(self, monkeypatch: pytest.MonkeyPatch, tmp_path):
        from dokkan_eza_link_farmer.automation.scanner.box_storage import sync_box_cache

        monkeypatch.setenv("DOKKAN_FARMER_HOME", str(tmp_path))
        legacy_box = tmp_path / "cache" / "user_box.json"
        legacy_box.parent.mkdir(parents=True, exist_ok=True)
        legacy_box.write_text('{"cards": [{"id": 42}]}', encoding="utf-8")

        canonical_cfg = Path("config/box.json")
        try:
            sync_box_cache(str(legacy_box))
            canonical_target = tmp_path / "user_box.json"
            assert canonical_target.exists()
            assert "42" in canonical_target.read_text(encoding="utf-8")
        finally:
            if canonical_cfg.exists():
                canonical_cfg.unlink()
