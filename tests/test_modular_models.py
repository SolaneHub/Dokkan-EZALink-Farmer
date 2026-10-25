"""Unit and integration tests for modularized ai domain models.

Validates:
1. Circular import immunity across all ai.* submodules under various import orders.
2. Backward compatibility of ai.models facade and ai.__init__ facade.
3. Schema and serialization immutability for DokkanCard, BossStage, and TeamRecommendation.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

import dokkan_eza_link_farmer.ai as ai_pkg
import dokkan_eza_link_farmer.ai.boss_models as boss_models
import dokkan_eza_link_farmer.ai.card_models as card_models
import dokkan_eza_link_farmer.ai.models as models_facade


class TestModularExtraction:
    """Tests modular separation between boss_models and card_models."""

    def test_boss_models_has_no_dependency_on_card_models(self) -> None:
        """boss_models must not import card_models or models."""
        import inspect

        source = inspect.getsource(boss_models)
        assert "card_models" not in source
        assert "DokkanCard" not in source

    def test_card_models_has_no_dependency_on_models_facade(self) -> None:
        """card_models must not import the models facade."""
        import inspect

        source = inspect.getsource(card_models)
        assert "dokkan_eza_link_farmer.ai.models" not in source

    @pytest.mark.parametrize(
        "import_sequence",
        [
            [
                "dokkan_eza_link_farmer.ai.boss_models",
                "dokkan_eza_link_farmer.ai.card_models",
                "dokkan_eza_link_farmer.ai.models",
            ],
            [
                "dokkan_eza_link_farmer.ai.card_models",
                "dokkan_eza_link_farmer.ai.boss_models",
                "dokkan_eza_link_farmer.ai.models",
            ],
            [
                "dokkan_eza_link_farmer.ai.models",
                "dokkan_eza_link_farmer.ai.boss_models",
                "dokkan_eza_link_farmer.ai.card_models",
            ],
            [
                "dokkan_eza_link_farmer.ai",
                "dokkan_eza_link_farmer.ai.models",
                "dokkan_eza_link_farmer.ai.card_models",
            ],
            ["dokkan_eza_link_farmer.ai.boss_models", "dokkan_eza_link_farmer.ai"],
        ],
    )
    def test_no_circular_imports_in_isolated_process(self, import_sequence: list[str]) -> None:
        """Runs fresh Python processes importing submodules in various orders."""
        code = "; ".join(f"__import__({mod!r})" for mod in import_sequence)
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Import failed with stderr: {result.stderr}"


class TestBackwardCompatibility:
    """Tests that ai.models and ai.__init__ preserve 100% of previous exports."""

    def test_models_facade_all_symbols(self) -> None:
        expected_symbols = {
            "AIModelFamily",
            "SupportedAIModel",
            "AIConfig",
            "PassiveTags",
            "SATags",
            "LeaderSkillSpec",
            "CardForm",
            "DokkanCard",
            "RotationPair",
            "TeamRecommendation",
            "BossMechanic",
            "BossEnemy",
            "BossPhase",
            "BossStage",
            "ChallengeStageInfo",
            "FailureReport",
            "TYPE_NAMES",
            "parse_dodge_percentage_from_text",
            "infer_boss_categories_from_name",
        }
        for sym in expected_symbols:
            assert hasattr(models_facade, sym), f"models_facade is missing symbol: {sym}"
            assert sym in models_facade.__all__, f"Symbol {sym} missing from models_facade.__all__"

    def test_symbol_identity_across_modules(self) -> None:
        assert models_facade.DokkanCard is card_models.DokkanCard
        assert models_facade.CardForm is card_models.CardForm
        assert models_facade.LeaderSkillSpec is card_models.LeaderSkillSpec
        assert models_facade.PassiveTags is card_models.PassiveTags
        assert models_facade.SATags is card_models.SATags
        assert models_facade.TeamRecommendation is card_models.TeamRecommendation
        assert models_facade.BossStage is boss_models.BossStage
        assert models_facade.BossPhase is boss_models.BossPhase
        assert models_facade.BossEnemy is boss_models.BossEnemy
        assert models_facade.BossMechanic is boss_models.BossMechanic
        assert models_facade.ChallengeStageInfo is boss_models.ChallengeStageInfo
        assert models_facade.TYPE_NAMES is boss_models.TYPE_NAMES
        assert (
            models_facade.infer_boss_categories_from_name
            is boss_models.infer_boss_categories_from_name
        )

    def test_ai_pkg_reexports(self) -> None:
        for sym in [
            "DokkanCard",
            "BossStage",
            "BossPhase",
            "BossEnemy",
            "BossMechanic",
            "ChallengeStageInfo",
            "CardForm",
            "LeaderSkillSpec",
            "PassiveTags",
            "SATags",
            "TeamRecommendation",
            "TYPE_NAMES",
            "infer_boss_categories_from_name",
            "parse_dodge_percentage_from_text",
        ]:
            assert hasattr(ai_pkg, sym), f"ai package is missing symbol: {sym}"
            assert sym in ai_pkg.__all__, f"{sym} missing from ai.__all__"


class TestSchemaSerializationImmutability:
    """Validates that to_dict and from_dict behavior is 100% preserved."""

    def test_dokkan_card_serialization_roundtrip(self) -> None:
        raw_card = {
            "id": 10234,
            "name": "Super Saiyan Goku",
            "subname": "Pinnacle of Fury",
            "rarity": 5,
            "element": 13,  # Super STR
            "element_name": "Super STR",
            "card_class": "Super",
            "leader_skill": "Super STR Ki +3 and HP, ATK & DEF +130%",
            "leader_spec": {
                "main_category_ids": [17],
                "extra_category_ids": [],
                "sub_elements_classes": [],
                "base_boost_pct": 170.0,
                "extra_boost_pct": 30.0,
                "sub_boost_pct": 0.0,
                "hp_stat_pct": 170.0,
                "atk_stat_pct": 170.0,
                "def_stat_pct": 170.0,
            },
            "passive_skill": "ATK & DEF +150%; high chance of evading enemy's attack; guards all attacks",
            "super_attack": "Greatly raises DEF for 1 turn and causes immense damage",
            "categories": ["Pure Saiyans", "Super Saiyans", "Goku's Family"],
            "category_ids": [17, 18, 22],
            "links": ["Super Saiyan", "Prepared for Battle", "Golden Warrior", "Fierce Battle"],
            "link_ids": [1, 5, 8, 12],
            "thumb_url": "https://example.com/thumb.png",
            "has_eza": True,
            "is_eza": True,
            "is_seza": False,
            "is_rainbow": True,
            "potential_percent": 100,
            "swipe_page": 1,
            "grid_slot": 3,
            "is_friend_leader": False,
            "standby_skill_name": "",
            "standby_skill_condition": "",
            "standby_skill_effect": "",
            "active_skill_name": "Rage",
            "active_skill_condition": "When HP is 50% or less",
            "active_skill_effect": "Rages for 1 turn",
            "base_form": {
                "form_id": 10234,
                "form_index": 0,
                "form_name": "Base Goku",
                "element": 13,
                "links": ["Super Saiyan", "Fierce Battle"],
                "link_ids": [1, 12],
                "passive_skill_text": "Base passive",
                "super_attack_text": "Base SA",
                "passive_tags": {
                    "slot1_viable": True,
                    "dr_base_percent": 50,
                    "permanent_dr_percent": 30,
                    "dr_turns_limit": None,
                    "is_dr_permanent": True,
                    "dodge_chance_percent": 50,
                    "dodge_turns_limit": None,
                    "is_dodge_permanent": True,
                    "has_guard": True,
                    "is_guard_permanent": True,
                    "is_guard_unconditional": True,
                    "guard_turns_limit": None,
                    "has_revive": False,
                    "has_taunt": False,
                    "has_support": False,
                    "has_standby": False,
                    "has_domain": False,
                    "has_orb_changing": False,
                    "has_on_hit_defense": False,
                    "has_on_hit_guard": False,
                    "has_on_hit_dr": False,
                    "has_on_hit_def": False,
                    "is_once_only_dr": False,
                    "pre_hit_guard": False,
                    "pre_hit_dr_percent": 0,
                    "has_slot_2_3_buff": False,
                    "has_enemy_conditional_defense": False,
                    "enemy_conditional_categories": [],
                    "enemy_conditional_classes": [],
                    "enemy_conditional_dr": 0,
                    "enemy_conditional_guard": False,
                    "enemy_conditional_dodge": 0,
                },
                "sa_tags": {
                    "stacks_def": True,
                    "stacks_atk": False,
                    "raise_def_turns": 1,
                    "raise_atk_turns": 0,
                    "is_aoe": False,
                },
                "min_turn": 1,
            },
            "transformations": [],
        }

        card = card_models.DokkanCard.from_dict(raw_card)
        serialized = card.to_dict()

        assert serialized["id"] == raw_card["id"]
        assert serialized["name"] == raw_card["name"]
        assert serialized["rarity"] == raw_card["rarity"]
        assert serialized["is_rainbow"] is True
        assert serialized["potential_percent"] == 100
        assert serialized["leader_spec"]["base_boost_pct"] == 170.0
        assert serialized["base_form"]["passive_tags"]["dr_base_percent"] == 50
        assert serialized["active_skill_name"] == "Rage"
        assert serialized["active_skill_condition"] == "When HP is 50% or less"
        assert serialized["active_skill_effect"] == "Rages for 1 turn"

        # Hydrate again and assert equivalence
        rehydrated = card_models.DokkanCard.from_dict(serialized)
        assert rehydrated.id == card.id
        assert rehydrated.name == card.name
        assert rehydrated.active_skill_name == "Rage"
        assert rehydrated.active_skill_condition == "When HP is 50% or less"
        assert rehydrated.active_skill_effect == "Rages for 1 turn"
        assert rehydrated.to_dict() == serialized

    def test_boss_stage_serialization_roundtrip(self) -> None:
        stage_data = {
            "stage_id": 9901,
            "event_id": 100,
            "stage_name": "Ultimate Clash",
            "event_name": "Red Zone",
            "difficulty": 3,
            "total_battles": 2,
            "phases": [
                {
                    "phase_index": 1,
                    "phase": 1,
                    "battle_index": 1,
                    "round_index": 1,
                    "is_new_battle": True,
                    "element": 0,
                    "element_name": "AGL",
                    "cancels_dodge": True,
                    "has_aoe": False,
                    "locks_slots": True,
                    "nullifies_stun_seal": True,
                    "nullifies_atk_down": True,
                    "nullifies_def_down": True,
                    "hp": 50000000,
                    "atk": 150000,
                    "def_stat": 80000,
                    "actions_per_turn": 8,
                    "estimated_sa_damage": 800000,
                    "special_skills": ["Super Attack: Final Flash"],
                    "bosses": [
                        {
                            "card_id": 5001,
                            "name": "Super Vegeta",
                            "subname": "Pure Pride",
                            "element": 0,
                            "type_name": "AGL",
                            "hp": 50000000,
                            "atk": 150000,
                            "def_stat": 80000,
                            "actions_per_turn": 8,
                            "categories": ["Pure Saiyans"],
                            "category_ids": [17],
                            "card_class": "Super",
                            "mechanics": [
                                {
                                    "id": 1,
                                    "name": "Cancels Dodge",
                                    "description": "Evading attacks disabled",
                                }
                            ],
                        }
                    ],
                }
            ],
        }

        stage = boss_models.BossStage.from_dict(stage_data)
        serialized = stage.to_dict()

        assert serialized["stage_id"] == 9901
        assert len(serialized["phases"]) == 1
        assert serialized["phases"][0]["cancels_dodge"] is True
        assert serialized["phases"][0]["bosses"][0]["name"] == "Super Vegeta"

        rehydrated = boss_models.BossStage.from_dict(serialized)
        assert rehydrated.stage_id == stage.stage_id
        assert rehydrated.phases[0].cancels_dodge == stage.phases[0].cancels_dodge

    def test_empty_and_minimal_inputs(self) -> None:
        minimal_card = card_models.DokkanCard.from_dict({"id": 1, "name": "Goku"})
        assert minimal_card.id == 1
        assert minimal_card.name == "Goku"
        assert minimal_card.element == 0
        assert minimal_card.element_name == "AGL"
        assert minimal_card.categories == []
        assert minimal_card.links == []
        assert minimal_card.base_form is not None
        assert minimal_card.base_form.form_id == 1

        # Idempotence: from_dict on already instantiated DokkanCard returns itself
        assert card_models.DokkanCard.from_dict(minimal_card) is minimal_card

        with pytest.raises(TypeError):
            card_models.DokkanCard.from_dict(None)  # type: ignore

        assert card_models.PassiveTags.from_dict(None) == card_models.PassiveTags()
        assert card_models.SATags.from_dict(None) == card_models.SATags()
        assert card_models.LeaderSkillSpec.from_dict(None) == card_models.LeaderSkillSpec()
        assert card_models.CardForm.from_dict(None) == card_models.CardForm()
        assert boss_models.BossEnemy.from_dict(None) == boss_models.BossEnemy(
            card_id=0, name="Unknown Boss"
        )
        assert boss_models.BossPhase.from_dict(None) == boss_models.BossPhase()
        assert boss_models.BossStage.from_dict(None) == boss_models.BossStage(
            stage_id=0, event_id=0, stage_name="", event_name=""
        )

        assert boss_models.infer_boss_categories_from_name("") == []
        assert boss_models.infer_boss_categories_from_name("Broly") == [
            "Movie Bosses",
            "Pure Saiyans",
        ]
        assert card_models.parse_dodge_percentage_from_text("") == 0
        assert card_models.parse_dodge_percentage_from_text("high chance of evading") == 50
        assert card_models.parse_dodge_percentage_from_text("great chance to dodge") == 70

    def test_domain_models_idempotent_from_dict(self) -> None:
        """Calling from_dict on an already instantiated object returns itself."""
        p_tag = card_models.PassiveTags(dr_base_percent=50)
        assert card_models.PassiveTags.from_dict(p_tag) is p_tag

        sa_tag = card_models.SATags(stacks_def=True)
        assert card_models.SATags.from_dict(sa_tag) is sa_tag

        lead_spec = card_models.LeaderSkillSpec(base_boost_pct=200.0)
        assert card_models.LeaderSkillSpec.from_dict(lead_spec) is lead_spec

        form = card_models.CardForm(form_id=10, form_name="Base")
        assert card_models.CardForm.from_dict(form) is form

        b_enemy = boss_models.BossEnemy(card_id=999, name="Broly")
        assert boss_models.BossEnemy.from_dict(b_enemy) is b_enemy

        b_phase = boss_models.BossPhase(phase=2, element_name="TEQ")
        assert boss_models.BossPhase.from_dict(b_phase) is b_phase

        b_stage = boss_models.BossStage(
            stage_id=50, event_id=1, stage_name="RZ Broly", event_name="Red Zone"
        )
        assert boss_models.BossStage.from_dict(b_stage) is b_stage

    def test_team_recommendation_serialization_roundtrip(self) -> None:
        """Validates TeamRecommendation serialization and rehydration with nested models."""
        c1 = card_models.DokkanCard.from_dict({"id": 1, "name": "Leader Goku"})
        c2 = card_models.DokkanCard.from_dict({"id": 2, "name": "Slot2 Vegeta"})
        c3 = card_models.DokkanCard.from_dict({"id": 3, "name": "Slot1 Gohan"})
        c4 = card_models.DokkanCard.from_dict({"id": 4, "name": "Slot2 Piccolo"})
        c5 = card_models.DokkanCard.from_dict({"id": 5, "name": "Floater 1"})
        c6 = card_models.DokkanCard.from_dict({"id": 6, "name": "Floater 2"})
        c7 = card_models.DokkanCard.from_dict({"id": 7, "name": "Friend Leader"})

        rot_a = card_models.RotationPair(
            slot1=c1,
            slot2=c2,
            shared_links=["Super Saiyan"],
            shared_ki_links=[],
            synergy_score=15.0,
        )
        rot_b = card_models.RotationPair(
            slot1=c3,
            slot2=c4,
            shared_links=["Prepared for Battle"],
            shared_ki_links=[],
            synergy_score=12.0,
        )
        stage = boss_models.BossStage(
            stage_id=9901, event_id=100, stage_name="Ultimate Clash", event_name="Red Zone"
        )

        rec = card_models.TeamRecommendation(
            leader=c1,
            friend_leader=c7,
            rotation_a=rot_a,
            rotation_b=rot_b,
            floaters=[c5, c6, c7],
            all_cards=[c1, c2, c3, c4, c5, c6, c7],
            tactical_analysis="Focus on turn 1 survivability",
            recommended_items=["Whis"],
            turn_plan=["Turn 1: slot 1 guard"],
            ai_reasoning="High synergy and guard coverage",
            boss_stage=stage,
        )

        d = rec.to_dict()
        assert d["leader"]["name"] == "Leader Goku"
        assert d["boss_stage"]["stage_id"] == 9901

        rehydrated = card_models.TeamRecommendation.from_dict(d)
        assert rehydrated.leader.name == "Leader Goku"
        assert rehydrated.rotation_a.slot1.id == 1
        assert rehydrated.boss_stage is not None
        assert rehydrated.boss_stage.stage_id == 9901
        assert card_models.TeamRecommendation.from_dict(rehydrated) is rehydrated

        # Also verify with boss_stage as None
        rec_no_stage = card_models.TeamRecommendation(
            leader=c1,
            friend_leader=c7,
            rotation_a=rot_a,
            rotation_b=rot_b,
            floaters=[],
            all_cards=[c1],
            tactical_analysis="",
            boss_stage=None,
        )
        d_none = rec_no_stage.to_dict()
        assert d_none["boss_stage"] is None
        rehydrated_none = card_models.TeamRecommendation.from_dict(d_none)
        assert rehydrated_none.boss_stage is None

    def test_wildcard_imports_parity(self) -> None:
        """Verifies wildcard import behavior strictly matches __all__ without leakage."""
        loc_models: dict[str, object] = {}
        exec("from dokkan_eza_link_farmer.ai.models import *", {}, loc_models)
        assert set(loc_models.keys()) == set(models_facade.__all__)

        loc_boss: dict[str, object] = {}
        exec("from dokkan_eza_link_farmer.ai.boss_models import *", {}, loc_boss)
        assert set(loc_boss.keys()) == set(boss_models.__all__)

        loc_card: dict[str, object] = {}
        exec("from dokkan_eza_link_farmer.ai.card_models import *", {}, loc_card)
        assert set(loc_card.keys()) == set(card_models.__all__)

    def test_pickle_compatibility(self) -> None:
        """Verifies pickle roundtrip and legacy symbol loading via ai.models namespace."""
        import pickle

        card = card_models.DokkanCard.from_dict({"id": 100, "name": "Pickle Goku"})
        p_data = pickle.dumps(card)
        loaded_card = pickle.loads(p_data)
        assert loaded_card.id == 100
        assert loaded_card.name == "Pickle Goku"

        # Simulates loading an object serialized under the legacy ai.models path
        legacy_stream = b"cdokkan_eza_link_farmer.ai.models\nDokkanCard\n."
        loaded_cls = pickle.loads(legacy_stream)
        assert loaded_cls is card_models.DokkanCard

    def test_pyinstaller_hidden_imports(self) -> None:
        """Verifies build_exe.py has hidden-import declarations for both new modular submodules."""
        import ast
        from pathlib import Path

        build_file = Path(__file__).resolve().parent.parent / "build_exe.py"
        assert build_file.exists(), "build_exe.py must exist in repo root"
        tree = ast.parse(build_file.read_text(encoding="utf-8"))

        hidden_imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.List):
                for i, elt in enumerate(node.elts):
                    if (
                        isinstance(elt, ast.Constant)
                        and elt.value == "--hidden-import"
                        and i + 1 < len(node.elts)
                    ):
                        next_elt = node.elts[i + 1]
                        if isinstance(next_elt, ast.Constant):
                            hidden_imports.append(str(next_elt.value))

        assert "dokkan_eza_link_farmer.ai.boss_models" in hidden_imports
        assert "dokkan_eza_link_farmer.ai.card_models" in hidden_imports
        assert "dokkan_eza_link_farmer.ai.models" in hidden_imports
        assert "dokkan_eza_link_farmer.ai.synergy" in hidden_imports
        assert "dokkan_eza_link_farmer.ai.llm_advisor" in hidden_imports
        assert "dokkan_eza_link_farmer.ai.solver" in hidden_imports
        assert "dokkan_eza_link_farmer.ai.syncer" in hidden_imports
        assert "dokkan_eza_link_farmer.ai.formatters" in hidden_imports
        assert "dokkan_eza_link_farmer.ai.boss_catalog" in hidden_imports
        assert "dokkan_eza_link_farmer.ai.support_catalog" in hidden_imports
        assert "dokkan_eza_link_farmer.ai.endgame" in hidden_imports

    def test_dokkan_card_full_skill_fidelity(self) -> None:
        """Ensures active skill, standby skill, and friend leader fields roundtrip without data loss."""
        card = card_models.DokkanCard(
            id=10999,
            name="Spirit Bomb Goku & SSJ Vegeta",
            is_friend_leader=True,
            active_skill_name="Super Spirit Bomb",
            active_skill_condition="Can be activated when HP is 50% or less from the 5th turn",
            active_skill_effect="Causes ultimate damage and raises allies' ATK by 50% for 1 turn",
            standby_skill_name="Finish Attack Standby",
            standby_skill_condition="Standby mode for 5 turns",
            standby_skill_effect="Guards all attacks and charges Ki",
            is_tank_override=True,
        )
        serialized = card.to_dict()
        assert serialized["is_friend_leader"] is True
        assert serialized["is_tank_override"] is True
        assert serialized["active_skill_name"] == "Super Spirit Bomb"
        assert serialized["standby_skill_name"] == "Finish Attack Standby"

        rehydrated = card_models.DokkanCard.from_dict(serialized)
        assert rehydrated.is_friend_leader is True
        assert rehydrated.is_tank_override is True
        assert rehydrated.active_skill_name == "Super Spirit Bomb"
        assert (
            rehydrated.active_skill_condition
            == "Can be activated when HP is 50% or less from the 5th turn"
        )
        assert (
            rehydrated.active_skill_effect
            == "Causes ultimate damage and raises allies' ATK by 50% for 1 turn"
        )
        assert rehydrated.standby_skill_name == "Finish Attack Standby"
        assert rehydrated.standby_skill_condition == "Standby mode for 5 turns"
        assert rehydrated.standby_skill_effect == "Guards all attacks and charges Ki"

    def test_dokkan_card_is_tank_override_variations(self) -> None:
        """Verifies is_tank_override preserves True, False, None, strings, and ints cleanly."""
        import json

        card_t = card_models.DokkanCard(id=1, name="Goku", is_tank_override=True)
        assert card_t.to_dict()["is_tank_override"] is True
        assert card_models.DokkanCard.from_dict(card_t.to_dict()).is_tank_override is True

        card_f = card_models.DokkanCard(id=2, name="Vegeta", is_tank_override=False)
        assert card_f.to_dict()["is_tank_override"] is False
        assert card_models.DokkanCard.from_dict(card_f.to_dict()).is_tank_override is False

        card_n = card_models.DokkanCard(id=3, name="Piccolo", is_tank_override=None)
        assert card_n.to_dict()["is_tank_override"] is None
        assert card_models.DokkanCard.from_dict(card_n.to_dict()).is_tank_override is None

        # String and int inputs
        assert (
            card_models.DokkanCard.from_dict(
                {"id": 4, "name": "G", "is_tank_override": "true"}
            ).is_tank_override
            is True
        )
        assert (
            card_models.DokkanCard.from_dict(
                {"id": 5, "name": "G", "is_tank_override": "false"}
            ).is_tank_override
            is False
        )
        assert (
            card_models.DokkanCard.from_dict(
                {"id": 6, "name": "G", "is_tank_override": 1}
            ).is_tank_override
            is True
        )
        assert (
            card_models.DokkanCard.from_dict(
                {"id": 7, "name": "G", "is_tank_override": 0}
            ).is_tank_override
            is False
        )

        # Full JSON string roundtrip
        json_str = json.dumps(card_t.to_dict())
        rehydrated = card_models.DokkanCard.from_dict(json.loads(json_str))
        assert rehydrated.is_tank_override is True

    def test_models_deserialization_handles_null_json_fields(self) -> None:
        """Verifies null / None values in JSON payloads do not raise TypeError across models."""
        c = card_models.DokkanCard.from_dict(
            {
                "id": None,
                "name": None,
                "rarity": None,
                "element": None,
                "potential_percent": None,
                "swipe_page": None,
                "grid_slot": None,
                "is_tank_override": None,
                "categories": None,
                "category_ids": None,
                "links": None,
                "link_ids": None,
            }
        )
        assert c.id == 0
        assert c.name == "Unknown"
        assert c.rarity == 4
        assert c.element == 0
        assert c.potential_percent == 0
        assert c.swipe_page == 0
        assert c.grid_slot == 0
        assert c.is_tank_override is None
        assert c.categories == []
        assert c.links == []

        p = card_models.PassiveTags.from_dict(
            {
                "dr_base_percent": None,
                "permanent_dr_percent": None,
                "enemy_conditional_categories": None,
                "enemy_conditional_classes": None,
            }
        )
        assert p.dr_base_percent == 0
        assert p.permanent_dr_percent == 0
        assert p.enemy_conditional_categories == []

        sa = card_models.SATags.from_dict(
            {
                "stacks_def": None,
                "raise_def_turns": None,
            }
        )
        assert sa.stacks_def is False
        assert sa.raise_def_turns == 0

        ls = card_models.LeaderSkillSpec.from_dict(
            {
                "base_boost_pct": None,
                "extra_boost_pct": None,
                "main_category_ids": None,
            }
        )
        assert ls.base_boost_pct == 170.0
        assert ls.extra_boost_pct == 30.0
        assert ls.main_category_ids == []

        cf = card_models.CardForm.from_dict(
            {
                "form_id": None,
                "form_name": None,
                "element": None,
                "links": None,
            }
        )
        assert cf.form_id == 0
        assert cf.form_name == ""
        assert cf.links == []

        be = boss_models.BossEnemy.from_dict(
            {
                "card_id": None,
                "name": None,
                "hp": None,
                "element": None,
                "categories": None,
                "mechanics": None,
            }
        )
        assert be.card_id == 0
        assert be.name == "Unknown Boss"
        assert be.categories == []
        assert be.mechanics == []

        bp = boss_models.BossPhase.from_dict(
            {
                "phase_index": None,
                "bosses": None,
                "special_skills": None,
                "actions_per_turn": None,
                "element": None,
            }
        )
        assert bp.phase_index == 1
        assert bp.bosses == []
        assert bp.special_skills == []

        bs = boss_models.BossStage.from_dict(
            {
                "stage_id": None,
                "difficulty": None,
                "total_battles": None,
                "phases": None,
            }
        )
        assert bs.stage_id == 0
        assert bs.difficulty == 1
        assert bs.total_battles == 1
        assert bs.phases == []

        rot = card_models.RotationPair.from_dict(
            {
                "slot1": c,
                "slot2": c,
                "shared_links": None,
                "shared_ki_links": None,
                "synergy_score": None,
            }
        )
        assert rot.shared_links == []
        assert rot.shared_ki_links == []
        assert rot.synergy_score == 0.0

        rec = card_models.TeamRecommendation.from_dict(
            {
                "leader": c,
                "friend_leader": c,
                "rotation_a": rot,
                "rotation_b": rot,
                "floaters": None,
                "all_cards": None,
                "recommended_items": None,
                "turn_plan": None,
                "target_missions": None,
            }
        )
        assert rec.floaters == []
        assert rec.all_cards == []
        assert rec.recommended_items == []
        assert rec.turn_plan == []

    def test_leaderskill_spec_float_precision_and_strings(self) -> None:
        """Verifies LeaderSkillSpec parses floats and string representations without raising ValueError."""
        spec_data = {
            "main_category_ids": [1, 2],
            "base_boost_pct": 170.5,
            "extra_boost_pct": "30.0",
            "hp_stat_pct": "200.0",
        }
        spec = card_models.LeaderSkillSpec.from_dict(spec_data)
        assert spec.base_boost_pct == 170.5
        assert spec.extra_boost_pct == 30.0
        assert spec.hp_stat_pct == 200.0
        assert isinstance(spec.base_boost_pct, float)
        assert isinstance(spec.extra_boost_pct, float)

    def test_boss_enemy_zero_def_preservation(self) -> None:
        """Verifies explicit 0 values for boss stats are preserved instead of falling back to legacy keys."""
        boss_data = {
            "card_id": 500,
            "name": "Glass Cannon Boss",
            "def_stat": 0,
            "defence": 99999,
            "actions_per_turn": 0,
            "multi_atk_num": 5,
        }
        boss = boss_models.BossEnemy.from_dict(boss_data)
        assert boss.def_stat == 0
        assert boss.actions_per_turn == 0

    def test_synergy_rotation_pair_from_dict_direct(self) -> None:
        """Verifies RotationPair.from_dict hydrates card instances cleanly using card_models."""
        from dokkan_eza_link_farmer.ai.synergy import RotationPair

        pair_data = {
            "slot1": {"id": 101, "name": "Partner A"},
            "slot2": {"id": 102, "name": "Partner B"},
            "shared_links": ["Super Saiyan"],
            "shared_ki_links": ["Prepared for Battle"],
            "synergy_score": 14.5,
        }
        rot_pair = RotationPair.from_dict(pair_data)
        assert isinstance(rot_pair.slot1, card_models.DokkanCard)
        assert isinstance(rot_pair.slot2, card_models.DokkanCard)
        assert rot_pair.slot1.name == "Partner A"
        assert rot_pair.slot2.name == "Partner B"
        assert rot_pair.synergy_score == 14.5
