from __future__ import annotations

import contextlib
import io
import logging
import sys
import time
from typing import TYPE_CHECKING, Any

from rich.console import Console
from rich.prompt import Prompt

if TYPE_CHECKING:
    from dokkan_eza_link_farmer.core.bot_engine import BotEngine

from dokkan_eza_link_farmer.core.i18n import get_available_languages, get_language, set_language, t
from dokkan_eza_link_farmer.ui import briefing, panels, wizards

logger = logging.getLogger(__name__)

if sys.platform == "win32":
    with contextlib.suppress(Exception):
        if isinstance(sys.stdout, io.TextIOWrapper):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if isinstance(sys.stderr, io.TextIOWrapper):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _get_flag_val(flags: list[str], *flag_names: str) -> str | None:
    """Helper to extract option argument or value from --flag=val or --flag val."""
    for idx, f in enumerate(flags):
        low = f.lower()
        for name in flag_names:
            if low == name and idx + 1 < len(flags) and not flags[idx + 1].startswith("-"):
                return flags[idx + 1]
            if low.startswith(f"{name}="):
                return f.split("=", 1)[1]
    return None


def _resolve_boss_stage(dokkandb: Any, target_stage: Any) -> Any | None:
    from dokkan_eza_link_farmer.ai.boss_catalog import get_boss_stage
    from dokkan_eza_link_farmer.ai.models import BossStage

    if isinstance(target_stage, BossStage):
        return target_stage
    if target_stage is None:
        return None
    with contextlib.suppress(Exception):
        return get_boss_stage(target_stage, dokkandb=dokkandb)
    query = str(target_stage).strip().lower()
    with contextlib.suppress(Exception):
        for ev in dokkandb.get_challenge_events(active_only=False):
            ev_name = (ev.get("name") or "").lower()
            ev_id = ev.get("id")
            if ev_id is not None and (query in ev_name or query == str(ev_id)):
                det = dokkandb.get_event_details(int(ev_id))
                if det and det.get("quests"):
                    stages = det["quests"][0].get("stages", [])
                    if stages and stages[0].get("stage_id"):
                        b_info = dokkandb.get_stage_boss_info(
                            int(ev_id), int(stages[0]["stage_id"])
                        )
                        if b_info and b_info.get("phases"):
                            return BossStage.from_dokkandb(b_info)
    return None


