#!/usr/bin/env python3
"""End-to-end dry-run verification script for Phase 4 Dokkan AI Teambuilder & Endgame Runner.

Validates the 4 core requirements:
1. Database Boss End-Game (boss_stages.json): 8 iconic stages loaded with real phases and gimmicks.
2. EndgameRunner 3-run autonomous state machine:
   - Run 1: Game Over at Phase 2 -> Surgical Swap / SurgicalReplace.
   - Run 2: Game Over at Final Phase 12% HP -> InstantRetry.
   - Run 3: Stage Clear -> Winning Team recorded in ai_memory.json.
3. In-game team formation optimization (Step B): verified invoked on team changes, skipped on InstantRetry.
4. CLI options & settings.yaml integration (scan-box, ai-run, ai_teambuilder config).
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from dokkan_eza_link_farmer.ai.boss_catalog import get_boss_stage, list_boss_stages
from dokkan_eza_link_farmer.ai.endgame_runner import (
    EndgameResult,
    EndgameRunner,
)
from dokkan_eza_link_farmer.ai.models import (
    BossPhase,
    BossStage,
    CardForm,
    DokkanCard,
    LeaderSkillSpec,
    PassiveTags,
    SATags,
)
from dokkan_eza_link_farmer.ai.telemetry import (
    CombatFrame,
    CombatTelemetryTracker,
    EpisodicMemory,
    TurnSnapshot,
)


def make_card(
    card_id: int,
    name: str,
    element: int = 0,
    leader_spec: LeaderSkillSpec | None = None,
    slot1_viable: bool = False,
    dr_pct: int = 0,
    has_guard: bool = False,
) -> DokkanCard:
    return DokkanCard(
        id=card_id,
        name=name,
        element=element,
        category_ids=[10, 20],
        links=["Super Saiyan", "Prepared for Battle", "Fierce Battle"],
        leader_spec=leader_spec,
        base_form=CardForm(
            form_id=card_id,
            form_index=0,
            form_name=name,
            element=element,
            links=["Super Saiyan", "Prepared for Battle", "Fierce Battle"],
            passive_tags=PassiveTags(
                slot1_viable=slot1_viable,
                dr_base_percent=dr_pct,
                has_guard=has_guard,
            ),
            sa_tags=SATags(stacks_def=True),
        ),
    )


def main() -> int:
    print("=" * 70)
    print("🚀 PHASE 4: END-TO-END DRY-RUN VERIFICATION (ENDGAME RUNNER & CLI)")
    print("=" * 70)

    # -------------------------------------------------------------------------
    # CHECK 1: Database Boss End-Game Catalog
    # -------------------------------------------------------------------------
    print("\n[CHECK 1/4] Verifying Boss Stages Catalog (boss_stages.json)...")
    stages = list_boss_stages()
    print(f"  ✓ Loaded {len(stages)} endgame challenge stages:")
    for s in stages:
        phases_str = " -> ".join(p.element_name for p in s.phases)
        gimmicks = []
        if any(p.cancels_dodge for p in s.phases):
            gimmicks.append("Cancels Dodge")
        if any(p.has_aoe for p in s.phases):
            gimmicks.append("AoE Attack")
        if any(p.locks_slots for p in s.phases):
            gimmicks.append("Locks Slots")
        g_str = f" [{', '.join(gimmicks)}]" if gimmicks else ""
        print(
            f"    * {s.stage_id}: {s.event_name} - {s.stage_name} ({len(s.phases)} phases: {phases_str}){g_str}"
        )

    assert len(stages) >= 8, f"Expected >= 8 stages, got {len(stages)}"
    broly = get_boss_stage("rz_broly")
    assert broly.phases[-1].cancels_dodge is True
    beast = get_boss_stage(20101)
    assert beast.phases[-1].cancels_dodge is True and beast.phases[-1].locks_slots is True
    print("  ✓ Check 1 PASSED: Catalog validated with authentic phases and lethal gimmicks.")

    # -------------------------------------------------------------------------
    # CHECK 2: Complete 3-Run Lifecycle of EndgameRunner
    # -------------------------------------------------------------------------
    print("\n[CHECK 2/4] Simulating Autonomous 3-Run Lifecycle...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        box_path = tmp_path / "user_box.json"
        memory_path = tmp_path / "ai_memory.json"

        lead_spec = LeaderSkillSpec(
            base_boost_pct=170, extra_boost_pct=30, main_category_ids=[10], extra_category_ids=[20]
        )
        c1 = make_card(
            101, "LR AGL Lead", element=0, leader_spec=lead_spec, slot1_viable=True, dr_pct=50
        )
        c2 = make_card(102, "LR TEQ Tank", element=1, slot1_viable=True, has_guard=True, dr_pct=40)
        c3 = make_card(103, "UR PHY DPS", element=4, dr_pct=20)
        c4 = make_card(104, "UR INT Sup", element=2, dr_pct=30)
        c5 = make_card(105, "UR STR Floater", element=3, dr_pct=0)
        c6 = make_card(106, "UR AGL Fill", element=0, dr_pct=20)
        c7_sub = make_card(
            107, "LR STR Shield Sub", element=3, slot1_viable=True, has_guard=True, dr_pct=60
        )
        c8_sub = make_card(108, "UR TEQ Assist Sub", element=1, dr_pct=40)

        cards = [c1, c2, c3, c4, c5, c6, c7_sub, c8_sub]
        box_path.write_text(json.dumps({"cards": [c.to_dict() for c in cards]}), encoding="utf-8")

        stage = BossStage(
            stage_id=10102,
            event_id=102,
            stage_name="Stage 2: Cell Max",
            event_name="Ultimate Red Zone: Red Ribbon Army",
            phases=[
                BossPhase(phase_index=1, element=24, element_name="Extreme PHY", hp=15000000),
                BossPhase(phase_index=2, element=22, element_name="Extreme INT", hp=25000000),
                BossPhase(
                    phase_index=3,
                    element=21,
                    element_name="Extreme TEQ",
                    hp=45000000,
                    cancels_dodge=True,
                ),
            ],
        )

        formation_applied_teams: list[list[int]] = []

        def mock_apply(team_cards, **_kwargs):
            formation_applied_teams.append([c.id for c in team_cards])
            return True

        recorded_culprit: list[int] = []

        def test_simulator(
            attempt_num: int, current_team: list[DokkanCard], _target_stage: BossStage
        ):
            if attempt_num == 1:
                # Run 1: Game Over at Phase 2 (INT Cell Max) -> Lethal hit on culprit
                culprit = current_team[4]
                recorded_culprit.append(culprit.id)
                snap = TurnSnapshot(
                    turn_number=3,
                    boss_phase_index=2,
                    boss_element=22,
                    boss_element_name="Extreme INT",
                    boss_hp_percent=65.0,
                    player_hp_percent=0.0,
                    active_rotation=[current_team[0], current_team[1], culprit],
                )
                frames = [
                    CombatFrame(
                        frame_id=1,
                        active_slot=3,
                        target_card_id=culprit.id,
                        incoming_damage=500000,
                        is_lethal=True,
                    )
                ]
                return ("defeat", snap, frames)

            elif attempt_num == 2:
                # Run 2: Game Over at Final Phase (Phase 3) with 12.0% Boss HP -> InstantRetry!
                snap = TurnSnapshot(
                    turn_number=6,
                    boss_phase_index=3,
                    boss_element=21,
                    boss_element_name="Extreme TEQ",
                    boss_hp_percent=12.0,
                    player_hp_percent=0.0,
                    active_rotation=[current_team[0], current_team[1], current_team[2]],
                )
                frames = [
                    CombatFrame(
                        frame_id=1,
                        active_slot=1,
                        target_card_id=current_team[0].id,
                        incoming_damage=600000,
                        is_lethal=True,
                    )
                ]
                return ("defeat", snap, frames)

            elif attempt_num == 3:
                # Run 3: Stage Clear / Victory!
                snap = TurnSnapshot(
                    turn_number=7,
                    boss_phase_index=3,
                    boss_element=21,
                    boss_element_name="Extreme TEQ",
                    boss_hp_percent=0.0,
                    player_hp_percent=55.0,
                    active_rotation=[current_team[0], current_team[1], current_team[2]],
                )
                return ("victory", snap, [])

            raise AssertionError(f"Unexpected attempt {attempt_num}")

        memory = EpisodicMemory(cache_path=memory_path)
        tracker = CombatTelemetryTracker(episodic_memory=memory)

        runner = EndgameRunner(
            user_box_path=box_path,
            memory_path=memory_path,
            memory=memory,
            telemetry_tracker=tracker,
            boss_stage=stage,
            max_attempts=10,
            dry_run=True,
            battle_simulator=test_simulator,
        )

        with patch(
            "dokkan_eza_link_farmer.ai.endgame_runner.apply_team_in_game", side_effect=mock_apply
        ):
            res: EndgameResult = runner.run(stage)

        print(f"  ✓ Session ended with success={res.success} in {res.attempts} attempts.")
        assert res.success is True
        assert res.attempts == 3

        print(
            f"  ✓ Run 1 Decision: {res.decisions[0].action} (Replaced: {res.decisions[0].replaced_card_ids} -> {res.decisions[0].new_card_ids})"
        )
        assert res.decisions[0].action == "SurgicalReplace"
        assert recorded_culprit[0] in res.decisions[0].replaced_card_ids

        print(f"  ✓ Run 2 Decision: {res.decisions[1].action} (Reason: {res.decisions[1].reason})")
        assert res.decisions[1].action == "InstantRetry"

        print(f"  ✓ Run 3 Result: Winning Team saved with {len(res.winning_team)} cards.")
        saved_mem = json.loads(memory_path.read_text(encoding="utf-8"))
        s_data = saved_mem["stages"][str(stage.stage_id)]
        assert s_data["cleared"] is True
        assert s_data["winning_team"] == [c.id for c in res.winning_team]
        print("  ✓ Check 2 PASSED: 3-Run state machine executed and verified with 100% precision.")

        # ---------------------------------------------------------------------
        # CHECK 3: Step B Formation Optimization
        # ---------------------------------------------------------------------
        print("\n[CHECK 3/4] Verifying Step B In-Game Team Formation calls...")
        print(f"  ✓ Total in-game formation operations: {len(formation_applied_teams)}")
        # Applied in Run 1 (initial) and Run 2 (surgical replacement), but NOT Run 3 (Instant Retry)
        assert len(formation_applied_teams) == 2, (
            f"Expected exactly 2 formation calls, got {len(formation_applied_teams)}"
        )
        print(
            "  ✓ Check 3 PASSED: Formation invoked on team modification and skipped on InstantRetry."
        )

    # -------------------------------------------------------------------------
    # CHECK 4: Settings.yaml & CLI Integration
    # -------------------------------------------------------------------------
    print("\n[CHECK 4/4] Verifying settings.yaml and CLI integration...")
    settings_file = Path("src/dokkan_eza_link_farmer/assets/config/settings.yaml")
    assert settings_file.exists(), "settings.yaml not found"
    import yaml

    with open(settings_file, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    assert "ai_teambuilder" in cfg, "ai_teambuilder section missing in settings.yaml"
    ai_tb = cfg["ai_teambuilder"]
    print(
        f"  ✓ Found ai_teambuilder config: model={ai_tb.get('ollama_model')}, timeout={ai_tb.get('timeout_seconds')}s, max_attempts={ai_tb.get('max_attempts')}, conf={ai_tb.get('confidence_threshold')}"
    )
    assert ai_tb.get("timeout_seconds") == 75
    assert ai_tb.get("max_attempts") == 10
    assert ai_tb.get("confidence_threshold") == 0.72

    from dokkan_eza_link_farmer.ai.models import AIConfig

    parsed_conf = AIConfig.from_dict(ai_tb)
    assert parsed_conf.max_attempts == 10
    assert parsed_conf.confidence_threshold == 0.72
    assert parsed_conf.model_name == "deepseek-r1:7b"
    assert parsed_conf.base_url == "http://localhost:11434/v1"
    print(
        "  ✓ AIConfig.from_dict seamlessly parsed ollama_model, ollama_url, max_attempts, confidence_threshold."
    )

    # Validate CLI arguments parsing (--stage, -s, --dry-run, --max-attempts)
    from dokkan_eza_link_farmer.__main__ import main

    with (
        patch("dokkan_eza_link_farmer.ui.cli.TerminalCLI.handle_ai_endgame_run") as mock_cli_run,
        patch(
            "sys.argv",
            ["dokkan-farmer", "ai-run", "-s", "20101", "--dry-run", "--max-attempts", "5"],
        ),
        patch(
            "dokkan_eza_link_farmer.core.system_tools.SingleInstanceMutex.acquire",
            return_value=True,
        ),
        patch("dokkan_eza_link_farmer.core.system_tools.SingleInstanceMutex.release"),
    ):
        main()
        mock_cli_run.assert_called_once_with("20101", dry_run=True, max_attempts=5)
    print("  ✓ CLI argument parser verified with -s, --dry-run, --max-attempts.")

    print("  ✓ Check 4 PASSED: Configuration and CLI integration verified.")

    print("\n" + "=" * 70)
    print("🏆 ALL PHASE 4 VERIFICATION CHECKS PASSED (100% SUCCESS)")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
