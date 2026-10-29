from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from dokkan_eza_link_farmer.core.i18n import t


def render_banner(console: Console | None = None) -> None:
    """Renders stylized welcome banner."""
    c = console or Console()
    banner = Text()
    banner.append(f"{t('cli.banner_title')}\n", style="bold red")
    banner.append(f"{t('cli.banner_subtitle')}\n", style="yellow")
    banner.append(t("cli.banner_help_hint"), style="dim")
    c.print(Panel(banner, border_style="red", expand=False))


def render_help(console: Console | None = None) -> None:
    """Renders interactive command table."""
    c = console or Console()
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
    table.add_row("scan-box", "[max_cards] [--fresh]", t("cli.help.desc_scan_box"))
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

    c.print(table)


def render_doctor(report: dict[str, Any], console: Console | None = None) -> None:
    """Renders comprehensive environment diagnostics."""
    c = console or Console()
    report = report or {}
    os_name = str(report.get("os") or "Unknown OS")
    table = Table(title=t("cli.doctor.title", os=os_name), border_style="green")
    table.add_column(t("cli.doctor.col_component"), style="bold")
    table.add_column(t("cli.doctor.col_status"), style="white")
    table.add_column(t("cli.doctor.col_details"), style="dim")

    # Python
    python_mode = (
        t("cli.doctor.standalone_mode") if report.get("is_frozen") else t("cli.doctor.dev_mode")
    )
    py_ver = str(report.get("python_version") or "3.x")
    table.add_row(
        t("cli.doctor.prop_python"),
        f"[green]{t('cli.doctor.status_ok')}[/]",
        f"v{py_ver} ({python_mode})",
    )

    # ADB
    adb_info = report.get("adb") or {}
    if adb_info.get("found"):
        adb_str = f"[green]{t('cli.doctor.status_found')}[/] ({adb_info.get('version', '')})"
        table.add_row(t("cli.doctor.prop_adb"), adb_str, str(adb_info.get("path", "")))
    else:
        table.add_row(
            t("cli.doctor.prop_adb"),
            f"[red]{t('cli.doctor.status_missing')}[/]",
            t("cli.doctor.adb_missing_desc"),
        )

    # scrcpy
    scrcpy_info = report.get("scrcpy") or {}
    if scrcpy_info.get("found"):
        scrcpy_str = f"[green]{t('cli.doctor.status_found')}[/] ({scrcpy_info.get('version', '')})"
        table.add_row(t("cli.doctor.prop_scrcpy"), scrcpy_str, str(scrcpy_info.get("path", "")))
    else:
        table.add_row(
            t("cli.doctor.prop_scrcpy"),
            f"[yellow]{t('cli.doctor.status_not_found')}[/]",
            t("cli.doctor.scrcpy_missing_desc"),
        )

    # Devices
    devs = report.get("devices") or []
    if devs:
        dev_str = ", ".join(
            f"{d.get('serial', '?') if isinstance(d, dict) else str(d)} ({d.get('model', '?') if isinstance(d, dict) else '?'})"
            for d in devs
        )
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

    c.print(table)

    # Installation hints if tools are missing
    adb_found = bool(adb_info.get("found"))
    scrcpy_found = bool(scrcpy_info.get("found"))
    if not scrcpy_found or not adb_found:
        h = report.get("install_help") or {}
        help_panel = Text()
        help_panel.append(
            f"\n{t('cli.doctor.install_help_title', os=os_name)}\n", style="bold yellow"
        )
        if not scrcpy_found and not adb_found:
            help_panel.append(t("cli.doctor.install_run_hint"), style="dim")
            help_panel.append(f"{h.get('all', '')}\n", style="bold green")
        elif not scrcpy_found:
            help_panel.append(t("cli.doctor.install_run_hint"), style="dim")
            help_panel.append(f"{h.get('scrcpy', '')}\n", style="bold green")
        elif not adb_found:
            help_panel.append(t("cli.doctor.install_run_hint"), style="dim")
            help_panel.append(f"{h.get('adb', '')}\n", style="bold green")
        if h.get("note"):
            help_panel.append(
                f"{t('cli.doctor.install_note_label', note=h.get('note'))}\n", style="italic"
            )
        c.print(Panel(help_panel, border_style="yellow", expand=False))


