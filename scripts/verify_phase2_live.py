"""
Verification script for Phase 2 implementation:
- Tests live catalog chunk retrieval and UR/LR filtering
- Tests live thumbnail fetching from Supabase mirror
- Tests parsing of tactical passive/SA tags and LeaderSkillSpec on sample card
- Tests BossStage and BossPhase telemetry structures
"""

from __future__ import annotations

import os
import tempfile

from dokkan_eza_link_farmer.ai.box_scanner import DEFAULT_USER_BOX_PATH
from dokkan_eza_link_farmer.ai.models import (
    BossEnemy,
    BossMechanic,
    BossPhase,
    BossStage,
)
from dokkan_eza_link_farmer.ai.syncer import (
    DokkanSyncer,
)


def main():
    print("=== 1. VERIFY SUPABASE THUMBNAIL FORMULA & DOWNLOAD ===")
    with tempfile.TemporaryDirectory() as tmpdir:
        syncer = DokkanSyncer(cache_dir=tmpdir)
        sample_card_id = 1012901  # LR Gogeta
        thumb_id = syncer.get_thumb_id(sample_card_id)
        assert thumb_id == "1012900", f"Expected 1012900, got {thumb_id}"
        print(f"  [OK] Card ID {sample_card_id} -> Thumb ID {thumb_id}")

        thumb_url = syncer.get_thumb_url(sample_card_id)
        print(f"  [OK] Supabase URL: {thumb_url}")

        downloaded = syncer.sync_thumbnails(
            cards=[{"id": sample_card_id}],
            max_workers=1,
            limit=1,
        )
        assert downloaded == 1, "Expected 1 thumbnail downloaded"
        target_path = os.path.join(syncer.thumbs_dir, f"card_{thumb_id}_thumb.png")
        assert os.path.exists(target_path) and os.path.getsize(target_path) > 1000
        print(f"  [OK] Thumbnail saved successfully: {target_path} ({os.path.getsize(target_path)} bytes)")

    print("\n=== 2. VERIFY LIVE DOKKANDB CHUNKS & UR/LR FILTERING ===")
    with tempfile.TemporaryDirectory() as tmpdir:
        syncer = DokkanSyncer(cache_dir=tmpdir)
        catalog = syncer.sync_catalog(force=True)
        print(f"  [OK] Catalog downloaded and filtered: {len(catalog)} UR/LR cards")
        assert len(catalog) > 800, "Catalog should have > 800 UR/LR cards"
        # Verify rarity filtering
        for c in catalog[:50]:
            assert c.get("rarity") in (4, 5), f"Found invalid rarity: {c.get('rarity')}"
        print("  [OK] All examined cards confirmed UR (rarity 4) or LR (rarity 5)")

    print("\n=== 3. VERIFY SAMPLE CARD LIVE FETCH & TACTICAL PARSING ===")
    with tempfile.TemporaryDirectory() as tmpdir:
        syncer = DokkanSyncer(cache_dir=tmpdir)
        # Card 1012901 is LR PHY Gogeta (has EZA)
        detail = syncer.fetch_card_detail_sync(1012901)
        assert detail is not None, "Failed to fetch card 1012901"
        print(f"  [OK] Fetched card 1012901: {detail.get('name')} - '{detail.get('subname')}'")

        # Build card as pre-EZA
        base_card = syncer.build_dokkan_card(detail, is_eza=False, is_seza=False)
        print(f"  [PRE-EZA] Leader: {base_card.leader_skill[:60]}...")
        print(f"  [PRE-EZA] Passive: {base_card.passive_skill[:60]}...")

        # Build card as EZA
        eza_card = syncer.build_dokkan_card(detail, is_eza=True, is_seza=False, is_rainbow=True)
        print(f"  [EZA] Leader: {eza_card.leader_skill[:60]}...")
        print(f"  [EZA] Passive: {eza_card.passive_skill[:60]}...")
        print(f"  [EZA] DR %: {eza_card.base_form.passive_tags.dr_base_percent}%")
        print(f"  [EZA] Guard: {eza_card.base_form.passive_tags.has_guard}")
        print(f"  [EZA] Slot 1 Viable: {eza_card.base_form.passive_tags.slot1_viable}")
        print(f"  [EZA] Leader Spec: main_cats={eza_card.leader_spec.main_category_ids}, boost={eza_card.leader_spec.base_boost_pct}%")
        assert len(eza_card.transformations) >= 1
        assert eza_card.transformations[0].form_name == "Super Vegito"
        print(f"  [EZA] Transformed Form: {eza_card.transformations[0].form_name} (ID: {eza_card.transformations[0].form_id})")

    print("\n=== 4. VERIFY BOX SCANNER DEFAULT PATH & METADATA COORDINATES ===")
    print(f"  [OK] Default user_box path: {DEFAULT_USER_BOX_PATH}")
    assert DEFAULT_USER_BOX_PATH.endswith(os.path.join(".dokkan-farmer", "cache", "user_box.json"))

    print("\n=== 5. VERIFY BOSS STAGE & BOSS PHASE TELEMETRY ===")
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
    print(f"  [OK] BossStage '{stage.stage_name}' with BossPhase {phase.phase_index} (cancels_dodge={phase.cancels_dodge}, has_aoe={phase.has_aoe})")

    print("\n🎉 ALL PHASE 2 VERIFICATIONS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    main()
