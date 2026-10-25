from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

try:
    import questionary
except ImportError:
    questionary = None  # type: ignore

if TYPE_CHECKING:
    from dokkan_eza_link_farmer.core.bot_engine import BotEngine

from dokkan_eza_link_farmer.automation.tasks.box_scanner import (
    DEFAULT_BOX_SCAN_LOG_PATH,
    DEFAULT_USER_BOX_PATH,
)
from dokkan_eza_link_farmer.core.i18n import get_language, t
from dokkan_eza_link_farmer.ui.briefing import (
    render_ai_stage_synthesis_header,
    render_linking_partners,
    render_mission_batches,
    render_stage_boss_info,
    render_team_presentation,
)
from dokkan_eza_link_farmer.ui.panels import render_ai_status

logger = logging.getLogger(__name__)


def handle_eza_interactive(
    engine: BotEngine,
    console: Console,
    args: list | None = None,
) -> None:
    """Handles EZA command: interactive DokkanDB selection or direct execution."""
    args = args or []
    default_lvl = engine.config.get("farming", {}).get("eza_target_level", 999)

    # 1. Direct command if level is given as integer (e.g. 'eza 30')
    if args and args[0].isdigit():
        target_lvl = int(args[0])
        engine.start_eza_farm(target_level=target_lvl)
        return

    # 2. Direct command if 'auto' is specified (e.g. 'eza auto 30')
    if args and args[0].lower() in ("auto", "classic"):
        target_lvl = int(args[1]) if len(args) > 1 and args[1].isdigit() else default_lvl
        engine.start_eza_farm(target_level=target_lvl)
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
            console.print(f"[yellow]{t('cli.dokkandb.canceled')}[/]")
            return

        if action == "auto":
            lvl_str = questionary.text(
                t("cli.dokkandb.target_level_prompt", default=default_lvl),
                default=str(default_lvl),
            ).ask()
            if lvl_str is None:
                console.print(f"[yellow]{t('cli.dokkandb.canceled')}[/]")
                return
            target_lvl = int(lvl_str) if lvl_str and lvl_str.isdigit() else default_lvl
            engine.start_eza_farm(target_level=target_lvl)
            return

        if action == "select":
            console.print(f"[cyan]{t('cli.dokkandb.fetching')}[/]")
            events = engine.dokkandb.get_zbattles()
            if not events:
                console.print(
                    f"[red]{t('cli.dokkandb.fetch_error', error='No events returned')}[/]"
                )
                return

            # Sort: open events first, then by ID descending
            events.sort(key=lambda x: (not x.get("is_currently_open", False), -int(x.get("id", 0))))

            choices_eza = []
            for e in events:
                status_tag = "🟢 [OPEN]" if e.get("is_currently_open") else "🔑 [PORTAL]"
                name = e.get("name", "Unknown EZA")
                eid = e.get("id", "?")
                choices_eza.append(
                    questionary.Choice(title=f"{status_tag} {name} (ID: {eid})", value=e)
                )
            choices_eza.append(questionary.Choice(title=t("cli.dokkandb.opt_cancel"), value=None))

            chosen = questionary.select(
                t("cli.dokkandb.select_prompt"),
                choices=choices_eza,
                use_search_filter=True,
                use_arrow_keys=True,
                use_jk_keys=False,
            ).ask()

            if not chosen:
                console.print(f"[yellow]{t('cli.dokkandb.canceled')}[/]")
                return

            lvl_str = questionary.text(
                t("cli.dokkandb.target_level_prompt", default=default_lvl),
                default=str(default_lvl),
            ).ask()
            if lvl_str is None:
                console.print(f"[yellow]{t('cli.dokkandb.canceled')}[/]")
                return
            target_lvl = int(lvl_str) if lvl_str and lvl_str.isdigit() else default_lvl

            chosen_name = chosen.get("name", "Selected EZA")
            console.print(f"[dim]{t('cli.dokkandb.downloading_banner', name=chosen_name)}[/dim]")
            banner_path = engine.dokkandb.download_banner(chosen)
            if banner_path:
                chosen["banner_local_path"] = banner_path
                console.print(
                    f"[green]{t('cli.dokkandb.banner_downloaded', path=os.path.basename(banner_path))}[/green]"
                )
            else:
                console.print(f"[yellow]{t('cli.dokkandb.banner_unavailable')}[/yellow]")

            console.print(
                f"[bold green]{t('cli.dokkandb.selected_summary', name=chosen_name, level=target_lvl)}[/bold green]"
            )
            engine.start_eza_farm(target_level=target_lvl, target_eza=chosen)

    except (KeyboardInterrupt, EOFError):
        console.print(f"\n[yellow]{t('cli.dokkandb.canceled')}[/]")
    except Exception as e:
        console.print(f"[bold red]{t('cli.unexpected_error', error=str(e))}[/]")


