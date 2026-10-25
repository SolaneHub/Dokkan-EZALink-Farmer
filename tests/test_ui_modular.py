from __future__ import annotations

import copy
import io
from pathlib import Path
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


class TestUIModularPanels:
    """Verifies presentation panels extracted into ui/panels.py."""

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
        # 1. All found
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

        # 2. Missing tools with install help
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

        # AI Status
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
        # Pass completely empty dicts
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


class TestUIModularBriefing:
    """Verifies tactical briefings extracted into ui/briefing.py."""

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

        # Result success and fail
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


class TestUIModularWizards:
    """Verifies wizard helper flows extracted into ui/wizards.py."""

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
        # Direct args
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

        # None args cancellation
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
        # 1. Preset stage selection
        with patch("questionary.select") as mock_select:
            mock_select.side_effect = [
                MagicMock(ask=MagicMock(return_value="preset")),
                MagicMock(ask=MagicMock(return_value="rz_broly")),
            ]
            stage = wizards.select_challenge_boss_stage(engine, console)
            assert stage is not None
            assert "broly" in str(stage.stage_id).lower() or "broly" in stage.stage_name.lower()

        # 2. KeyboardInterrupt during preset selection cleanly returns None
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

        # ai_find_partners cancellation
        with patch("questionary.text") as mock_text:
            mock_text.return_value.ask.side_effect = KeyboardInterrupt
            wizards.ai_find_partners(engine, console, query="")

        # ai_build_team cancellation
        with patch("questionary.select") as mock_select:
            mock_select.return_value.ask.side_effect = KeyboardInterrupt
            wizards.ai_build_team(engine, console, query="")

        # handle_ai_interactive cancellation
        with patch("questionary.select") as mock_select:
            mock_select.side_effect = KeyboardInterrupt
            wizards.handle_ai_interactive(engine, console, args=[])

    def test_handle_box_scan_interactive_cancellation_and_custom_prompt(self):
        engine = MagicMock()
        engine.adb.is_connected.return_value = True
        console, _ = _create_test_console()

        # KeyboardInterrupt during mode select
        with patch("questionary.select") as mock_select:
            mock_select.return_value.ask.side_effect = KeyboardInterrupt
            wizards.handle_box_scan_interactive(engine, console)
            engine.start_box_scanner.assert_not_called()

        # KeyboardInterrupt during custom cards Prompt.ask
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

        # KeyboardInterrupt during stage select
        with patch("questionary.select") as mock_select:
            mock_select.side_effect = KeyboardInterrupt
            wizards.handle_challenge_interactive(engine, console)
            engine.start_challenge_farm.assert_not_called()

        # KeyboardInterrupt during confirm
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

        # Cancellation in 'auto' mode during target_level prompt
        with patch("questionary.select") as mock_select, patch("questionary.text") as mock_text:
            mock_select.return_value.ask.return_value = "auto"
            mock_text.return_value.ask.return_value = None
            wizards.handle_eza_interactive(engine, console, None)
            engine.start_eza_farm.assert_not_called()

        # Cancellation in 'select' mode during target_level prompt
        with patch("questionary.select") as mock_select, patch("questionary.text") as mock_text:
            mock_select.side_effect = [
                MagicMock(ask=MagicMock(return_value="select")),
                MagicMock(ask=MagicMock(return_value={"id": 1, "name": "EZA Event"})),
            ]
            engine.dokkandb.get_zbattles.return_value = [{"id": 1, "name": "EZA Event"}]
            mock_text.return_value.ask.return_value = None
            wizards.handle_eza_interactive(engine, console, None)
            engine.start_eza_farm.assert_not_called()


