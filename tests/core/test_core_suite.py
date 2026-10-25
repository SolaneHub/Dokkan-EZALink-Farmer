from __future__ import annotations

import os

import pytest
from tests.harness.fake_dokkandb import (
    FakeDokkanDBClient,
    fake_dokkandb_requests_get,
)

from dokkan_eza_link_farmer.core.i18n import get_available_languages, get_language, set_language, t
from dokkan_eza_link_farmer.core.system_tools import ToolLocator, get_config_path, get_resource_path


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
