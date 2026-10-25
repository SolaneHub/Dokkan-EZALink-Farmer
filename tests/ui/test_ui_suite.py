from __future__ import annotations

import copy
import io
from unittest.mock import MagicMock, patch

from rich.console import Console

from dokkan_eza_link_farmer.ai.models import (
    BossPhase,
    BossStage,
    DokkanCard,
    RotationPair,
    TeamRecommendation,
)
from dokkan_eza_link_farmer.ui import briefing, panels, wizards
from dokkan_eza_link_farmer.ui.cli import TerminalCLI


def _create_test_console() -> tuple[Console, io.StringIO]:
    buf = io.StringIO()
    return Console(file=buf, width=120, record=True), buf


class TestUIPanels:
    """Verifies presentation panels in dokkan_eza_link_farmer.ui.panels."""

    def test_render_banner_and_help(self):
        console, buf = _create_test_console()
        panels.render_banner(console)
        out = buf.getvalue()
        assert "DOKKAN" in out

        console, buf = _create_test_console()
        panels.render_help(console)
        out = buf.getvalue()
        assert "devices" in out
        assert "connect" in out
        assert "link" in out
        assert "eza" in out

    def test_render_doctor_ok_and_missing(self):
        report_ok = {
            "os": "Windows",
            "is_frozen": False,
            "python_version": "3.11.0",
            "adb": {"found": True, "version": "1.0.41", "path": "C:\\adb.exe"},
            "scrcpy": {"found": True, "version": "2.1", "path": "C:\\scrcpy.exe"},
            "devices": [{"serial": "127.0.0.1:5555", "model": "Pixel"}],
            "install_help": {},
        }
        console, buf = _create_test_console()
        panels.render_doctor(report_ok, console)
        out = buf.getvalue()
        assert "127.0.0.1:5555" in out

        report_missing = {
            "os": "Windows",
            "is_frozen": False,
            "python_version": "3.11.0",
            "adb": {"found": False, "version": "", "path": ""},
            "scrcpy": {"found": False, "version": "", "path": ""},
            "devices": [],
            "install_help": {"all": "winget install adb scrcpy", "note": "Restart terminal"},
        }
        console, buf = _create_test_console()
        panels.render_doctor(report_missing, console)
        out = buf.getvalue()
        assert "winget install" in out

    def test_render_status_and_ai_status(self):
        info = {
            "device_serial": "emulator-5554",
            "task_running": True,
            "task_type": "EZAFarmTask",
            "runs_target": 30,
            "runs_completed": 5,
            "current_state": "INGAME_BATTLE",
        }
        console, buf = _create_test_console()
        panels.render_status(info, console)
        out = buf.getvalue()
        assert "emulator-5554" in out
        assert "5 / 30" in out

        conf = MagicMock()
        conf.model_family.value = "qwen"
        conf.model_name = "qwen3.5:4b"
        conf.provider = "ollama"
        conf.base_url = "http://127.0.0.1:11434"

        console, buf = _create_test_console()
        panels.render_ai_status(conf, is_up=True, console=console)
        assert "ONLINE" in buf.getvalue()

        console, buf = _create_test_console()
        panels.render_ai_status(conf, is_up=False, console=console)
        assert "OFFLINE" in buf.getvalue()

    def test_render_devices_table(self):
        console, buf = _create_test_console()
        panels.render_devices_table([], console)
        assert "device" in buf.getvalue().lower() or "dispositiv" in buf.getvalue().lower()

        console, buf = _create_test_console()
        panels.render_devices_table(
            [{"serial": "emulator-5554", "status": "device", "model": "Nexus"}],
            console,
        )
        assert "emulator-5554" in buf.getvalue()

    def test_render_doctor_and_status_empty_partial_dict(self):
        console, buf = _create_test_console()
        panels.render_doctor({}, console)
        assert "Diagnostics" in buf.getvalue() or "Diagnostica" in buf.getvalue()

        console, buf = _create_test_console()
        panels.render_status({}, console)
        assert "Status" in buf.getvalue() or "Stato" in buf.getvalue()

    def test_render_panels_with_none_values_and_malformed_devices(self):
        console, buf = _create_test_console()
        panels.render_doctor(
            {"adb": None, "scrcpy": None, "install_help": None, "devices": None},
            console,
        )
        assert (
            "Missing" in buf.getvalue()
            or "Mancante" in buf.getvalue()
            or "Assente" in buf.getvalue()
        )

        console, buf = _create_test_console()
        panels.render_devices_table([{"serial": "emulator-5554"}, "plain_device"], console)
        assert "emulator-5554" in buf.getvalue()
        assert "plain_device" in buf.getvalue()

        console, buf = _create_test_console()
        panels.render_status(
            {"task_type": None, "runs_completed": None, "current_state": None},
            console,
        )
        assert "0 / ∞" in buf.getvalue()