def render_status(info: dict[str, Any], console: Console | None = None) -> None:
    """Renders status summary card."""
    c = console or Console()
    info = info or {}
    table = Table(title=t("cli.status.title"), border_style="blue")
    table.add_column(t("cli.status.prop_device"), style="bold")
    table.add_column(t("cli.status.prop_value"), style="yellow")

    device_val = info.get("device_serial") or t("cli.status.not_connected")
    running_val = t("cli.status.yes") if info.get("task_running") else t("cli.status.no")

    table.add_row(t("cli.status.prop_device"), str(device_val))
    table.add_row(t("cli.status.prop_task_running"), running_val)
    task_type = info.get("task_type") or t("cli.status.none")
    table.add_row(t("cli.status.prop_task_type"), str(task_type))
    runs_target_val = info.get("runs_target")
    target_display = (
        str(runs_target_val) if runs_target_val is not None and runs_target_val > 0 else "∞"
    )
    runs_comp = info.get("runs_completed")
    runs_comp_val = runs_comp if runs_comp is not None else 0
    table.add_row(t("cli.status.prop_runs_completed"), f"{runs_comp_val} / {target_display}")
    screen_state = info.get("current_state") or "IDLE"
    table.add_row(t("cli.status.prop_screen_state"), str(screen_state))

    c.print(table)


def render_ai_status(conf: Any, is_up: bool, console: Console | None = None) -> None:
    """Displays AI backend connection status and model details."""
    c = console or Console()
    table = Table(title=t("cli.ai.status_title"), border_style="cyan")
    table.add_column(t("cli.ai.prop_property"), style="bold")
    table.add_column(t("cli.ai.prop_value"))

    base_url = getattr(conf, "base_url", "http://localhost:11434")
    model_family = getattr(conf, "model_family", None)
    if model_family is not None and hasattr(model_family, "value"):
        family_str = str(model_family.value).upper()
    else:
        family_str = str(model_family or "LLAMA").upper()
    model_name = getattr(conf, "model_name", "llama3.2:3b")
    provider = getattr(conf, "provider", "ollama")

    status_str = (
        f"[bold green]{t('cli.ai.online')}[/]"
        if is_up
        else f"[bold red]{t('cli.ai.offline', url=base_url)}[/]"
    )
    table.add_row(t("cli.ai.prop_status"), status_str)
    table.add_row(t("cli.ai.prop_family"), family_str)
    table.add_row(t("cli.ai.prop_model"), str(model_name))
    table.add_row(t("cli.ai.prop_provider"), f"{provider} ({base_url})")

    c.print(table)
    if not is_up:
        c.print(f"[dim yellow]{t('cli.ai.ollama_hint', model=model_name)}[/dim yellow]\n")


def render_devices_table(devices: list[Any], console: Console | None = None) -> None:
    """Renders connected Android devices table."""
    c = console or Console()
    if not devices:
        c.print(f"[red]{t('cli.devices.none_found')}[/]")
    else:
        t_dev = Table(title=t("cli.devices.title"), border_style="green")
        t_dev.add_column(t("cli.devices.col_serial"), style="bold")
        t_dev.add_column(t("cli.devices.col_status"))
        t_dev.add_column(t("cli.devices.col_model"))
        for d in devices:
            if isinstance(d, dict):
                serial = str(d.get("serial", "N/A"))
                status = str(d.get("status", "unknown"))
                model = str(d.get("model", "N/A"))
            else:
                serial = str(d)
                status = "unknown"
                model = "N/A"
            t_dev.add_row(serial, status, model)
        c.print(t_dev)
