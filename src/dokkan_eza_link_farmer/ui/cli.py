from __future__ import annotations

import contextlib
import io
import logging
import os
import sys
import time
from typing import TYPE_CHECKING, Any

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

try:
    import questionary
except ImportError:
    questionary = None  # type: ignore

if TYPE_CHECKING:
    from dokkan_eza_link_farmer.core.bot_engine import BotEngine

from dokkan_eza_link_farmer.core.i18n import get_available_languages, get_language, set_language, t

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

    def _on_log(self, msg: str):
        """Displays formatted log message in terminal."""
        self.console.print(f"[dim]{time.strftime('%H:%M:%S')}[/dim] [cyan][BOT][/cyan] {msg}")

    def _on_run_update(self, curr: int, tot: Any):
        """Displays run completion counter."""
        tot_str = str(tot) if tot and tot > 0 else "∞"
        self.console.print(f"[bold green]{t('cli.progress_format', curr=curr, tot=tot_str)}[/]")

    def print_banner(self):
        """Renders stylized welcome banner."""
        banner = Text()
        banner.append(f"{t('cli.banner_title')}\n", style="bold red")
        banner.append(f"{t('cli.banner_subtitle')}\n", style="yellow")
        banner.append(t("cli.banner_help_hint"), style="dim")
        self.console.print(Panel(banner, border_style="red", expand=False))

    def print_help(self):
        """Renders interactive command table."""
        table = Table(title=t("cli.help.title"), border_style="cyan")
        table.add_column(t("cli.help.col_command"), style="bold green")
        table.add_column(t("cli.help.col_params"), style="italic")
        table.add_column(t("cli.help.col_description"), style="white")

        table.add_row("devices", "", t("cli.help.desc_devices"))
        table.add_row("connect", "[serial]", t("cli.help.desc_connect"))
        table.add_row("scrcpy", "", t("cli.help.desc_scrcpy"))
        table.add_row("scrcpy-stop", "", t("cli.help.desc_scrcpy_stop"))
        table.add_row("inspect", "", t("cli.help.desc_inspect"))
        table.add_row("shot", "[file.png]", t("cli.help.desc_shot"))
        table.add_row("eza", "[level=999]", t("cli.help.desc_eza"))
        table.add_row("link", "[runs] [--ur] [--lr] [--boost]", t("cli.help.desc_link"))
        table.add_row("stage / farm", "[runs] [--boost]", t("cli.help.desc_stage"))
        table.add_row("challenge", "", t("cli.help.desc_challenge"))
        table.add_row("scan-box", "[max_cards]", t("cli.help.desc_scan_box"))
        table.add_row("enrich-box", "[box_path] [--force]", t("cli.help.desc_enrich_box"))
        table.add_row("ai-run / endgame", "[stage_id]", t("cli.help.desc_ai_run"))
        table.add_row("ai / team", "[build|partner|status]", t("cli.help.desc_ai"))
        table.add_row("discord", "[setup|run]", t("cli.help.desc_discord"))
        table.add_row("doctor / check", "", t("cli.help.desc_doctor"))
        table.add_row("status", "", t("cli.help.desc_status"))
        table.add_row("lang", "[en|it]", t("cli.help.desc_lang"))
        table.add_row("stop", "", t("cli.help.desc_stop"))
        table.add_row("pause", "", t("cli.help.desc_pause"))
        table.add_row("resume", "", t("cli.help.desc_resume"))
        table.add_row("exit / quit", "", t("cli.help.desc_exit"))

        self.console.print(table)

    def print_doctor(self):
        """Renders comprehensive environment diagnostics."""
        report = self.engine.diagnose_environment()
        table = Table(title=t("cli.doctor.title", os=report["os"]), border_style="green")
        table.add_column(t("cli.doctor.col_component"), style="bold")
        table.add_column(t("cli.doctor.col_status"), style="white")
        table.add_column(t("cli.doctor.col_details"), style="dim")

        # Python
        python_mode = (
            t("cli.doctor.standalone_mode") if report["is_frozen"] else t("cli.doctor.dev_mode")
        )
        table.add_row(
            t("cli.doctor.prop_python"),
            f"[green]{t('cli.doctor.status_ok')}[/]",
            f"v{report['python_version']} ({python_mode})",
        )

        # ADB
        if report["adb"]["found"]:
            adb_str = f"[green]{t('cli.doctor.status_found')}[/] ({report['adb']['version']})"
            table.add_row(t("cli.doctor.prop_adb"), adb_str, report["adb"]["path"])
        else:
            table.add_row(
                t("cli.doctor.prop_adb"),
                f"[red]{t('cli.doctor.status_missing')}[/]",
                t("cli.doctor.adb_missing_desc"),
            )

        # scrcpy
        if report["scrcpy"]["found"]:
            scrcpy_str = f"[green]{t('cli.doctor.status_found')}[/] ({report['scrcpy']['version']})"
            table.add_row(t("cli.doctor.prop_scrcpy"), scrcpy_str, report["scrcpy"]["path"])
        else:
            table.add_row(
                t("cli.doctor.prop_scrcpy"),
                f"[yellow]{t('cli.doctor.status_not_found')}[/]",
                t("cli.doctor.scrcpy_missing_desc"),
            )

        # Devices
        devs = report.get("devices", [])
        if devs:
            dev_str = ", ".join(f"{d['serial']} ({d['model']})" for d in devs)
            table.add_row(
                t("cli.doctor.prop_devices"),
                f"[green]{t('cli.doctor.devices_connected', count=len(devs))}[/]",
                dev_str,
            )
        else:
            table.add_row(
                t("cli.doctor.prop_devices"),
                f"[yellow]{t('cli.doctor.devices_none')}[/]",
                t("cli.doctor.devices_none_desc"),
            )

        self.console.print(table)

        # Installation hints if tools are missing
        if not report["scrcpy"]["found"] or not report["adb"]["found"]:
            h = report.get("install_help", {})
            help_panel = Text()
            help_panel.append(
                f"\n{t('cli.doctor.install_help_title', os=report['os'])}\n", style="bold yellow"
            )
            if not report["scrcpy"]["found"] and not report["adb"]["found"]:
                help_panel.append(t("cli.doctor.install_run_hint"), style="dim")
                help_panel.append(f"{h.get('all', '')}\n", style="bold green")
            elif not report["scrcpy"]["found"]:
                help_panel.append(t("cli.doctor.install_run_hint"), style="dim")
                help_panel.append(f"{h.get('scrcpy', '')}\n", style="bold green")
            elif not report["adb"]["found"]:
                help_panel.append(t("cli.doctor.install_run_hint"), style="dim")
                help_panel.append(f"{h.get('adb', '')}\n", style="bold green")
            if h.get("note"):
                help_panel.append(
                    f"{t('cli.doctor.install_note_label', note=h.get('note'))}\n", style="italic"
                )
            self.console.print(Panel(help_panel, border_style="yellow", expand=False))

    def print_status(self):
        """Renders status summary card."""
        info = self.engine.get_status_summary()
        table = Table(title=t("cli.status.title"), border_style="blue")
        table.add_column(t("cli.status.prop_device"), style="bold")
        table.add_column(t("cli.status.prop_value"), style="yellow")

        device_val = info["device_serial"] or t("cli.status.not_connected")
        running_val = t("cli.status.yes") if info["task_running"] else t("cli.status.no")

        table.add_row(t("cli.status.prop_device"), str(device_val))
        table.add_row(t("cli.status.prop_task_running"), running_val)
        table.add_row(t("cli.status.prop_task_type"), str(info["task_type"]))
        runs_target_val = info.get("runs_target")
        target_display = (
            str(runs_target_val) if runs_target_val is not None and runs_target_val > 0 else "∞"
        )
        table.add_row(
            t("cli.status.prop_runs_completed"), f"{info['runs_completed']} / {target_display}"
        )
        table.add_row(t("cli.status.prop_screen_state"), str(info["current_state"]))

        self.console.print(table)

    def handle_eza_interactive(self, args: list):
        """Handles EZA command: interactive DokkanDB selection or direct execution."""
        default_lvl = self.engine.config.get("farming", {}).get("eza_target_level", 999)

        # 1. Direct command if level is given as integer (e.g. 'eza 30')
        if args and args[0].isdigit():
            target_lvl = int(args[0])
            self.engine.start_eza_farm(target_level=target_lvl)
            return

        # 2. Direct command if 'auto' is specified (e.g. 'eza auto 30')
        if args and args[0].lower() in ("auto", "classic"):
            target_lvl = int(args[1]) if len(args) > 1 and args[1].isdigit() else default_lvl
            self.engine.start_eza_farm(target_level=target_lvl)
            return

        # 3. Interactive prompt via questionary
        try:
            import questionary

            choices = [
                questionary.Choice(title=t("cli.dokkandb.opt_select"), value="select"),
                questionary.Choice(title=t("cli.dokkandb.opt_auto"), value="auto"),
                questionary.Choice(title=t("cli.dokkandb.opt_cancel"), value="cancel"),
            ]
            action = questionary.select(t("cli.dokkandb.menu_title"), choices=choices).ask()

            if not action or action == "cancel":
                self.console.print(f"[yellow]{t('cli.dokkandb.canceled')}[/]")
                return

            if action == "auto":
                lvl_str = questionary.text(
                    t("cli.dokkandb.target_level_prompt", default=default_lvl),
                    default=str(default_lvl),
                ).ask()
                target_lvl = int(lvl_str) if lvl_str and lvl_str.isdigit() else default_lvl
                self.engine.start_eza_farm(target_level=target_lvl)
                return

            if action == "select":
                self.console.print(f"[cyan]{t('cli.dokkandb.fetching')}[/]")
                events = self.engine.dokkandb.get_zbattles()
                if not events:
                    self.console.print(
                        f"[red]{t('cli.dokkandb.fetch_error', error='No events returned')}[/]"
                    )
                    return

                # Sort: open events first, then by ID descending
                events.sort(
                    key=lambda x: (not x.get("is_currently_open", False), -int(x.get("id", 0)))
                )

                choices_eza = []
                for e in events:
                    status_tag = "🟢 [OPEN]" if e.get("is_currently_open") else "🔑 [PORTAL]"
                    name = e.get("name", "Unknown EZA")
                    eid = e.get("id", "?")
                    choices_eza.append(
                        questionary.Choice(title=f"{status_tag} {name} (ID: {eid})", value=e)
                    )
                choices_eza.append(
                    questionary.Choice(title=t("cli.dokkandb.opt_cancel"), value=None)
                )

                chosen = questionary.select(
                    t("cli.dokkandb.select_prompt"),
                    choices=choices_eza,
                    use_search_filter=True,
                    use_arrow_keys=True,
                    use_jk_keys=False,
                ).ask()

                if not chosen:
                    self.console.print(f"[yellow]{t('cli.dokkandb.canceled')}[/]")
                    return

                lvl_str = questionary.text(
                    t("cli.dokkandb.target_level_prompt", default=default_lvl),
                    default=str(default_lvl),
                ).ask()
                target_lvl = int(lvl_str) if lvl_str and lvl_str.isdigit() else default_lvl

                chosen_name = chosen.get("name", "Selected EZA")
                self.console.print(
                    f"[dim]{t('cli.dokkandb.downloading_banner', name=chosen_name)}[/dim]"
                )
                banner_path = self.engine.dokkandb.download_banner(chosen)
                if banner_path:
                    chosen["banner_local_path"] = banner_path
                    self.console.print(
                        f"[green]{t('cli.dokkandb.banner_downloaded', path=os.path.basename(banner_path))}[/green]"
                    )
                else:
                    self.console.print(f"[yellow]{t('cli.dokkandb.banner_unavailable')}[/yellow]")

                self.console.print(
                    f"[bold green]{t('cli.dokkandb.selected_summary', name=chosen_name, level=target_lvl)}[/bold green]"
                )
                self.engine.start_eza_farm(target_level=target_lvl, target_eza=chosen)

        except (KeyboardInterrupt, EOFError):
            self.console.print(f"\n[yellow]{t('cli.dokkandb.canceled')}[/]")
        except Exception as e:
            self.console.print(f"[bold red]{t('cli.unexpected_error', error=str(e))}[/]")

    def handle_link_interactive(self, args: list):
        """Handles Link Leveling command with interactive stage dropdown and rarity flags."""
        runs: int | None = None
        use_boost: bool | None = None
        filter_ur: bool = False
        filter_lr: bool = False
        target_stage: str | None = None
        stage_name: str | None = None
        rarity_specified_in_cli: bool = False

        for arg in args:
            low = arg.lower()
            if low in ("--ur", "-ur", "ur"):
                filter_ur = True
                rarity_specified_in_cli = True
            elif low in ("--lr", "-lr", "lr"):
                filter_lr = True
                rarity_specified_in_cli = True
            elif low in ("boost", "--boost", "-b"):
                use_boost = True
            elif low in ("noboost", "no-boost", "--no-boost", "-nb"):
                use_boost = False
            elif low in ("39-3", "39_3", "393", "area_39_3"):
                target_stage = "area_39_3"
                stage_name = "Area 39 Stage 3: Great stamina-friendly option (also drops green gems) | 5 fights"
            elif low in ("35-1", "35_1", "351", "area_35_1"):
                target_stage = "area_35_1"
                stage_name = "Area 35 Stage 1: Good stamina-friendly option (also drops blue gems) | 4 fights"
            elif low in ("spirit", "spirit_and_time", "event"):
                target_stage = "spirit_and_time"
                stage_name = t("cli.link.stage_spirit")
            elif arg.isdigit():
                val = int(arg)
                if val > 0:
                    runs = val

        try:
            import questionary

            # 1. Interactive stage selection dropdown if not provided in CLI args
            if not target_stage:
                stage_choices = [
                    questionary.Choice(
                        title="Area 39 Stage 3: Great stamina-friendly option (also drops green gems) | 5 fights",
                        value="area_39_3",
                    ),
                    questionary.Choice(
                        title="Area 35 Stage 1: Good stamina-friendly option (also drops blue gems) | 4 fights",
                        value="area_35_1",
                    ),
                    questionary.Choice(
                        title=t("cli.link.stage_spirit"),
                        value="spirit_and_time",
                    ),
                    questionary.Choice(
                        title=t("cli.dokkandb.opt_cancel"),
                        value="cancel",
                    ),
                ]
                selected_stage = questionary.select(
                    t("cli.link.menu_title"),
                    choices=stage_choices,
                ).ask()

                if not selected_stage or selected_stage == "cancel":
                    self.console.print(f"[yellow]{t('cli.dokkandb.canceled')}[/yellow]")
                    return

                target_stage = selected_stage
                if target_stage == "area_39_3":
                    stage_name = "Area 39 Stage 3: Great stamina-friendly option (also drops green gems) | 5 fights"
                elif target_stage == "area_35_1":
                    stage_name = "Area 35 Stage 1: Good stamina-friendly option (also drops blue gems) | 4 fights"
                elif target_stage == "spirit_and_time":
                    stage_name = t("cli.link.stage_spirit")

            # 2. Interactive runs prompt if not provided in CLI
            if runs is None:
                runs_str = questionary.text(
                    t("cli.link.runs_prompt"),
                    default="",
                ).ask()
                if runs_str and runs_str.isdigit():
                    runs = int(runs_str)
                elif runs_str is None:  # Cancelled
                    self.console.print(f"[yellow]{t('cli.dokkandb.canceled')}[/yellow]")
                    return

            # 3. Interactive rarity prompt if not provided in CLI args
            if not rarity_specified_in_cli:
                rarity_choices = [
                    questionary.Choice(title="UR (Ultra Rare)", value="ur"),
                    questionary.Choice(title="LR (Legendary Rare)", value="lr"),
                ]
                selected_rarities = questionary.checkbox(
                    t("cli.link.rarity_prompt"),
                    choices=rarity_choices,
                ).ask()

                if selected_rarities is None:  # Cancelled
                    self.console.print(f"[yellow]{t('cli.dokkandb.canceled')}[/yellow]")
                    return

                if "ur" in selected_rarities:
                    filter_ur = True
                if "lr" in selected_rarities:
                    filter_lr = True

        except (KeyboardInterrupt, EOFError):
            self.console.print(f"\n[yellow]{t('cli.dokkandb.canceled')}[/yellow]")
            return
        except Exception as e:
            self.console.print(f"[bold red]{t('cli.unexpected_error', error=str(e))}[/bold red]")
            return

        # Boost label display
        if use_boost is True:
            boost_label = t("cli.link.boost_on")
        elif use_boost is False:
            boost_label = t("cli.link.boost_off")
        else:
            boost_label = t("cli.link.boost_config")

        runs_display = f"{runs} runs" if runs is not None else t("cli.link.runs_unlimited")

        # Rarity label display
        rarity_tags = []
        if filter_ur:
            rarity_tags.append("UR")
        if filter_lr:
            rarity_tags.append("LR")
        rarity_label = " + ".join(rarity_tags) if rarity_tags else t("cli.link.rarity_all")

        self.console.print(
            f"[bold green]{t('cli.link.selected_stage', name=stage_name)}[/bold green]"
        )
        self.console.print(
            f"[dim]Runs: {runs_display} | {boost_label} | Rarity: {rarity_label}[/dim]"
        )

        spirit_event = None
        if target_stage == "spirit_and_time":
            self.console.print(f"[cyan]{t('cli.dokkandb.fetching')}[/cyan]")
            spirit_event = self.engine.dokkandb.get_chamber_of_spirit_and_time()
            if spirit_event:
                status_text = (
                    t("cli.link.status_open")
                    if spirit_event.get("is_currently_open")
                    else t("cli.link.status_rotating")
                )
                name = spirit_event.get("name", stage_name)
                self.console.print(
                    f"[bold green]{t('cli.link.event_info', name=name, status=status_text)}[/bold green]"
                )

        self.engine.start_link_level_farm(
            runs=runs,
            target_event=spirit_event,
            use_boost=use_boost,
            filter_ur=filter_ur,
            filter_lr=filter_lr,
            target_stage=target_stage,
            stage_name=stage_name,
        )

    def handle_stage_farm_interactive(self, args: list):
        """
        Handles stage auto-clearing command:
        Repeats the currently selected stage until stamina runs out (or target runs reached).
        """
        runs: int | None = None
        use_boost: bool | None = None
        preferred_diff: str | None = None

        for arg in args:
            low = arg.lower()
            if low in ("boost", "--boost", "-b"):
                use_boost = True
            elif low in ("noboost", "no-boost", "--no-boost", "-nb"):
                use_boost = False
            elif low in ("super", "--super"):
                preferred_diff = "super"
            elif low in ("super2", "--super2"):
                preferred_diff = "super2"
            elif low in ("z-hard", "zhard", "--zhard", "--z-hard"):
                preferred_diff = "z_hard"
            elif low.startswith("--diff="):
                preferred_diff = low.split("=", 1)[1].replace("-", "_")
            elif arg.isdigit() and int(arg) > 0:
                runs = int(arg)

        # Informational displays
        runs_display = f"{runs} runs" if runs is not None else t("cli.stage.runs_unlimited")
        if use_boost is True:
            boost_label = t("cli.stage.boost_on")
        elif use_boost is False:
            boost_label = t("cli.stage.boost_off")
        else:
            boost_label = t("cli.stage.boost_default")

        diff_label = preferred_diff.upper() if preferred_diff else t("cli.stage.diff_auto")

        self.console.print(
            f"[bold green]{t('cli.stage.summary', runs=runs_display, boost=boost_label, diff=diff_label)}[/bold green]"
        )
        self.console.print(f"[dim cyan]{t('cli.stage.hint_navigate')}[/dim cyan]")

        self.engine.start_stage_farm(
            runs=runs,
            use_boost=use_boost,
            preferred_difficulty=preferred_diff,
        )

    def handle_challenge_interactive(self, args: list | None = None):
        """Interactive Challenge Event selector, Stage selector & Multi-mission Solver."""
        import questionary
        from rich.prompt import Prompt
        from rich.table import Table

        from dokkan_eza_link_farmer.ai.mission_solver import MissionBundler, MissionParser

        try:
            show_all = any(a.lower() in ("--all", "--closed", "-a") for a in (args or []))
            query_args = [
                a
                for a in (args or [])
                if a.lower() not in ("-y", "--yes", "--all", "--closed", "-a")
            ]
            auto_confirm = any(a.lower() in ("-y", "--yes") for a in (args or []))

            self.console.print(f"[dim]{t('cli.challenge.loading')}[/dim]")
            events = self.engine.dokkandb.get_challenge_events(active_only=not show_all)
            if not events:
                self.console.print(f"[yellow]{t('cli.challenge.no_events')}[/yellow]")
                return

            explicit_stage: int | None = None
            if len(query_args) >= 2 and query_args[-1].isdigit():
                explicit_stage = int(query_args[-1])
                query_args = query_args[:-1]

            query = " ".join(query_args).strip().lower()

            if query:
                filtered = [
                    e
                    for e in events
                    if query in (e.get("name") or "").lower() or query == str(e.get("id"))
                ]
                if filtered:
                    events = filtered
                else:
                    self.console.print(
                        f"[yellow]No events matched query '{query}'. Showing all.[/yellow]"
                    )

            selected_event = None
            if len(events) == 1:
                selected_event = events[0]
                clean_t = (selected_event.get("name") or "Unknown").replace("\n", " ").strip()
                self.console.print(
                    f"[bold green]Selected: {clean_t} (ID: {selected_event.get('id')})[/bold green]"
                )
            else:
                choices = []
                for e in events[:100]:
                    clean_t = (e.get("name") or "Unknown").replace("\n", " ").strip()
                    if e.get("active") == "portal":
                        status_tag = "🌀 [PORTAL]"
                    elif e.get("is_currently_open"):
                        status_tag = "🟢 [OPEN]"
                    else:
                        status_tag = "🔒 [CLOSED]"
                    choices.append(
                        questionary.Choice(
                            title=f"{status_tag} {clean_t} (ID: {e.get('id')})", value=e
                        )
                    )
                choices.append(questionary.Choice(title=t("cli.ai.opt_cancel"), value=None))

                try:
                    selected_event = questionary.select(
                        t("cli.challenge.select_event"),
                        choices=choices,
                        use_arrow_keys=True,
                        use_jk_keys=False,
                    ).ask()
                except Exception:
                    self.console.print(
                        f"\n[bold cyan]{t('cli.challenge.select_event')}[/bold cyan]"
                    )
                    display_limit = min(len(events), 50)
                    for idx, e in enumerate(events[:display_limit], 1):
                        clean_t = (e.get("name") or "").replace("\n", " ").strip()
                        if e.get("active") == "portal":
                            status_tag = "🌀"
                        elif e.get("is_currently_open"):
                            status_tag = "🟢"
                        else:
                            status_tag = "🔒"
                        self.console.print(
                            f"  [green]{idx:2d}[/green]. {status_tag} {clean_t} (ID: {e.get('id')})"
                        )
                    try:
                        num_str = Prompt.ask("Enter number (0 to cancel)", default="1").strip()
                        if num_str != "0" and num_str.isdigit():
                            idx = int(num_str) - 1
                            if 0 <= idx < len(events[:display_limit]):
                                selected_event = events[idx]
                    except (EOFError, KeyboardInterrupt):
                        selected_event = None

            if not selected_event:
                self.console.print(f"[yellow]{t('cli.dokkandb.canceled')}[/yellow]")
                return

            ev_id = int(selected_event.get("id") or 0)
            ev_name = (selected_event.get("name") or "Challenge").replace("\n", " ").strip()

            # 2. Query event details for available stages
            details = self.engine.dokkandb.get_event_details(ev_id)
            quests = details.get("quests", []) if details else []
            quests.sort(key=lambda q: int(q.get("quest_id", 0)))

            target_stage_num: int = 1
            target_stage_id: int | None = None
            target_stage_name: str | None = None

            if explicit_stage is not None:
                target_stage_num = explicit_stage
                matched_quest = next(
                    (
                        q
                        for idx, q in enumerate(quests, 1)
                        if idx == explicit_stage
                        or int(str(q.get("quest_id", 0))[-3:]) == explicit_stage
                    ),
                    None,
                )
                if matched_quest:
                    stages_arr = matched_quest.get("stages", [])
                    target_stage_id = stages_arr[0].get("stage_id") if stages_arr else None
                    target_stage_name = matched_quest.get("quest_name")
                else:
                    target_stage_name = f"Stage {explicit_stage}"
            elif quests and len(quests) > 0:
                stage_choices = []
                for idx, q in enumerate(quests, 1):
                    q_name = q.get("quest_name") or f"Stage {idx}"
                    stages_arr = q.get("stages", [])
                    st_id = stages_arr[0].get("stage_id") if stages_arr else None
                    title = f"Stage {idx}: {q_name}"
                    if st_id:
                        title += f" (ID: {st_id})"
                    stage_choices.append(
                        questionary.Choice(
                            title=title,
                            value={"stage_num": idx, "stage_id": st_id, "stage_name": q_name},
                        )
                    )
                stage_choices.append(
                    questionary.Choice(
                        title=t("cli.challenge.all_stages"),
                        value={"stage_num": 0, "stage_id": None, "stage_name": "All Stages"},
                    )
                )
                stage_choices.append(
                    questionary.Choice(
                        title=t("cli.ai.opt_cancel"),
                        value=None,
                    )
                )

                try:
                    chosen_stage_dict = questionary.select(
                        t("cli.challenge.select_stage"),
                        choices=stage_choices,
                        use_arrow_keys=True,
                        use_jk_keys=False,
                    ).ask()
                except Exception:
                    chosen_stage_dict = stage_choices[0].value if stage_choices else None

                if chosen_stage_dict is None:
                    self.console.print(f"[yellow]{t('cli.dokkandb.canceled')}[/yellow]")
                    return

                target_stage_num = chosen_stage_dict.get("stage_num", 1)
                target_stage_id = chosen_stage_dict.get("stage_id")
                target_stage_name = chosen_stage_dict.get("stage_name")

            # 3. Stage Boss Telemetry
            if target_stage_id and ev_id:
                boss_info = self.engine.dokkandb.get_stage_boss_info(ev_id, target_stage_id)
                if boss_info and boss_info.get("phases"):
                    t_boss = Table(
                        title=f"{t('cli.challenge.stage_boss_info_title')} - {target_stage_name} (Stage {target_stage_num})",
                        border_style="magenta",
                    )
                    t_boss.add_column("Phase", style="bold cyan", justify="center")
                    t_boss.add_column("Boss Enemy", style="bold")
                    t_boss.add_column("Typing", style="bold yellow")
                    t_boss.add_column("Key Mechanics & Immunities", style="dim")

                    for ph in boss_info["phases"]:
                        ph_num = ph.get("phase", 1)
                        for b in ph.get("bosses", []):
                            b_name = b.get("name", "Unknown Boss")
                            b_type = b.get("type_name", "Unknown")
                            mechs = (
                                ", ".join(
                                    m.get("name") for m in b.get("mechanics", []) if m.get("name")
                                )
                                or "None"
                            )
                            t_boss.add_row(f"Phase {ph_num}", b_name, b_type, mechs)
                    self.console.print(t_boss)

            # 4. Missions Filtering & Optimization
            raw_missions = self.engine.dokkandb.get_challenge_missions(
                ev_name,
                stage_num=target_stage_num if target_stage_num > 0 else None,
                event_id=ev_id,
            )
            missions = [MissionParser.parse(m) for m in raw_missions]
            batches = MissionBundler.bundle_missions(
                missions, target_stage=target_stage_num if target_stage_num > 0 else None
            )

            saved = max(0, len(missions) - len(batches))
            if target_stage_num > 0:
                self.console.print(
                    f"[bold cyan]{t('cli.challenge.stage_missions_found', stage=target_stage_num, total=len(missions), batches=len(batches))}[/bold cyan]"
                )
            else:
                self.console.print(
                    f"[bold cyan]{t('cli.challenge.missions_found', total=len(missions), batches=len(batches))}[/bold cyan]"
                )

            if saved > 0:
                self.console.print(
                    f"[bold green]{t('cli.challenge.savings_badge', saved=saved)}[/bold green]"
                )

            t_batches = Table(
                title=f"🎯 Mission Batches for {ev_name} (Stage {target_stage_num})",
                border_style="green",
            )
            t_batches.add_column("Batch #", style="bold cyan")
            t_batches.add_column("Combined Requirements", style="bold")
            t_batches.add_column("Missions Cleared in Batch", style="dim")

            for idx, b in enumerate(batches, 1):
                m_names = ", ".join(f"#{m.id}" for m in b.missions) or "Standard Clear"
                t_batches.add_row(f"Run Batch #{idx}", b.summary, m_names)

            self.console.print(t_batches)

            start = auto_confirm
            if not start:
                try:
                    start = questionary.confirm(
                        t("cli.challenge.start_confirm"),
                        default=True,
                    ).ask()
                except Exception:
                    try:
                        ans = (
                            Prompt.ask(t("cli.challenge.start_confirm") + " (y/n)", default="y")
                            .strip()
                            .lower()
                        )
                        start = ans in ("y", "yes", "s", "si")
                    except (EOFError, KeyboardInterrupt):
                        start = False

            if start:
                stage_str = f"Stage {target_stage_num}" + (
                    f": {target_stage_name}" if target_stage_name else ""
                )
                self.console.print(
                    f"[bold green]{t('cli.challenge.starting', name=ev_name, stage=stage_str)}[/bold green]"
                )
                if not self.engine.adb.is_connected():
                    try:
                        self.engine.connect()
                    except Exception as e:
                        self.console.print(f"[yellow]Device connection: {e}[/yellow]")
                self.engine.start_challenge_farm(
                    target_event=selected_event,
                    stage_num=target_stage_num or 1,
                    stage_id=target_stage_id,
                    stage_name=target_stage_name,
                )
        except (KeyboardInterrupt, EOFError):
            self.console.print(f"\n[yellow]{t('cli.dokkandb.canceled')}[/yellow]")
        except Exception as e:
            self.console.print(f"[bold red]{t('cli.unexpected_error', error=str(e))}[/bold red]")

    def handle_box_scan_interactive(self, args: list | None = None, log_file: str | None = None):
        """Interactive OCR Character Box Scanner to autonomously build config/box.json."""
        import questionary

        from dokkan_eza_link_farmer.automation.tasks.box_scanner import (
            DEFAULT_BOX_SCAN_LOG_PATH,
            DEFAULT_USER_BOX_PATH,
        )

        try:
            self.console.print("\n[bold cyan]📦 Autonomous Character Box Scanner (OCR)[/bold cyan]")
            self.console.print(
                "[dim]Scans your owned in-game cards, recognizes names & titles, and creates config/box.json.[/dim]\n"
            )

            # Check device connection
            if not self.engine.adb.is_connected():
                self.console.print(
                    "[yellow]Device not connected. Attempting auto-connection...[/yellow]"
                )
                try:
                    serial = self.engine.connect()
                    self.console.print(f"[green]✓ Connected to {serial}![/green]")
                except Exception as e:
                    self.console.print(f"[bold red]Cannot connect to device: {e}[/bold red]")
                    return

            # Check existing box
            existing_ids = self.engine.dokkandb.get_user_box_card_ids()
            if existing_ids:
                self.console.print(
                    f"[green]Found existing box database with {len(existing_ids)} cards indexed.[/green]"
                )
                self.console.print(
                    "[dim]New scans are incremental: existing cards will be preserved and updated.[/dim]\n"
                )

            # Parse optional max limit and log file from args (e.g. scan-box 50, scan-box --log-file custom.log)
            max_cards: int | None = None
            custom_log: str | None = log_file
            if args:
                skip_next = False
                for idx, a in enumerate(args):
                    if skip_next:
                        skip_next = False
                        continue
                    if a in ("--log-file", "--log", "-lf") and idx + 1 < len(args):
                        custom_log = args[idx + 1]
                        skip_next = True
                    elif a.startswith("--log-file="):
                        custom_log = a.split("=", 1)[1]
                    elif str(a).isdigit():
                        max_cards = int(a)

            if max_cards is None:
                choices = [
                    questionary.Choice("🚀 Full Box Scan (All owned UR/LR characters)", value=0),
                    questionary.Choice("⚡ Quick Scan (First 50 cards)", value=50),
                    questionary.Choice("🎯 Custom Card Limit", value=-1),
                    questionary.Choice("❌ Cancel", value=None),
                ]
                try:
                    mode = questionary.select(
                        "Select Box Scan scope:",
                        choices=choices,
                    ).ask()
                except Exception:
                    mode = 0

                if mode is None:
                    self.console.print("[yellow]Scan cancelled.[/yellow]")
                    return
                elif mode == -1:
                    lim_str = Prompt.ask("Enter maximum cards to scan", default="100").strip()
                    max_cards = int(lim_str) if lim_str.isdigit() else 100
                elif mode > 0:
                    max_cards = mode

            target_log = custom_log if custom_log is not None else DEFAULT_BOX_SCAN_LOG_PATH
            limit_text = f"up to {max_cards} cards" if max_cards else "all cards"
            self.console.print(
                f"[bold green]Starting autonomous box scanner ({limit_text})...[/bold green]"
            )
            self.console.print(f"[dim]Debug log saved to: {target_log}[/dim]")
            self.console.print(
                "[dim]Please ensure Dokkan Battle is showing the 'Character List' (Box) screen.[/dim]\n"
            )

            self.engine.start_box_scanner(
                output_file=DEFAULT_USER_BOX_PATH,
                max_cards_to_scan=max_cards,
                log_file=target_log,
            )

        except (KeyboardInterrupt, EOFError):
            self.console.print("\n[yellow]Box scan cancelled.[/yellow]")
        except Exception as e:
            self.console.print(f"[bold red]Unexpected error in box scanner: {e}[/bold red]")

    def handle_ai_endgame_run(
        self,
        target_stage: int | str | Any = None,
        dry_run: bool = False,
        force_solve: bool = False,
        max_attempts: int | None = None,
    ):
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

        dry_badge = " [bold magenta][DRY-RUN SIMULATION][/bold magenta]" if dry_run else ""
        force_badge = " [bold red][FORCE-SOLVE][/bold red]" if force_solve else ""
        mission_line = (
            f"\n[bold yellow]Target Missions:[/bold yellow] [green]{mission_batch.summary}[/green]"
            if mission_batch
            else ""
        )
        self.console.print(
            Panel.fit(
                f"[bold cyan]⚔️ Dokkan AI Endgame Autonomous Runner[/bold cyan]{dry_badge}{force_badge}\n"
                f"[bold yellow]Event:[/bold yellow] {stage.event_name}\n"
                f"[bold yellow]Stage:[/bold yellow] {stage.stage_name} (ID: {stage.stage_id}){mission_line}\n"
                f"[bold yellow]Phases:[/bold yellow] {len(stage.phases)} sequential battles\n"
                f"[dim]Adaptive Trial & Error loop with Episodic Memory & Surgical Team Swapping[/dim]",
                border_style="cyan",
            )
        )

        res = self.engine.run_ai_endgame_sync(
            stage_identifier=stage,
            dry_run=dry_run,
            force_solve=force_solve,
            mission_batch=mission_batch,
            max_attempts=max_attempts,
        )
        if res.success:
            self.console.print(
                f"\n[bold green]🏆 STAGE CLEARED in {res.attempts} attempt(s)![/bold green]"
            )
            winning_cards_str = ", ".join(
                f"[{c.element_color}][{c.element_name}] {c.name}[/]" for c in res.winning_team
            )
            self.console.print(f"[bold]Winning Team:[/bold] {winning_cards_str}")
        else:
            self.console.print(
                f"\n[bold red]❌ Run finished without clear ({res.attempts} attempts reached).[/bold red]"
            )

    def handle_enrich_box(self, args: list | None = None):
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
        """Interactively prompts the user to select an endgame stage:
        allows picking from live DokkanDB Challenge Events (Union Master, Red Zone, SMB, etc.)
        or from classic catalog presets (Broly, Cell Max, Beast Gohan, etc.).
        Returns resolved BossStage or None if cancelled.
        """
        import questionary
        from rich.prompt import Prompt

        from dokkan_eza_link_farmer.ai.boss_catalog import get_boss_stage, list_boss_stages
        from dokkan_eza_link_farmer.ai.models import BossStage

        self.console.print(f"[dim]{t('cli.challenge.loading')}[/dim]")
        events = self.engine.dokkandb.get_challenge_events(active_only=active_only)

        choices = [
            questionary.Choice(
                "⭐ [Preset Catalog] Classic Bosses (Broly, Cell Max, Beast Gohan...)",
                value="preset",
            ),
            questionary.Separator("── DokkanDB Challenge Events ──"),
        ]

        for e in events[:50]:
            clean_t = (e.get("name") or "Unknown").replace("\n", " ").strip()
            if e.get("active") == "portal":
                status_tag = "🌀 [PORTAL]"
            elif e.get("is_currently_open"):
                status_tag = "🟢 [OPEN]"
            else:
                status_tag = "🔒 [CLOSED]"
            choices.append(
                questionary.Choice(
                    title=f"{status_tag} {clean_t} (ID: {e.get('id')})",
                    value=e,
                )
            )
        choices.append(questionary.Choice(title=t("cli.ai.opt_cancel"), value=None))

        selected: Any = None
        try:
            selected = questionary.select(
                t("cli.challenge.select_event"),
                choices=choices,
                use_arrow_keys=True,
                use_jk_keys=False,
            ).ask()
        except Exception:
            self.console.print(f"\n[bold cyan]{t('cli.challenge.select_event')}[/bold cyan]")
            self.console.print(
                "  [green] 1[/green]. ⭐ Classic Catalog Bosses (Broly, Cell Max, Beast Gohan...)"
            )
            for idx, e in enumerate(events[:25], 2):
                clean_t = (e.get("name") or "").replace("\n", " ").strip()
                self.console.print(f"  [green]{idx:2d}[/green]. {clean_t} (ID: {e.get('id')})")
            try:
                num_str = Prompt.ask("Enter number (0 to cancel)", default="1").strip()
                if num_str == "1":
                    selected = "preset"
                elif num_str.isdigit() and int(num_str) > 1:
                    i = int(num_str) - 2
                    if 0 <= i < len(events[:25]):
                        selected = events[i]
                else:
                    selected = None
            except Exception:
                selected = None

        if not selected:
            return None

        if selected == "preset":
            stages = list_boss_stages()
            st_choices = [
                questionary.Choice(
                    title=f"{s.stage_name} ({s.event_name})",
                    value=s.stage_id,
                )
                for s in stages
            ]
            st_choices.append(questionary.Choice(title=t("cli.ai.opt_cancel"), value=None))
            chosen = questionary.select("Select target boss stage:", choices=st_choices).ask()
            if chosen:
                return get_boss_stage(chosen)
            return None

        # Live DokkanDB Challenge Event
        ev_id = int(selected.get("id") or 0)
        ev_name = (selected.get("name") or "Challenge").replace("\n", " ").strip()

        details = self.engine.dokkandb.get_event_details(ev_id)
        quests = details.get("quests", []) if details else []
        quests.sort(key=lambda q: int(q.get("quest_id", 0)))

        if not quests:
            self.console.print(
                f"[yellow]No stages found for event '{ev_name}' (ID: {ev_id}).[/yellow]"
            )
            return None

        stage_choices = []
        for idx, q in enumerate(quests, 1):
            q_name = q.get("quest_name") or f"Stage {idx}"
            stages_arr = q.get("stages", [])
            st_id = stages_arr[0].get("stage_id") if stages_arr else None
            title = f"Stage {idx}: {q_name}"
            if st_id:
                title += f" (ID: {st_id})"
            stage_choices.append(
                questionary.Choice(
                    title=title,
                    value={"stage_num": idx, "stage_id": st_id, "stage_name": q_name},
                )
            )
        stage_choices.append(questionary.Choice(title=t("cli.ai.opt_cancel"), value=None))

        chosen_stage = questionary.select(
            t("cli.challenge.select_stage"),
            choices=stage_choices,
            use_arrow_keys=True,
            use_jk_keys=False,
        ).ask()

        if not chosen_stage:
            return None

        target_stage_id = chosen_stage.get("stage_id")
        if not target_stage_id:
            self.console.print("[yellow]Invalid stage ID selected.[/yellow]")
            return None

        boss_info = self.engine.dokkandb.get_stage_boss_info(ev_id, target_stage_id)
        if not boss_info or not boss_info.get("phases"):
            return BossStage(
                stage_id=target_stage_id,
                event_id=ev_id,
                stage_name=chosen_stage.get("stage_name")
                or f"Stage {chosen_stage.get('stage_num')}",
                event_name=ev_name,
                difficulty=4,
                phases=[],
            )

        return BossStage.from_dokkandb(boss_info)

    def _prompt_stage_missions(self, stage: Any) -> Any | None:
        """
        Interactively prompts the user via a checkbox multi-selector to select one or more
        missions specific to the chosen stage. Returns a consolidated MissionBatch or None.
        """
        import questionary

        from dokkan_eza_link_farmer.ai.mission_solver import MissionBundler, MissionParser

        ev_id = getattr(stage, "event_id", 0)
        st_id = getattr(stage, "stage_id", 0)
        st_name = getattr(stage, "stage_name", "")

        if not ev_id and st_id:
            st_str = str(st_id)
            if len(st_str) >= 8:
                try:
                    ev_id = int(st_str[:4])
                except ValueError:
                    ev_id = 0

        if not ev_id:
            return None

        # Extract numeric stage number
        stage_num: int | None = None
        if str(st_id).startswith(str(ev_id)) and len(str(st_id)) > len(str(ev_id)) + 1:
            try:
                stage_num = int(str(st_id)[len(str(ev_id)) : -1])
            except ValueError:
                stage_num = None

        if stage_num is None:
            import re

            m = re.search(r"Stage\s*(\d+)", st_name, re.IGNORECASE)
            if m:
                stage_num = int(m.group(1))

        try:
            with self.console.status("[dim]Fetching stage missions from DokkanDB...[/dim]"):
                raw_missions = self.engine.dokkandb.get_event_missions(ev_id)
        except Exception as e:
            logger.debug(f"Failed to fetch event missions for event {ev_id}: {e}")
            return None

        if not raw_missions:
            return None

        parsed_missions = [MissionParser.parse(m) for m in raw_missions]
        restricted_stage_missions = [
            m for m in parsed_missions if m.applies_to_stage(stage_num) and m.is_restricted
        ]

        if not restricted_stage_missions:
            return None

        choices = [
            questionary.Choice(
                title=f"🎯 {m.display_title}",
                value=m,
            )
            for m in restricted_stage_missions
        ]

        try:
            selected = questionary.checkbox(
                "Select stage missions to target (Space to toggle, Enter to confirm/skip):",
                choices=choices,
                use_arrow_keys=True,
                use_jk_keys=False,
            ).ask()
        except (KeyboardInterrupt, EOFError):
            return None

        if not selected:
            self.console.print(
                "[dim]No specific mission selected. Building standard optimal team...[/dim]"
            )
            return None

        batch = MissionBundler.create_batch_from_selection(selected)
        self.console.print(
            Panel.fit(
                f"[bold green]🎯 Mission Targeting Enabled:[/bold green] [bold yellow]{batch.summary}[/bold yellow]\n"
                f"[dim]The AI Solver will strictly constrain team synthesis to satisfy these mission conditions.[/dim]",
                border_style="green",
            )
        )
        return batch

    def _ai_build_team_for_stage(self, stage: Any):
        """Solves and optimizes the best team against a specific Challenge BossStage using the AI Teambuilder."""
        from dokkan_eza_link_farmer.ai.models import DokkanCard

        def _fmt_phase(p: Any) -> str:
            en = p.element_name or "Boss"
            u = en.upper()
            if "AGL" in u:
                return f"[bold cyan]{en}[/bold cyan]"
            if "TEQ" in u:
                return f"[bold green]{en}[/bold green]"
            if "INT" in u:
                return f"[bold magenta]{en}[/bold magenta]"
            if "STR" in u:
                return f"[bold red]{en}[/bold red]"
            if "PHY" in u:
                return f"[bold yellow]{en}[/bold yellow]"
            return en

        phases_str = (
            " -> ".join(_fmt_phase(p) for p in stage.phases) if stage.phases else "Standard Boss"
        )
        gimmicks = []
        if any(p.cancels_dodge for p in stage.phases):
            gimmicks.append("Cancels Dodge")
        if any(p.has_aoe for p in stage.phases):
            gimmicks.append("AoE Attack")
        if any(p.locks_slots for p in stage.phases):
            gimmicks.append("Locks Slots")
        gimmicks_str = f" [{', '.join(gimmicks)}]" if gimmicks else ""

        self.console.print(
            Panel.fit(
                f"[bold cyan]🎯 AI Team Synthesis for: {stage.event_name}[/bold cyan]\n"
                f"[bold yellow]Stage:[/bold yellow] {stage.stage_name} (ID: {stage.stage_id})\n"
                f"[bold yellow]Phases:[/bold yellow] {len(stage.phases)} battles ({phases_str}){gimmicks_str}\n"
                f"[dim]Consulting Constraint Solver & AI Tactical Advisor against lethal boss gimmicks...[/dim]",
                border_style="cyan",
            )
        )

        # Stage mission selection
        mission_batch = self._prompt_stage_missions(stage)

        candidate_pool = self.engine.team_builder.load_user_box()
        if len(candidate_pool) < 6:
            self.console.print(
                "[dim]User box has < 6 cards, loading DokkanDB catalog fallback...[/dim]"
            )
            catalog = self.engine.dokkandb.get_cards_catalog()
            candidate_pool = [DokkanCard.from_dokkandb(raw) for raw in catalog[:400]]

        shortlist = None
        try:
            with self.console.status(
                "[bold cyan]Synthesizing optimal team with AI Solver & Advisor...", spinner="dots"
            ):
                rec, shortlist = self.engine.team_builder.select_best_team_for_boss(
                    candidate_pool=candidate_pool,
                    boss_stage=stage,
                    language=get_language(),
                    mission_batch=mission_batch,
                )
        except Exception as e:
            self.console.print(
                f"[yellow]Algorithmic solver notice: {e}. Building best synergy plan...[/yellow]"
            )
            rec = self.engine.team_builder.build_team_plan(
                candidate_pool[:6],
                language=get_language(),
            )

        self._render_team_presentation(
            rec,
            title=f"🔄 AI Recommended Tactical Rotations for {stage.stage_name}",
            shortlist=shortlist,
        )

    def _render_team_presentation(
        self,
        rec: Any,
        title: str = "",
        shortlist: list[Any] | None = None,
    ):
        """Displays rich team representation with Dokkan typing colors for all cards."""
        from rich.table import Table

        from dokkan_eza_link_farmer.ai.team_builder import render_team_summary_table_rich

        # 0. Mission Completion Banner if targeted
        if getattr(rec, "mission_summary", None):
            self.console.print(
                Panel.fit(
                    f"[bold green]🎯 Solved for Stage Missions:[/bold green] [bold yellow]{rec.mission_summary}[/bold yellow]\n"
                    f"[bold cyan]All 6 team members strictly comply with mission requirements![/bold cyan]",
                    border_style="green",
                )
            )

        # 1. 6-Card Team Summary Table with Dokkan Colors
        self.console.print(render_team_summary_table_rich(rec.all_cards, rec.leader))

        # 2. Rotations Breakdown Table with Dokkan Colors
        t_team = Table(
            title=title or "🔄 AI Recommended Tactical Rotations",
            border_style="green",
        )
        t_team.add_column("Role", style="bold cyan")
        t_team.add_column("Character")
        t_team.add_column("Notes", style="dim")

        t_team.add_row(
            "Leader", rec.leader.rich_formatted_name(), rec.leader.leader_skill[:60] + "..."
        )
        t_team.add_row(
            "Rotation A (Slot 1)",
            rec.rotation_a.slot1.rich_formatted_name(),
            f"Tank | Shared: {', '.join(rec.rotation_a.shared_links[:4])}",
        )
        t_team.add_row(
            "Rotation A (Slot 2)",
            rec.rotation_a.slot2.rich_formatted_name(),
            f"Damage | Synergy: {rec.rotation_a.synergy_score:.1f}",
        )
        t_team.add_row(
            "Rotation B (Slot 1)",
            rec.rotation_b.slot1.rich_formatted_name(),
            f"Tank | Shared: {', '.join(rec.rotation_b.shared_links[:4])}",
        )
        t_team.add_row(
            "Rotation B (Slot 2)",
            rec.rotation_b.slot2.rich_formatted_name(),
            f"Damage | Synergy: {rec.rotation_b.synergy_score:.1f}",
        )
        for idx, fl in enumerate(rec.floaters, 1):
            t_team.add_row(f"Floater #{idx} (Slot 3)", fl.rich_formatted_name(), "Support / Flex")

        self.console.print(t_team)

        # 3. Top-5 Substitutes Shortlist with Dokkan Colors
        if shortlist:
            t_short = Table(
                title="🔄 Top-5 Recommended Substitutes (Shortlist)", border_style="cyan"
            )
            t_short.add_column("Rank", style="bold cyan", justify="center")
            t_short.add_column("Candidate Character")
            t_short.add_column("Score", justify="right", style="yellow")
            t_short.add_column("Key Strengths", style="dim")
            for idx, cand in enumerate(shortlist[:5], 1):
                reason_str = getattr(cand, "reasoning", "")
                if not reason_str and getattr(cand, "counter_points", None):
                    reason_str = "; ".join(cand.counter_points)
                if not reason_str and cand.card and cand.card.categories:
                    reason_str = ", ".join(cand.card.categories[:3])
                t_short.add_row(
                    f"#{idx}",
                    cand.card.rich_formatted_name(),
                    f"{cand.score:.1f}",
                    reason_str or "Synergy pick",
                )
            self.console.print(t_short)

        if rec.ai_reasoning:
            self.console.print(
                Panel(
                    f"[italic dim cyan]{rec.ai_reasoning}[/italic dim cyan]",
                    title=f"🧠 {t('cli.ai.reasoning_title')}",
                    border_style="magenta",
                )
            )

        self.console.print(
            Panel(
                rec.tactical_analysis,
                title=f"⚔️ {t('cli.ai.tactical_title')}",
                border_style="yellow",
            )
        )

    def handle_ai_interactive(self, args: list):
        """Interactive AI Team Builder & Tactical Advisor (Qwen / DeepSeek-R1)."""
        import questionary

        sub = (args[0].lower() if args else "").strip()
        if sub in ("status", "check"):
            self._ai_show_status()
            return
        if sub in ("partner", "link", "links"):
            query = " ".join(args[1:]) if len(args) > 1 else ""
            self._ai_find_partners(query)
            return
        if sub in ("build", "team"):
            query = " ".join(args[1:]) if len(args) > 1 else ""
            self._ai_build_team(query)
            return
        if sub in ("config", "switch"):
            self._ai_configure_model()
            return
        if sub in ("run", "endgame", "ai-run"):
            stage_target = args[1] if len(args) > 1 else None
            if stage_target:
                self.handle_ai_endgame_run(stage_target)
            else:
                stage = self._select_challenge_boss_stage()
                if stage:
                    self.handle_ai_endgame_run(stage)
            return

        choices = [
            questionary.Choice(title=t("cli.ai.opt_build"), value="build"),
            questionary.Choice(
                title="⚔️ Run AI Endgame Loop (Red Zone / SMB / Challenge)", value="endgame"
            ),
            questionary.Choice(title=t("cli.ai.opt_partner"), value="partner"),
            questionary.Choice(title=t("cli.ai.opt_status"), value="status"),
            questionary.Choice(title=t("cli.ai.opt_config"), value="config"),
            questionary.Choice(title=t("cli.ai.opt_cancel"), value=None),
        ]

        action = questionary.select(
            t("cli.ai.menu_title"),
            choices=choices,
        ).ask()

        if action == "build":
            self._ai_build_team()
        elif action == "endgame":
            stage = self._select_challenge_boss_stage()
            if stage:
                self.handle_ai_endgame_run(stage)
        elif action == "partner":
            self._ai_find_partners()
        elif action == "status":
            self._ai_show_status()
        elif action == "config":
            self._ai_configure_model()

    def _ai_show_status(self):
        """Displays AI backend connection status and model details."""
        conf = self.engine.ai_config
        is_up = self.engine.ai_client.is_available()

        table = Table(title=t("cli.ai.status_title"), border_style="cyan")
        table.add_column("Property", style="bold")
        table.add_column("Value")

        status_str = (
            f"[bold green]{t('cli.ai.online')}[/]"
            if is_up
            else f"[bold red]{t('cli.ai.offline', url=conf.base_url)}[/]"
        )
        table.add_row("Status", status_str)
        table.add_row("Model Family", conf.model_family.value.upper())
        table.add_row("Model Name", conf.model_name)
        table.add_row("Provider / Endpoint", f"{conf.provider} ({conf.base_url})")

        self.console.print(table)
        if not is_up:
            self.console.print(
                "[dim yellow]Hint: To run locally via Ollama, open terminal and type: "
                f"ollama run {conf.model_name}[/dim yellow]\n"
            )

    def _ai_find_partners(self, query: str = ""):
        """Finds top linking partners for a card using DokkanDB and synergy scoring."""
        import questionary

        from dokkan_eza_link_farmer.ai.models import DokkanCard

        if not query:
            query = questionary.text(t("cli.ai.query_prompt")).ask()
            if not query:
                return

        self.console.print(f"[dim]{t('cli.ai.searching')}[/dim]")
        cards = self.engine.dokkandb.search_cards(query, limit=12)
        if not cards:
            self.console.print(f"[yellow]{t('cli.ai.no_cards_found', query=query)}[/yellow]")
            return

        choices = [
            questionary.Choice(
                title=f"{c.get('name')} - {c.get('subname', '')} (ID: {c.get('id')})",
                value=c.get("id"),
            )
            for c in cards
        ]
        choices.append(questionary.Choice(title=t("cli.ai.opt_cancel"), value=None))

        chosen_id = questionary.select(
            t("cli.ai.select_leader"),
            choices=choices,
        ).ask()

        if not chosen_id:
            return

        card_data = self.engine.dokkandb.get_card(int(chosen_id))
        if not card_data:
            self.console.print("[red]Could not retrieve card details.[/red]")
            return

        target_card = DokkanCard.from_dokkandb(card_data)

        # Retrieve catalog to find best partners
        catalog = self.engine.dokkandb.get_cards_catalog()
        candidate_pool: list[DokkanCard] = []
        for raw in catalog[:300]:
            if int(raw.get("id") or 0) == target_card.id:
                continue
            candidate_pool.append(DokkanCard.from_dokkandb(raw))

        partners = self.engine.team_builder.find_best_partners_for_card(
            target_card, candidate_pool, top_k=7
        )

        table = Table(
            title=f"Top Linking Partners for {target_card.full_name}",
            border_style="green",
        )
        table.add_column("Rank", style="bold cyan")
        table.add_column("Partner Card")
        table.add_column("Synergy", justify="right", style="yellow")
        table.add_column("Shared Links", style="dim")

        for idx, (p_card, score, shared) in enumerate(partners, 1):
            table.add_row(
                f"#{idx}",
                p_card.rich_formatted_name(),
                f"{score:.1f}",
                ", ".join(shared),
            )

        self.console.print(table)

    def _ai_build_team(self, query: str = ""):
        """Builds an optimized team and gets Qwen/DeepSeek-R1 tactical breakdown."""
        import questionary

        from dokkan_eza_link_farmer.ai.models import DokkanCard

        if not query:
            build_mode = questionary.select(
                "Select Team Building target:",
                choices=[
                    questionary.Choice(
                        "🎯 Build & Optimize Team for a Challenge Event (DokkanDB)",
                        value="challenge",
                    ),
                    questionary.Choice(
                        "👤 Build Team around a Specific Leader Character", value="leader"
                    ),
                    questionary.Choice(t("cli.ai.opt_cancel"), value=None),
                ],
            ).ask()
            if not build_mode:
                return
            if build_mode == "challenge":
                stage = self._select_challenge_boss_stage()
                if stage:
                    self._ai_build_team_for_stage(stage)
                return

            query = questionary.text(t("cli.ai.query_prompt")).ask()
            if not query:
                return

        self.console.print(f"[dim]{t('cli.ai.searching')}[/dim]")
        cards = self.engine.dokkandb.search_cards(query, limit=10)
        if not cards:
            self.console.print(f"[yellow]{t('cli.ai.no_cards_found', query=query)}[/yellow]")
            return

        choices = [
            questionary.Choice(
                title=f"{c.get('name')} - {c.get('subname', '')} (ID: {c.get('id')})",
                value=c.get("id"),
            )
            for c in cards
        ]
        choices.append(questionary.Choice(title=t("cli.ai.opt_cancel"), value=None))

        leader_id = questionary.select(
            t("cli.ai.select_leader"),
            choices=choices,
        ).ask()

        if not leader_id:
            return

        leader_data = self.engine.dokkandb.get_card(int(leader_id))
        if not leader_data:
            self.console.print("[red]Could not load card details.[/red]")
            return

        leader_card = DokkanCard.from_dokkandb(leader_data)

        # Build team pool around leader
        catalog = self.engine.dokkandb.get_cards_catalog()
        candidate_pool = [
            DokkanCard.from_dokkandb(raw)
            for raw in catalog[:400]
            if int(raw.get("id") or 0) != leader_card.id
        ]

        top_partners = self.engine.team_builder.find_best_partners_for_card(
            leader_card, candidate_pool, top_k=5
        )
        sub_units = [p[0] for p in top_partners]
        while len(sub_units) < 5 and candidate_pool:
            sub_units.append(candidate_pool.pop(0))

        team_cards = [leader_card] + sub_units[:5]

        rec = self.engine.team_builder.build_team_plan(
            team_cards,
            language=get_language(),
        )

        self._render_team_presentation(
            rec,
            title="🔄 AI Recommended Tactical Rotations",
        )

    def _ai_configure_model(self):
        """Allows switching strictly between the 3 universal models: deepseek-r1:7b, qwen2.5:7b, qwen2.5:3b."""
        import questionary

        from dokkan_eza_link_farmer.ai.client import DokkanAIClient
        from dokkan_eza_link_farmer.ai.models import AIConfig, SupportedAIModel
        from dokkan_eza_link_farmer.ai.team_builder import TeamBuilder

        choice = questionary.select(
            t("cli.ai.switch_family_prompt"),
            choices=[
                questionary.Choice(
                    title="1. deepseek-r1:7b  (DeepSeek-R1 CoT Reasoning - Consigliato PC & Mac)",
                    value=SupportedAIModel.DEEPSEEK_R1_7B.value,
                ),
                questionary.Choice(
                    title="2. qwen2.5:7b      (Qwen 2.5 Diretto, veloce e strutturato - PC & Mac)",
                    value=SupportedAIModel.QWEN_2_5_7B.value,
                ),
                questionary.Choice(
                    title="3. qwen2.5:3b      (Qwen 2.5 Ultraleggero per MacBook Air & Batteria)",
                    value=SupportedAIModel.QWEN_2_5_3B.value,
                ),
            ],
        ).ask()

        if not choice:
            return

        model_name = SupportedAIModel.normalize(choice)
        family = "deepseek_r1" if model_name == SupportedAIModel.DEEPSEEK_R1_7B.value else "qwen"

        if "ai" not in self.engine.config:
            self.engine.config["ai"] = {}

        self.engine.config["ai"]["enabled"] = True
        self.engine.config["ai"]["model_family"] = family
        self.engine.config["ai"]["model_name"] = model_name
        self.engine.save_config()

        self.engine.ai_config = AIConfig.from_dict(self.engine.config.get("ai"))
        self.engine.ai_client = DokkanAIClient(self.engine.ai_config)
        self.engine.team_builder = TeamBuilder(
            dokkandb=self.engine.dokkandb, ai_client=self.engine.ai_client
        )

        self.console.print(f"[bold green]{t('cli.ai.config_saved')}[/bold green]")
        self._ai_show_status()

    def run(self):
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
                    if not devices:
                        self.console.print(f"[red]{t('cli.devices.none_found')}[/]")
                    else:
                        t_dev = Table(title=t("cli.devices.title"), border_style="green")
                        t_dev.add_column(t("cli.devices.col_serial"), style="bold")
                        t_dev.add_column(t("cli.devices.col_status"))
                        t_dev.add_column(t("cli.devices.col_model"))
                        for d in devices:
                            t_dev.add_row(d["serial"], d["status"], d["model"])
                        self.console.print(t_dev)

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
