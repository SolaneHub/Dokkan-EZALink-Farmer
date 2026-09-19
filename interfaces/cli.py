import os
import sys
import time

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.prompt import Prompt

from core.bot_engine import BotEngine
from core.i18n import t, set_language, get_language, get_available_languages


class TerminalCLI:
    """Rich interactive Terminal Command Interface for DokkanBattleBot."""

    def __init__(self, engine: BotEngine):
        self.engine = engine
        self.console = Console()

        # Route bot logs into Rich console
        self.engine.register_log_callback(self._on_log)
        self.engine.register_run_callback(self._on_run_update)

    def _on_log(self, msg: str):
        """Displays formatted log message in terminal."""
        self.console.print(f"[dim]{time.strftime('%H:%M:%S')}[/dim] [cyan][BOT][/cyan] {msg}")

    def _on_run_update(self, curr: int, tot: int):
        """Displays run completion counter."""
        self.console.print(f"[bold green]{t('cli.progress_format', curr=curr, tot=tot)}[/]")

    def print_banner(self):
        """Renders stylized welcome banner."""
        banner = Text()
        banner.append(f"{t('cli.banner_title')}\n", style="bold red")
        banner.append(f"{t('cli.banner_subtitle')}\n", style="yellow")
        banner.append(t('cli.banner_help_hint'), style="dim")
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
        table.add_row("farm", "[run=10]", t("cli.help.desc_farm"))
        table.add_row("eza", "[level=999]", t("cli.help.desc_eza"))
        table.add_row("link", "[run=20]", t("cli.help.desc_link"))
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
        table = Table(title=t("cli.doctor.title", os=report['os']), border_style="green")
        table.add_column(t("cli.doctor.col_component"), style="bold")
        table.add_column(t("cli.doctor.col_status"), style="white")
        table.add_column(t("cli.doctor.col_details"), style="dim")

        # Python
        python_mode = t("cli.doctor.standalone_mode") if report['is_frozen'] else t("cli.doctor.dev_mode")
        table.add_row(t("cli.doctor.prop_python"), f"[green]{t('cli.doctor.status_ok')}[/]", f"v{report['python_version']} ({python_mode})")

        # ADB
        if report["adb"]["found"]:
            adb_str = f"[green]{t('cli.doctor.status_found')}[/] ({report['adb']['version']})"
            table.add_row(t("cli.doctor.prop_adb"), adb_str, report["adb"]["path"])
        else:
            table.add_row(t("cli.doctor.prop_adb"), f"[red]{t('cli.doctor.status_missing')}[/]", t("cli.doctor.adb_missing_desc"))

        # scrcpy
        if report["scrcpy"]["found"]:
            scrcpy_str = f"[green]{t('cli.doctor.status_found')}[/] ({report['scrcpy']['version']})"
            table.add_row(t("cli.doctor.prop_scrcpy"), scrcpy_str, report["scrcpy"]["path"])
        else:
            table.add_row(t("cli.doctor.prop_scrcpy"), f"[yellow]{t('cli.doctor.status_not_found')}[/]", t("cli.doctor.scrcpy_missing_desc"))

        # Devices
        devs = report.get("devices", [])
        if devs:
            dev_str = ", ".join(f"{d['serial']} ({d['model']})" for d in devs)
            table.add_row(t("cli.doctor.prop_devices"), f"[green]{t('cli.doctor.devices_connected', count=len(devs))}[/]", dev_str)
        else:
            table.add_row(t("cli.doctor.prop_devices"), f"[yellow]{t('cli.doctor.devices_none')}[/]", t("cli.doctor.devices_none_desc"))

        self.console.print(table)

        # Installation hints if tools are missing
        if not report["scrcpy"]["found"] or not report["adb"]["found"]:
            h = report.get("install_help", {})
            help_panel = Text()
            help_panel.append(f"\n{t('cli.doctor.install_help_title', os=report['os'])}\n", style="bold yellow")
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
                help_panel.append(f"{t('cli.doctor.install_note_label', note=h.get('note'))}\n", style="italic")
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
        table.add_row(t("cli.status.prop_runs_completed"), f"{info['runs_completed']} / {info['runs_target']}")
        table.add_row(t("cli.status.prop_screen_state"), str(info["current_state"]))

        self.console.print(table)

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
                        self.console.print(f"[cyan]{t('cli.current_language', lang=current)}[/] (Available: {avail})")
                    else:
                        target_lang = args[0].lower()
                        if target_lang in get_available_languages():
                            set_language(target_lang)
                            self.engine.config["language"] = target_lang
                            self.engine.save_config()
                            self.console.print(f"[bold green]{t('cli.language_changed', lang=target_lang)}[/]")
                        else:
                            avail_str = ", ".join(get_available_languages())
                            self.console.print(f"[bold red]{t('cli.invalid_language', lang=target_lang, available=avail_str)}[/]")

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
                        self.console.print(f"[bold red]{t('cli.devices.connect_error', error=str(e))}[/]")

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
                        self.console.print(f"[bold green]{t('cli.inspect.state_format', state=f'[bold yellow]{state.value}[/bold yellow]')}[/]")
                    except Exception as e:
                        self.console.print(f"[red]{t('cli.inspect.error', error=str(e))}[/]")

                elif cmd in ("shot", "screenshot"):
                    filename = args[0] if args else f"screenshot_{int(time.time())}.png"
                    try:
                        path = self.engine.save_screenshot_to_file(filename)
                        self.console.print(f"[green]{t('cli.shot.saved', path=path)}[/]")
                    except Exception as e:
                        self.console.print(f"[red]{t('cli.shot.error', error=str(e))}[/]")

                elif cmd == "farm":
                    runs = int(args[0]) if args and args[0].isdigit() else 10
                    self.engine.start_stage_farm(runs=runs)

                elif cmd == "eza":
                    default_lvl = self.engine.config.get("farming", {}).get("eza_target_level", 999)
                    target_lvl = int(args[0]) if args and args[0].isdigit() else default_lvl
                    self.engine.start_eza_farm(target_level=target_lvl)

                elif cmd == "link":
                    runs = int(args[0]) if args and args[0].isdigit() else 20
                    self.engine.start_link_level_farm(runs=runs)

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
