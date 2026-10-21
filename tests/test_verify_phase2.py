"""Pytest test suite converted from scripts/verify_phase2_live.py."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock, patch

from dokkan_eza_link_farmer.ai.box_scanner import (
    CANONICAL_BOX_PATH,
    DEFAULT_BOX_SCAN_LOG_PATH,
    DEFAULT_USER_BOX_PATH,
)
from dokkan_eza_link_farmer.ai.models import (
    BossEnemy,
    BossMechanic,
    BossPhase,
    BossStage,
)
from dokkan_eza_link_farmer.ai.syncer import DokkanSyncer


def test_supabase_thumbnail_formula_and_download():
    """Verify Supabase thumbnail ID and URL calculations."""
    with tempfile.TemporaryDirectory() as tmpdir:
        syncer = DokkanSyncer(cache_dir=tmpdir)
        sample_card_id = 1012901  # LR Gogeta
        thumb_id = syncer.get_thumb_id(sample_card_id)
        assert thumb_id == "1012900"

        thumb_url = syncer.get_thumb_url(sample_card_id)
        assert "1012900" in thumb_url

        # Test download with mock or network fallback
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"fake-png-thumbnail-bytes-" * 20
        with patch("requests.get", return_value=mock_resp):
            downloaded = syncer.sync_thumbnails(
                cards=[{"id": sample_card_id}],
                max_workers=1,
                limit=1,
            )
            assert downloaded == 1
            target_path = os.path.join(syncer.thumbs_dir, f"card_{thumb_id}_thumb.png")
            assert os.path.exists(target_path)
            assert os.path.getsize(target_path) > 100


def test_catalog_chunks_and_rarity_filtering():
    """Verify catalog chunk fetching and rarity filtering."""
    with tempfile.TemporaryDirectory() as tmpdir:
        syncer = DokkanSyncer(cache_dir=tmpdir)
        sample_chunk = [
            {"id": 1001, "name": "LR Vegito", "rarity": 5},
            {"id": 1002, "name": "UR Gogeta", "rarity": 4},
            {"id": 1003, "name": "SR Raditz", "rarity": 3},
            {"id": 1004, "name": "R Saibaman", "rarity": 2},
        ]
        with patch("requests.get") as mock_get:
            resp1 = MagicMock(status_code=200)
            resp1.json.return_value = sample_chunk
            resp2 = MagicMock(status_code=200)
            resp2.json.return_value = []
            resp3 = MagicMock(status_code=200)
            resp3.json.return_value = sample_chunk
            resp4 = MagicMock(status_code=200)
            resp4.json.return_value = []
            mock_get.side_effect = [resp1, resp2, resp3, resp4]

            catalog = syncer.sync_catalog(force=True)
            assert len(catalog) == 3
            ids = [c["id"] for c in catalog]
            assert 1001 in ids
            assert 1002 in ids
            assert 1003 in ids
            assert 1004 not in ids

            catalog_ur_lr = syncer.sync_catalog(force=True, rarities=(4, 5))
            assert len(catalog_ur_lr) == 2
            assert 1003 not in [c["id"] for c in catalog_ur_lr]


def test_sample_card_tactical_parsing():
    """Verify tactical passive, SA tags, and LeaderSkillSpec generation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        syncer = DokkanSyncer(cache_dir=tmpdir)
        mock_detail = {
            "id": 1012901,
            "name": "Super Saiyan Goku (Angel) & Super Saiyan Vegeta (Angel)",
            "subname": "Fused Fighting Force",
            "rarity": 5,
            "element": 4,
            "leader_skill": "Fusion Category Ki +3 and HP, ATK & DEF +170%",
            "passive_skill_description": "ATK & DEF +120%; guards all attacks for 3 turns; reduces damage received by 30%",
            "sa_description": "Causes colossal damage and greatly raises DEF for 1 turn",
            "link_ids": [1, 2],
            "category_ids": [10, 20],
        }

        eza_card = syncer.build_dokkan_card(
            mock_detail, is_eza=True, is_seza=False, is_rainbow=True
        )
        assert eza_card.base_form is not None
        assert eza_card.base_form.passive_tags is not None
        assert eza_card.base_form.passive_tags.has_guard is True
        assert eza_card.base_form.passive_tags.dr_base_percent == 30
        assert eza_card.leader_spec is not None


def test_box_scanner_paths():
    """Verify canonical, default box and debug log paths."""
    assert DEFAULT_USER_BOX_PATH.endswith(os.path.join(".dokkan-farmer", "cache", "user_box.json"))
    assert CANONICAL_BOX_PATH == "config/box.json"
    assert DEFAULT_BOX_SCAN_LOG_PATH.endswith(os.path.join(".dokkan-farmer", "box_scan.log"))


def test_boss_stage_and_boss_phase_telemetry():
    """Verify BossStage and BossPhase serialization."""
    phase = BossPhase(
        phase_index=2,
        element=21,
        element_name="Extreme TEQ",
        cancels_dodge=True,
        has_aoe=True,
        locks_slots=True,
        nullifies_stun_seal=True,
        bosses=[
            BossEnemy(
                card_id=90001,
                name="Omega Shenron",
                subname="Cataclysmic Shadow Dragon",
                element=21,
                type_name="Extreme TEQ",
                mechanics=[
                    BossMechanic(id=1, name="Disables evasion", description="Cancels enemy dodge"),
                    BossMechanic(id=2, name="AOE Super", description="Hits all targets"),
                ],
            )
        ],
    )
    stage = BossStage(
        stage_id=200,
        event_id=10,
        stage_name="Shadow Dragons Final Battle",
        event_name="Red Zone [GT Bosses]",
        difficulty=5,
        phases=[phase],
    )
    stage_json = stage.to_dict()
    assert stage_json["phases"][0]["cancels_dodge"] is True
    assert stage_json["phases"][0]["has_aoe"] is True
    assert stage_json["phases"][0]["locks_slots"] is True