class TerminalCLI:
    """Rich interactive Terminal Command Interface for Dokkan-EZALink-Farmer."""

    def __init__(self, engine: BotEngine, args: list[str] | None = None):
        self.engine = engine
        self.console = Console()
        self.cli_args = list(args) if args else []

        # Route bot logs into Rich console
        self.engine.register_log_callback(self._on_log)
        self.engine.register_run_callback(self._on_run_update)

    def _on_log(self, msg: str) -> None:
        """Displays formatted log message in terminal."""
        self.console.print(f"[dim]{time.strftime('%H:%M:%S')}[/dim] [cyan][BOT][/cyan] {msg}")

    def _on_run_update(self, curr: int, tot: Any) -> None:
        """Displays run completion counter."""
        tot_str = str(tot) if tot and tot > 0 else "∞"
        self.console.print(f"[bold green]{t('cli.progress_format', curr=curr, tot=tot_str)}[/]")

    def print_banner(self) -> None:
        """Renders stylized welcome banner."""
        panels.render_banner(self.console)

    def print_help(self) -> None:
        """Renders interactive command table."""
        panels.render_help(self.console)

    def print_doctor(self) -> None:
        """Renders comprehensive environment diagnostics."""
        report = self.engine.diagnose_environment()
        panels.render_doctor(report, self.console)

    def print_status(self) -> None:
        """Renders status summary card."""
        info = self.engine.get_status_summary()
        panels.render_status(info, self.console)

    def monitor_task(self, poll_interval: float = 0.5) -> None:
        """Monitors a running background task until completion without interactive prompts."""
        try:
            while self.engine.is_task_running():
                time.sleep(poll_interval)
        except (KeyboardInterrupt, EOFError):
            with contextlib.suppress(Exception):
                self.engine.stop_task()
            self.console.print(f"\n[bold yellow]{t('cli.exit_message')}[/]")

    def execute_flags(self, flags: list[str]) -> bool:
        """Parses declarative CLI flags and executes the matching action without interactive prompts."""
        if not flags:
            return False

        f_list = [str(f) for f in flags]
        lows = [f.lower() for f in f_list]

        # 1. Diagnostics / Help
        if any(f in ("--doctor", "--check", "doctor", "check") for f in lows):
            self.print_doctor()
            return True

        if any(f in ("--devices", "devices") for f in lows):
            panels.render_devices_table(self.engine.list_devices(), self.console)
            return True

        # 2. AI Endgame Run (Checked before --stage to avoid flag collision)
        if any(
            f in ("--ai-run", "--endgame", "ai-run", "endgame")
            or f.startswith(("--ai-run=", "--endgame="))
            for f in lows
        ):
            target_stage = _get_flag_val(
                f_list, "--stage", "-s", "--ai-run", "--endgame", "ai-run", "endgame"
            )
            if target_stage is None:
                for idx, a in enumerate(f_list):
                    if (
                        not a.startswith("-")
                        and a.lower() not in ("ai-run", "endgame", "ai_run")
                        and (idx == 0 or f_list[idx - 1].lower() != "--max-attempts")
                    ):
                        target_stage = a
                        break
            max_att = (
                int(m) if (m := _get_flag_val(f_list, "--max-attempts")) and m.isdigit() else None
            )
            self.handle_ai_endgame_run(
                target_stage=target_stage,
                dry_run=any(f in ("--dry-run", "-d") for f in lows),
                force_solve=any(f in ("--force-solve", "--force", "-f") for f in lows),
                max_attempts=max_att,
            )
            return True

        # 3. EZA Continuous Grinder
        if any(f in ("--eza", "-e", "eza") or f.startswith(("--eza=", "--level=")) for f in lows):
            sub = [
                f.split("=", 1)[1] if f.lower().startswith(("--eza=", "--level=")) else f
                for f in f_list
                if f.lower() not in ("--eza", "-e", "eza")
            ]
            self.handle_eza_interactive(sub if sub else ["999"])
            return True

        # 4. Link Leveling
        if any(f in ("--link", "link") or f.startswith("--link=") for f in lows):
            sub = [
                f.split("=", 1)[1] if f.lower().startswith("--link=") else f
                for f in f_list
                if f.lower() not in ("--link", "link")
            ]
            val = _get_flag_val(f_list, "--link")
            if val and val not in sub:
                sub.insert(0, val)
            self.handle_link_interactive(sub if sub else ["39-3"])
            return True

        # 5. Autonomous Challenge Solver (Checked before --stage to avoid flag collision)
        if any(
            f in ("--challenge", "-c", "challenge", "redzone", "smb")
            or f.startswith(("--challenge=", "-c="))
            for f in lows
        ):
            sub = [
                f.split("=", 1)[1] if f.lower().startswith(("--challenge=", "-c=")) else f
                for f in f_list
                if f.lower() not in ("--challenge", "-c", "challenge", "redzone", "smb")
            ]
            val = _get_flag_val(f_list, "--challenge", "-c")
            if val and val not in sub:
                sub.insert(0, val)
            if sub and "-y" not in [a.lower() for a in sub]:
                sub.append("-y")
            self.handle_challenge_interactive(sub)
            return True

        # 6. Character Box Scanner (OCR)
        if any(
            f in ("--scan-box", "--scan", "--box-scan", "scan-box", "box-scan", "scan")
            for f in lows
        ):
            self.handle_box_scan_interactive(
                f_list, log_file=_get_flag_val(f_list, "--log-file", "-lf", "--log")
            )
            return True

        # 7. Enrich Box
        if any(
            f in ("--enrich-box", "--enrich_box", "--enrich", "enrich-box", "enrich_box", "enrich")
            for f in lows
        ):
            self.handle_enrich_box(f_list)
            return True

        # 8. AI Advisor / Teambuilder (Checked before --stage to avoid flag collision)
        if any(
            f in ("--ai", "--team", "ai", "team") or f.startswith(("--ai=", "--team="))
            for f in lows
        ):
            sub = [
                f.split("=", 1)[1] if f.lower().startswith(("--ai=", "--team=")) else f
                for f in f_list
                if f.lower() not in ("--ai", "--team", "ai", "team")
            ]
            self.handle_ai_interactive(sub)
            return True

        # 9. Stage Farm (Only when not part of other commands)
        if any(
            f in ("--stage", "-s", "stage", "farm", "repeat", "clear", "farm-stage")
            or f.startswith("--stage=")
            for f in lows
        ):
            sub = [
                f.split("=", 1)[1] if f.lower().startswith("--stage=") else f
                for f in f_list
                if f.lower()
                not in ("--stage", "-s", "stage", "farm", "repeat", "clear", "farm-stage")
            ]
            self.handle_stage_farm_interactive(sub)
            return True

        return False

    def handle_eza_interactive(self, args: list | None = None) -> None:
        """Handles EZA command: declarative flag execution or interactive DokkanDB selection."""
        wizards.handle_eza_interactive(self.engine, self.console, args or [])

    def handle_link_interactive(self, args: list | None = None) -> None:
        """Handles Link Leveling command: declarative flag execution or interactive wizard."""
        wizards.handle_link_interactive(self.engine, self.console, args or [])

    def handle_stage_farm_interactive(self, args: list | None = None) -> None:
        """Handles stage auto-clearing command: repeats stage until stamina runs out."""
        wizards.handle_stage_farm_interactive(self.engine, self.console, args or [])

    def handle_challenge_interactive(self, args: list | None = None) -> None:
        """Interactive Challenge Event selector, Stage selector & Multi-mission Solver."""
        wizards.handle_challenge_interactive(self.engine, self.console, args)

    def handle_box_scan_interactive(
        self, args: list | None = None, log_file: str | None = None
    ) -> None:
        """Interactive OCR Character Box Scanner to autonomously build config/box.json."""
        wizards.handle_box_scan_interactive(self.engine, self.console, args, log_file=log_file)

    def handle_ai_endgame_run(
        self,
        target_stage: int | str | Any = None,
        dry_run: bool = False,
        force_solve: bool = False,
        max_attempts: int | None = None,
    ) -> None:
        """Runs the autonomous AI Endgame Trial & Error loop on target stage."""
        from dokkan_eza_link_farmer.ai.boss_catalog import list_boss_stages

        stage = (
            _resolve_boss_stage(self.engine.dokkandb, target_stage)
            if target_stage is not None
            else self._select_challenge_boss_stage()
        )
        if not stage:
            if target_stage is not None:
                self.console.print(
                    f"[bold red]Stage '{target_stage}' not found in catalog or DokkanDB.[/bold red]"
                )
                self.console.print("[yellow]Available catalog presets:[/yellow]")
                for s in list_boss_stages():
                    self.console.print(
                        f"  • [cyan]{s.stage_id}[/cyan]: {s.event_name} - {s.stage_name}"
                    )
            return

        mission_batch = self._prompt_stage_missions(stage)
        briefing.render_endgame_header(
            stage,
            dry_run=dry_run,
            force_solve=force_solve,
            mission_batch=mission_batch,
            console=self.console,
        )
        res = self.engine.run_ai_endgame_sync(
            stage_identifier=stage,
            dry_run=dry_run,
            force_solve=force_solve,
            mission_batch=mission_batch,
            max_attempts=max_attempts,
        )
        briefing.render_endgame_result(res, console=self.console)

    def handle_enrich_box(self, args: list | None = None) -> None:
        """Enriches ~/.dokkan-farmer/cache/user_box.json or config/box.json with DokkanDB deep data."""
        from dokkan_eza_link_farmer.ai.syncer import DokkanSyncer

        args = args or []
        force = "--force" in args or "-f" in args
        target_file = next((a for a in args if not a.startswith("-")), None)
        self.console.print(
            "[cyan]Enriching character box with deep card details (leader skills, categories, passives)...[/cyan]"
        )
        try:
            enriched = DokkanSyncer().sync_box_details(
                box_file=target_file, force=force, save_to_file=True
            )
            self.console.print(
                f"[bold green]✓ Successfully enriched {len(enriched)} cards in box![/bold green]"
            )
        except Exception as e:
            self.console.print(f"[bold red]Box enrichment failed: {e}[/bold red]")

    def _select_challenge_boss_stage(self, active_only: bool = True) -> Any:
        return wizards.select_challenge_boss_stage(
            self.engine, self.console, active_only=active_only
        )

    def _prompt_stage_missions(self, stage: Any) -> Any | None:
        return wizards.prompt_stage_missions(stage, self.engine.dokkandb, self.console)

    def _ai_build_team_for_stage(self, stage: Any) -> None:
        wizards.ai_build_team_for_stage(
            self.engine, self.console, stage, on_render=self._render_team_presentation
        )

    def _render_team_presentation(
        self, rec: Any, title: str = "", shortlist: list[Any] | None = None
    ) -> None:
        briefing.render_team_presentation(
            rec, console=self.console, title=title, shortlist=shortlist
        )

    def handle_ai_interactive(self, args: list | None = None) -> None:
        """Interactive AI Team Builder & Tactical Advisor (Qwen / DeepSeek-R1)."""
        wizards.handle_ai_interactive(
            self.engine,
            self.console,
            args or [],
            on_status=self._ai_show_status,
            on_partner=self._ai_find_partners,
            on_build=self._ai_build_team,
            on_config=self._ai_configure_model,
            on_endgame=self.handle_ai_endgame_run,
            on_select_stage=self._select_challenge_boss_stage,
        )

    def _ai_show_status(self) -> None:
        panels.render_ai_status(
            self.engine.ai_config, self.engine.ai_client.is_available(), self.console
        )

    def _ai_find_partners(self, query: str = "") -> None:
        wizards.ai_find_partners(self.engine, self.console, query=query)

    def _ai_build_team(self, query: str = "") -> None:
        wizards.ai_build_team(
            self.engine,
            self.console,
            query=query,
            on_build_for_stage=self._ai_build_team_for_stage,
            on_render=self._render_team_presentation,
            on_select_stage=self._select_challenge_boss_stage,
        )

    def _ai_configure_model(self) -> None:
        wizards.ai_configure_model(self.engine, self.console, on_status=self._ai_show_status)

    def run(self, args: list[str] | None = None, interactive: bool | None = None) -> None:
        """Runs the CLI: executes declarative flags, monitors running tasks, or runs interactive shell."""
        effective_args = args if args is not None else getattr(self, "cli_args", [])

        # Declarative CLI flags priority: zero interaction
        if effective_args and self.execute_flags(effective_args):
            if self.engine.is_task_running():
                self.monitor_task()
            return

        # If a task is already executing, monitor without prompting
        if interactive is False or (interactive is None and self.engine.is_task_running()):
            self.monitor_task()
            return

        self.print_banner()

        # Attempt auto-connect initially
        try:
            self.engine.connect()
        except Exception as e:
            self.console.print(f"[yellow]{t('cli.no_device_warning', error=str(e))}[/]")
            self.console.print(f"[dim]{t('cli.no_device_connect_hint')}[/dim]\n")

        while True:
            try:
                prompt_text = f"[bold cyan]{t('cli.prompt')}[/bold cyan]"
                line = Prompt.ask(prompt_text).strip()
                if not line:
                    continue

                parts = line.split()
                cmd = parts[0].lower()
                cmd_args = parts[1:]

                if cmd in ("exit", "quit", "q"):
                    if self.engine.is_task_running():
                        self.engine.stop_task()
                    self.engine.stop_scrcpy()
                    self.console.print(f"[bold yellow]{t('cli.exit_message')}[/]")
                    break

                if cmd in ("help", "?"):
                    self.print_help()
                elif cmd == "lang":
                    self._dispatch_lang(cmd_args)
                elif cmd == "connect":
                    serial = cmd_args[0] if cmd_args else None
                    try:
                        self.engine.connect(serial)
                    except Exception as e:
                        self.console.print(
                            f"[bold red]{t('cli.devices.connect_error', error=str(e))}[/]"
                        )
                elif cmd == "scrcpy":
                    self.engine.start_scrcpy()
                elif cmd == "scrcpy-stop":
                    self.engine.stop_scrcpy()
                elif cmd in ("inspect", "state"):
                    self._dispatch_inspect()
                elif cmd in ("shot", "screenshot"):
                    self._dispatch_shot(cmd_args)
                elif cmd == "discord":
                    self._dispatch_discord(cmd_args)
                elif cmd in ("stop", "pause", "resume"):
                    getattr(self.engine, f"{cmd}_task")()
                elif self._dispatch_interactive_task(cmd, cmd_args):
                    pass
                else:
                    self.console.print(f"[red]{t('cli.unknown_command', cmd=cmd)}[/]")

            except (KeyboardInterrupt, EOFError):
                if self.engine.is_task_running():
                    self.engine.stop_task()
                self.engine.stop_scrcpy()
                self.console.print(f"\n[bold yellow]{t('cli.exit_message')}[/]")
                break
            except Exception as e:
                self.console.print(f"[bold red]{t('cli.unexpected_error', error=str(e))}[/]")

    def _dispatch_lang(self, args: list[str]) -> None:
        if not args:
            avail = ", ".join(get_available_languages())
            self.console.print(
                f"[cyan]{t('cli.current_language', lang=get_language())}[/] ({t('cli.available_prefix', available=avail)})"
            )
            return
        target = args[0].lower()
        if target in get_available_languages():
            set_language(target)
            self.engine.config["language"] = target
            self.engine.save_config()
            self.console.print(f"[bold green]{t('cli.language_changed', lang=target)}[/]")
        else:
            self.console.print(
                f"[bold red]{t('cli.invalid_language', lang=target, available=', '.join(get_available_languages()))}[/]"
            )

    def _dispatch_discord(self, args: list[str]) -> None:
        from dokkan_eza_link_farmer.integrations.discord_bot import (
            run_discord_bot,
            setup_discord_interactive,
        )

        sub = args[0].lower() if args else "setup"
        if sub in ("setup", "config", "init"):
            setup_discord_interactive(self.engine)
        elif sub in ("start", "run"):
            self.console.print(f"[cyan]{t('cli.discord.starting')}[/cyan]")
            with contextlib.suppress(KeyboardInterrupt):
                run_discord_bot(self.engine)
        else:
            self.console.print(f"[yellow]{t('cli.discord.usage')}[/yellow]")

    def _dispatch_inspect(self) -> None:
        try:
            st = self.engine.inspect_current_state()
            self.console.print(
                f"[bold green]{t('cli.inspect.state_format', state=f'[bold yellow]{st.value}[/bold yellow]')}[/]"
            )
        except Exception as e:
            self.console.print(f"[red]{t('cli.inspect.error', error=str(e))}[/]")

    def _dispatch_shot(self, args: list[str]) -> None:
        fn = args[0] if args else f"screenshot_{int(time.time())}.png"
        try:
            self.console.print(
                f"[green]{t('cli.shot.saved', path=self.engine.save_screenshot_to_file(fn))}[/]"
            )
        except Exception as e:
            self.console.print(f"[red]{t('cli.shot.error', error=str(e))}[/]")

    def _dispatch_interactive_task(self, cmd: str, cmd_args: list[str]) -> bool:
        if cmd == "devices":
            panels.render_devices_table(self.engine.list_devices(), self.console)
        elif cmd in ("doctor", "check"):
            self.print_doctor()
        elif cmd == "status":
            self.print_status()
        elif cmd == "eza":
            self.handle_eza_interactive(cmd_args)
        elif cmd == "link":
            self.handle_link_interactive(cmd_args)
        elif cmd in ("enrich-box", "enrich_box", "enrich"):
            self.handle_enrich_box(cmd_args)
        elif cmd in ("ai", "team"):
            self.handle_ai_interactive(cmd_args)
        elif cmd in ("stage", "farm", "repeat", "clear", "farm-stage"):
            self.handle_stage_farm_interactive(cmd_args)
        elif cmd in ("challenge", "redzone", "smb"):
            self.handle_challenge_interactive(cmd_args)
        elif cmd in ("scan-box", "box-scan", "scan"):
            self.handle_box_scan_interactive(cmd_args)
        elif cmd in ("ai-run", "ai_run", "endgame", "ai-endgame"):
            st = None
            skip_s = False
            for idx, a in enumerate(cmd_args):
                if skip_s:
                    skip_s = False
                    continue
                if a.lower() in ("--stage", "-s") and idx + 1 < len(cmd_args):
                    st = cmd_args[idx + 1]
                    skip_s = True
                elif a.lower().startswith(("--stage=", "-s=")):
                    st = a.split("=", 1)[1]
                elif not a.startswith("-"):
                    st = a
                    break
            self.handle_ai_endgame_run(
                st,
                dry_run="--dry-run" in cmd_args or "-d" in cmd_args,
                force_solve=any(a in cmd_args for a in ("--force-solve", "--force", "-f")),
            )
        else:
            return False
        return True