def handle_link_interactive(
    engine: BotEngine,
    console: Console,
    args: list | None = None,
) -> None:
    """Handles Link Leveling command with interactive stage dropdown and rarity flags."""
    args = args or []
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
            stage_name = (
                "Area 39 Stage 3: Great stamina-friendly option (also drops green gems) | 5 fights"
            )
        elif low in ("35-1", "35_1", "351", "area_35_1"):
            target_stage = "area_35_1"
            stage_name = (
                "Area 35 Stage 1: Good stamina-friendly option (also drops blue gems) | 4 fights"
            )
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
                console.print(f"[yellow]{t('cli.dokkandb.canceled')}[/yellow]")
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
                console.print(f"[yellow]{t('cli.dokkandb.canceled')}[/yellow]")
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
                console.print(f"[yellow]{t('cli.dokkandb.canceled')}[/yellow]")
                return

            if "ur" in selected_rarities:
                filter_ur = True
            if "lr" in selected_rarities:
                filter_lr = True

    except (KeyboardInterrupt, EOFError):
        console.print(f"\n[yellow]{t('cli.dokkandb.canceled')}[/yellow]")
        return
    except Exception as e:
        console.print(f"[bold red]{t('cli.unexpected_error', error=str(e))}[/bold red]")
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

    console.print(f"[bold green]{t('cli.link.selected_stage', name=stage_name)}[/bold green]")
    console.print(f"[dim]Runs: {runs_display} | {boost_label} | Rarity: {rarity_label}[/dim]")

    spirit_event = None
    if target_stage == "spirit_and_time":
        console.print(f"[cyan]{t('cli.dokkandb.fetching')}[/cyan]")
        spirit_event = engine.dokkandb.get_chamber_of_spirit_and_time()
        if spirit_event:
            status_text = (
                t("cli.link.status_open")
                if spirit_event.get("is_currently_open")
                else t("cli.link.status_rotating")
            )
            name = spirit_event.get("name", stage_name)
            console.print(
                f"[bold green]{t('cli.link.event_info', name=name, status=status_text)}[/bold green]"
            )

    engine.start_link_level_farm(
        runs=runs,
        target_event=spirit_event,
        use_boost=use_boost,
        filter_ur=filter_ur,
        filter_lr=filter_lr,
        target_stage=target_stage,
        stage_name=stage_name,
    )


def handle_stage_farm_interactive(
    engine: BotEngine,
    console: Console,
    args: list | None = None,
) -> None:
    """Handles stage auto-clearing command: repeats stage until stamina depleted or runs reached."""
    args = args or []
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

    console.print(
        f"[bold green]{t('cli.stage.summary', runs=runs_display, boost=boost_label, diff=diff_label)}[/bold green]"
    )
    console.print(f"[dim cyan]{t('cli.stage.hint_navigate')}[/dim cyan]")

    engine.start_stage_farm(
        runs=runs,
        use_boost=use_boost,
        preferred_difficulty=preferred_diff,
    )