class TestUIModularTerminalCLI:
    """Verifies that TerminalCLI remains a streamlined router satisfying line count and backward compatibility."""

    def test_cli_line_count_strictly_under_500(self):
        cli_file = Path(__file__).parent.parent / "src" / "dokkan_eza_link_farmer" / "ui" / "cli.py"
        lines = cli_file.read_text(encoding="utf-8").splitlines()
        assert len(lines) < 500, f"cli.py must be under 500 lines, but was {len(lines)}"

    def test_ui_package_exports(self):
        import dokkan_eza_link_farmer.ui as ui

        assert hasattr(ui, "TerminalCLI")
        assert hasattr(ui, "briefing")
        assert hasattr(ui, "panels")
        assert hasattr(ui, "wizards")

    def test_terminal_cli_public_methods_and_delegation(self):
        engine = MagicMock()
        cli = TerminalCLI(engine)

        # 1. Panel delegates
        with patch("dokkan_eza_link_farmer.ui.panels.render_banner") as mock_banner:
            cli.print_banner()
            mock_banner.assert_called_once_with(cli.console)

        with patch("dokkan_eza_link_farmer.ui.panels.render_help") as mock_help:
            cli.print_help()
            mock_help.assert_called_once_with(cli.console)

        with patch("dokkan_eza_link_farmer.ui.panels.render_doctor") as mock_doc:
            cli.print_doctor()
            mock_doc.assert_called_once()

        with patch("dokkan_eza_link_farmer.ui.panels.render_status") as mock_stat:
            cli.print_status()
            mock_stat.assert_called_once()

        # 2. Wizard delegates
        with patch("dokkan_eza_link_farmer.ui.wizards.handle_eza_interactive") as mock_eza:
            cli.handle_eza_interactive(["30"])
            mock_eza.assert_called_once_with(engine, cli.console, ["30"])

            # Call with no args and None
            cli.handle_eza_interactive()
            cli.handle_eza_interactive(None)

        with patch("dokkan_eza_link_farmer.ui.wizards.handle_link_interactive") as mock_link:
            cli.handle_link_interactive(["10"])
            mock_link.assert_called_once_with(engine, cli.console, ["10"])

            # Call with no args and None
            cli.handle_link_interactive()
            cli.handle_link_interactive(None)

        with patch("dokkan_eza_link_farmer.ui.wizards.handle_stage_farm_interactive") as mock_stage:
            cli.handle_stage_farm_interactive(["--boost"])
            mock_stage.assert_called_once_with(engine, cli.console, ["--boost"])

            # Call with no args and None
            cli.handle_stage_farm_interactive()
            cli.handle_stage_farm_interactive(None)

        with patch("dokkan_eza_link_farmer.ui.wizards.handle_challenge_interactive") as mock_chal:
            cli.handle_challenge_interactive(["-y"])
            mock_chal.assert_called_once_with(engine, cli.console, ["-y"])

        with patch("dokkan_eza_link_farmer.ui.wizards.handle_box_scan_interactive") as mock_scan:
            cli.handle_box_scan_interactive(["50"])
            mock_scan.assert_called_once_with(engine, cli.console, ["50"], log_file=None)

        with patch("dokkan_eza_link_farmer.ui.wizards.handle_ai_interactive") as mock_ai:
            cli.handle_ai_interactive()
            mock_ai.assert_called_once()

    def test_handle_enrich_box_delegation_and_resilience(self):
        engine = MagicMock()
        cli = TerminalCLI(engine)

        with patch("dokkan_eza_link_farmer.ai.syncer.DokkanSyncer.sync_box_details") as mock_sync:
            mock_sync.return_value = [101, 102]
            # 1. Custom file and force flag
            cli.handle_enrich_box(["custom_box.json", "--force"])
            mock_sync.assert_called_with(
                box_file="custom_box.json",
                force=True,
                save_to_file=True,
            )

            # 2. None args
            mock_sync.reset_mock()
            cli.handle_enrich_box(None)
            mock_sync.assert_called_with(
                box_file=None,
                force=False,
                save_to_file=True,
            )

            # 3. Exception resilience
            mock_sync.side_effect = RuntimeError("Sync failure")
            cli.handle_enrich_box(["--force"])

    def test_terminal_cli_internal_delegates(self):
        engine = MagicMock()
        cli = TerminalCLI(engine)

        with patch("dokkan_eza_link_farmer.ui.wizards.ai_find_partners") as mock_find:
            cli._ai_find_partners("goku")
            mock_find.assert_called_once_with(engine, cli.console, query="goku")

        with patch("dokkan_eza_link_farmer.ui.wizards.ai_build_team") as mock_build:
            cli._ai_build_team("vegeta")
            mock_build.assert_called_once()

        with patch("dokkan_eza_link_farmer.ui.wizards.ai_configure_model") as mock_conf:
            cli._ai_configure_model()
            mock_conf.assert_called_once()

        with patch("dokkan_eza_link_farmer.ui.wizards.ai_build_team_for_stage") as mock_st_build:
            stage_mock = MagicMock()
            cli._ai_build_team_for_stage(stage_mock)
            mock_st_build.assert_called_once()

        with patch("dokkan_eza_link_farmer.ui.briefing.render_team_presentation") as mock_pres:
            rec_mock = MagicMock()
            cli._render_team_presentation(rec_mock, title="Title")
            mock_pres.assert_called_once_with(
                rec_mock, console=cli.console, title="Title", shortlist=None
            )

        with patch("dokkan_eza_link_farmer.ui.panels.render_ai_status") as mock_ai_stat:
            cli._ai_show_status()
            mock_ai_stat.assert_called_once()