class TestUIBriefing:
    """Verifies tactical briefings and visual team presentations in dokkan_eza_link_farmer.ui.briefing."""

    def test_render_stage_boss_info(self):
        boss_info = {
            "phases": [
                {
                    "phase": 1,
                    "bosses": [
                        {
                            "name": "Super Saiyan Broly",
                            "type_name": "Extreme AGL",
                            "mechanics": [{"name": "Cancels Dodge"}, {"name": "AoE"}],
                        }
                    ],
                }
            ]
        }
        console, buf = _create_test_console()
        briefing.render_stage_boss_info(boss_info, "Wrath of the Saiyan", 1, console)
        out = buf.getvalue()
        assert "Broly" in out
        assert "Extreme AGL" in out
        assert "Cancels Dodge, AoE" in out

    def test_render_mission_batches(self):
        batch = MagicMock()
        batch.summary = "6 Realm of Gods units"
        mission = MagicMock()
        mission.id = 101
        batch.missions = [mission]

        console, buf = _create_test_console()
        briefing.render_mission_batches(
            [batch], "Broly Red Zone", 1, saved=2, total_missions=3, console=console
        )
        out = buf.getvalue()
        assert "6 Realm of Gods units" in out
        assert "#101" in out

    def test_render_endgame_header_and_result(self):
        stage = BossStage(
            stage_id=101,
            event_id=1,
            stage_name="Final Battle",
            event_name="Red Zone",
            difficulty=4,
            phases=[BossPhase(phase_index=1, element_name="Extreme TEQ")],
        )
        console, buf = _create_test_console()
        briefing.render_endgame_header(stage, dry_run=True, force_solve=True, console=console)
        out = buf.getvalue()
        assert "DRY-RUN" in out
        assert "FORCE-SOLVE" in out
        assert "Red Zone" in out

        res_ok = MagicMock()
        res_ok.success = True
        res_ok.attempts = 2
        card = DokkanCard(id=1, name="Goku", element=11)
        res_ok.winning_team = [card]

        console, buf = _create_test_console()
        briefing.render_endgame_result(res_ok, console)
        assert "STAGE CLEARED" in buf.getvalue()

        res_fail = MagicMock()
        res_fail.success = False
        res_fail.attempts = 5
        console, buf = _create_test_console()
        briefing.render_endgame_result(res_fail, console)
        assert "without clear" in buf.getvalue()

    def test_render_team_presentation(self):
        lead = DokkanCard(id=101, name="Goku", subname="Supreme", element=44)
        friend = copy.copy(lead)
        friend.is_friend_leader = True
        sub1 = DokkanCard(id=102, name="Vegeta", element=23)
        sub2 = DokkanCard(id=103, name="Trunks", element=11)
        sub3 = DokkanCard(id=104, name="Gohan", element=11)
        sub4 = DokkanCard(id=105, name="Piccolo", element=11)
        sub5 = DokkanCard(id=106, name="Krillin", element=23)

        rec = TeamRecommendation(
            leader=lead,
            friend_leader=friend,
            all_cards=[lead, sub1, sub2, sub3, sub4, sub5],
            rotation_a=RotationPair(
                slot1=sub1,
                slot2=sub2,
                shared_links=["Super Saiyan"],
                shared_ki_links=[],
                synergy_score=8.0,
            ),
            rotation_b=RotationPair(
                slot1=sub3,
                slot2=sub4,
                shared_links=["Kamehameha"],
                shared_ki_links=[],
                synergy_score=7.0,
            ),
            floaters=[lead, sub5, friend],
            tactical_analysis="Focus on slot 1 protection.",
            ai_reasoning="High synergy build.",
        )
        console, buf = _create_test_console()
        briefing.render_team_presentation(rec, console=console)
        out = buf.getvalue()
        assert "Rotazione A" in out
        assert "Rotazione B" in out
        assert "Leader • Floater" in out
        assert "Friend • Floater" in out

    def test_render_endgame_result_empty_winning_team(self):
        console, buf = _create_test_console()
        res = MagicMock()
        res.success = True
        res.attempts = 1
        res.winning_team = []
        briefing.render_endgame_result(res, console=console)
        assert "Team N/A" in buf.getvalue()

    def test_render_linking_partners_plain_objects(self):
        console, buf = _create_test_console()
        partner_mock = MagicMock()
        del partner_mock.rich_formatted_name
        partner_mock.name = "Vegeta (Plain)"
        briefing.render_linking_partners(
            target_card="Goku (Target)",
            partners=[(partner_mock, 7.5, ["Super Saiyan"])],
            console=console,
        )
        out = buf.getvalue()
        assert "Goku (Target)" in out
        assert "Vegeta (Plain)" in out

    def test_render_stage_boss_info_none_bosses_and_mixed_mechanics(self):
        console, buf = _create_test_console()
        boss_info = {
            "phases": [
                {"bosses": None},
                {
                    "bosses": [
                        {
                            "name": "Broly",
                            "type_name": "Extreme AGL",
                            "mechanics": ["Dodge Cancel", {"name": "AoE"}],
                        }
                    ]
                },
            ]
        }
        briefing.render_stage_boss_info(boss_info, "Broly Event", 1, console=console)
        out = buf.getvalue()
        assert "Broly" in out
        assert "Dodge Cancel, AoE" in out

    def test_render_ai_stage_synthesis_header_dict_phases(self):
        console, buf = _create_test_console()

        class MockStage:
            event_name = "Red Zone"
            stage_name = "Stage 1"
            stage_id = 101
            phases = [{"element_name": "Extreme AGL", "cancels_dodge": True}]

        briefing.render_ai_stage_synthesis_header(MockStage(), console=console)
        out = buf.getvalue()
        assert "Red Zone" in out
        assert "Cancels Dodge" in out

    def test_render_team_presentation_plain_objects_and_shortlist(self):
        console, buf = _create_test_console()

        class MockRec:
            boss_stage = None
            mission_summary = None
            all_cards = []
            leader = None
            friend_leader = None

            class Rot:
                slot1 = None
                slot2 = object()
                shared_links = []
                synergy_score = 5.0

            rotation_a = Rot()
            rotation_b = Rot()
            floaters = [object()]
            ai_reasoning = None
            tactical_analysis = None

        class MockCand:
            card = object()
            score = 8.5
            reasoning = "Good sub"

        briefing.render_team_presentation(MockRec(), console=console, shortlist=[MockCand()])
        out = buf.getvalue()
        assert "Rotazione A" in out
        assert "Good sub" in out
        assert "8.5" in out

    def test_render_mission_batches_and_endgame_header_none_safety(self):
        console, buf = _create_test_console()
        mock_batch = MagicMock()
        mock_batch.missions = None
        mock_batch.summary = None
        briefing.render_mission_batches(
            [mock_batch], "Event", 1, saved=0, total_missions=0, console=console
        )
        assert "Mission Batches" in buf.getvalue()

        console, buf = _create_test_console()
        mock_stage = MagicMock()
        mock_stage.phases = None
        briefing.render_endgame_header(
            mock_stage, dry_run=False, force_solve=False, mission_batch=None, console=console
        )
        assert "Endgame Autonomous Runner" in buf.getvalue()


