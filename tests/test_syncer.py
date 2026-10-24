from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

from dokkan_eza_link_farmer.ai.models import (
    BossEnemy,
    BossMechanic,
    BossPhase,
    BossStage,
    DokkanCard,
)
from dokkan_eza_link_farmer.ai.syncer import (
    DokkanSyncer,
    parse_leader_spec,
    parse_passive_tags,
    parse_sa_tags,
)
from tests.harness.fake_dokkandb import fake_dokkandb_requests_get


class TestDokkanSyncer:
    """Comprehensive test suite for DokkanSyncer, data models, and Phase 2 data foundations."""

    def test_thumb_id_and_url_calculation(self):
        """Verifies the exact Supabase thumbnail formula: str(card_id)[:-1] + '0'."""
        assert DokkanSyncer.get_thumb_id(1012901) == "1012900"
        assert DokkanSyncer.get_thumb_id(1003211) == "1003210"
        assert DokkanSyncer.get_thumb_id(1028731) == "1028730"
        assert DokkanSyncer.get_thumb_id(9324301) == "9324300"

        syncer = DokkanSyncer()
        url = syncer.get_thumb_url(1012901)
        assert "card_1012900_thumb.png" in url
        assert "https://enaskhebnjtktdfszdcb.supabase.co" in url

    def test_catalog_chunks_download_and_ur_lr_filter(self):
        """Verifies chunk 1 and 2 retrieval, accepting {3, 4, 5} by default, and disk caching."""
        with tempfile.TemporaryDirectory() as tmpdir:
            syncer = DokkanSyncer(cache_dir=tmpdir)

            with patch("requests.get", side_effect=fake_dokkandb_requests_get):
                catalog = syncer.sync_catalog(force=True)
                assert len(catalog) == 4
                ids = [c["id"] for c in catalog]
                assert 1001 in ids
                assert 1002 in ids
                assert 1003 in ids
                assert 1005 in ids
                assert 1004 not in ids
                assert os.path.exists(syncer.catalog_cache_file)

                # When rarities=(4, 5) is explicitly passed, SSR (3) is excluded
                catalog_ur_lr = syncer.sync_catalog(force=True, rarities=(4, 5))
                assert len(catalog_ur_lr) == 3
                assert 1003 not in [c["id"] for c in catalog_ur_lr]

    def test_catalog_cache_respects_include_ssr(self):
        """Verifies that catalog cache detects missing SSR cards and re-fetches when {3, 4, 5} are required."""
        with tempfile.TemporaryDirectory() as tmpdir:
            syncer = DokkanSyncer(cache_dir=tmpdir)

            # Pre-populate cache with only UR/LR cards (rarity 4 and 5)
            cached_cards = [{"id": 1000 + i, "name": f"UR {i}", "rarity": 4} for i in range(850)]
            with open(syncer.catalog_cache_file, "w", encoding="utf-8") as f:
                json.dump(cached_cards, f)

            # Calling with explicit rarities=(4, 5) should return cached UR cards without network call
            with patch("requests.get") as mock_get:
                cat_no_ssr = syncer.sync_catalog(rarities=(4, 5))
                assert len(cat_no_ssr) == 850
                mock_get.assert_not_called()

            # Calling default (or include_ssr=True) requires {3, 4, 5}, detects missing SSRs and fetches from API
            raw_chunks = [
                [
                    {"id": 2001, "name": "LR Beast", "rarity": 5},
                    {"id": 2002, "name": "SSR Pan", "rarity": 3},
                ]
            ]
            with patch("requests.get") as mock_get:
                mock_resp1 = MagicMock(status_code=200)
                mock_resp1.json.return_value = raw_chunks[0]
                mock_resp2 = MagicMock(status_code=200)
                mock_resp2.json.return_value = []
                mock_get.side_effect = [mock_resp1, mock_resp2]

                cat_ssr = syncer.sync_catalog()
                assert len(cat_ssr) == 2
                assert any(c["rarity"] == 3 for c in cat_ssr)
                assert mock_get.called

    def test_sync_thumbnails(self):
        """Tests concurrent thumbnail downloading from Supabase mirror into cache/thumbs/."""
        with tempfile.TemporaryDirectory() as tmpdir:
            syncer = DokkanSyncer(cache_dir=tmpdir)
            cards = [
                {"id": 1012901, "name": "LR Gogeta"},
                {"id": 1003211, "name": "SS3 Goku"},
            ]

            with patch("requests.get", side_effect=fake_dokkandb_requests_get):
                downloaded = syncer.sync_thumbnails(cards=cards, max_workers=2)

            assert downloaded == 2
            assert os.path.exists(os.path.join(syncer.thumbs_dir, "card_1012900_thumb.png"))
            assert os.path.exists(os.path.join(syncer.thumbs_dir, "card_1003210_thumb.png"))

            # Re-running should skip already downloaded files
            downloaded_cached = syncer.sync_thumbnails(cards=cards, max_workers=2)
            assert downloaded_cached == 0

    def test_lazy_details_fetching_only_for_user_box(self):
        """Verifies that deep card details are ONLY fetched for cards in user_box.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            syncer = DokkanSyncer(cache_dir=tmpdir)
            box_file = os.path.join(tmpdir, "user_box.json")

            # Box contains only 2 cards out of a 1436 catalog
            box_data = {
                "cards": [
                    {
                        "id": 1001,
                        "is_rainbow": True,
                        "is_eza": True,
                        "swipe_page": 0,
                        "grid_slot": 2,
                    },
                    {
                        "id": 1002,
                        "is_rainbow": False,
                        "is_eza": False,
                        "swipe_page": 1,
                        "grid_slot": 7,
                    },
                ]
            }
            with open(box_file, "w", encoding="utf-8") as f:
                json.dump(box_data, f)

            fetched_codes = []

            def tracked_fake_get(url, *args, **kwargs):
                if "code=1001" in url:
                    fetched_codes.append(1001)
                elif "code=1002" in url:
                    fetched_codes.append(1002)
                return fake_dokkandb_requests_get(url, *args, **kwargs)

            with patch("requests.get", side_effect=tracked_fake_get):
                cards = syncer.sync_user_box_details(user_box_file=box_file, concurrency=2)

            assert len(cards) == 2
            assert fetched_codes == [1001, 1002]

            card1001 = next(c for c in cards if c.id == 1001)
            assert card1001.is_rainbow is True
            assert card1001.is_eza is True
            assert card1001.swipe_page == 0
            assert card1001.grid_slot == 2
            assert card1001.base_form is not None and card1001.base_form.passive_tags is not None
            assert card1001.base_form.sa_tags is not None
            assert card1001.base_form.passive_tags.has_guard is True
            assert card1001.base_form.passive_tags.dr_base_percent == 60
            assert card1001.base_form.sa_tags.stacks_def is True

            card1002 = next(c for c in cards if c.id == 1002)
            assert card1002.is_eza is False
            assert card1002.swipe_page == 1
            assert card1002.grid_slot == 7
            assert card1002.base_form is not None and card1002.base_form.sa_tags is not None
            assert card1002.base_form.sa_tags.stacks_def is False

    def test_distinguish_passive_base_vs_eza_vs_seza(self):
        """Verifies tactical tag extraction across Base, regular EZA, and Super EZA (SEZA) awakening tiers."""
        raw_dokkandb_data = {
            "id": 1003211,
            "name": "SS3 Goku",
            "rarity": 5,
            "element": 10,
            "leader_skill": "AGL Type ATK +3000",
            "eza_leader_skill_pre": "AGL Type Ki +3, Stats +70%",
            "eza_leader_skill": "AGL Type Ki +3, Stats +90%",
            "passive_skill_description": "ATK 100% for 7 turns",
            "eza_passive_skill_description_pre": "DEF 70%; ATK 120% for 7 turns",
            "eza_passive_skill_description": "Guards all attacks; reduces damage received by 50%; chance of evading enemy attacks +50%",
            "special_descriptions": ["Causes colossal damage"],
            "special_descriptions_eza": ["Greatly raises DEF and causes colossal damage"],
        }

        syncer = DokkanSyncer()

        # 1. Base Form (pre-EZA)
        base_card = syncer.build_dokkan_card(raw_dokkandb_data, is_eza=False, is_seza=False)
        assert base_card.has_guard is False
        assert base_card.damage_reduction_percent == 0
        assert base_card.base_form is not None and base_card.base_form.passive_tags is not None
        assert base_card.base_form.passive_tags.slot1_viable is False

        # 2. Regular EZA (uses _pre fields because card has SEZA)
        eza_card = syncer.build_dokkan_card(raw_dokkandb_data, is_eza=True, is_seza=False)
        assert eza_card.has_guard is False
        assert eza_card.damage_reduction_percent == 0
        assert "DEF 70%" in eza_card.passive_skill

        # 3. Super EZA (SEZA)
        seza_card = syncer.build_dokkan_card(raw_dokkandb_data, is_eza=True, is_seza=True)
        assert seza_card.has_guard is True
        assert seza_card.damage_reduction_percent == 50
        assert seza_card.base_form is not None and seza_card.base_form.passive_tags is not None
        assert seza_card.base_form.passive_tags.dodge_chance_percent == 50
        assert seza_card.base_form.passive_tags.slot1_viable is True

    def test_structured_leader_skill_spec(self):
        """Verifies parsing of 200% base, 170%+30% category bonus, and instant set intersection."""
        cats_catalog = [
            {"id": 65, "name": "Super Heroes"},
            {"id": 14, "name": "Hybrid Saiyans"},
            {"id": 18, "name": "Movie Heroes"},
        ]

        # Case 1: 170% + 30% leader
        lead_text = (
            '"Super Heroes" or "Hybrid Saiyans" Category Ki +3 and HP, ATK & DEF +170%, '
            'plus an additional HP, ATK & DEF +30% for characters who also belong to the "Movie Heroes" Category'
        )
        spec = parse_leader_spec(lead_text, categories_catalog=cats_catalog)
        assert spec.base_boost_pct == 170
        assert spec.extra_boost_pct == 30
        assert 65 in spec.main_category_ids
        assert 14 in spec.main_category_ids
        assert 18 in spec.extra_category_ids

        # Test instant set intersection on 200% candidate
        leader = DokkanCard(id=1, name="Leader", leader_skill=lead_text, leader_spec=spec)
        candidate_200 = DokkanCard(
            id=2, name="Piccolo", category_ids=[65, 18], categories=["Super Heroes", "Movie Heroes"]
        )
        is_cov, pct, desc = candidate_200.is_covered_by_leader(leader)
        assert is_cov is True
        assert pct == 200.0

        # Candidate with only 170% base category
        candidate_170 = DokkanCard(
            id=3, name="Trunks", category_ids=[14], categories=["Hybrid Saiyans"]
        )
        is_cov, pct, desc = candidate_170.is_covered_by_leader(leader)
        assert is_cov is True
        assert pct == 170.0

        # Case 2: Flat 200% leader
        lead_200_text = '"Super Heroes" Category Ki +3 and HP, ATK & DEF +200%'
        spec_200 = parse_leader_spec(lead_200_text, categories_catalog=cats_catalog)
        assert spec_200.base_boost_pct == 200
        assert spec_200.extra_boost_pct == 0
        assert 65 in spec_200.main_category_ids

    def test_boss_stage_and_boss_phase_models(self):
        """Verifies Red Zone / Blue Zone BossStage and BossPhase telemetry models."""
        phase_raw = {
            "phase": 1,
            "phase_index": 1,
            "bosses": [
                {
                    "card_id": 999901,
                    "name": "Fusion Zamasu",
                    "subname": "Wrath of God",
                    "element": 21,
                    "type_name": "Extreme TEQ",
                    "mechanics": [
                        {
                            "id": 1,
                            "name": "Cancels evasion",
                            "description": "Disables enemy's evasion",
                        },
                        {
                            "id": 2,
                            "name": "AOE Attack",
                            "description": "Super Attack hits all targets",
                        },
                        {"id": 3, "name": "Locking", "description": "Locks slot positions"},
                        {"id": 4, "name": "Immunity", "description": "Immune to stun and sealing"},
                    ],
                }
            ],
        }

        phase = BossPhase.from_dict(phase_raw)
        assert phase.phase_index == 1
        assert phase.element == 21
        assert phase.element_name == "Extreme TEQ"
        assert phase.cancels_dodge is True
        assert phase.has_aoe is True
        assert phase.locks_slots is True
        assert phase.nullifies_stun_seal is True

        stage = BossStage(
            stage_id=101,
            event_id=50,
            stage_name="Dismal Future",
            event_name="Red Zone [Future Saga]",
            difficulty=5,
            phases=[phase],
        )

        stage_dict = stage.to_dict()
        assert stage_dict["stage_name"] == "Dismal Future"
        assert len(stage_dict["phases"]) == 1
        assert stage_dict["phases"][0]["cancels_dodge"] is True

        restored_stage = BossStage.from_dict(stage_dict)
        assert restored_stage.stage_id == 101
        assert restored_stage.phases[0].has_aoe is True

    def test_real_world_dokkan_passive_and_sa_tag_edge_cases(self):
        """Tests parsing of official Dokkan in-game phrasings (guards against, damage reduction rate, etc.)."""
        # 1. Official Guard phrasing: "Guards against all attacks"
        p1 = "Guards against all attacks for 4 turns; reduces damage received by up to 50%"
        tags1 = parse_passive_tags(p1)
        assert tags1.has_guard is True
        assert tags1.dr_base_percent == 50
        assert tags1.slot1_viable is True

        # 2. Damage reduction rate 65% and Damage received -50%
        p2 = "Damage reduction rate 65%; Damage received -50%"
        tags2 = parse_passive_tags(p2)
        assert tags2.dr_base_percent == 65

        # 3. Guaranteed evasion and un-plussed dodge %: "Evades enemy's attack", "Chance of evading enemy's attack 7%"
        p3 = "Evades enemy's attack; plus an additional chance of evading enemy's attack 7%"
        tags3 = parse_passive_tags(p3)
        assert tags3.dodge_chance_percent == 100

        # 4. Taunt: "Directs enemy's attacks to this character"
        p4 = "Directs enemy's attacks to this character for 1 turn"
        tags4 = parse_passive_tags(p4)
        assert tags4.has_taunt is True

        # 5. Support: "Allies' ATK & DEF +40%"
        p5 = "Allies' ATK & DEF +40% and chance of performing a critical hit +10%"
        tags5 = parse_passive_tags(p5)
        assert tags5.has_support is True

        # 6. Temporary SA buff: "Raises ATK & DEF for 1 turn"
        sa1 = "Raises ATK & DEF for 1 turn and causes immense damage"
        sa_tags1 = parse_sa_tags(sa1)
        assert sa_tags1.stacks_def is False
        assert sa_tags1.stacks_atk is False
        assert sa_tags1.raise_def_turns == 1
        assert sa_tags1.raise_atk_turns == 1

        # 7. Permanent Stacking of both stats: "Raises ATK & DEF and causes immense damage"
        sa2 = "Greatly raises ATK & DEF and causes colossal damage"
        sa_tags2 = parse_sa_tags(sa2)
        assert sa_tags2.stacks_def is True
        assert sa_tags2.stacks_atk is True

    def test_category_substring_boundary_and_sub_element_boost(self):
        """Verifies no substring collision on 'Super Saiyan 3' vs 'Super Saiyan' and accurate secondary lead boost."""
        cats = [
            {"id": 1, "name": "Super Saiyan"},
            {"id": 2, "name": "Super Saiyan 3"},
            {"id": 3, "name": "Potara"},
        ]
        # Leader for Super Saiyan 3 only
        spec_ss3 = parse_leader_spec('"Super Saiyan 3" Category Ki +3, Stats +170%', cats)
        assert 2 in spec_ss3.main_category_ids
        assert 1 not in spec_ss3.main_category_ids  # Must NOT match "Super Saiyan"

        # Leader with secondary type boost: Potara 170% or INT 90%
        lead_potara = '"Potara" Category Ki +3, HP & ATK +170% and DEF +130%; or INT Type Ki +3 and HP, ATK & DEF +90%'
        spec_potara = parse_leader_spec(lead_potara, cats)
        assert 3 in spec_potara.main_category_ids
        assert spec_potara.sub_boost_pct == 90

        lead_card = DokkanCard(
            id=1012901, name="LR Vegito", leader_skill=lead_potara, leader_spec=spec_potara
        )
        non_potara_int = DokkanCard(id=999, name="INT Goku", element=12, category_ids=[1])
        is_cov, mult, desc = non_potara_int.is_covered_by_leader(lead_card)
        assert is_cov is True
        assert mult == 90.0  # Must receive 90%, NOT 170%!

    def test_eza_without_seza_does_not_autoupgrade_to_seza(self):
        """Verifies that an EZA card does not silently upgrade to SEZA if is_seza is omitted."""
        raw = {
            "id": 1003211,
            "name": "SS3 Goku",
            "leader_skill": "Base lead",
            "eza_leader_skill_pre": "EZA lead",
            "eza_leader_skill": "SEZA lead",
            "passive_skill_description": "Base passive",
            "eza_passive_skill_description_pre": "EZA passive",
            "eza_passive_skill_description": "SEZA passive",
            "eza_leader_skill_set_id_pre": 123,
        }
        card = DokkanCard.from_dokkandb(raw, is_eza=True)
        assert card.is_eza is True
        assert card.is_seza is False
        assert card.passive_skill == "EZA passive"
        assert card.leader_skill == "EZA lead"

    def test_in_battle_transformation_parsing_without_awakening_medals(self):
        """Verifies that in-battle transformations parse transformation_names without fake awakening medals."""
        raw = {
            "id": 1012901,
            "name": "Super Saiyan Goku & Super Saiyan Vegeta",
            "transformation_names": ["Super Vegito"],
            "transformation_ids": [4012901],
            "transformation_elements": [12],
            "awakening_data": [{"id": 101, "name": "Medal A"}, {"id": 102, "name": "Medal B"}],
        }
        syncer = DokkanSyncer()
        card = syncer.build_dokkan_card(raw, is_eza=True)
        assert len(card.transformations) == 1
        assert card.transformations[0].form_id == 4012901
        assert card.transformations[0].form_name == "Super Vegito"
        assert card.transformations[0].element == 12

    def test_boss_phase_keyword_telemetry_detection(self):
        """Verifies that BossPhase detects 'Cancels Dodge' and 'Nullifies Stun' regardless of wording."""
        b1 = BossEnemy(
            card_id=1,
            name="Broly",
            element=23,
            type_name="Extreme STR",
            mechanics=[
                BossMechanic(
                    id=1, name="Cancels Dodge", description="Enemy attack cannot be evaded"
                ),
                BossMechanic(id=2, name="Nullifies Stun", description="Cannot be stunned"),
            ],
        )
        phase = BossPhase(bosses=[b1])
        assert phase.cancels_dodge is True
        assert phase.nullifies_stun_seal is True
        assert phase.element == 23
        assert phase.element_name == "Extreme STR"