def handle_challenge_interactive(
    engine: BotEngine,
    console: Console,
    args: list | None = None,
) -> None:
    """Interactive Challenge Event selector, Stage selector & Multi-mission Solver."""
    import questionary

    from dokkan_eza_link_farmer.ai.mission_solver import MissionBundler, MissionParser

    try:
        show_all = any(a.lower() in ("--all", "--closed", "-a") for a in (args or []))
        query_args = [
            a for a in (args or []) if a.lower() not in ("-y", "--yes", "--all", "--closed", "-a")
        ]
        auto_confirm = any(a.lower() in ("-y", "--yes") for a in (args or []))

        console.print(f"[dim]{t('cli.challenge.loading')}[/dim]")
        events = engine.dokkandb.get_challenge_events(active_only=not show_all)
        if not events:
            console.print(f"[yellow]{t('cli.challenge.no_events')}[/yellow]")
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
                console.print(f"[yellow]No events matched query '{query}'. Showing all.[/yellow]")

        selected_event = None
        if len(events) == 1:
            selected_event = events[0]
            clean_t = (selected_event.get("name") or "Unknown").replace("\n", " ").strip()
            console.print(
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
                    questionary.Choice(title=f"{status_tag} {clean_t} (ID: {e.get('id')})", value=e)
                )
            choices.append(questionary.Choice(title=t("cli.ai.opt_cancel"), value=None))

            try:
                selected_event = questionary.select(
                    t("cli.challenge.select_event"),
                    choices=choices,
                    use_arrow_keys=True,
                    use_jk_keys=False,
                ).ask()
            except (KeyboardInterrupt, EOFError):
                console.print(f"\n[yellow]{t('cli.dokkandb.canceled')}[/yellow]")
                return
            except Exception:
                console.print(f"\n[bold cyan]{t('cli.challenge.select_event')}[/bold cyan]")
                display_limit = min(len(events), 50)
                for idx, e in enumerate(events[:display_limit], 1):
                    clean_t = (e.get("name") or "").replace("\n", " ").strip()
                    if e.get("active") == "portal":
                        status_tag = "🌀"
                    elif e.get("is_currently_open"):
                        status_tag = "🟢"
                    else:
                        status_tag = "🔒"
                    console.print(
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
            console.print(f"[yellow]{t('cli.dokkandb.canceled')}[/yellow]")
            return

        ev_id = int(selected_event.get("id") or 0)
        ev_name = (selected_event.get("name") or "Challenge").replace("\n", " ").strip()

        # 2. Query event details for available stages
        details = engine.dokkandb.get_event_details(ev_id)
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
            except (KeyboardInterrupt, EOFError):
                console.print(f"\n[yellow]{t('cli.dokkandb.canceled')}[/yellow]")
                return
            except Exception:
                chosen_stage_dict = stage_choices[0].value if stage_choices else None

            if chosen_stage_dict is None:
                console.print(f"[yellow]{t('cli.dokkandb.canceled')}[/yellow]")
                return

            target_stage_num = chosen_stage_dict.get("stage_num", 1)
            target_stage_id = chosen_stage_dict.get("stage_id")
            target_stage_name = chosen_stage_dict.get("stage_name")

        # 3. Stage Boss Telemetry
        if target_stage_id and ev_id:
            boss_info = engine.dokkandb.get_stage_boss_info(ev_id, target_stage_id)
            if boss_info and boss_info.get("phases"):
                render_stage_boss_info(
                    boss_info,
                    target_stage_name=target_stage_name,
                    target_stage_num=target_stage_num,
                    console=console,
                )

        # 4. Missions Filtering & Optimization
        raw_missions = engine.dokkandb.get_challenge_missions(
            ev_name,
            stage_num=target_stage_num if target_stage_num > 0 else None,
            event_id=ev_id,
        )
        missions = [MissionParser.parse(m) for m in raw_missions]
        batches = MissionBundler.bundle_missions(
            missions, target_stage=target_stage_num if target_stage_num > 0 else None
        )

        saved = max(0, len(missions) - len(batches))
        render_mission_batches(
            batches,
            ev_name=ev_name,
            target_stage_num=target_stage_num,
            saved=saved,
            total_missions=len(missions),
            console=console,
        )

        start = auto_confirm
        if not start:
            try:
                start = questionary.confirm(
                    t("cli.challenge.start_confirm"),
                    default=True,
                ).ask()
            except (KeyboardInterrupt, EOFError):
                console.print(f"\n[yellow]{t('cli.dokkandb.canceled')}[/yellow]")
                return
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
            console.print(
                f"[bold green]{t('cli.challenge.starting', name=ev_name, stage=stage_str)}[/bold green]"
            )
            if not engine.adb.is_connected():
                try:
                    engine.connect()
                except Exception as e:
                    console.print(f"[yellow]Device connection: {e}[/yellow]")
            engine.start_challenge_farm(
                target_event=selected_event,
                stage_num=target_stage_num or 1,
                stage_id=target_stage_id,
                stage_name=target_stage_name,
            )
    except (KeyboardInterrupt, EOFError):
        console.print(f"\n[yellow]{t('cli.dokkandb.canceled')}[/yellow]")
    except Exception as e:
        console.print(f"[bold red]{t('cli.unexpected_error', error=str(e))}[/bold red]")


def handle_box_scan_interactive(
    engine: BotEngine,
    console: Console,
    args: list | None = None,
    log_file: str | None = None,
) -> None:
    """Interactive OCR Character Box Scanner to autonomously build config/box.json."""
    import questionary

    try:
        console.print("\n[bold cyan]📦 Autonomous Character Box Scanner (OCR)[/bold cyan]")
        console.print(
            "[dim]Scans your owned in-game cards, recognizes names & titles, and creates config/box.json.[/dim]\n"
        )

        # Check device connection
        if not engine.adb.is_connected():
            console.print("[yellow]Device not connected. Attempting auto-connection...[/yellow]")
            try:
                serial = engine.connect()
                console.print(f"[green]✓ Connected to {serial}![/green]")
            except Exception as e:
                console.print(f"[bold red]Cannot connect to device: {e}[/bold red]")
                return

        # Check existing box
        existing_ids = engine.dokkandb.get_user_box_card_ids()
        if existing_ids:
            console.print(
                f"[green]Found existing box database with {len(existing_ids)} cards indexed.[/green]"
            )
            console.print(
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
            except (KeyboardInterrupt, EOFError):
                console.print("\n[yellow]Box scan cancelled.[/yellow]")
                return
            except Exception:
                mode = 0

            if mode is None:
                console.print("[yellow]Scan cancelled.[/yellow]")
                return
            elif mode == -1:
                try:
                    lim_str = Prompt.ask("Enter maximum cards to scan", default="100").strip()
                    max_cards = int(lim_str) if lim_str.isdigit() else 100
                except (KeyboardInterrupt, EOFError):
                    console.print("\n[yellow]Box scan cancelled.[/yellow]")
                    return
            elif mode > 0:
                max_cards = mode

        target_log = custom_log if custom_log is not None else DEFAULT_BOX_SCAN_LOG_PATH
        limit_text = f"up to {max_cards} cards" if max_cards else "all cards"
        console.print(f"[bold green]Starting autonomous box scanner ({limit_text})...[/bold green]")
        console.print(f"[dim]Debug log saved to: {target_log}[/dim]")
        console.print(
            "[dim]Please ensure Dokkan Battle is showing the 'Character List' (Box) screen.[/dim]\n"
        )

        engine.start_box_scanner(
            output_file=DEFAULT_USER_BOX_PATH,
            max_cards_to_scan=max_cards,
            log_file=target_log,
        )

    except (KeyboardInterrupt, EOFError):
        console.print("\n[yellow]Box scan cancelled.[/yellow]")
    except Exception as e:
        console.print(f"[bold red]Unexpected error in box scanner: {e}[/bold red]")


def select_challenge_boss_stage(
    engine: BotEngine,
    console: Console,
    active_only: bool = True,
) -> Any:
    """Interactively prompts the user to select an endgame stage from presets or DokkanDB."""
    try:
        import questionary

        from dokkan_eza_link_farmer.ai.boss_catalog import get_boss_stage, list_boss_stages
        from dokkan_eza_link_farmer.ai.models import BossStage

        console.print(f"[dim]{t('cli.challenge.loading')}[/dim]")
        events = engine.dokkandb.get_challenge_events(active_only=active_only)

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
        except (KeyboardInterrupt, EOFError):
            console.print(f"\n[yellow]{t('cli.dokkandb.canceled')}[/yellow]")
            return None
        except Exception:
            console.print(f"\n[bold cyan]{t('cli.challenge.select_event')}[/bold cyan]")
            console.print(
                "  [green] 1[/green]. ⭐ Classic Catalog Bosses (Broly, Cell Max, Beast Gohan...)"
            )
            for idx, e in enumerate(events[:25], 2):
                clean_t = (e.get("name") or "").replace("\n", " ").strip()
                console.print(f"  [green]{idx:2d}[/green]. {clean_t} (ID: {e.get('id')})")
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
            except (EOFError, KeyboardInterrupt):
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
            try:
                chosen = questionary.select("Select target boss stage:", choices=st_choices).ask()
            except (KeyboardInterrupt, EOFError):
                console.print(f"\n[yellow]{t('cli.dokkandb.canceled')}[/yellow]")
                return None
            except Exception:
                chosen = None
            if chosen:
                return get_boss_stage(chosen)
            return None

        # Live DokkanDB Challenge Event
        ev_id = int(selected.get("id") or 0)
        ev_name = (selected.get("name") or "Challenge").replace("\n", " ").strip()

        details = engine.dokkandb.get_event_details(ev_id)
        quests = details.get("quests", []) if details else []
        quests.sort(key=lambda q: int(q.get("quest_id", 0)))

        if not quests:
            console.print(f"[yellow]No stages found for event '{ev_name}' (ID: {ev_id}).[/yellow]")
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

        try:
            chosen_stage = questionary.select(
                t("cli.challenge.select_stage"),
                choices=stage_choices,
                use_arrow_keys=True,
                use_jk_keys=False,
            ).ask()
        except (KeyboardInterrupt, EOFError):
            console.print(f"\n[yellow]{t('cli.dokkandb.canceled')}[/yellow]")
            return None
        except Exception:
            chosen_stage = stage_choices[0].value if stage_choices else None

        if not chosen_stage:
            return None

        target_stage_id = chosen_stage.get("stage_id")
        if not target_stage_id:
            console.print("[yellow]Invalid stage ID selected.[/yellow]")
            return None

        boss_info = engine.dokkandb.get_stage_boss_info(ev_id, target_stage_id)
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
    except (KeyboardInterrupt, EOFError):
        console.print(f"\n[yellow]{t('cli.dokkandb.canceled')}[/yellow]")
        return None
    except Exception as e:
        console.print(f"[bold red]{t('cli.unexpected_error', error=str(e))}[/bold red]")
        return None


def prompt_stage_missions(stage: Any, dokkandb: Any, console: Console) -> Any | None:
    """Interactively prompts the user via checkbox to target specific stage missions."""
    try:
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
            m = re.search(r"Stage\s*(\d+)", st_name, re.IGNORECASE)
            if m:
                stage_num = int(m.group(1))

        try:
            with console.status("[dim]Fetching stage missions from DokkanDB...[/dim]"):
                raw_missions = dokkandb.get_event_missions(ev_id)
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
        except Exception:
            return None

        if not selected:
            console.print(
                "[dim]No specific mission selected. Building standard optimal team...[/dim]"
            )
            return None

        batch = MissionBundler.create_batch_from_selection(selected)
        console.print(
            Panel.fit(
                f"[bold green]🎯 Mission Targeting Enabled:[/bold green] [bold yellow]{batch.summary}[/bold yellow]\n"
                f"[dim]The AI Solver will strictly constrain team synthesis to satisfy these mission conditions.[/dim]",
                border_style="green",
            )
        )
        return batch
    except (KeyboardInterrupt, EOFError):
        return None
    except Exception as e:
        logger.debug(f"Unexpected error in prompt_stage_missions: {e}")
        return None


def ai_find_partners(engine: BotEngine, console: Console, query: str = "") -> None:
    """Finds top linking partners for a card using DokkanDB and synergy scoring."""
    try:
        import questionary

        from dokkan_eza_link_farmer.ai.models import DokkanCard

        if not query:
            try:
                query = questionary.text(t("cli.ai.query_prompt")).ask()
            except (KeyboardInterrupt, EOFError):
                console.print(f"\n[yellow]{t('cli.dokkandb.canceled')}[/yellow]")
                return
            if not query:
                return

        console.print(f"[dim]{t('cli.ai.searching')}[/dim]")
        cards = engine.dokkandb.search_cards(query, limit=12)
        if not cards:
            console.print(f"[yellow]{t('cli.ai.no_cards_found', query=query)}[/yellow]")
            return

        choices = [
            questionary.Choice(
                title=f"{c.get('name')} - {c.get('subname', '')} (ID: {c.get('id')})",
                value=c.get("id"),
            )
            for c in cards
        ]
        choices.append(questionary.Choice(title=t("cli.ai.opt_cancel"), value=None))

        try:
            chosen_id = questionary.select(
                t("cli.ai.select_leader"),
                choices=choices,
            ).ask()
        except (KeyboardInterrupt, EOFError):
            console.print(f"\n[yellow]{t('cli.dokkandb.canceled')}[/yellow]")
            return

        if not chosen_id:
            return

        card_data = engine.dokkandb.get_card(int(chosen_id))
        if not card_data:
            console.print("[red]Could not retrieve card details.[/red]")
            return

        target_card = DokkanCard.from_dokkandb(card_data)

        # Retrieve catalog to find best partners
        catalog = engine.dokkandb.get_cards_catalog()
        candidate_pool: list[DokkanCard] = []
        for raw in catalog[:300]:
            if int(raw.get("id") or 0) == target_card.id:
                continue
            candidate_pool.append(DokkanCard.from_dokkandb(raw))

        partners = engine.team_builder.find_best_partners_for_card(
            target_card, candidate_pool, top_k=7
        )

        render_linking_partners(target_card, partners, console=console)
    except (KeyboardInterrupt, EOFError):
        console.print(f"\n[yellow]{t('cli.dokkandb.canceled')}[/yellow]")
    except Exception as e:
        console.print(f"[bold red]{t('cli.unexpected_error', error=str(e))}[/bold red]")


def ai_build_team_for_stage(
    engine: BotEngine,
    console: Console,
    stage: Any,
    on_render: Callable[..., Any] | None = None,
) -> None:
    """Solves and optimizes the best team against a specific Challenge BossStage using the AI Teambuilder."""
    try:
        from dokkan_eza_link_farmer.ai.models import DokkanCard

        render_ai_stage_synthesis_header(stage, console=console)

        mission_batch = prompt_stage_missions(stage, engine.dokkandb, console)

        candidate_pool = engine.team_builder.load_user_box()
        if len(candidate_pool) < 6:
            console.print("[dim]User box has < 6 cards, loading DokkanDB catalog fallback...[/dim]")
            catalog = engine.dokkandb.get_cards_catalog()
            candidate_pool = [DokkanCard.from_dokkandb(raw) for raw in catalog[:400]]

        shortlist = None
        try:
            with console.status(
                "[bold cyan]Synthesizing optimal team with AI Solver & Advisor...", spinner="dots"
            ):
                rec, shortlist = engine.team_builder.select_best_team_for_boss(
                    candidate_pool=candidate_pool,
                    boss_stage=stage,
                    language=get_language(),
                    mission_batch=mission_batch,
                )
        except Exception as e:
            console.print(
                f"[yellow]Algorithmic solver notice: {e}. Building best synergy plan...[/yellow]"
            )
            rec = engine.team_builder.build_team_plan(
                candidate_pool[:6],
                language=get_language(),
            )

        render_fn = on_render or render_team_presentation
        render_fn(
            rec,
            title=f"🔄 AI Recommended Tactical Rotations for {stage.stage_name}",
            shortlist=shortlist,
        )
    except (KeyboardInterrupt, EOFError):
        console.print(f"\n[yellow]{t('cli.dokkandb.canceled')}[/yellow]")
    except Exception as e:
        console.print(f"[bold red]{t('cli.unexpected_error', error=str(e))}[/bold red]")


def ai_build_team(
    engine: BotEngine,
    console: Console,
    query: str = "",
    on_build_for_stage: Callable[..., Any] | None = None,
    on_render: Callable[..., Any] | None = None,
    on_select_stage: Callable[..., Any] | None = None,
) -> None:
    """Builds an optimized team and gets Qwen/DeepSeek-R1 tactical breakdown."""
    try:
        import questionary

        from dokkan_eza_link_farmer.ai.models import DokkanCard

        if not query:
            try:
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
            except (KeyboardInterrupt, EOFError):
                console.print(f"\n[yellow]{t('cli.dokkandb.canceled')}[/yellow]")
                return

            if not build_mode:
                return
            if build_mode == "challenge":
                select_fn = on_select_stage or (
                    lambda: select_challenge_boss_stage(engine, console)
                )
                stage = select_fn()
                if stage:
                    stage_build_fn = on_build_for_stage or (
                        lambda st: ai_build_team_for_stage(engine, console, st, on_render=on_render)
                    )
                    stage_build_fn(stage)
                return

            try:
                query = questionary.text(t("cli.ai.query_prompt")).ask()
            except (KeyboardInterrupt, EOFError):
                console.print(f"\n[yellow]{t('cli.dokkandb.canceled')}[/yellow]")
                return

            if not query:
                return

        console.print(f"[dim]{t('cli.ai.searching')}[/dim]")
        cards = engine.dokkandb.search_cards(query, limit=10)
        if not cards:
            console.print(f"[yellow]{t('cli.ai.no_cards_found', query=query)}[/yellow]")
            return

        choices = [
            questionary.Choice(
                title=f"{c.get('name')} - {c.get('subname', '')} (ID: {c.get('id')})",
                value=c.get("id"),
            )
            for c in cards
        ]
        choices.append(questionary.Choice(title=t("cli.ai.opt_cancel"), value=None))

        try:
            leader_id = questionary.select(
                t("cli.ai.select_leader"),
                choices=choices,
            ).ask()
        except (KeyboardInterrupt, EOFError):
            console.print(f"\n[yellow]{t('cli.dokkandb.canceled')}[/yellow]")
            return

        if not leader_id:
            return

        leader_data = engine.dokkandb.get_card(int(leader_id))
        if not leader_data:
            console.print("[red]Could not load card details.[/red]")
            return

        leader_card = DokkanCard.from_dokkandb(leader_data)

        # Build team pool around leader
        catalog = engine.dokkandb.get_cards_catalog()
        candidate_pool = [
            DokkanCard.from_dokkandb(raw)
            for raw in catalog[:400]
            if int(raw.get("id") or 0) != leader_card.id
        ]

        top_partners = engine.team_builder.find_best_partners_for_card(
            leader_card, candidate_pool, top_k=5
        )
        sub_units = [p[0] for p in top_partners]
        while len(sub_units) < 5 and candidate_pool:
            sub_units.append(candidate_pool.pop(0))

        team_cards = [leader_card] + sub_units[:5]

        rec = engine.team_builder.build_team_plan(
            team_cards,
            language=get_language(),
        )

        render_fn = on_render or render_team_presentation
        render_fn(
            rec,
            title="🔄 AI Recommended Tactical Rotations",
        )
    except (KeyboardInterrupt, EOFError):
        console.print(f"\n[yellow]{t('cli.dokkandb.canceled')}[/yellow]")
    except Exception as e:
        console.print(f"[bold red]{t('cli.unexpected_error', error=str(e))}[/bold red]")


def ai_configure_model(
    engine: BotEngine,
    console: Console,
    on_status: Callable[[], Any] | None = None,
) -> None:
    """Configures the single universal model qwen3.5:4b."""
    from dokkan_eza_link_farmer.ai.client import DokkanAIClient
    from dokkan_eza_link_farmer.ai.models import AIConfig, SupportedAIModel
    from dokkan_eza_link_farmer.ai.team_builder import TeamBuilder

    model_name = SupportedAIModel.QWEN_3_5_4B.value
    family = "qwen"

    if "ai" not in engine.config:
        engine.config["ai"] = {}

    engine.config["ai"]["enabled"] = True
    engine.config["ai"]["model_family"] = family
    engine.config["ai"]["model_name"] = model_name
    engine.save_config()

    engine.ai_config = AIConfig.from_dict(engine.config.get("ai"))
    engine.ai_client = DokkanAIClient(engine.ai_config)
    engine.team_builder = TeamBuilder(dokkandb=engine.dokkandb, ai_client=engine.ai_client)

    console.print(
        f"[bold green]✓ Modello AI impostato su {model_name} (Ottimizzato 100% GPU / zero-latency)[/bold green]"
    )
    if on_status:
        on_status()
    else:
        render_ai_status(engine.ai_config, engine.ai_client.is_available(), console)


def handle_ai_interactive(
    engine: BotEngine,
    console: Console,
    args: list | None = None,
    on_status: Callable[[], Any] | None = None,
    on_partner: Callable[[str], Any] | None = None,
    on_build: Callable[[str], Any] | None = None,
    on_config: Callable[[], Any] | None = None,
    on_endgame: Callable[..., Any] | None = None,
    on_select_stage: Callable[[], Any] | None = None,
) -> None:
    """Interactive AI Team Builder & Tactical Advisor (Qwen / DeepSeek-R1)."""
    try:
        import questionary

        args = args or []
        sub = (args[0].lower() if args else "").strip()
        if sub in ("status", "check"):
            if on_status:
                on_status()
            else:
                render_ai_status(engine.ai_config, engine.ai_client.is_available(), console)
            return
        if sub in ("partner", "link", "links"):
            query = " ".join(args[1:]) if len(args) > 1 else ""
            if on_partner:
                on_partner(query)
            else:
                ai_find_partners(engine, console, query=query)
            return
        if sub in ("build", "team"):
            query = " ".join(args[1:]) if len(args) > 1 else ""
            if on_build:
                on_build(query)
            else:
                ai_build_team(engine, console, query=query)
            return
        if sub in ("config", "switch"):
            if on_config:
                on_config()
            else:
                ai_configure_model(engine, console, on_status=on_status)
            return
        if sub in ("run", "endgame", "ai-run"):
            stage_target = args[1] if len(args) > 1 else None
            if stage_target:
                if on_endgame:
                    on_endgame(stage_target)
            else:
                stage = (
                    on_select_stage()
                    if on_select_stage
                    else select_challenge_boss_stage(engine, console)
                )
                if stage and on_endgame:
                    on_endgame(stage)
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
            if on_build:
                on_build("")
            else:
                ai_build_team(engine, console)
        elif action == "endgame":
            stage = (
                on_select_stage()
                if on_select_stage
                else select_challenge_boss_stage(engine, console)
            )
            if stage and on_endgame:
                on_endgame(stage)
        elif action == "partner":
            if on_partner:
                on_partner("")
            else:
                ai_find_partners(engine, console)
        elif action == "status":
            if on_status:
                on_status()
            else:
                render_ai_status(engine.ai_config, engine.ai_client.is_available(), console)
        elif action == "config":
            if on_config:
                on_config()
            else:
                ai_configure_model(engine, console, on_status=on_status)
    except (KeyboardInterrupt, EOFError):
        console.print(f"\n[yellow]{t('cli.dokkandb.canceled')}[/yellow]")
    except Exception as e:
        console.print(f"[bold red]{t('cli.unexpected_error', error=str(e))}[/bold red]")