class TestUIWizards:
    """Verifies interactive wizard flows and prompt handling in dokkan_eza_link_farmer.ui.wizards."""

    def test_handle_stage_farm_interactive_direct(self):
        engine = MagicMock()
        console, _ = _create_test_console()
        wizards.handle_stage_farm_interactive(engine, console, ["10", "--boost", "--super2"])
        engine.start_stage_farm.assert_called_once_with(
            runs=10, use_boost=True, preferred_difficulty="super2"
        )

    def test_handle_stage_farm_interactive_none_args(self):
        engine = MagicMock()
        console, _ = _create_test_console()
        wizards.handle_stage_farm_interactive(engine, console, None)
        engine.start_stage_farm.assert_called_once_with(
            runs=None, use_boost=None, preferred_difficulty=None
        )

    def test_handle_link_interactive_none_and_args(self):
        engine = MagicMock()
        console, _ = _create_test_console()
        wizards.handle_link_interactive(engine, console, ["15", "--ur", "--lr", "39-3", "--boost"])
        engine.start_link_level_farm.assert_called_once_with(
            runs=15,
            target_event=None,
            use_boost=True,
            filter_ur=True,
            filter_lr=True,
            target_stage="area_39_3",
            stage_name="Area 39 Stage 3: Great stamina-friendly option (also drops green gems) | 5 fights",
        )

        engine.start_link_level_farm.reset_mock()
        with patch("questionary.select") as mock_select:
            mock_select.return_value.ask.return_value = "cancel"
            wizards.handle_link_interactive(engine, console, None)
            engine.start_link_level_farm.assert_not_called()

    def test_handle_eza_interactive_direct_and_cancel(self):
        engine = MagicMock()
        console, _ = _create_test_console()
        wizards.handle_eza_interactive(engine, console, ["45"])
        engine.start_eza_farm.assert_called_once_with(target_level=45)

        engine.start_eza_farm.reset_mock()
        with patch("questionary.select") as mock_select:
            mock_select.side_effect = KeyboardInterrupt
            wizards.handle_eza_interactive(engine, console, None)
            engine.start_eza_farm.assert_not_called()

    def test_select_challenge_boss_stage_preset_and_cancellation(self):
        engine = MagicMock()
        console, _ = _create_test_console()
        with patch("questionary.select") as mock_select:
            mock_select.side_effect = [
                MagicMock(ask=MagicMock(return_value="preset")),
                MagicMock(ask=MagicMock(return_value="rz_broly")),
            ]
            stage = wizards.select_challenge_boss_stage(engine, console)
            assert stage is not None
            assert "broly" in str(stage.stage_id).lower() or "broly" in stage.stage_name.lower()

        with patch("questionary.select") as mock_select:
            mock_select.side_effect = [
                MagicMock(ask=MagicMock(return_value="preset")),
                MagicMock(ask=MagicMock(side_effect=KeyboardInterrupt)),
            ]
            res = wizards.select_challenge_boss_stage(engine, console)
            assert res is None

    def test_select_challenge_boss_stage_dokkandb_cancellation(self):
        engine = MagicMock()
        engine.dokkandb.get_challenge_events.return_value = [{"id": 100, "name": "Test Event"}]
        engine.dokkandb.get_event_details.return_value = {
            "quests": [{"quest_id": 1, "quest_name": "Stage 1", "stages": [{"stage_id": 1001}]}]
        }
        console, _ = _create_test_console()

        with patch("questionary.select") as mock_select:
            mock_select.side_effect = [
                MagicMock(ask=MagicMock(return_value={"id": 100, "name": "Test Event"})),
                MagicMock(ask=MagicMock(side_effect=KeyboardInterrupt)),
            ]
            res = wizards.select_challenge_boss_stage(engine, console)
            assert res is None

    def test_prompt_stage_missions_cancellation(self):
        stage = MagicMock()
        stage.event_id = 100
        stage.stage_id = 10001
        stage.stage_name = "Stage 1"
        dokkandb = MagicMock()
        dokkandb.get_event_missions.return_value = [
            {"id": 1, "name": "Mission 1", "description": "Clear Stage 1 with Realm of Gods"}
        ]
        console, _ = _create_test_console()

        with patch("questionary.checkbox") as mock_checkbox:
            mock_checkbox.return_value.ask.side_effect = KeyboardInterrupt
            res = wizards.prompt_stage_missions(stage, dokkandb, console)
            assert res is None

    def test_ai_find_partners_and_build_team_cancellation(self):
        engine = MagicMock()
        console, _ = _create_test_console()

        with patch("questionary.text") as mock_text:
            mock_text.return_value.ask.side_effect = KeyboardInterrupt
            wizards.ai_find_partners(engine, console, query="")

        with patch("questionary.select") as mock_select:
            mock_select.return_value.ask.side_effect = KeyboardInterrupt
            wizards.ai_build_team(engine, console, query="")

        with patch("questionary.select") as mock_select:
            mock_select.side_effect = KeyboardInterrupt
            wizards.handle_ai_interactive(engine, console, args=[])

    def test_handle_box_scan_interactive_cancellation_and_custom_prompt(self):
        engine = MagicMock()
        engine.adb.is_connected.return_value = True
        console, _ = _create_test_console()

        with patch("questionary.select") as mock_select:
            mock_select.return_value.ask.side_effect = KeyboardInterrupt
            wizards.handle_box_scan_interactive(engine, console)
            engine.start_box_scanner.assert_not_called()

        with (
            patch("questionary.select") as mock_select,
            patch("rich.prompt.Prompt.ask", side_effect=KeyboardInterrupt),
        ):
            mock_select.return_value.ask.return_value = -1
            wizards.handle_box_scan_interactive(engine, console)
            engine.start_box_scanner.assert_not_called()

    def test_handle_challenge_interactive_cancellation_during_stage_and_confirm(self):
        engine = MagicMock()
        engine.dokkandb.get_challenge_events.return_value = [{"id": 100, "name": "Event 100"}]
        engine.dokkandb.get_event_details.return_value = {
            "quests": [{"quest_id": 1, "quest_name": "Stage 1", "stages": [{"stage_id": 1001}]}]
        }
        engine.dokkandb.get_challenge_missions.return_value = []
        console, _ = _create_test_console()

        with patch("questionary.select") as mock_select:
            mock_select.side_effect = KeyboardInterrupt
            wizards.handle_challenge_interactive(engine, console)
            engine.start_challenge_farm.assert_not_called()

        with (
            patch("questionary.select") as mock_select,
            patch("questionary.confirm") as mock_confirm,
        ):
            mock_select.return_value.ask.return_value = {
                "stage_num": 1,
                "stage_id": 1001,
                "stage_name": "Stage 1",
            }
            mock_confirm.return_value.ask.side_effect = KeyboardInterrupt
            wizards.handle_challenge_interactive(engine, console)
            engine.start_challenge_farm.assert_not_called()

    def test_handle_eza_interactive_target_level_cancellation(self):
        engine = MagicMock()
        console, _ = _create_test_console()

        with patch("questionary.select") as mock_select, patch("questionary.text") as mock_text:
            mock_select.return_value.ask.return_value = "auto"
            mock_text.return_value.ask.return_value = None
            wizards.handle_eza_interactive(engine, console, None)
            engine.start_eza_farm.assert_not_called()

        with patch("questionary.select") as mock_select, patch("questionary.text") as mock_text:
            mock_select.side_effect = [
                MagicMock(ask=MagicMock(return_value="select")),
                MagicMock(ask=MagicMock(return_value={"id": 1, "name": "EZA Event"})),
            ]
            engine.dokkandb.get_zbattles.return_value = [{"id": 1, "name": "EZA Event"}]
            mock_text.return_value.ask.return_value = None
            wizards.handle_eza_interactive(engine, console, None)
            engine.start_eza_farm.assert_not_called()


