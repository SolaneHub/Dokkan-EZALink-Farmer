from __future__ import annotations

import unittest

from tests.harness.fake_dokkandb import FakeDokkanDBClient, fake_dokkandb_requests_get


class TestFakeDokkanDBHarness(unittest.TestCase):
    """Verifies that FakeDokkanDBClient satisfies all interface and catalog requirements in-memory."""

    def setUp(self):
        self.fake_client = FakeDokkanDBClient()

    def test_zbattles_in_memory(self):
        zbattles = self.fake_client.get_zbattles()
        self.assertGreater(len(zbattles), 0)
        self.assertTrue(all("name" in z for z in zbattles))
        self.assertTrue(all(z.get("is_currently_open") for z in zbattles))

    def test_events_and_growth_chamber(self):
        events = self.fake_client.get_events()
        self.assertGreater(len(events), 0)
        chamber = self.fake_client.get_chamber_of_spirit_and_time()
        self.assertIsNotNone(chamber)
        assert chamber is not None
        self.assertIn("chamber of spirit and time", chamber.get("name", "").lower())
        self.assertIsNotNone(chamber.get("banner_local_path"))

    def test_categories_and_links(self):
        cats = self.fake_client.get_categories()
        links = self.fake_client.get_links()
        self.assertGreater(len(cats), 0)
        self.assertGreater(len(links), 0)
        pure_saiyans = next((c for c in cats if c.get("id") == 1), None)
        self.assertIsNotNone(pure_saiyans)

    def test_cards_catalog_and_card_details(self):
        catalog = self.fake_client.get_cards_catalog()
        self.assertGreater(len(catalog), 0)
        card_1001 = self.fake_client.get_card(1001)
        self.assertIsNotNone(card_1001)
        assert card_1001 is not None
        self.assertEqual(card_1001["id"], 1001)
        self.assertIn("Guards", card_1001.get("passive_skill_description", ""))

    def test_search_and_linking_partners(self):
        goku_cards = self.fake_client.search_cards("Goku")
        self.assertGreater(len(goku_cards), 0)
        partners = self.fake_client.get_best_linking_partners(1001)
        self.assertIsInstance(partners, list)

    def test_http_request_interceptor(self):
        resp_chunk1 = fake_dokkandb_requests_get(
            "https://api.dokkandb.com/api/cards-catalog-with-transformations?chunk=1"
        )
        self.assertEqual(resp_chunk1.status_code, 200)
        self.assertGreater(len(resp_chunk1.json()), 0)

        resp_card = fake_dokkandb_requests_get("https://api.dokkandb.com/api/card?code=1001")
        self.assertEqual(resp_card.status_code, 200)
        self.assertEqual(resp_card.json()[0]["id"], 1001)

        resp_img = fake_dokkandb_requests_get(
            "https://enaskhebnjtktdfszdcb.supabase.co/storage/v1/object/public/assets/mirror/thumb.png"
        )
        self.assertEqual(resp_img.status_code, 200)
        self.assertGreater(len(resp_img.content), 50)

        resp_cat_lead = fake_dokkandb_requests_get(
            "https://api.dokkandb.com/api/category-leaders?code=1"
        )
        self.assertEqual(resp_cat_lead.status_code, 200)
        self.assertGreater(len(resp_cat_lead.json()), 0)

    def test_category_leaders_in_memory(self):
        leaders = self.fake_client.get_category_leaders(1)
        self.assertGreater(len(leaders), 0)
        leader_map = self.fake_client.get_category_leaders_map(1)
        self.assertIn(1001, leader_map)
        parsed = leader_map[1001]
        self.assertEqual(parsed["base_boost_pct"], 170.0)
        self.assertEqual(parsed["ki"], 3)
        self.assertTrue(parsed["is_main_leader"])
