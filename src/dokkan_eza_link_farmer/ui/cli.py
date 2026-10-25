from __future__ import annotations

import contextlib
import io
import logging
import sys
import time
from typing import TYPE_CHECKING, Any

from rich.console import Console
from rich.prompt import Prompt

try:
    import questionary
except ImportError:
    questionary = None  # type: ignore

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


class TerminalCLI:
    """Rich interactive Terminal Command Interface for Dokkan-EZALink-Farmer."""

    def __init__(self, engine: BotEngine):
        self.engine = engine
        self.console = Console()

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

    def handle_eza_interactive(self, args: list | None = None) -> None:
        """Handles EZA command: interactive DokkanDB selection or direct execution."""
        wizards.handle_eza_interactive(self.engine, self.console, args or [])

    def handle_link_interactive(self, args: list | None = None) -> None:
        """Handles Link Leveling command with interactive stage dropdown and rarity flags."""
        wizards.handle_link_interactive(self.engine, self.console, args or [])

    def handle_stage_farm_interactive(self, args: list | None = None) -> None:
        """Handles stage auto-clearing command: repeats stage until stamina runs out."""
        wizards.handle_stage_farm_interactive(self.engine, self.console, args or [])

    def handle_challenge_interactive(self, args: list | None = None) -> None:
        """Interactive Challenge Event selector, Stage selector & Multi-mission Solver."""
        wizards.handle_challenge_interactive(self.engine, self.console, args)

    def handle_box_scan_interactive(
        self,
        args: list | None = None,
        log_file: str | None = None,
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
        from dokkan_eza_link_farmer.ai.boss_catalog import get_boss_stage, list_boss_stages
        from dokkan_eza_link_farmer.ai.models import BossStage

        stage: BossStage | None = None

        if isinstance(target_stage, BossStage):
            stage = target_stage
        elif target_stage is not None:
            try:
                stage = get_boss_stage(target_stage, dokkandb=self.engine.dokkandb)
            except Exception:
                # Query DokkanDB Challenge events by name or ID
                query = str(target_stage).strip().lower()
                try:
                    events = self.engine.dokkandb.get_challenge_events(active_only=False)
                    for ev in events:
                        ev_name = (ev.get("name") or "").lower()
                        ev_id = ev.get("id")
                        if ev_id is not None and (query in ev_name or query == str(ev_id)):
                            ev_id_int = int(ev_id)
                            det = self.engine.dokkandb.get_event_details(ev_id_int)
                            if det and det.get("quests"):
                                stages_arr = det["quests"][0].get("stages", [])
                                if stages_arr:
                                    st_id = stages_arr[0].get("stage_id")
                                    if st_id:
                                        b_info = self.engine.dokkandb.get_stage_boss_info(
                                            ev_id_int, int(st_id)
                                        )
                                        if b_info and b_info.get("phases"):
                                            stage = BossStage.from_dokkandb(b_info)
                                            break
                except Exception:
                    pass

                if not stage:
                    self.console.print(
                        f"[bold red]Stage '{target_stage}' not found in catalog or DokkanDB.[/bold red]"
                    )
                    self.console.print("[yellow]Available catalog presets:[/yellow]")
                    for s in list_boss_stages():
                        self.console.print(
                            f"  • [cyan]{s.stage_id}[/cyan]: {s.event_name} - {s.stage_name}"
                        )
                    return
        else:
            # Interactive selection from DokkanDB Challenge category
            stage = self._select_challenge_boss_stage()
            if not stage:
                return

        # Interactive stage mission selection
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
        target_file = None
        for a in args:
            if not a.startswith("-"):
                target_file = a
                break

        self.console.print(
            "[cyan]Enriching character box with deep card details (leader skills, categories, passives)...[/cyan]"
        )
        syncer = DokkanSyncer()
        try:
            enriched = syncer.sync_box_details(
                box_file=target_file,
                force=force,
                save_to_file=True,
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
        self,
        rec: Any,
        title: str = "",
        shortlist: list[Any] | None = None,
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

    def run(self) -> None:
        """Runs the interactive CLI command loop."""
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
                args = parts[1:]

                if cmd in ("exit", "quit", "q"):
                    if self.engine.is_task_running():
                        self.engine.stop_task()
                    self.engine.stop_scrcpy()
                    self.console.print(f"[bold yellow]{t('cli.exit_message')}[/]")
                    break

                elif cmd in ("help", "?"):
                    self.print_help()

                elif cmd == "lang":
                    if not args:
                        current = get_language()
                        avail = ", ".join(get_available_languages())
                        self.console.print(
                            f"[cyan]{t('cli.current_language', lang=current)}[/] ({t('cli.available_prefix', available=avail)})"
                        )
                    else:
                        target_lang = args[0].lower()
                        if target_lang in get_available_languages():
                            set_language(target_lang)
                            self.engine.config["language"] = target_lang
                            self.engine.save_config()
                            self.console.print(
                                f"[bold green]{t('cli.language_changed', lang=target_lang)}[/]"
                            )
                        else:
                            avail_str = ", ".join(get_available_languages())
                            self.console.print(
                                f"[bold red]{t('cli.invalid_language', lang=target_lang, available=avail_str)}[/]"
                            )

                elif cmd == "devices":
                    devices = self.engine.list_devices()
                    panels.render_devices_table(devices, self.console)

                elif cmd == "connect":
                    serial = args[0] if args else None
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

                elif cmd in ("doctor", "check"):
                    self.print_doctor()

                elif cmd == "status":
                    self.print_status()

                elif cmd in ("inspect", "state"):
                    try:
                        state = self.engine.inspect_current_state()
                        self.console.print(
                            f"[bold green]{t('cli.inspect.state_format', state=f'[bold yellow]{state.value}[/bold yellow]')}[/]"
                        )
                    except Exception as e:
                        self.console.print(f"[red]{t('cli.inspect.error', error=str(e))}[/]")

                elif cmd in ("shot", "screenshot"):
                    filename = args[0] if args else f"screenshot_{int(time.time())}.png"
                    try:
                        path = self.engine.save_screenshot_to_file(filename)
                        self.console.print(f"[green]{t('cli.shot.saved', path=path)}[/]")
                    except Exception as e:
                        self.console.print(f"[red]{t('cli.shot.error', error=str(e))}[/]")

                elif cmd == "eza":
                    self.handle_eza_interactive(args)

                elif cmd == "link":
                    self.handle_link_interactive(args)

                elif cmd in ("stage", "farm", "repeat", "clear", "farm-stage"):
                    self.handle_stage_farm_interactive(args)

                elif cmd == "discord":
                    from dokkan_eza_link_farmer.integrations.discord_bot import (
                        run_discord_bot,
                        setup_discord_interactive,
                    )

                    sub = args[0].lower() if args else "setup"
                    if sub in ("setup", "config", "init"):
                        setup_discord_interactive(self.engine)
                    elif sub in ("start", "run"):
                        self.console.print(f"[cyan]{t('cli.discord.starting')}[/cyan]")
                        try:
                            run_discord_bot(self.engine)
                        except KeyboardInterrupt:
                            self.console.print(f"[yellow]{t('cli.discord.stopped')}[/yellow]")
                    else:
                        self.console.print(f"[yellow]{t('cli.discord.usage')}[/yellow]")

                elif cmd in ("challenge", "redzone", "smb"):
                    self.handle_challenge_interactive(args)

                elif cmd in ("scan-box", "box-scan", "scan"):
                    self.handle_box_scan_interactive(args)

                elif cmd in ("enrich-box", "enrich_box", "enrich"):
                    self.handle_enrich_box(args)

                elif cmd in ("ai-run", "ai_run", "endgame", "ai-endgame"):
                    stage_target = None
                    for a in args:
                        if not a.startswith("-"):
                            stage_target = a
                            break
                    is_dry = "--dry-run" in args
                    is_force = "--force-solve" in args or "--force" in args
                    self.handle_ai_endgame_run(stage_target, dry_run=is_dry, force_solve=is_force)

                elif cmd in ("ai", "team"):
                    self.handle_ai_interactive(args)

                elif cmd == "stop":
                    self.engine.stop_task()

                elif cmd == "pause":
                    self.engine.pause_task()

                elif cmd == "resume":
                    self.engine.resume_task()

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
