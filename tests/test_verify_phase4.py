"""Pytest test suite converted from scripts/verify_phase4_endgame.py."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import yaml

from dokkan_eza_link_farmer.ai.boss_catalog import get_boss_stage, list_boss_stages
from dokkan_eza_link_farmer.ai.endgame_runner import (
    EndgameResult,
    EndgameRunner,
)
from dokkan_eza_link_farmer.ai.models import (
    AIConfig,
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


def test_boss_catalog_stages():
    """Check 1: Database Boss End-Game Catalog (boss_stages.json)."""
    stages = list_boss_stages()
    assert len(stages) >= 8
    broly = get_boss_stage("rz_broly")
    assert broly.phases[-1].cancels_dodge is True
    beast = get_boss_stage(20101)
    assert beast.phases[-1].cancels_dodge is True and beast.phases[-1].locks_slots is True


def test_endgame_runner_3_run_lifecycle_and_step_b(tmp_path: Path):
    """Check 2 & 3: 3-Run state machine and Step B formation invocation."""
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

    def test_simulator(attempt_num: int, current_team: list[DokkanCard], _target_stage: BossStage):
        if attempt_num == 1:
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

    assert res.success is True
    assert res.attempts == 3
    assert res.decisions[0].action == "SurgicalReplace"
    assert recorded_culprit[0] in res.decisions[0].replaced_card_ids
    assert res.decisions[1].action == "InstantRetry"

    saved_mem = json.loads(memory_path.read_text(encoding="utf-8"))
    s_data = saved_mem["stages"][str(stage.stage_id)]
    assert s_data["cleared"] is True
    assert s_data["winning_team"] == [c.id for c in res.winning_team]

    # Step B Formation calls: Run 1 and Run 2, but NOT Run 3 (Instant Retry)
    assert len(formation_applied_teams) == 2


def test_settings_yaml_and_cli_integration():
    """Check 4: Settings.yaml & CLI integration."""
    settings_file = Path("src/dokkan_eza_link_farmer/assets/config/settings.yaml")
    assert settings_file.exists()

    with open(settings_file, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    assert "ai_teambuilder" in cfg
    ai_tb = cfg["ai_teambuilder"]
    assert ai_tb.get("timeout_seconds") == 75
    assert ai_tb.get("max_attempts") == 10
    assert ai_tb.get("confidence_threshold") == 0.72

    parsed_conf = AIConfig.from_dict(ai_tb)
    assert parsed_conf.max_attempts == 10
    assert parsed_conf.confidence_threshold == 0.72

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
