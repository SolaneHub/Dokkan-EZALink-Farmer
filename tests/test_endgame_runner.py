"""Integration and unit tests for EndgameRunner and autonomous trial-and-error loop.

Simulates the complete 3-run lifecycle specified in Phase 4:
- Run 1: Game Over at Phase 2 -> Surgical Swap / SurgicalReplace of culprit card.
- Run 2: Game Over at Final Phase with 12% Boss HP -> InstantRetry with unchanged team.
- Run 3: Victory and persistence of the Winning Team in ai_memory.json.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from dokkan_eza_link_farmer.ai.boss_catalog import get_boss_stage, list_boss_stages
from dokkan_eza_link_farmer.ai.endgame.runner import (
    EndgameResult,
    EndgameRunner,
    EndgameRunnerState,
)
from dokkan_eza_link_farmer.ai.endgame.telemetry import (
    CombatFrame,
    CombatTelemetryTracker,
    EpisodicMemory,
    TurnSnapshot,
)
from dokkan_eza_link_farmer.ai.models import (
    BossEnemy,
    BossPhase,
    BossStage,
    CardForm,
    DokkanCard,
    LeaderSkillSpec,
    PassiveTags,
    SATags,
)


def create_test_card(
    card_id: int,
    name: str,
    element: int = 0,
    links: list[str] | None = None,
    category_ids: list[int] | None = None,
    leader_spec: LeaderSkillSpec | None = None,
    slot1_viable: bool = False,
    dr_pct: int = 0,
    has_guard: bool = False,
    is_rainbow: bool = False,
) -> DokkanCard:
    """Helper to synthesize fully valid DokkanCard models."""
    links_list = links or [
        "Super Saiyan",
        "Prepared for Battle",
        "Fierce Battle",
        "Kamehameha",
    ]
    cats = category_ids or [10, 20, 30]
    base_form = CardForm(
        form_id=card_id,
        form_index=0,
        form_name=name,
        element=element,
        links=list(links_list),
        passive_tags=PassiveTags(
            slot1_viable=slot1_viable,
            dr_base_percent=dr_pct,
            has_guard=has_guard,
        ),
        sa_tags=SATags(stacks_def=True),
    )
    return DokkanCard(
        id=card_id,
        name=name,
        element=element,
        category_ids=cats,
        links=list(links_list),
        leader_spec=leader_spec,
        base_form=base_form,
        is_rainbow=is_rainbow,
    )


@pytest.fixture
def test_box_and_stage(tmp_path: Path):
    """Fixture providing user box cards, a 3-phase challenge stage, and paths."""
    box_path = tmp_path / "user_box.json"
    memory_path = tmp_path / "ai_memory.json"

    # Leader: 200% lead on category 10 + 20
    lead_spec = LeaderSkillSpec(
        base_boost_pct=170,
        extra_boost_pct=30,
        main_category_ids=[10],
        extra_category_ids=[20],
    )
    c1_lead = create_test_card(
        101, "LR AGL Goku Lead", element=0, leader_spec=lead_spec, slot1_viable=True, dr_pct=50
    )
    c2_tank = create_test_card(
        102, "LR TEQ Vegeta Tank", element=1, slot1_viable=True, has_guard=True, dr_pct=40
    )
    c3_dps = create_test_card(103, "UR PHY Trunks DPS", element=4, slot1_viable=False, dr_pct=20)
    c4_sup = create_test_card(104, "UR INT Gohan Support", element=2, slot1_viable=False, dr_pct=30)
    c5_weak = create_test_card(
        105, "UR STR Yamcha Floater", element=3, slot1_viable=False, dr_pct=0
    )
    c6_fill = create_test_card(106, "UR AGL Krillin", element=0, slot1_viable=False, dr_pct=20)

    # Substitute card in box with high defense
    c7_sub = create_test_card(
        107, "LR STR Piccolo Tank", element=3, slot1_viable=True, has_guard=True, dr_pct=60
    )
    c8_sub2 = create_test_card(108, "UR TEQ Tien", element=1, slot1_viable=False, dr_pct=40)

    cards = [c1_lead, c2_tank, c3_dps, c4_sup, c5_weak, c6_fill, c7_sub, c8_sub2]

    # Save to user_box.json
    box_data = {"cards": [c.to_dict() for c in cards]}
    box_path.write_text(json.dumps(box_data, indent=2), encoding="utf-8")

    # 3-phase challenge stage (Phase 1: PHY, Phase 2: INT, Phase 3: TEQ Final Phase)
    stage = BossStage(
        stage_id=9901,
        event_id=99,
        stage_name="Stage 1: Test Challenge Boss",
        event_name="Ultimate Red Zone: Test Edition",
        difficulty=1,
        phases=[
            BossPhase(
                phase_index=1,
                element=24,
                element_name="Extreme PHY",
                hp=15000000,
                atk=300000,
                bosses=[BossEnemy(card_id=901, name="Phase 1 Boss", element=24)],
            ),
            BossPhase(
                phase_index=2,
                element=22,
                element_name="Extreme INT",
                hp=25000000,
                atk=500000,
                bosses=[BossEnemy(card_id=902, name="Phase 2 Boss", element=22)],
            ),
            BossPhase(
                phase_index=3,
                element=21,
                element_name="Extreme TEQ",
                hp=45000000,
                atk=800000,
                cancels_dodge=True,
                bosses=[BossEnemy(card_id=903, name="Phase 3 Final Boss", element=21)],
            ),
        ],
    )

    return cards, stage, box_path, memory_path


class TestEndgameRunnerFullLifecycle:
    """Simulates the 3-Run End-to-End Orchestrator Loop."""

    def test_endgame_runner_3_run_lifecycle(self, test_box_and_stage):
        _cards, stage, box_path, memory_path = test_box_and_stage

        # Track formation calls and target_slot kwargs
        formation_calls: list[list[int]] = []
        formation_slots: list[int | None] = []

        def mock_formation(team_cards, target_slot=None, **_kwargs):
            formation_calls.append([c.id for c in team_cards])
            formation_slots.append(target_slot)
            return True

        recorded_culprit_id: list[int] = []

        # Custom simulator providing the 3-run scenario
        def battle_simulator(
            attempt_num: int, current_team: list[DokkanCard], _target_stage: BossStage
        ):
            if attempt_num == 1:
                # Run 1: Game Over at Phase 2 (INT Boss) -> Culprit is current_team[4]
                culprit_card = current_team[4]
                recorded_culprit_id.append(culprit_card.id)
                # Snapshot on Turn 3, Phase 2, Boss HP 60%
                snap = TurnSnapshot(
                    turn_number=3,
                    boss_phase_index=2,
                    boss_element=22,
                    boss_element_name="Extreme INT",
                    boss_hp_percent=60.0,
                    player_hp_percent=15.0,
                    active_rotation=[current_team[0], current_team[1], culprit_card],
                )
                # Lethal frame hits Slot 3
                frames = [
                    CombatFrame(
                        frame_id=1,
                        active_slot=1,
                        target_card_id=current_team[0].id,
                        incoming_damage=20000,
                        player_hp_after=80.0,
                    ),
                    CombatFrame(
                        frame_id=2,
                        active_slot=2,
                        target_card_id=current_team[1].id,
                        incoming_damage=15000,
                        player_hp_after=65.0,
                    ),
                    CombatFrame(
                        frame_id=3,
                        active_slot=3,
                        target_card_id=culprit_card.id,
                        incoming_damage=500000,
                        player_hp_after=0.0,
                        is_lethal=True,
                    ),
                ]
                return ("defeat", snap, frames)

            elif attempt_num == 2:
                # Run 2: Game Over at Final Phase (Phase 3) with 12.0% Boss HP -> Instant Retry
                snap = TurnSnapshot(
                    turn_number=6,
                    boss_phase_index=3,
                    boss_element=21,
                    boss_element_name="Extreme TEQ",
                    boss_hp_percent=12.0,  # < 20% triggers InstantRetry!
                    player_hp_percent=5.0,
                    active_rotation=[current_team[0], current_team[1], current_team[2]],
                )
                frames = [
                    CombatFrame(
                        frame_id=1,
                        active_slot=1,
                        target_card_id=current_team[0].id,
                        incoming_damage=500000,
                        player_hp_after=0.0,
                        is_lethal=True,
                    )
                ]
                return ("defeat", snap, frames)

            elif attempt_num == 3:
                # Run 3: Stage Clear / Victory at Turn 7!
                snap = TurnSnapshot(
                    turn_number=7,
                    boss_phase_index=3,
                    boss_element=21,
                    boss_element_name="Extreme TEQ",
                    boss_hp_percent=0.0,
                    player_hp_percent=45.0,
                    active_rotation=[current_team[0], current_team[1], current_team[2]],
                )
                return ("victory", snap, [])

            raise AssertionError(f"Unexpected attempt number: {attempt_num}")

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
            battle_simulator=battle_simulator,
        )

        with patch(
            "dokkan_eza_link_farmer.ai.endgame.runner.apply_team_in_game",
            side_effect=mock_formation,
        ):
            result: EndgameResult = runner.run(stage)

        # 1. Verification of Outcome
        assert result.success is True
        assert result.attempts == 3
        assert len(result.winning_team) == 6

        # 2. Verification of Run 1 -> Surgical Swap
        assert len(result.decisions) == 2
        decision_run1 = result.decisions[0]
        assert decision_run1.action == "SurgicalReplace"
        assert recorded_culprit_id[0] in decision_run1.replaced_card_ids
        assert len(decision_run1.new_card_ids) == 1

        # 3. Verification of Run 2 -> Instant Retry (Boss HP < 20% in Final Phase)
        decision_run2 = result.decisions[1]
        assert decision_run2.action == "InstantRetry"
        assert decision_run2.replaced_card_ids == []
        assert "Final Phase Boss HP < 20%" in decision_run2.reason

        # 4. Verification of Step B In-Game Team Formation Optimization
        # Formation was applied in Run 1 (initial team, target_slot=None) and Run 2 (surgically replaced slot 5),
        # but NOT in Run 3 (Instant Retry kept identical team)
        assert len(formation_calls) == 2
        assert formation_slots == [None, 5]

        # 5. Verification of ai_memory.json persistence
        assert memory_path.exists()
        saved_memory = json.loads(memory_path.read_text(encoding="utf-8"))
        stage_data = saved_memory["stages"][str(stage.stage_id)]
        assert stage_data["cleared"] is True
        assert stage_data["winning_team"] == [c.id for c in result.winning_team]
        assert stage_data["attempts"] == 3
        assert stage_data["victories"] == 1
        assert len(stage_data["history"]) == 3  # Defeat 1, Defeat 2, Victory


class TestBossCatalogLoading:
    """Verifies boss catalog JSON and helper functions."""

    def test_load_all_catalog_stages(self):
        stages = list_boss_stages()
        assert len(stages) >= 8

        stage_ids = {s.stage_id for s in stages}
        # Red Zone stages
        assert 10101 in stage_ids  # Broly
        assert 10102 in stage_ids  # Cell Max
        assert 10103 in stage_ids  # Fusion Zamasu
        assert 10104 in stage_ids  # Kid Buu
        assert 10105 in stage_ids  # Omega Shenron

        # Blue Zone (Supreme Magnificent Battle) stages
        assert 20101 in stage_ids  # Beast Gohan
        assert 20102 in stage_ids  # Super Gogeta
        assert 20103 in stage_ids  # Evo Blue & UI Goku

    def test_get_boss_stage_by_slug_and_id(self):
        broly = get_boss_stage("rz_broly")
        assert broly.stage_id == 10101
        assert len(broly.phases) == 4
        # Final phase cancels dodge
        assert broly.phases[-1].cancels_dodge is True
        assert broly.phases[2].has_aoe is True

        beast = get_boss_stage("smb_beast_gohan")
        assert beast.stage_id == 20101
        assert beast.phases[-1].cancels_dodge is True
        assert beast.phases[-1].locks_slots is True

    def test_get_boss_stage_not_found(self):
        with pytest.raises(KeyError) as exc_info:
            get_boss_stage("non_existent_stage_xyz")
        assert "not found in catalog" in str(exc_info.value)


class TestEndgameRunnerEdgeCases:
    """Verifies boundary conditions, max attempts limit, and error handling."""

    def test_max_attempts_limit_reached(self, test_box_and_stage):
        cards, stage, box_path, memory_path = test_box_and_stage

        # Defeat simulator that always dies
        def always_die(_attempt_num, current_team, _target_stage):
            snap = TurnSnapshot(
                turn_number=1,
                boss_phase_index=1,
                boss_element=24,
                boss_element_name="Extreme PHY",
                boss_hp_percent=95.0,
                player_hp_percent=0.0,
                active_rotation=[current_team[0], current_team[1], current_team[2]],
            )
            return ("defeat", snap, [])

        runner = EndgameRunner(
            user_box_path=box_path,
            memory_path=memory_path,
            boss_stage=stage,
            max_attempts=3,
            dry_run=True,
            battle_simulator=always_die,
        )

        with patch(
            "dokkan_eza_link_farmer.ai.endgame.runner.apply_team_in_game", return_value=True
        ):
            res = runner.run(stage)

        assert res.success is False
        assert res.attempts == 3
        assert runner.current_state == EndgameRunnerState.MAX_ATTEMPTS_REACHED
        assert "Failed to clear stage" in res.message

    def test_runner_stop_signal(self, test_box_and_stage):
        _cards, stage, box_path, memory_path = test_box_and_stage
        runner = EndgameRunner(
            user_box_path=box_path,
            memory_path=memory_path,
            boss_stage=stage,
            max_attempts=5,
            dry_run=True,
        )
        runner.stop()
        assert runner.is_stopped() is True
        res = runner.run(stage)
        assert res.success is False
        assert res.attempts == 0

    def test_endgame_runner_with_catalog_stage_broly(self, test_box_and_stage):
        _cards, _, box_path, memory_path = test_box_and_stage
        broly_stage = get_boss_stage("rz_broly")

        def instant_win_sim(_attempt_num, current_team, _target_stage):
            snap = TurnSnapshot(
                turn_number=4,
                boss_phase_index=4,
                boss_element=20,
                boss_element_name="Extreme AGL",
                boss_hp_percent=0.0,
                player_hp_percent=80.0,
                active_rotation=[current_team[0], current_team[1], current_team[2]],
            )
            return ("victory", snap, [])

        runner = EndgameRunner(
            user_box_path=box_path,
            memory_path=memory_path,
            boss_stage=broly_stage,
            max_attempts=3,
            dry_run=True,
            battle_simulator=instant_win_sim,
        )

        with patch(
            "dokkan_eza_link_farmer.ai.endgame.runner.apply_team_in_game", return_value=True
        ):
            res = runner.run(broly_stage)

        assert res.success is True
        assert res.attempts == 1
        assert len(res.winning_team) == 6
        assert res.stage is not None and res.stage.stage_id == 10101

    def test_endgame_runner_friend_leader_immunity(self, test_box_and_stage):
        _cards, stage, box_path, memory_path = test_box_and_stage

        attempts_seen = []

        def friend_death_then_win(attempt_num, current_team, _target_stage):
            attempts_seen.append(attempt_num)
            if attempt_num == 1:
                snap = TurnSnapshot(
                    turn_number=3,
                    boss_phase_index=2,
                    boss_element=22,
                    boss_element_name="Extreme INT",
                    boss_hp_percent=70.0,
                    player_hp_percent=0.0,
                    active_rotation=[current_team[0], current_team[1], current_team[2]],
                )
                # Slot 7 is friend leader!
                frames = [
                    CombatFrame(
                        frame_id=1,
                        active_slot=7,
                        target_card_id=999,
                        incoming_damage=600000,
                        player_hp_after=0.0,
                        is_lethal=True,
                    )
                ]
                return ("defeat", snap, frames)
            else:
                snap = TurnSnapshot(
                    turn_number=5,
                    boss_phase_index=3,
                    boss_element=21,
                    boss_element_name="Extreme TEQ",
                    boss_hp_percent=0.0,
                    player_hp_percent=100.0,
                    active_rotation=[current_team[0], current_team[1], current_team[2]],
                )
                return ("victory", snap, [])

        runner = EndgameRunner(
            user_box_path=box_path,
            memory_path=memory_path,
            boss_stage=stage,
            max_attempts=3,
            dry_run=True,
            battle_simulator=friend_death_then_win,
        )

        with patch(
            "dokkan_eza_link_farmer.ai.endgame.runner.apply_team_in_game", return_value=True
        ):
            res = runner.run(stage)

        assert res.success is True
        assert res.attempts == 2
        assert len(res.decisions) == 1
        assert res.decisions[0].action == "InstantRetry"
        assert "Friend Leader (Slot 7)" in res.decisions[0].reason

    def test_bot_engine_run_ai_endgame_sync(self, test_box_and_stage):
        from dokkan_eza_link_farmer.core.bot_engine import BotEngine

        cards, stage, box_path, memory_path = test_box_and_stage
        engine = BotEngine()

        with patch("dokkan_eza_link_farmer.ai.endgame.runner.EndgameRunner.run") as mock_runner_run:
            mock_runner_run.return_value = EndgameResult(
                success=True,
                attempts=1,
                winning_team=cards[:6],
                stage=stage,
            )
            res = engine.run_ai_endgame_sync(10101, dry_run=True, max_attempts=5)
            assert res.success is True
            assert res.attempts == 1
            assert mock_runner_run.called

    def test_bot_engine_start_ai_endgame_background(self, test_box_and_stage):
        from dokkan_eza_link_farmer.core.bot_engine import BotEngine

        cards, stage, box_path, memory_path = test_box_and_stage
        engine = BotEngine()

        with patch("dokkan_eza_link_farmer.ai.endgame.runner.EndgameRunner.run") as mock_runner_run:
            mock_runner_run.return_value = EndgameResult(
                success=True,
                attempts=1,
                winning_team=cards[:6],
                stage=stage,
            )
            started = engine.start_ai_endgame(10101, dry_run=True, max_attempts=2)
            assert started is True
            assert engine.current_task is not None
            engine.stop_task()
            assert engine.is_task_running() is False

    def test_cli_ai_run_argument_parsing(self):
        from dokkan_eza_link_farmer.__main__ import main

        with (
            patch("dokkan_eza_link_farmer.ui.cli.TerminalCLI.handle_ai_endgame_run") as mock_handle,
            patch("sys.argv", ["dokkan-farmer", "ai-run", "--stage", "10101", "--dry-run"]),
            patch(
                "dokkan_eza_link_farmer.core.system_tools.SingleInstanceMutex.acquire",
                return_value=True,
            ),
            patch("dokkan_eza_link_farmer.core.system_tools.SingleInstanceMutex.release"),
        ):
            main()
        mock_handle.assert_called_once_with("10101", dry_run=True, max_attempts=None)

    def test_cli_ai_run_interactive_selection_when_no_stage(self):
        from dokkan_eza_link_farmer.__main__ import main

        with (
            patch("dokkan_eza_link_farmer.ui.cli.TerminalCLI.handle_ai_endgame_run") as mock_handle,
            patch("sys.argv", ["dokkan-farmer", "ai-run", "--dry-run"]),
            patch(
                "dokkan_eza_link_farmer.core.system_tools.SingleInstanceMutex.acquire",
                return_value=True,
            ),
            patch("dokkan_eza_link_farmer.core.system_tools.SingleInstanceMutex.release"),
        ):
            main()
        mock_handle.assert_called_once_with(None, dry_run=True, max_attempts=None)

    def test_dokkandb_user_box_cache_path_priority(self, tmp_path: Path):
        from dokkan_eza_link_farmer.integrations.dokkandb_client import DokkanDBClient

        test_box = tmp_path / "user_box.json"
        test_payload = {"cards": [{"id": 1099991, "name": "Test Card"}]}
        test_box.write_text(json.dumps(test_payload), encoding="utf-8")

        db = DokkanDBClient(cache_dir=str(tmp_path))
        with patch(
            "dokkan_eza_link_farmer.integrations.dokkandb_client.DEFAULT_USER_BOX_PATH",
            str(test_box),
        ):
            box_ids = db.get_user_box_card_ids()
            assert 1099991 in box_ids

    def test_get_boss_stage_dokkandb_numeric_stage_id(self):
        from unittest.mock import MagicMock

        from dokkan_eza_link_farmer.ai.boss_catalog import get_boss_stage

        mock_dokkandb = MagicMock()
        mock_dokkandb.get_stage_boss_info.return_value = {
            "event_id": 1737,
            "stage_id": 17370775,
            "event_name": "Ultimate Red Zone",
            "stage_name": "DAIMA Edition Stage 1",
            "difficulty": 5,
            "phases": [
                {
                    "phase": 1,
                    "bosses": [
                        {
                            "name": "Tamagami Number Three",
                            "element": 10,
                            "type_name": "Super AGL",
                            "card_id": 9130881,
                        }
                    ],
                }
            ],
        }

        stage = get_boss_stage(17370775, dokkandb=mock_dokkandb)
        assert stage.stage_id == 17370775
        assert stage.event_id == 1737
        assert stage.event_name == "Ultimate Red Zone"
        assert stage.stage_name == "DAIMA Edition Stage 1"
        assert len(stage.phases) == 1
        assert stage.phases[0].element_name == "Super AGL"
        mock_dokkandb.get_stage_boss_info.assert_called_once_with(1737, 17370775)
