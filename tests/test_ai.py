from __future__ import annotations

from unittest.mock import MagicMock, patch

from dokkan_eza_link_farmer.ai.client import DokkanAIClient
from dokkan_eza_link_farmer.ai.mission_solver import (
    MissionBatch,
    MissionBundler,
    MissionParser,
)
from dokkan_eza_link_farmer.ai.models import (
    AIConfig,
    AIModelFamily,
    CardForm,
    DokkanCard,
    LeaderSkillSpec,
    PassiveTags,
    SupportedAIModel,
)
from dokkan_eza_link_farmer.ai.support_catalog import (
    get_recommended_support_items,
    get_recommended_support_memory,
)
from dokkan_eza_link_farmer.ai.team_builder import TeamBuilder
from dokkan_eza_link_farmer.integrations.dokkandb_client import DokkanDBClient


class TestDokkanAI:
    """Test suite for AI models, DeepSeek-R1 CoT parsing, Qwen reasoning, and TeamBuilder."""

    def test_ai_config_parsing(self):
        conf_qwen = AIConfig.from_dict(
            {
                "model_name": "qwen3.5:4b",
                "base_url": "http://localhost:11434/v1",
            }
        )
        assert conf_qwen.model_family == AIModelFamily.QWEN
        assert conf_qwen.model_name == SupportedAIModel.QWEN_3_5_4B.value
        assert conf_qwen.provider == "ollama"

        # Test normalization strictly maps any model to the single supported qwen3.5:4b
        conf_fallback = AIConfig.from_dict({"model_name": "gpt-4o-unknown"})
        assert conf_fallback.model_name == SupportedAIModel.QWEN_3_5_4B.value
        assert conf_fallback.model_family == AIModelFamily.QWEN

    def test_dokkan_card_slot1_tank_detection(self):
        tank_card = DokkanCard(
            id=1,
            name="Beast Gohan",
            passive_skill="Guards all attacks; reduces damage received by 50%",
            links=["Super Saiyan", "Fierce Battle"],
        )
        assert tank_card.is_slot1_tank is True

        glass_cannon = DokkanCard(
            id=2,
            name="Goku Nuker",
            passive_skill="ATK +300% when performing a Super Attack",
            links=["Super Saiyan", "Prepared for Battle"],
        )
        assert glass_cannon.is_slot1_tank is False

    def test_qwen_think_tag_stripping(self):
        client = DokkanAIClient(AIConfig(model_family=AIModelFamily.QWEN, model_name="qwen3.5:4b"))

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": (
                            "<think>\n"
                            "Broly deals massive damage in slot 1.\n"
                            "Beast Gohan has guard and damage reduction, so he must take Slot 1.\n"
                            "</think>\n\n"
                            "Consiglio strategico: metti Beast Gohan in Slot 1 e usa Whis al terzo turno."
                        )
                    }
                }
            ]
        }

        with patch("requests.post", return_value=mock_resp):
            content, reasoning = client.chat_completion([{"role": "user", "content": "analyze"}])
            assert "Consiglio strategico" in content
            assert "<think>" not in content

    def test_qwen_strategy_analysis(self):
        client = DokkanAIClient(AIConfig(model_family=AIModelFamily.QWEN, model_name="qwen3.5:4b"))

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": (
                            "Rotazione 1: Beast Gohan (Slot 1 Tank) + Gamma 1 & 2 (Slot 2 Danno).\n"
                            "Rotazione 2: Piccolo STR (Slot 1) + Gogeta PHY (Slot 2).\n"
                            "Usa Whis alla seconda fase."
                        )
                    }
                }
            ]
        }

        with patch("requests.post", return_value=mock_resp):
            guide, reasoning = client.analyze_team_strategy("Team Super Heroes")
            assert "Rotazione 1" in guide
            assert reasoning is None

    def test_link_synergy_and_ki_links(self):
        card1 = DokkanCard(
            id=101,
            name="Super Saiyan Goku",
            links=["Prepared for Battle", "Super Saiyan", "Fierce Battle"],
        )
        card2 = DokkanCard(
            id=102,
            name="Super Saiyan Vegeta",
            links=["Prepared for Battle", "Super Saiyan", "Fierce Battle"],
        )
        card3 = DokkanCard(
            id=103,
            name="Frieza",
            links=["Big Bad Bosses", "Shocking Speed"],
        )

        score_saiyans, shared, shared_ki = TeamBuilder.calculate_link_synergy(card1, card2)
        assert len(shared) == 3
        assert "Prepared for Battle" in shared_ki
        assert score_saiyans > 6.0

        score_mismatch, shared_mismatch, _ = TeamBuilder.calculate_link_synergy(card1, card3)
        assert len(shared_mismatch) == 0
        assert score_mismatch == 0.0

    def test_rotation_optimizer(self):
        tb = TeamBuilder()

        # 6 cards: 2 defensive tanks and 4 attackers
        cards = [
            DokkanCard(
                id=1,
                name="Tank A",
                is_tank_override=True,
                links=["Super Saiyan", "Prepared for Battle"],
            ),
            DokkanCard(
                id=2,
                name="Attacker A",
                is_tank_override=False,
                links=["Super Saiyan", "Prepared for Battle", "Fierce Battle"],
            ),
            DokkanCard(
                id=3,
                name="Tank B",
                is_tank_override=True,
                links=["Shocking Speed", "Big Bad Bosses"],
            ),
            DokkanCard(
                id=4,
                name="Attacker B",
                is_tank_override=False,
                links=["Shocking Speed", "Big Bad Bosses"],
            ),
            DokkanCard(id=5, name="Floater 1", links=["Fierce Battle"]),
            DokkanCard(id=6, name="Floater 2", links=["Prepared for Battle"]),
        ]

        rot_a, rot_b, floaters = tb.optimize_rotations_for_team(cards)
        assert rot_a is not None
        assert rot_b is not None
        assert len(floaters) == 2

        # Verify that each rotation has its proper slot 1 defender
        assert rot_a.slot1.is_slot1_tank or rot_a.slot2.is_slot1_tank
        assert rot_b.slot1.is_slot1_tank or rot_b.slot2.is_slot1_tank

    def test_team_builder_algorithmic_fallback(self):
        tb = TeamBuilder()
        cards = [
            DokkanCard(
                id=1,
                name="Leader",
                leader_skill="Super Heroes Ki +3 HP, ATK & DEF +200%",
                links=["Super Saiyan"],
            ),
            DokkanCard(id=2, name="Sub 1", links=["Super Saiyan"]),
            DokkanCard(id=3, name="Sub 2", links=["Super Saiyan"]),
            DokkanCard(id=4, name="Sub 3", links=["Super Saiyan"]),
            DokkanCard(id=5, name="Sub 4", links=["Super Saiyan"]),
            DokkanCard(id=6, name="Sub 5", links=["Super Saiyan"]),
        ]

        rec = tb.build_team_plan(cards, language="it")
        assert rec.leader.name == "Leader"
        assert "Rotazione A" in rec.tactical_analysis
        assert "Whis" in rec.recommended_items

    def test_support_catalog_items_and_memory(self):
        items = get_recommended_support_items(max_items=4)
        assert len(items) == 4
        assert items[0]["name"] == "Whis"
        assert items[0]["rank"] == 1
        assert "40%" in items[0]["effect"]
        assert items[1]["name"] == "Ghost Usher"
        assert items[2]["name"] == "Icarus"
        assert items[3]["name"] == "Princess Snake"

        # Team with Movie Heroes category
        movie_heroes_team = [
            DokkanCard(id=1, name="Gogeta", categories=["Movie Heroes", "Fused Fighters"]),
            DokkanCard(id=2, name="Piccolo", categories=["Movie Heroes"]),
            DokkanCard(id=3, name="Gohan", categories=["Movie Heroes", "Hybrid Saiyans"]),
            DokkanCard(id=4, name="Gamma 1", categories=["Movie Heroes", "Super Heroes"]),
            DokkanCard(id=5, name="Gamma 2", categories=["Movie Heroes", "Super Heroes"]),
            DokkanCard(id=6, name="Beast Gohan", categories=["Movie Heroes", "Super Heroes"]),
        ]
        mem = get_recommended_support_memory(movie_heroes_team)
        assert mem is not None
        assert "Permanente" in mem["duration"]
        assert mem["name"] in ("Kakarot", "Super Hero Fading Away")

        # Team with Majin Buu Saga
        buu_team = [
            DokkanCard(id=10, name="Buu", categories=["Majin Buu Saga"]),
            DokkanCard(id=11, name="Gotenks", categories=["Majin Buu Saga"]),
            DokkanCard(id=12, name="Vegito", categories=["Majin Buu Saga"]),
            DokkanCard(id=13, name="Goku", categories=["Majin Buu Saga"]),
            DokkanCard(id=14, name="Vegeta", categories=["Majin Buu Saga"]),
            DokkanCard(id=15, name="Gohan", categories=["Majin Buu Saga"]),
        ]
        mem_buu = get_recommended_support_memory(buu_team)
        assert mem_buu is not None
        assert mem_buu["name"] == "Buu's Slumber"
        assert "Permanente" in mem_buu["duration"]

    def test_tactical_form_timeline_standby_exchange_switch(self):
        # 1. Standby card
        standby_card = DokkanCard(
            id=1025731,
            name="SSJ3 Goku & SSJ2 Vegeta",
            standby_skill_name="Enters Standby Mode",
            standby_skill_condition="Can be activated when HP is 50% or less, or from 4th turn",
            standby_skill_effect="Stands by for 5 turns, charge count increases with Ki",
        )
        timeline_sb = standby_card.get_tactical_form_timeline()
        assert len(timeline_sb) >= 1
        assert timeline_sb[0]["type"] == "Standby Mode"
        assert "Turno 4" in timeline_sb[0]["timing"]

        # 2. Exchange card
        exchange_card = DokkanCard(
            id=1017661,
            name="Super Vegeta/Super Trunks",
            active_skill_name="Exchange",
            active_skill_condition="Can be activated from the 3rd turn",
            active_skill_effect="Exchange with Super Trunks",
        )
        timeline_ex = exchange_card.get_tactical_form_timeline()
        assert len(timeline_ex) >= 1
        assert timeline_ex[0]["type"] == "Scambio (Exchange)"

        # 3. Reversible Switch card
        switch_card = DokkanCard(
            id=1099999,
            name="Gamma 1 & Gamma 2",
            active_skill_name="Switch Core",
            active_skill_condition="Can switch back and forth each turn",
            active_skill_effect="Switches between offensive and defensive mode",
        )
        timeline_sw = switch_card.get_tactical_form_timeline()
        assert len(timeline_sw) >= 1
        assert timeline_sw[0]["type"] == "Scambio Reversibile (Switch)"

        # 4. Transforming card
        trans_card = DokkanCard(
            id=1030431,
            name="Angel Goku & Vegeta",
            transformations=[
                CardForm(
                    form_id=1030432,
                    form_name="Super Gogeta",
                    min_turn=4,
                    passive_skill_text="Super effective against all types; high chance of critical hit",
                )
            ],
        )
        timeline_tr = trans_card.get_tactical_form_timeline()
        assert len(timeline_tr) >= 1
        assert timeline_tr[0]["type"] == "Trasformazione"
        assert "Fase Finale" in timeline_tr[0]["timing"]

    def test_friend_leader_flexible_rotation_slot1(self):
        tb = TeamBuilder()
        main_leader = DokkanCard(
            id=1001,
            name="Main Leader",
            element=0,
            leader_skill="Super Heroes Ki +3 HP, ATK & DEF +200%",
            leader_spec=LeaderSkillSpec(main_category_ids=[88], base_boost_pct=200),
            categories=["Super Heroes"],
            links=["Super Saiyan", "Prepared for Battle"],
        )
        beast_friend = DokkanCard(
            id=1002,
            name="Beast Gohan Friend",
            element=1,
            leader_skill="Super Heroes Ki +3 HP, ATK & DEF +200%",
            leader_spec=LeaderSkillSpec(main_category_ids=[88], base_boost_pct=200),
            categories=["Super Heroes"],
            passive_skill="Guards all attacks; reduces damage received by 58%",
            base_form=CardForm(
                form_id=1002,
                passive_tags=PassiveTags(slot1_viable=True, has_guard=True, dr_base_percent=58),
            ),
            links=["Super Saiyan", "Prepared for Battle", "Fierce Battle"],
        )
        sub_cards = [
            main_leader,
            DokkanCard(
                id=1003,
                name="Sub 1",
                categories=["Super Heroes"],
                links=["Super Saiyan", "Prepared for Battle"],
            ),
            DokkanCard(
                id=1004,
                name="Sub 2",
                categories=["Super Heroes"],
                links=["Super Saiyan", "Prepared for Battle"],
            ),
            DokkanCard(
                id=1005,
                name="Sub 3",
                categories=["Super Heroes"],
                links=["Prepared for Battle"],
            ),
            DokkanCard(
                id=1006,
                name="Sub 4",
                categories=["Super Heroes"],
                links=["Prepared for Battle"],
            ),
            DokkanCard(
                id=1007,
                name="Sub 5",
                categories=["Super Heroes"],
                links=["Prepared for Battle"],
            ),
        ]
        selected_friend = tb.select_best_friend_leader(sub_cards, candidate_pool=[beast_friend])
        assert selected_friend.id == beast_friend.id

        rec = tb.build_team_plan(sub_cards, candidate_pool=[beast_friend])
        assert rec.friend_leader is not None
        assert rec.friend_leader.id == beast_friend.id
        assert len(rec.floaters) == 3

        rot_cards = [
            rec.rotation_a.slot1,
            rec.rotation_a.slot2,
            rec.rotation_b.slot1,
            rec.rotation_b.slot2,
        ]
        assert any(c.id == beast_friend.id for c in rot_cards)
        assert (
            rec.rotation_a.slot1.id == beast_friend.id or rec.rotation_b.slot1.id == beast_friend.id
        )

    def test_dokkandb_client_card_and_catalog(self, tmp_path):
        db = DokkanDBClient(cache_dir=str(tmp_path))

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {
                "id": 1028751,
                "name": "Catopesra",
                "subname": "Policeman of Universe 3",
                "category_names": ["Defenders of Justice", "Special Pose"],
                "link_skill_name_1": "Shocking Speed",
            }
        ]

        with patch("requests.get", return_value=mock_resp):
            card = db.get_card(1028751)
            assert card is not None
            assert card["name"] == "Catopesra"
            assert "Defenders of Justice" in card["category_names"]

    def test_mission_parser_and_bundler(self):
        from dokkan_eza_link_farmer.ai.mission_solver import MissionBundler, MissionParser

        m1_data = {
            "id": 1,
            "name": "Rainbow Mission",
            "description": "Clear stage with an AGL, TEQ, INT, STR and PHY Type character on your team!",
        }
        m2_data = {
            "id": 2,
            "name": "Seekers Mission",
            "description": 'Clear Stage with 6 "Dragon Ball Seekers" Category characters!',
        }
        m3_data = {
            "id": 3,
            "name": "Realm of Gods Mission",
            "description": 'Clear Stage with 6 "Realm of Gods" Category characters!',
        }

        m1 = MissionParser.parse(m1_data)
        m2 = MissionParser.parse(m2_data)
        m3 = MissionParser.parse(m3_data)

        assert m1.rainbow_types is True
        assert len(m2.categories) == 1
        assert m2.categories[0] == (6, "Dragon Ball Seekers")

        # Rainbow + 6 Dragon Ball Seekers ARE compatible (6 Dragon Ball Seekers covering all 5 types)
        assert MissionBundler.are_compatible(m1, m2) is True
        # 6 Dragon Ball Seekers and 6 Realm of Gods are NOT compatible in a single 6-man team
        assert MissionBundler.are_compatible(m2, m3) is False

        # Bundling: 3 missions should be packaged into 2 batches instead of 3 runs!
        batches = MissionBundler.bundle_missions([m1, m2, m3])
        assert len(batches) == 2
        # First batch bundles m1 + m2 together
        assert len(batches[0].missions) == 2
        assert batches[0].requires_rainbow is True
        assert batches[0].required_categories[0][1] == "Dragon Ball Seekers"

    def test_challenge_task_initialization_and_bundling(self):
        from dokkan_eza_link_farmer.automation.tasks.challenge_task import ChallengeTask

        mock_adb = MagicMock()
        mock_vision = MagicMock()
        mock_dokkandb = MagicMock()
        mock_ai_client = MagicMock()

        mock_dokkandb.get_challenge_missions.return_value = [
            {
                "id": 101,
                "name": "Mission 1",
                "description": "Clear Stage 1 with 6 'Pure Saiyans' Category characters!",
            },
            {
                "id": 102,
                "name": "Mission 2",
                "description": "Clear Stage 1 with 5 Types (Rainbow Team)!",
            },
        ]

        task = ChallengeTask(
            adb=mock_adb,
            vision=mock_vision,
            config={},
            dokkandb=mock_dokkandb,
            ai_client=mock_ai_client,
            target_event={"name": "Ultimate Red Zone [Movie Bosses]"},
            stage_num=1,
        )

        batches = task.load_and_bundle_missions()
        assert len(batches) == 1
        assert len(batches[0].missions) == 2
        assert batches[0].requires_rainbow is True
        assert batches[0].required_categories[0][1] == "Pure Saiyans"

    def test_build_best_team_for_batch_and_retry_permutation(self):
        from dokkan_eza_link_farmer.ai.team_builder import TeamBuilder

        tb = TeamBuilder()

        # Create a candidate pool with 2 leaders and 6 subs
        leader_200 = DokkanCard(
            id=101,
            name="Super Heroes Leader",
            leader_skill='"Super Heroes" Category Ki +3 and HP, ATK & DEF +200%',
            categories=["Super Heroes"],
            links=["Prepared for Battle", "Fierce Battle"],
            rarity=5,
        )
        leader_170 = DokkanCard(
            id=102,
            name="Alternate Heroes Lead",
            leader_skill='"Super Heroes" Category Ki +3 and HP, ATK & DEF +170%',
            categories=["Super Heroes"],
            links=["Prepared for Battle"],
            rarity=4,
        )
        sub_tank = DokkanCard(
            id=103,
            name="Tank Gohan",
            passive_skill="Guards all attacks; reduces damage received by 50%",
            categories=["Super Heroes"],
            links=["Prepared for Battle", "Fierce Battle"],
            rarity=5,
            is_rainbow=True,
        )
        sub_piccolo = DokkanCard(
            id=104,
            name="Orange Piccolo",
            passive_skill="Reduces damage by 20%",
            categories=["Super Heroes"],
            links=["Prepared for Battle"],
            rarity=5,
        )
        sub_gamma1 = DokkanCard(
            id=105,
            name="Gamma 1",
            categories=["Super Heroes"],
            links=["Prepared for Battle", "Fierce Battle"],
        )
        sub_gamma2 = DokkanCard(
            id=106,
            name="Gamma 2",
            categories=["Super Heroes"],
            links=["Prepared for Battle", "Fierce Battle"],
        )
        sub_pan = DokkanCard(
            id=107,
            name="Pan",
            categories=["Super Heroes"],
            links=["Prepared for Battle"],
        )
        sub_goten = DokkanCard(
            id=108,
            name="Goten",
            categories=["Super Heroes"],
            links=["Prepared for Battle"],
        )

        pool = [
            leader_170,
            sub_piccolo,
            sub_pan,
            sub_gamma1,
            leader_200,
            sub_tank,
            sub_gamma2,
            sub_goten,
        ]
        batch = MissionBatch(missions=[], required_categories=[(6, "Super Heroes")])

        # Attempt 1: Should pick leader_200 as leader because 200% > 170%
        rec_att1 = tb.build_best_team_for_batch(pool, batch, attempt=1)
        assert rec_att1.leader.id == leader_200.id

        # Attempt 2: Should rotate to leader_170 to test alternative team configuration
        rec_att2 = tb.build_best_team_for_batch(pool, batch, attempt=2)
        assert rec_att2.leader.id == leader_170.id

        # Rotation checks: sub_tank is a verified Slot 1 tank and should be placed in Slot 1
        all_slot1_ids = [rec_att1.rotation_a.slot1.id, rec_att1.rotation_b.slot1.id]
        assert sub_tank.id in all_slot1_ids

    def test_dokkandb_challenge_events_and_details(self):
        client = DokkanDBClient()
        mock_events = [
            {
                "id": 1775,
                "category": 20,
                "name": "Supreme Magnificent Battle",
                "event_priority": 2609148,
                "active": "normal",
            },
            {
                "id": 1728,
                "category": 20,
                "name": "Union Master",
                "event_priority": 2610203,
                "active": "normal",
            },
            {"id": 501, "category": 5, "name": "Get STR Awakening Medals!", "active": "normal"},
            {
                "id": 999,
                "category": 20,
                "name": "Dummy Event",
                "banner_image_path": "banners/en/dummy_image/dummy_image.png",
                "active": "normal",
            },
            {"id": 100, "category": 1, "name": "Story Quest", "active": "normal"},
        ]
        mock_details = [
            {
                "id": 1775,
                "name": "Supreme Magnificent Battle",
                "quests": [
                    {
                        "quest_id": 1775003,
                        "quest_name": "Vs. Gohan",
                        "stages": [{"stage_id": 17750035}],
                    }
                ],
                "mission_categories": [
                    {
                        "missions": [
                            {
                                "id": 35108,
                                "name": "Clear Stage 3 with 6 Androids/Cell Saga",
                                "description": "Clear Stage 3",
                            }
                        ]
                    }
                ],
            }
        ]

        with patch.object(client, "get_events", return_value=mock_events):
            challenges = client.get_challenge_events(active_only=True)
            # Medals (cat 5), dummy image and category 1 are filtered out; 1728 sorted before 1775 by priority
            assert len(challenges) == 2
            assert challenges[0]["id"] == 1728
            assert challenges[1]["id"] == 1775

        with patch("requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = mock_details
            mock_get.return_value = mock_resp

            detail = client.get_event_details(1775, force_refresh=True)
            assert detail is not None
            assert detail["id"] == 1775

            missions = client.get_event_missions(1775, force_refresh=True)
            assert len(missions) == 1
            assert missions[0]["id"] == 35108

    def test_dokkandb_stage_boss_info_parsing(self):
        client = DokkanDBClient()

        mock_stage_stats = [
            {
                "name": "Supreme Magnificent Battle",
                "quest_name": "Vs. Gohan",
                "difficulty": 5,
                "enemy_info": {
                    "battles": [
                        {
                            "rounds": [
                                {
                                    "round_no": 1,
                                    "enemies": [
                                        {"card_id": 9324301, "enemy_skill_ids": [600070, 600104]}
                                    ],
                                }
                            ]
                        }
                    ]
                },
            }
        ]

        mock_cards = [{"id": 9324301, "name": "Super Saiyan Gohan", "element": 11}]
        mock_skills = [
            {"id": 600070, "name": "Damage Reduction", "description": "Reduces damage received"},
            {"id": 600104, "name": "Stun Immunity", "description": "Immune to stun"},
        ]

        with (
            patch("requests.get") as mock_get,
            patch.object(client, "get_cards_by_ids", return_value=mock_cards),
            patch.object(client, "get_enemy_skills_by_ids", return_value=mock_skills),
        ):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = mock_stage_stats
            mock_get.return_value = mock_resp

            boss_info = client.get_stage_boss_info(1775, 17750035, force_refresh=True)
            assert boss_info is not None
            assert boss_info["stage_name"] == "Vs. Gohan"
            assert len(boss_info["phases"]) == 1
            phase1 = boss_info["phases"][0]
            assert phase1["phase"] == 1
            boss = phase1["bosses"][0]
            assert boss["name"] == "Super Saiyan Gohan"
            assert boss["type_name"] == "Super TEQ"
            assert len(boss["mechanics"]) == 2
            assert boss["mechanics"][0]["name"] == "Damage Reduction"
            assert boss["mechanics"][1]["name"] == "Stun Immunity"

    def test_dokkan_card_kit_evaluation_and_properties(self):
        # 1. Top Tier Modern LR with Guard, 50% DR, DEF Stacking, Revive and Standby
        god_unit = DokkanCard(
            id=1001,
            name="Beast Gohan",
            rarity=5,
            passive_skill="Guards all attacks; reduces damage received by 50%; activates Standby Skill; revival skill when HP <= 50%",
            super_attack="Greatly raises DEF and causes mega-colossal damage",
            categories=["Super Heroes", "Hybrid Saiyans", "Movie Heroes"],
            links=["Super Saiyan", "Prepared for Battle", "Fierce Battle"],
            is_rainbow=True,
            has_eza=False,
        )

        assert god_unit.has_guard is True
        assert god_unit.has_damage_reduction is True
        assert god_unit.damage_reduction_percent == 50
        assert god_unit.has_stacking_def is True
        assert god_unit.has_revive is True
        assert god_unit.has_standby is True
        assert god_unit.is_slot1_tank is True

        kit_score, breakdown = god_unit.evaluate_kit_power()
        assert kit_score >= 60.0
        assert "guard" in breakdown
        assert breakdown["guard"] == 15.0
        assert "stack_def" in breakdown

        # 2. Support / Orb Changer unit
        support_unit = DokkanCard(
            id=1002,
            name="Bulma",
            rarity=5,
            passive_skill="All allies' Ki +3 and ATK & DEF +50%; changes Ki spheres of a certain type to Rainbow Ki spheres",
            super_attack="Raises ATK & DEF for 1 turn and causes colossal damage",
            categories=["Dragon Ball Seekers", "Earthlings"],
        )

        assert support_unit.has_support is True
        assert support_unit.has_orb_changing is True
        assert support_unit.has_stacking_def is False  # Only 1 turn, not infinite

        kit_score_supp, supp_breakdown = support_unit.evaluate_kit_power()
        assert "support" in supp_breakdown
        assert "orb_changing" in supp_breakdown

    def test_dokkan_card_leader_coverage_parsing(self):
        leader_200 = DokkanCard(
            id=2001,
            name="Beast Gohan Lead",
            leader_skill='"Super Heroes" or "Hybrid Saiyans" Category Ki +3 and HP, ATK & DEF +170%, plus an additional HP, ATK & DEF +30% for characters who also belong to the "Movie Heroes" Category',
        )

        # Unit with both base category (Super Heroes) and extra category (Movie Heroes) -> 200%
        full_200_unit = DokkanCard(
            id=2002,
            name="Orange Piccolo",
            categories=["Super Heroes", "Movie Heroes", "Namekians"],
        )
        is_cov, pct, desc = full_200_unit.is_covered_by_leader(leader_200)
        assert is_cov is True
        assert pct == 200.0
        assert "200%" in desc

        # Unit with only base category (Hybrid Saiyans) -> 170%
        sub_170_unit = DokkanCard(
            id=2003,
            name="Future Trunks",
            categories=["Hybrid Saiyans", "Future Saga"],
        )
        is_cov, pct, desc = sub_170_unit.is_covered_by_leader(leader_200)
        assert is_cov is True
        assert pct == 170.0
        assert "170%" in desc

        # Unit with NO matching categories -> False (0%)
        uncovered_unit = DokkanCard(
            id=2004,
            name="Broly",
            categories=["Pure Saiyans", "Planetary Destruction"],
        )
        is_cov, pct, desc = uncovered_unit.is_covered_by_leader(leader_200)
        assert is_cov is False
        assert pct == 0.0

    def test_three_level_priority_team_builder(self):
        """Verifies that TeamBuilder follows: 1) Leader Coverage, 2) Card Kit/Effects, 3) Link Skills."""
        tb = TeamBuilder()

        leader = DokkanCard(
            id=3001,
            name="Leader Unit",
            leader_skill='"Super Heroes" Category Ki +3, HP, ATK & DEF +200%',
            categories=["Super Heroes"],
            links=["Super Saiyan", "Prepared for Battle", "Fierce Battle"],
        )

        # Unit A: Covered by leader + Godly Kit (Guard + 50% DR) + Weak links with leader (1 link)
        unit_a_god_kit = DokkanCard(
            id=3002,
            name="God Kit Tank",
            categories=["Super Heroes"],
            passive_skill="Guards all attacks; reduces damage received by 50%",
            links=["Fierce Battle"],
            rarity=5,
        )

        # Unit B: Covered by leader + Glass cannon / Outdated Kit + Perfect 3 links with leader
        unit_b_glass = DokkanCard(
            id=3003,
            name="Glass Cannon Linker",
            categories=["Super Heroes"],
            passive_skill="ATK +100% at start of turn",
            links=["Super Saiyan", "Prepared for Battle", "Fierce Battle"],
            rarity=4,
        )

        # Unit C: NOT covered by leader + Godly Kit + Perfect 3 links with leader
        unit_c_uncovered = DokkanCard(
            id=3004,
            name="Uncovered God",
            categories=["Majin Power"],
            passive_skill="Guards all attacks; reduces damage received by 50%",
            links=["Super Saiyan", "Prepared for Battle", "Fierce Battle"],
            rarity=5,
        )

        score_a = tb.rate_sub_unit(unit_a_god_kit, leader)
        score_b = tb.rate_sub_unit(unit_b_glass, leader)
        score_c = tb.rate_sub_unit(unit_c_uncovered, leader)

        # Priority 1 Check: Uncovered unit C must be fatal / negative score
        assert score_c < 0.0

        # Priority 2 Check: God Kit Unit A MUST beat Glass Cannon Unit B, even though Unit B links better!
        assert score_a > score_b

    def test_challenge_stage_mission_parsing_and_matching(self):
        """Verifies that MissionParser extracts stage numbers and applies_to_stage filters properly."""
        # 1. Stage-specific mission
        m_stage3 = {
            "id": 33795,
            "name": "Clear Stage 3 with 6 Representatives of Universe 7",
            "description": 'Clear Stage 3 of the Challenge Event "Supreme Magnificent Battle: RE [Universe Survival Saga]" once with 6 "Representatives of Universe 7" Category characters on your team!',
        }
        parsed3 = MissionParser.parse(m_stage3)
        assert parsed3.stage_num == 3
        assert parsed3.applicable_stages == [3]
        assert parsed3.applies_to_stage(3) is True
        assert parsed3.applies_to_stage(2) is False
        assert parsed3.applies_to_stage(1) is False
        assert parsed3.applies_to_stage(None) is True
        assert parsed3.applies_to_stage(0) is True

        # 2. Any stage / general mission
        m_any = {
            "id": 33794,
            "name": "Clear any stage with Rainbow team",
            "description": 'Clear any stage of the Challenge Event "Supreme Magnificent Battle: RE [Universe Survival Saga]" once with an AGL, TEQ, INT, STR and PHY Type character on your team!',
        }
        parsed_any = MissionParser.parse(m_any)
        assert parsed_any.stage_num is None
        assert parsed_any.applicable_stages == []
        assert parsed_any.applies_to_stage(1) is True
        assert parsed_any.applies_to_stage(2) is True
        assert parsed_any.applies_to_stage(3) is True
        assert parsed_any.applies_to_stage(6) is True

        # 3. Multi-stage mission
        m_multi = {
            "id": 99999,
            "name": "Clear Stage 1 and Stage 2",
            "description": "Clear Stage 1 and Stage 2 without items",
        }
        parsed_multi = MissionParser.parse(m_multi)
        assert parsed_multi.applicable_stages == [1, 2]
        assert parsed_multi.applies_to_stage(1) is True
        assert parsed_multi.applies_to_stage(2) is True
        assert parsed_multi.applies_to_stage(3) is False

    def test_challenge_stage_specific_bundling(self):
        """Verifies that MissionBundler isolates missions for a chosen stage and bundles them."""
        missions_raw = [
            # General mission for any stage
            {
                "id": 1,
                "name": "Rainbow Clear",
                "description": "Clear any stage with AGL TEQ INT STR PHY",
            },
            # Stage 3 specific missions
            {
                "id": 2,
                "name": "Stage 3 RoU7",
                "description": 'Clear Stage 3 with 6 "Representatives of Universe 7" Category characters',
            },
            {
                "id": 3,
                "name": "Stage 3 Turn Limit",
                "description": "Clear Stage 3 within 8 turns",
            },
            {
                "id": 4,
                "name": "Stage 3 No Items",
                "description": "Clear Stage 3 without support items",
            },
            # Stage 6 specific missions (must be excluded when playing Stage 3)
            {
                "id": 5,
                "name": "Stage 6 Worthy Rivals",
                "description": 'Clear Stage 6 with 6 "Worthy Rivals" Category characters',
            },
            {
                "id": 6,
                "name": "Stage 6 USS No Items",
                "description": 'Clear Stage 6 with 6 "Universe Survival Saga" Category characters without support items',
            },
        ]

        parsed = [MissionParser.parse(m) for m in missions_raw]

        # Bundle for Stage 3:
        batches_s3 = MissionBundler.bundle_missions(parsed, target_stage=3)
        # All Stage 3 compatible missions + Any stage mission (1, 2, 3, 4) should bundle into 1 single batch
        assert len(batches_s3) == 1
        s3_batch_ids = [m.id for m in batches_s3[0].missions]
        assert set(s3_batch_ids) == {1, 2, 3, 4}
        assert 5 not in s3_batch_ids
        assert 6 not in s3_batch_ids
        assert batches_s3[0].requires_rainbow is True
        assert batches_s3[0].requires_no_items is True
        assert batches_s3[0].max_turns == 8

        # Bundle for Stage 6:
        batches_s6 = MissionBundler.bundle_missions(parsed, target_stage=6)
        # Stage 6 has two conflicting 6-card category missions (Worthy Rivals vs USS) -> 2 batches
        assert len(batches_s6) == 2
        all_s6_ids = [m.id for b in batches_s6 for m in b.missions]
        assert 1 in all_s6_ids
        assert 5 in all_s6_ids
        assert 6 in all_s6_ids
        assert 2 not in all_s6_ids
        assert 3 not in all_s6_ids

    def test_cli_challenge_interactive_stage_selection(self):
        """Verifies that CLI handle_challenge_interactive queries stages and starts ChallengeTask with correct stage."""
        from dokkan_eza_link_farmer.core.bot_engine import BotEngine
        from dokkan_eza_link_farmer.ui.cli import TerminalCLI

        engine = MagicMock(spec=BotEngine)
        engine.dokkandb = MagicMock()
        engine.adb = MagicMock()
        engine.adb.is_connected.return_value = True

        mock_event = {
            "id": 795,
            "name": "Supreme Magnificent Battle [Universe Survival Saga]",
            "category": 20,
            "is_currently_open": True,
        }
        engine.dokkandb.get_challenge_events.return_value = [mock_event]
        engine.dokkandb.get_event_details.return_value = {
            "id": 795,
            "quests": [
                {
                    "quest_id": 795001,
                    "quest_name": "Vs. Master Roshi",
                    "stages": [{"stage_id": 7950015}],
                },
                {
                    "quest_id": 795002,
                    "quest_name": "Vs. Androids #17 & #18",
                    "stages": [{"stage_id": 7950025}],
                },
                {
                    "quest_id": 795003,
                    "quest_name": "Vs. Gohan & Piccolo",
                    "stages": [{"stage_id": 7950035}],
                },
            ],
        }
        engine.dokkandb.get_stage_boss_info.return_value = {
            "phases": [
                {
                    "phase": 1,
                    "bosses": [
                        {
                            "name": "Gohan",
                            "type_name": "Super TEQ",
                            "mechanics": [{"name": "Stun Immunity"}],
                        }
                    ],
                }
            ]
        }
        engine.dokkandb.get_challenge_missions.return_value = [
            {
                "id": 33795,
                "name": "Stage 3 RoU7",
                "description": "Clear Stage 3 with 6 Representatives of Universe 7",
            }
        ]

        cli = TerminalCLI(engine)

        # Test direct CLI args: challenge 795 3 -y
        cli.handle_challenge_interactive(args=["795", "3", "-y"])
        engine.start_challenge_farm.assert_called_once_with(
            target_event=mock_event,
            stage_num=3,
            stage_id=7950035,
            stage_name="Vs. Gohan & Piccolo",
        )

    def test_cli_ai_interactive_challenge_event_selection(self):
        from dokkan_eza_link_farmer.ai.models import BossStage
        from dokkan_eza_link_farmer.ui.cli import TerminalCLI

        engine = MagicMock()
        engine.adb.is_connected.return_value = True

        mock_event = {
            "id": 1728,
            "name": "Union Master",
            "category": 20,
            "event_priority": 2610203,
            "is_currently_open": True,
        }
        engine.dokkandb.get_challenge_events.return_value = [mock_event]
        engine.dokkandb.get_event_details.return_value = {
            "id": 1728,
            "quests": [
                {
                    "quest_id": 1728024,
                    "quest_name": "Joined Forces [5 Required]",
                    "stages": [{"stage_id": 17280244}],
                }
            ],
        }
        engine.dokkandb.get_stage_boss_info.return_value = {
            "event_id": 1728,
            "stage_id": 17280244,
            "event_name": "Union Master",
            "stage_name": "Joined Forces [5 Required]",
            "difficulty": 4,
            "phases": [
                {
                    "phase": 1,
                    "bosses": [
                        {"name": "Super Garlic Jr.", "type_name": "Extreme AGL", "mechanics": []}
                    ],
                }
            ],
        }

        cli = TerminalCLI(engine)

        with patch("questionary.select") as mock_select:
            # 1st select: choose mock_event, 2nd select: choose stage dict
            mock_select.side_effect = [
                MagicMock(ask=MagicMock(return_value=mock_event)),
                MagicMock(
                    ask=MagicMock(
                        return_value={
                            "stage_num": 1,
                            "stage_id": 17280244,
                            "stage_name": "Joined Forces [5 Required]",
                        }
                    )
                ),
            ]
            boss_stage = cli._select_challenge_boss_stage()

            assert isinstance(boss_stage, BossStage)
            assert boss_stage.stage_id == 17280244
            assert boss_stage.event_name == "Union Master"

        with (
            patch.object(cli, "_select_challenge_boss_stage", return_value=boss_stage),
            patch.object(cli, "handle_ai_endgame_run") as mock_run,
        ):
            cli.handle_ai_interactive(["run"])
            mock_run.assert_called_once_with(boss_stage)

    def test_render_team_presentation_rotations_table_and_markdown_panel(self):
        """Verifies CLI rendering of rotations table with proper badge labeling and markdown tactical panel."""
        import copy

        from rich.markdown import Markdown
        from rich.panel import Panel
        from rich.table import Table

        from dokkan_eza_link_farmer.ai.models import DokkanCard, RotationPair, TeamRecommendation
        from dokkan_eza_link_farmer.ui.cli import TerminalCLI

        engine = MagicMock()
        cli = TerminalCLI(engine)

        lead = DokkanCard(id=1029191, name="Goku & Vegeta", subname="Strongest", element=44)
        friend = copy.copy(lead)
        friend.is_friend_leader = True

        sub1 = DokkanCard(id=101, name="Beerus & Whis", element=23)
        sub2 = DokkanCard(id=102, name="Beerus", element=11)
        sub3 = DokkanCard(id=103, name="SSG Goku", element=11)
        sub4 = DokkanCard(id=104, name="SSGSS Goku", element=11)
        sub5 = DokkanCard(id=105, name="Goku Black & Zamasu", element=23)

        rec = TeamRecommendation(
            leader=lead,
            friend_leader=friend,
            all_cards=[lead, sub1, sub2, sub3, sub4, sub5],
            rotation_a=RotationPair(
                slot1=sub1,
                slot2=sub2,
                shared_links=["Godly Power"],
                shared_ki_links=[],
                synergy_score=8.0,
            ),
            rotation_b=RotationPair(
                slot1=sub3,
                slot2=sub4,
                shared_links=["Warrior Gods"],
                shared_ki_links=[],
                synergy_score=7.5,
            ),
            floaters=[lead, sub5, friend],
            tactical_analysis="### 🛡️ Rotazioni\n- **Rotazione A**: Mantieni Beerus & Whis in Slot 1.",
        )

        printed_objects = []
        with patch.object(cli.console, "print", side_effect=printed_objects.append):
            cli._render_team_presentation(rec)

        # 1. Find the rotations table
        rot_tables = [
            obj
            for obj in printed_objects
            if isinstance(obj, Table) and "Rotazione" in [c.header for c in obj.columns]
        ]
        assert len(rot_tables) == 1
        table = rot_tables[0]
        assert table.expand is True

        # Check column properties
        col_names = [c.header for c in table.columns]
        assert "Rotazione" in col_names
        assert "Posizione" in col_names
        assert "Personaggio" in col_names

        p_col = next(c for c in table.columns if c.header == "Personaggio")
        assert p_col.no_wrap is False

        # 2. Verify distinction between Leader and Friend in floaters
        floater_cells = [str(cell) for cell in table.columns[2]._cells]
        lead_floater = next((c for c in floater_cells if "Leader • Floater" in c), None)
        friend_floater = next((c for c in floater_cells if "Friend • Floater" in c), None)
        assert lead_floater is not None
        assert friend_floater is not None

        # 3. Verify tactical panel wraps content in Markdown
        panels = [obj for obj in printed_objects if isinstance(obj, Panel)]
        tactical_panel = next((p for p in panels if "⚔️" in str(p.title)), None)
        assert tactical_panel is not None
        assert isinstance(tactical_panel.renderable, Markdown)