class TestUITerminalCLI:
    """Verifies TerminalCLI command routing and zero-interaction flag handling."""

    def test_ui_package_exports(self):
        import dokkan_eza_link_farmer.ui as ui

        assert hasattr(ui, "TerminalCLI")
        assert hasattr(ui, "briefing")
        assert hasattr(ui, "panels")
        assert hasattr(ui, "wizards")

    def test_handle_enrich_box_delegation_and_resilience(self):
        engine = MagicMock()
        cli = TerminalCLI(engine)

        with patch("dokkan_eza_link_farmer.ai.syncer.DokkanSyncer.sync_box_details") as mock_sync:
            mock_sync.return_value = [101, 102]
            cli.handle_enrich_box(["custom_box.json", "--force"])
            mock_sync.assert_called_with(
                box_file="custom_box.json",
                force=True,
                save_to_file=True,
            )

            mock_sync.reset_mock()
            cli.handle_enrich_box(None)
            mock_sync.assert_called_with(
                box_file=None,
                force=False,
                save_to_file=True,
            )

            mock_sync.side_effect = RuntimeError("Sync failure")
            cli.handle_enrich_box(["--force"])

    def test_declarative_cli_flags_zero_interaction(self):
        """Verifies that direct declarative CLI flags bypass interactive wizards entirely."""
        engine = MagicMock()
        engine.is_task_running.return_value = False

        # 1. Direct --eza 999 flag
        cli_eza = TerminalCLI(engine, args=["--eza", "999"])
        cli_eza.run()
        engine.start_eza_farm.assert_called_once_with(target_level=999)

        # 2. Direct --link 39-3 with --boost and --runs
        engine.reset_mock()
        cli_link = TerminalCLI(engine, args=["--link", "39-3", "--boost", "--runs", "10"])
        cli_link.run()
        engine.start_link_level_farm.assert_called_once()
        _, kwargs = engine.start_link_level_farm.call_args
        assert kwargs["target_stage"] == "area_39_3"
        assert kwargs["use_boost"] is True
        assert kwargs["runs"] == 10

        # 3. Direct --stage 15 with --super2
        engine.reset_mock()
        cli_stage = TerminalCLI(engine, args=["--stage", "15", "--super2"])
        cli_stage.run()
        engine.start_stage_farm.assert_called_once_with(
            runs=15, use_boost=None, preferred_difficulty="super2"
        )

        # 4. Direct --challenge flag with event and stage
        engine.reset_mock()
        with patch("dokkan_eza_link_farmer.ui.wizards.handle_challenge_interactive") as mock_chal:
            cli_chal = TerminalCLI(engine, args=["--challenge", "broly", "1"])
            cli_chal.run()
            mock_chal.assert_called_once_with(engine, cli_chal.console, ["broly", "1", "-y"])

        # 5. Direct --ai-run flag with --stage does not conflict with stage farming
        engine.reset_mock()
        with patch.object(TerminalCLI, "handle_ai_endgame_run") as mock_ai_endgame:
            cli_ai = TerminalCLI(engine, args=["--ai-run", "--stage", "10101", "--dry-run"])
            cli_ai.run()
            mock_ai_endgame.assert_called_once_with(
                target_stage="10101",
                dry_run=True,
                force_solve=False,
                max_attempts=None,
            )
            engine.start_stage_farm.assert_not_called()

        # 6. Direct --enrich-box flag
        engine.reset_mock()
        with patch.object(TerminalCLI, "handle_enrich_box") as mock_enrich:
            cli_enrich = TerminalCLI(engine, args=["--enrich-box"])
            cli_enrich.run()
            mock_enrich.assert_called_once_with(["--enrich-box"])

        # 7. Direct --challenge=broly 1 with = syntax
        engine.reset_mock()
        with patch("dokkan_eza_link_farmer.ui.wizards.handle_challenge_interactive") as mock_chal:
            cli_chal = TerminalCLI(engine, args=["--challenge=broly", "1"])
            cli_chal.run()
            mock_chal.assert_called_once_with(engine, cli_chal.console, ["broly", "1", "-y"])

        # 8. Direct --ai-run with intervening flag (--dry-run) before positional stage
        engine.reset_mock()
        with patch.object(TerminalCLI, "handle_ai_endgame_run") as mock_ai_endgame:
            cli_ai2 = TerminalCLI(engine, args=["--ai-run", "--dry-run", "10101"])
            cli_ai2.run()
            mock_ai_endgame.assert_called_once_with(
                target_stage="10101",
                dry_run=True,
                force_solve=False,
                max_attempts=None,
            )

        # 9. Direct --eza with auto and target level
        engine.reset_mock()
        cli_eza_auto = TerminalCLI(engine, args=["--eza", "auto", "50"])
        cli_eza_auto.run()
        engine.start_eza_farm.assert_called_once_with(target_level=50)

        # 10. Direct --link with = syntax and --runs
        engine.reset_mock()
        cli_link_eq = TerminalCLI(engine, args=["--link=35-1", "--runs=10"])
        cli_link_eq.run()
        engine.start_link_level_farm.assert_called_once()
        _, kw_link = engine.start_link_level_farm.call_args
        assert kw_link["target_stage"] == "area_35_1"
        assert kw_link["runs"] == 10

        # 11. Direct --link with arbitrary positional stage
        engine.reset_mock()
        cli_link_pos = TerminalCLI(engine, args=["--link", "area_12_3"])
        cli_link_pos.run()
        engine.start_link_level_farm.assert_called_once()
        _, kw_link2 = engine.start_link_level_farm.call_args
        assert kw_link2["target_stage"] == "area_12_3"

        # 12. Direct --challenge with --stage flag bypasses stage farm
        engine.reset_mock()
        with patch("dokkan_eza_link_farmer.ui.wizards.handle_challenge_interactive") as mock_chal:
            cli_chal2 = TerminalCLI(engine, args=["--challenge", "broly", "--stage", "1"])
            cli_chal2.run()
            mock_chal.assert_called_once_with(
                engine, cli_chal2.console, ["broly", "--stage", "1", "-y"]
            )
            engine.start_stage_farm.assert_not_called()

        # 13. Direct --challenge=broly --stage=2 with = syntax
        engine.reset_mock()
        with patch("dokkan_eza_link_farmer.ui.wizards.handle_challenge_interactive") as mock_chal:
            cli_chal3 = TerminalCLI(engine, args=["--challenge=broly", "--stage=2"])
            cli_chal3.run()
            mock_chal.assert_called_once_with(
                engine, cli_chal3.console, ["broly", "--stage=2", "-y"]
            )
            engine.start_stage_farm.assert_not_called()

        # 14. Standalone --challenge without args does not pass -y
        engine.reset_mock()
        with patch("dokkan_eza_link_farmer.ui.wizards.handle_challenge_interactive") as mock_chal:
            cli_chal4 = TerminalCLI(engine, args=["--challenge"])
            cli_chal4.run()
            mock_chal.assert_called_once_with(engine, cli_chal4.console, [])

        # 15. Direct --ai run --stage 10101
        engine.reset_mock()
        with patch.object(TerminalCLI, "handle_ai_endgame_run") as mock_ai_endgame:
            cli_ai_stage = TerminalCLI(engine, args=["--ai", "run", "--stage", "10101"])
            cli_ai_stage.run()
            mock_ai_endgame.assert_called_once_with("10101")
            engine.start_stage_farm.assert_not_called()

        # 16. Direct --ai run 10101 positional
        engine.reset_mock()
        with patch.object(TerminalCLI, "handle_ai_endgame_run") as mock_ai_endgame:
            cli_ai_pos = TerminalCLI(engine, args=["--ai", "run", "10101"])
            cli_ai_pos.run()
            mock_ai_endgame.assert_called_once_with("10101")

    def test_handle_challenge_interactive_declarative_stage_and_event_id(self):
        """Verifies handle_challenge_interactive executes zero-interaction runs for event IDs and stage flags."""
        engine = MagicMock()
        engine.dokkandb.get_challenge_events.return_value = [
            {"id": 100, "name": "Cell Max"},
            {"id": 601, "name": "Broly"},
        ]
        engine.dokkandb.get_event_details.return_value = {
            "quests": [
                {"quest_id": 1, "quest_name": "Stage 1", "stages": [{"stage_id": 60101}]},
                {"quest_id": 2, "quest_name": "Stage 2", "stages": [{"stage_id": 60102}]},
            ]
        }
        engine.dokkandb.get_challenge_missions.return_value = []
        console, _ = _create_test_console()

        # 1. Event ID only -> defaults to Stage 1 without prompt
        engine.reset_mock()
        wizards.handle_challenge_interactive(engine, console, ["601"])
        engine.start_challenge_farm.assert_called_once()
        assert engine.start_challenge_farm.call_args[1]["stage_num"] == 1
        assert engine.start_challenge_farm.call_args[1]["target_event"]["id"] == 601

        # 2. Event ID + Stage positional
        engine.reset_mock()
        wizards.handle_challenge_interactive(engine, console, ["601", "2"])
        engine.start_challenge_farm.assert_called_once()
        assert engine.start_challenge_farm.call_args[1]["stage_num"] == 2

        # 3. Event ID + --stage flag
        engine.reset_mock()
        wizards.handle_challenge_interactive(engine, console, ["601", "--stage", "2"])
        engine.start_challenge_farm.assert_called_once()
        assert engine.start_challenge_farm.call_args[1]["stage_num"] == 2

        # 4. Event name + --stage= flag
        engine.reset_mock()
        wizards.handle_challenge_interactive(engine, console, ["broly", "--stage=2"])
        engine.start_challenge_farm.assert_called_once()
        assert engine.start_challenge_farm.call_args[1]["stage_num"] == 2

    def test_handle_eza_interactive_declarative_flags(self):
        """Verifies that handle_eza_interactive parses varied declarative level flags without interaction."""
        engine = MagicMock()
        console, _ = _create_test_console()

        for flag_args, expected_lvl in [
            (["--eza", "50"], 50),
            (["--eza=75"], 75),
            (["--level", "100"], 100),
            (["-e", "35"], 35),
            (["auto", "40"], 40),
            (["99"], 99),
            (["--eza"], 999),
            (["-e"], 999),
        ]:
            engine.reset_mock()
            wizards.handle_eza_interactive(engine, console, flag_args)
            engine.start_eza_farm.assert_called_once_with(target_level=expected_lvl)

    def test_handle_link_interactive_declarative_flags(self):
        """Verifies that handle_link_interactive parses stage and options with zero secondary prompts."""
        engine = MagicMock()
        console, _ = _create_test_console()

        # Positional stage
        engine.reset_mock()
        wizards.handle_link_interactive(engine, console, ["35-1"])
        engine.start_link_level_farm.assert_called_once()
        assert engine.start_link_level_farm.call_args[1]["target_stage"] == "area_35_1"

        # Explicit --stage flag with --runs
        engine.reset_mock()
        wizards.handle_link_interactive(
            engine, console, ["--stage", "39-3", "--runs", "20", "--no-boost"]
        )
        engine.start_link_level_farm.assert_called_once()
        kw = engine.start_link_level_farm.call_args[1]
        assert kw["target_stage"] == "area_39_3"
        assert kw["runs"] == 20
        assert kw["use_boost"] is False

        # Standalone --link flag defaults cleanly
        engine.reset_mock()
        wizards.handle_link_interactive(engine, console, ["--link"])
        engine.start_link_level_farm.assert_called_once()
        assert engine.start_link_level_farm.call_args[1]["target_stage"] == "area_39_3"

        # Regex resolution for arbitrary story quest stage
        stage_id, stage_desc = wizards._resolve_link_stage("34-4")
        assert stage_id == "area_34_4"
        assert "34" in stage_desc and "4" in stage_desc

    def test_terminal_cli_monitor_task(self):
        """Verifies that monitor_task polls while task is running and handles exit safely."""
        engine = MagicMock()
        cli = TerminalCLI(engine)

        call_count = [0]

        def fake_is_running():
            call_count[0] += 1
            return call_count[0] < 3

        engine.is_task_running.side_effect = fake_is_running
        cli.monitor_task(poll_interval=0.01)
        assert call_count[0] >= 3

        engine.reset_mock()
        engine.is_task_running.side_effect = KeyboardInterrupt
        cli.monitor_task(poll_interval=0.01)
        engine.stop_task.assert_called_once()
