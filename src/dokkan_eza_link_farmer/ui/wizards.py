from __future__ import annotations

import contextlib
import logging
import os
import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import questionary
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

if TYPE_CHECKING:
    from dokkan_eza_link_farmer.core.bot_engine import BotEngine

from dokkan_eza_link_farmer.ai.boss_models import (
    DIFFICULTY_NAMES,
    infer_difficulty_from_stage_id,
    parse_difficulty_code,
)
from dokkan_eza_link_farmer.core.i18n import get_language, t
from dokkan_eza_link_farmer.core.system_tools import AppPaths
from dokkan_eza_link_farmer.ui.briefing import (
    render_ai_stage_synthesis_header,
    render_linking_partners,
    render_mission_batches,
    render_stage_boss_info,
    render_team_presentation,
)
from dokkan_eza_link_farmer.ui.panels import render_ai_status

logger = logging.getLogger(__name__)

STAGE_NAMES = {
    "area_39_3": "Area 39 Stage 3: Great stamina-friendly option (also drops green gems) | 5 fights",
    "area_35_1": "Area 35 Stage 1: Good stamina-friendly option (also drops blue gems) | 4 fights",
}


def _resolve_link_stage(val: str) -> tuple[str, str]:
    """Resolves link stage identifier into (target_stage, stage_name)."""
    low = val.lower().strip()
    if low in ("39-3", "39_3", "393", "area_39_3"):
        return "area_39_3", STAGE_NAMES["area_39_3"]
    if low in ("35-1", "35_1", "351", "area_35_1"):
        return "area_35_1", STAGE_NAMES["area_35_1"]
    if low in ("spirit", "spirit_and_time", "event"):
        return "spirit_and_time", t("cli.link.stage_spirit")
    m = re.match(r"^(?:area_)?(\d+)[-_](\d+)$", low)
    if m:
        return f"area_{m.group(1)}_{m.group(2)}", f"Area {m.group(1)} Stage {m.group(2)}"
    return val, f"Stage {val}"


@contextlib.contextmanager
def _ui_boundary(console: Console, cancel_msg: str | None = None):
    """Context manager handling user cancellations and terminal errors uniformly."""
    try:
        yield
    except (KeyboardInterrupt, EOFError):
        console.print(f"\n[yellow]{cancel_msg or t('cli.dokkandb.canceled')}[/yellow]")
    except Exception as e:
        console.print(f"[bold red]{t('cli.unexpected_error', error=str(e))}[/bold red]")


def _ask_target_level(default_lvl: int) -> int | None:
    """Prompts for target EZA climbing level."""
    lvl_str = questionary.text(
        t("cli.dokkandb.target_level_prompt", default=default_lvl),
        default=str(default_lvl),
    ).ask()
    if lvl_str is None:
        return None
    return int(lvl_str) if lvl_str.isdigit() else default_lvl


def _build_event_choices(events: list[dict[str, Any]], limit: int = 50) -> list[Any]:
    """Builds questionary event choices with open/closed/portal indicator tags."""
    choices: list[Any] = []
    for e in events[:limit]:
        clean_t = (e.get("name") or "Unknown").replace("\n", " ").strip()
        status_tag = (
            "🌀 [PORTAL]"
            if e.get("active") == "portal"
            else ("🟢 [OPEN]" if e.get("is_currently_open") else "🔒 [CLOSED]")
        )
        choices.append(
            questionary.Choice(title=f"{status_tag} {clean_t} (ID: {e.get('id')})", value=e)
        )
    choices.append(questionary.Choice(title=t("cli.ai.opt_cancel"), value=None))
    return choices


def _extract_stage_difficulty(s: dict[str, Any] | None) -> int:
    """Extracts integer difficulty code from a stage dict (0..5), inferring from stage_id if needed."""
    if not s:
        return 1
    diff = s.get("difficulty")
    if diff is not None:
        try:
            return int(diff)
        except (ValueError, TypeError):
            pass
    inferred = infer_difficulty_from_stage_id(s.get("stage_id"))
    return inferred if inferred is not None else 1


def _build_quest_stage_choices(
    quests: list[dict[str, Any]], include_all: bool = False
) -> list[Any]:
    """Builds questionary stage choices from event quests with difficulty indicators."""
    choices: list[Any] = []
    for idx, q in enumerate(quests, 1):
        q_name = q.get("quest_name") or f"Stage {idx}"
        stages_arr = q.get("stages", [])
        diff_names = [
            DIFFICULTY_NAMES.get(_extract_stage_difficulty(s), f"D{_extract_stage_difficulty(s)}")
            for s in stages_arr
        ]
        diff_summary = f" [{', '.join(diff_names)}]" if diff_names else ""
        sorted_stages = sorted(stages_arr, key=_extract_stage_difficulty, reverse=True)
        st_id = sorted_stages[0].get("stage_id") if sorted_stages else None
        title = f"Stage {idx}: {q_name}{diff_summary}" + (
            f" (ID: {st_id})" if st_id and not diff_summary else ""
        )
        choices.append(
            questionary.Choice(
                title=title,
                value={
                    "stage_num": idx,
                    "stage_id": st_id,
                    "stage_name": q_name,
                    "stages": stages_arr,
                    "quest": q,
                },
            )
        )
    if include_all:
        choices.append(
            questionary.Choice(
                title=t("cli.challenge.all_stages"),
                value={
                    "stage_num": 0,
                    "stage_id": None,
                    "stage_name": "All Stages",
                    "stages": [],
                },
            )
        )
    choices.append(questionary.Choice(title=t("cli.ai.opt_cancel"), value=None))
    return choices


def _build_difficulty_choices(stages: list[dict[str, Any]]) -> list[Any]:
    """Builds questionary difficulty choices for a selected quest's stages."""
    sorted_stages = sorted(stages, key=_extract_stage_difficulty, reverse=True)
    choices: list[Any] = []
    max_diff = _extract_stage_difficulty(sorted_stages[0]) if sorted_stages else 0
    for s in sorted_stages:
        diff_val = _extract_stage_difficulty(s)
        diff_label = DIFFICULTY_NAMES.get(diff_val, f"Difficulty {diff_val}")
        act = s.get("act", 0)
        s_id = s.get("stage_id")
        prefix = "⭐ " if diff_val == max_diff else ""
        sta_str = f" (STA: {act})" if act else ""
        id_str = f" (ID: {s_id})" if s_id else ""
        title = f"{prefix}{diff_label}{sta_str}{id_str}"
        choices.append(questionary.Choice(title=title, value=s))
    choices.append(questionary.Choice(title=t("cli.ai.opt_cancel"), value=None))
    return choices


def _resolve_stage_by_diff(stages: list[dict[str, Any]], diff_spec: Any) -> dict[str, Any] | None:
    """Matches a stage by difficulty code/name, defaulting to highest difficulty."""
    if not stages:
        return None
    if diff_spec is None:
        return max(stages, key=_extract_stage_difficulty)
    code = parse_difficulty_code(diff_spec)
    if code is not None:
        for s in stages:
            if _extract_stage_difficulty(s) == code:
                return s
    diff_str = str(diff_spec).lower()
    for s in stages:
        d_val = _extract_stage_difficulty(s)
        d_name = DIFFICULTY_NAMES.get(d_val, "").lower()
        if diff_str in d_name or d_name in diff_str:
            return s
    return max(stages, key=_extract_stage_difficulty)


def handle_eza_interactive(engine: BotEngine, console: Console, args: list | None = None) -> None:
    """Handles EZA command: declarative flag execution or interactive DokkanDB selection."""
    args = list(args) if args else []
    farming_cfg = (
        engine.config.get("farming", {})
        if isinstance(getattr(engine, "config", None), dict)
        else {}
    )
    raw_lvl = farming_cfg.get("eza_target_level", 999) if isinstance(farming_cfg, dict) else 999
    default_lvl = raw_lvl if isinstance(raw_lvl, int) else 999

    # 1. Declarative CLI flag priority: zero interaction if target level is provided
    target_lvl: int | None = None
    if any(str(a).lower() in ("--eza", "-e") for a in args) and not any(
        str(a).isdigit() for a in args
    ):
        target_lvl = default_lvl
    for idx, arg in enumerate(args):
        low = str(arg).lower()
        if (
            low in ("--eza", "-e", "--level", "-l")
            and idx + 1 < len(args)
            and str(args[idx + 1]).isdigit()
        ):
            target_lvl = int(args[idx + 1])
            break
        elif (low.startswith("--eza=") or low.startswith("--level=")) and (
            v := low.split("=", 1)[1]
        ).isdigit():
            target_lvl = int(v)
            break
        elif low in ("auto", "classic"):
            target_lvl = (
                int(args[idx + 1])
                if idx + 1 < len(args) and str(args[idx + 1]).isdigit()
                else default_lvl
            )
            break
        elif str(arg).isdigit():
            target_lvl = int(arg)
            break

    if target_lvl is not None:
        console.print(f"[bold green]Starting EZA farming up to level {target_lvl}...[/bold green]")
        engine.start_eza_farm(target_level=target_lvl)
        return

    # 2. Interactive questionary wizard (only triggered when executed without target arguments)
    with _ui_boundary(console):
        choices = [
            questionary.Choice(title=t("cli.dokkandb.opt_select"), value="select"),
            questionary.Choice(title=t("cli.dokkandb.opt_auto"), value="auto"),
            questionary.Choice(title=t("cli.dokkandb.opt_cancel"), value="cancel"),
        ]
        action = questionary.select(t("cli.dokkandb.menu_title"), choices=choices).ask()
        if not action or action == "cancel":
            console.print(f"[yellow]{t('cli.dokkandb.canceled')}[/yellow]")
            return

        if action == "auto":
            lvl = _ask_target_level(default_lvl)
            if lvl is None:
                console.print(f"[yellow]{t('cli.dokkandb.canceled')}[/yellow]")
                return
            engine.start_eza_farm(target_level=lvl)
            return

        if action == "select":
            console.print(f"[cyan]{t('cli.dokkandb.fetching')}[/cyan]")
            events = engine.dokkandb.get_zbattles()
            if not events:
                console.print(
                    f"[red]{t('cli.dokkandb.fetch_error', error='No events returned')}[/red]"
                )
                return

            events.sort(key=lambda x: (not x.get("is_currently_open", False), -int(x.get("id", 0))))
            choices_eza = [
                questionary.Choice(
                    title=f"{'🟢 [OPEN]' if e.get('is_currently_open') else '🔑 [PORTAL]'} {e.get('name', 'Unknown EZA')} (ID: {e.get('id', '?')})",
                    value=e,
                )
                for e in events
            ]
            choices_eza.append(questionary.Choice(title=t("cli.dokkandb.opt_cancel"), value=None))

            chosen = questionary.select(
                t("cli.dokkandb.select_prompt"),
                choices=choices_eza,
                use_search_filter=True,
                use_arrow_keys=True,
                use_jk_keys=False,
            ).ask()
            if not chosen:
                console.print(f"[yellow]{t('cli.dokkandb.canceled')}[/yellow]")
                return

            lvl = _ask_target_level(default_lvl)
            if lvl is None:
                console.print(f"[yellow]{t('cli.dokkandb.canceled')}[/yellow]")
                return

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
                f"[bold green]{t('cli.dokkandb.selected_summary', name=chosen_name, level=lvl)}[/bold green]"
            )
            engine.start_eza_farm(target_level=lvl, target_eza=chosen)


def handle_link_interactive(engine: BotEngine, console: Console, args: list | None = None) -> None:
    """Handles Link Leveling command: declarative flag execution or interactive wizard."""
    args = list(args) if args else []
    runs: int | None = None
    use_boost: bool | None = None
    filter_ur = False
    filter_lr = False
    target_stage: str | None = None
    stage_name: str | None = None
    has_target_args = False

    skip_next = False
    for idx, arg in enumerate(args):
        if skip_next:
            skip_next = False
            continue
        low = str(arg).lower()
        if low in ("--link", "link"):
            has_target_args = True
        elif low in ("--ur", "-ur", "ur"):
            filter_ur = has_target_args = True
        elif low in ("--lr", "-lr", "lr"):
            filter_lr = has_target_args = True
        elif low in ("boost", "--boost", "-b"):
            use_boost = has_target_args = True
        elif low in ("noboost", "no-boost", "--no-boost", "-nb"):
            use_boost = False
            has_target_args = True
        elif low in ("--runs", "-r") and idx + 1 < len(args) and str(args[idx + 1]).isdigit():
            runs, has_target_args, skip_next = int(args[idx + 1]), True, True
        elif low.startswith("--runs=") and (v := low.split("=", 1)[1]).isdigit():
            runs, has_target_args = int(v), True
        elif low in ("--stage", "-s") and idx + 1 < len(args):
            target_stage, stage_name = _resolve_link_stage(str(args[idx + 1]))
            has_target_args, skip_next = True, True
        elif low.startswith("--stage="):
            target_stage, stage_name = _resolve_link_stage(low.split("=", 1)[1])
            has_target_args = True
        elif str(arg).isdigit() and int(arg) > 0:
            runs, has_target_args = int(arg), True
        elif not low.startswith("-"):
            target_stage, stage_name = _resolve_link_stage(low)
            has_target_args = True

    # Interactive questionary wizard only if NO target arguments provided
    if not has_target_args:
        with _ui_boundary(console):
            stage_choices = [
                questionary.Choice(title=STAGE_NAMES["area_39_3"], value="area_39_3"),
                questionary.Choice(title=STAGE_NAMES["area_35_1"], value="area_35_1"),
                questionary.Choice(title=t("cli.link.stage_spirit"), value="spirit_and_time"),
                questionary.Choice(title=t("cli.dokkandb.opt_cancel"), value="cancel"),
            ]
            selected_stage = questionary.select(
                t("cli.link.menu_title"), choices=stage_choices
            ).ask()
            if not selected_stage or selected_stage == "cancel":
                console.print(f"[yellow]{t('cli.dokkandb.canceled')}[/yellow]")
                return

            target_stage = str(selected_stage)
            stage_name = STAGE_NAMES.get(target_stage, t("cli.link.stage_spirit"))

            runs_str = questionary.text(t("cli.link.runs_prompt"), default="").ask()
            if runs_str is None:
                console.print(f"[yellow]{t('cli.dokkandb.canceled')}[/yellow]")
                return
            if runs_str.isdigit():
                runs = int(runs_str)

            rarity_choices = [
                questionary.Choice(title="UR (Ultra Rare)", value="ur"),
                questionary.Choice(title="LR (Legendary Rare)", value="lr"),
            ]
            selected_rarities = questionary.checkbox(
                t("cli.link.rarity_prompt"), choices=rarity_choices
            ).ask()
            if selected_rarities is None:
                console.print(f"[yellow]{t('cli.dokkandb.canceled')}[/yellow]")
                return
            filter_ur = "ur" in selected_rarities
            filter_lr = "lr" in selected_rarities
        if target_stage is None:
            return

    if not target_stage:
        target_stage, stage_name = "area_39_3", STAGE_NAMES["area_39_3"]

    boost_label = (
        t("cli.link.boost_on")
        if use_boost is True
        else (t("cli.link.boost_off") if use_boost is False else t("cli.link.boost_config"))
    )
    runs_display = f"{runs} runs" if runs is not None else t("cli.link.runs_unlimited")
    rarity_tags = [r for r, cond in [("UR", filter_ur), ("LR", filter_lr)] if cond]
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
            console.print(
                f"[bold green]{t('cli.link.event_info', name=spirit_event.get('name', stage_name), status=status_text)}[/bold green]"
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
    engine: BotEngine, console: Console, args: list | None = None
) -> None:
    """Handles stage auto-clearing command: repeats stage until stamina depleted or runs reached."""
    args = list(args) if args else []
    runs: int | None = None
    use_boost: bool | None = None
    preferred_diff: str | None = None

    skip_next = False
    for idx, arg in enumerate(args):
        if skip_next:
            skip_next = False
            continue
        low = str(arg).lower()
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
        elif (
            low in ("--stage", "-s", "--runs", "-r")
            and idx + 1 < len(args)
            and (v := str(args[idx + 1])).isdigit()
            and int(v) > 0
        ):
            runs, skip_next = int(v), True
        elif (
            (low.startswith("--stage=") or low.startswith("--runs="))
            and (v := low.split("=", 1)[1]).isdigit()
            and int(v) > 0
        ):
            runs = int(v)
        elif str(arg).isdigit() and int(arg) > 0:
            runs = int(arg)

    runs_display = f"{runs} runs" if runs is not None else t("cli.stage.runs_unlimited")
    boost_label = (
        t("cli.stage.boost_on")
        if use_boost is True
        else (t("cli.stage.boost_off") if use_boost is False else t("cli.stage.boost_default"))
    )
    diff_label = preferred_diff.upper() if preferred_diff else t("cli.stage.diff_auto")

    console.print(
        f"[bold green]{t('cli.stage.summary', runs=runs_display, boost=boost_label, diff=diff_label)}[/bold green]"
    )
    console.print(f"[dim cyan]{t('cli.stage.hint_navigate')}[/dim cyan]")

    engine.start_stage_farm(runs=runs, use_boost=use_boost, preferred_difficulty=preferred_diff)


def handle_challenge_interactive(
    engine: BotEngine, console: Console, args: list | None = None
) -> None:
    """Interactive Challenge Event selector, Stage selector & Multi-mission Solver."""
    from dokkan_eza_link_farmer.ai.mission_solver import MissionBundler, MissionParser

    with _ui_boundary(console):
        args_list = list(args) if args else []
        show_all = any(str(a).lower() in ("--all", "--closed", "-a") for a in args_list)
        raw_query_args = [
            a.split("=", 1)[1] if str(a).lower().startswith(("--challenge=", "-c=")) else a
            for a in args_list
            if str(a).lower() not in ("-y", "--yes", "--all", "--closed", "-a", "--challenge", "-c")
            and not str(a).lower().startswith(("--challenge=", "-c="))
        ]

        explicit_stage: int | None = None
        explicit_diff: str | int | None = None
        query_args: list[str] = []
        skip_next = False
        for idx, a in enumerate(raw_query_args):
            if skip_next:
                skip_next = False
                continue
            low_a = str(a).lower()
            if low_a in ("--stage", "-s") and idx + 1 < len(raw_query_args):
                val_str = str(raw_query_args[idx + 1])
                if val_str.isdigit():
                    explicit_stage = int(val_str)
                    skip_next = True
                    continue
            elif low_a.startswith(("--stage=", "-s=")):
                val_str = low_a.split("=", 1)[1]
                if val_str.isdigit():
                    explicit_stage = int(val_str)
                    continue
            elif low_a in ("--difficulty", "--diff", "-d") and idx + 1 < len(raw_query_args):
                explicit_diff = str(raw_query_args[idx + 1]).lower()
                skip_next = True
                continue
            elif low_a.startswith(("--difficulty=", "--diff=", "-d=")):
                explicit_diff = low_a.split("=", 1)[1].lower()
                continue
            elif low_a in (
                "--super3",
                "--super2",
                "--super",
                "--zhard",
                "--z-hard",
                "--hard",
                "--normal",
            ):
                explicit_diff = low_a.lstrip("-")
                continue
            query_args.append(str(a))

        if explicit_stage is None and len(query_args) >= 2 and str(query_args[-1]).isdigit():
            explicit_stage = int(query_args[-1])
            query_args = query_args[:-1]

        auto_confirm = any(str(a).lower() in ("-y", "--yes") for a in args_list) or bool(query_args)

        console.print(f"[dim]{t('cli.challenge.loading')}[/dim]")
        events = engine.dokkandb.get_challenge_events(active_only=not show_all)
        if not events:
            console.print(f"[yellow]{t('cli.challenge.no_events')}[/yellow]")
            return

        query = " ".join(str(a) for a in query_args).strip().lower()
        if query:
            exact = [
                e
                for e in events
                if query == str(e.get("id")) or query == (e.get("name") or "").lower().strip()
            ]
            if exact:
                events = exact
            else:
                filtered = [e for e in events if query in (e.get("name") or "").lower()]
                if filtered:
                    events = filtered
                else:
                    console.print(
                        f"[yellow]No events matched query '{query}'. Showing all.[/yellow]"
                    )

        selected_event = None
        if len(events) == 1:
            selected_event = events[0]
            clean_t = (selected_event.get("name") or "Unknown").replace("\n", " ").strip()
            console.print(
                f"[bold green]Selected: {clean_t} (ID: {selected_event.get('id')})[/bold green]"
            )
        else:
            selected_event = questionary.select(
                t("cli.challenge.select_event"),
                choices=_build_event_choices(events, limit=100),
                use_arrow_keys=True,
                use_jk_keys=False,
            ).ask()

        if not selected_event:
            console.print(f"[yellow]{t('cli.dokkandb.canceled')}[/yellow]")
            return

        ev_id = int(selected_event.get("id") or 0)
        ev_name = (selected_event.get("name") or "Challenge").replace("\n", " ").strip()
        details = engine.dokkandb.get_event_details(ev_id)
        quests = details.get("quests", []) if details else []
        quests.sort(key=lambda q: int(q.get("quest_id", 0)))

        target_stage_num: int = 1
        target_stage_id: int | None = None
        target_stage_name: str | None = None
        target_diff: int = 1

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
                if explicit_diff is not None:
                    matched_s = _resolve_stage_by_diff(stages_arr, explicit_diff)
                    target_stage_id = matched_s.get("stage_id") if matched_s else None
                    target_diff = _extract_stage_difficulty(matched_s)
                elif len(stages_arr) > 1 and not auto_confirm:
                    chosen_diff = questionary.select(
                        t("cli.challenge.select_difficulty"),
                        choices=_build_difficulty_choices(stages_arr),
                        use_arrow_keys=True,
                        use_jk_keys=False,
                    ).ask()
                    if not chosen_diff:
                        console.print(f"[yellow]{t('cli.dokkandb.canceled')}[/yellow]")
                        return
                    target_stage_id = chosen_diff.get("stage_id")
                    target_diff = _extract_stage_difficulty(chosen_diff)
                else:
                    matched_s = _resolve_stage_by_diff(stages_arr, None)
                    target_stage_id = matched_s.get("stage_id") if matched_s else None
                    target_diff = _extract_stage_difficulty(matched_s)
                target_stage_name = matched_quest.get("quest_name")
            else:
                target_stage_name = f"Stage {explicit_stage}"
        elif quests and not auto_confirm:
            stage_choices = _build_quest_stage_choices(quests, include_all=True)
            chosen_stage_dict = questionary.select(
                t("cli.challenge.select_stage"),
                choices=stage_choices,
                use_arrow_keys=True,
                use_jk_keys=False,
            ).ask()
            if chosen_stage_dict is None:
                console.print(f"[yellow]{t('cli.dokkandb.canceled')}[/yellow]")
                return
            target_stage_num = chosen_stage_dict.get("stage_num", 1)
            target_stage_name = chosen_stage_dict.get("stage_name")
            stages_arr = chosen_stage_dict.get("stages", [])

            if target_stage_num == 0:
                target_stage_id = None
                target_diff = 1
            elif explicit_diff is not None:
                matched_s = _resolve_stage_by_diff(stages_arr, explicit_diff)
                target_stage_id = matched_s.get("stage_id") if matched_s else None
                target_diff = _extract_stage_difficulty(matched_s)
            elif len(stages_arr) > 1:
                chosen_diff = questionary.select(
                    t("cli.challenge.select_difficulty"),
                    choices=_build_difficulty_choices(stages_arr),
                    use_arrow_keys=True,
                    use_jk_keys=False,
                ).ask()
                if not chosen_diff:
                    console.print(f"[yellow]{t('cli.dokkandb.canceled')}[/yellow]")
                    return
                target_stage_id = chosen_diff.get("stage_id")
                target_diff = _extract_stage_difficulty(chosen_diff)
            else:
                matched_s = _resolve_stage_by_diff(stages_arr, None)
                target_stage_id = matched_s.get("stage_id") if matched_s else None
                target_diff = _extract_stage_difficulty(matched_s)
        elif quests:
            target_stage_num = 1
            stages_arr = quests[0].get("stages", [])
            matched_s = _resolve_stage_by_diff(stages_arr, explicit_diff)
            target_stage_id = matched_s.get("stage_id") if matched_s else None
            target_diff = _extract_stage_difficulty(matched_s)
            target_stage_name = quests[0].get("quest_name")

        if target_stage_id and ev_id:
            boss_info = engine.dokkandb.get_stage_boss_info(ev_id, target_stage_id)
            if boss_info and boss_info.get("phases"):
                render_stage_boss_info(
                    boss_info,
                    target_stage_name=target_stage_name,
                    target_stage_num=target_stage_num,
                    console=console,
                )

        raw_missions = engine.dokkandb.get_challenge_missions(
            ev_name, stage_num=target_stage_num if target_stage_num > 0 else None, event_id=ev_id
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

        if not auto_confirm:
            start = questionary.confirm(t("cli.challenge.start_confirm"), default=True).ask()
            if not start:
                console.print(f"[yellow]{t('cli.dokkandb.canceled')}[/yellow]")
                return

        diff_str = DIFFICULTY_NAMES.get(target_diff, f"Diff {target_diff}")
        stage_str = (
            f"Stage {target_stage_num}"
            + (f": {target_stage_name}" if target_stage_name else "")
            + f" [{diff_str}]"
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
            preferred_difficulty=diff_str.lower(),
            difficulty=target_diff,
        )


def handle_box_scan_interactive(
    engine: BotEngine,
    console: Console,
    args: list | None = None,
    log_file: str | None = None,
) -> None:
    """Interactive OCR Character Box Scanner to autonomously build config/box.json."""
    with _ui_boundary(console, cancel_msg="Box scan cancelled."):
        console.print("\n[bold cyan]📦 Autonomous Character Box Scanner (OCR)[/bold cyan]")
        console.print(
            "[dim]Scans your owned in-game cards, recognizes names & titles, and creates config/box.json.[/dim]\n"
        )

        if not engine.adb.is_connected():
            console.print("[yellow]Device not connected. Attempting auto-connection...[/yellow]")
            try:
                serial = engine.connect()
                console.print(f"[green]✓ Connected to {serial}![/green]")
            except Exception as e:
                console.print(f"[bold red]Cannot connect to device: {e}[/bold red]")
                return

        existing_ids = engine.dokkandb.get_user_box_card_ids()
        if existing_ids:
            console.print(
                f"[green]Found existing box database with {len(existing_ids)} cards indexed.[/green]\n"
            )

        max_cards: int | None = None
        custom_log: str | None = log_file
        args_list = list(args) if args else []
        skip_next = False
        has_direct_flags = False
        for idx, a in enumerate(args_list):
            if skip_next:
                skip_next = False
                continue
            low = str(a).lower()
            if low in ("--scan-box", "--scan", "--box-scan", "scan-box", "box-scan", "scan"):
                has_direct_flags = True
            elif low in ("--log-file", "--log", "-lf") and idx + 1 < len(args_list):
                custom_log = str(args_list[idx + 1])
                skip_next = True
                has_direct_flags = True
            elif str(a).startswith("--log-file="):
                custom_log = str(a).split("=", 1)[1]
                has_direct_flags = True
            elif str(a).isdigit():
                max_cards = int(a)
                has_direct_flags = True

        if max_cards is None and not has_direct_flags and not args_list:
            choices = [
                questionary.Choice("🚀 Full Box Scan (All owned UR/LR characters)", value=0),
                questionary.Choice("⚡ Quick Scan (First 50 cards)", value=50),
                questionary.Choice("🎯 Custom Card Limit", value=-1),
                questionary.Choice("❌ Cancel", value=None),
            ]
            mode = questionary.select("Select Box Scan scope:", choices=choices).ask()
            if mode is None:
                console.print("[yellow]Box scan cancelled.[/yellow]")
                return
            elif mode == -1:
                lim_str = Prompt.ask("Enter maximum cards to scan", default="100").strip()
                max_cards = int(lim_str) if lim_str.isdigit() else 100
            elif mode > 0:
                max_cards = mode
        elif max_cards is None:
            max_cards = 0

        target_log = custom_log if custom_log is not None else AppPaths.get_box_scan_log_path()
        limit_text = f"up to {max_cards} cards" if max_cards else "all cards"
        console.print(f"[bold green]Starting autonomous box scanner ({limit_text})...[/bold green]")
        console.print(f"[dim]Debug log saved to: {target_log}[/dim]\n")

        engine.start_box_scanner(
            output_file=AppPaths.get_user_box_path(),
            max_cards_to_scan=max_cards,
            log_file=target_log,
        )


def select_challenge_boss_stage(
    engine: BotEngine, console: Console, active_only: bool = True
) -> Any:
    """Interactively prompts the user to select an endgame stage from presets or DokkanDB."""
    with _ui_boundary(console):
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
        choices.extend(_build_event_choices(events, limit=50))

        selected = questionary.select(
            t("cli.challenge.select_event"), choices=choices, use_arrow_keys=True, use_jk_keys=False
        ).ask()
        if not selected:
            return None

        if selected == "preset":
            st_choices = [
                questionary.Choice(title=f"{s.stage_name} ({s.event_name})", value=s.stage_id)
                for s in list_boss_stages()
            ]
            st_choices.append(questionary.Choice(title=t("cli.ai.opt_cancel"), value=None))
            chosen = questionary.select("Select target boss stage:", choices=st_choices).ask()
            return get_boss_stage(chosen) if chosen else None

        ev_id = int(selected.get("id") or 0)
        ev_name = (selected.get("name") or "Challenge").replace("\n", " ").strip()
        details = engine.dokkandb.get_event_details(ev_id)
        quests = (
            sorted(details.get("quests", []), key=lambda q: int(q.get("quest_id", 0)))
            if details
            else []
        )
        if not quests:
            console.print(f"[yellow]No stages found for event '{ev_name}' (ID: {ev_id}).[/yellow]")
            return None

        chosen_stage = questionary.select(
            t("cli.challenge.select_stage"),
            choices=_build_quest_stage_choices(quests),
            use_arrow_keys=True,
            use_jk_keys=False,
        ).ask()
        if not chosen_stage:
            return None

        stages_arr = chosen_stage.get("stages", [])
        target_stage_id = chosen_stage.get("stage_id")
        target_diff = 1
        if len(stages_arr) > 1:
            chosen_diff = questionary.select(
                t("cli.challenge.select_difficulty"),
                choices=_build_difficulty_choices(stages_arr),
                use_arrow_keys=True,
                use_jk_keys=False,
            ).ask()
            if not chosen_diff:
                return None
            target_stage_id = chosen_diff.get("stage_id")
            target_diff = _extract_stage_difficulty(chosen_diff)
        elif stages_arr:
            target_stage_id = stages_arr[0].get("stage_id")
            target_diff = _extract_stage_difficulty(stages_arr[0])

        if not target_stage_id:
            return None

        boss_info = engine.dokkandb.get_stage_boss_info(ev_id, target_stage_id)
        if not boss_info or not boss_info.get("phases"):
            return BossStage(
                stage_id=target_stage_id,
                event_id=ev_id,
                stage_name=chosen_stage.get("stage_name")
                or f"Stage {chosen_stage.get('stage_num')}",
                event_name=ev_name,
                difficulty=target_diff,
                phases=[],
            )
        boss_info.setdefault("stage_id", target_stage_id)
        boss_info.setdefault("event_id", ev_id)
        boss_info.setdefault(
            "stage_name",
            chosen_stage.get("stage_name") or f"Stage {chosen_stage.get('stage_num')}",
        )
        boss_info.setdefault("event_name", ev_name)
        boss_info.setdefault("difficulty", target_diff)
        return BossStage.from_dokkandb(boss_info)
    return None


def prompt_stage_missions(stage: Any, dokkandb: Any, console: Console) -> Any | None:
    """Interactively prompts the user via checkbox to target specific stage missions."""
    try:
        from dokkan_eza_link_farmer.ai.mission_solver import MissionBundler, MissionParser

        ev_id = getattr(stage, "event_id", 0)
        st_id = getattr(stage, "stage_id", 0)
        st_name = getattr(stage, "stage_name", "")

        if not ev_id and st_id and len(str(st_id)) >= 8:
            with contextlib.suppress(ValueError):
                ev_id = int(str(st_id)[:4])
        if not ev_id:
            return None

        stage_num: int | None = None
        if str(st_id).startswith(str(ev_id)) and len(str(st_id)) > len(str(ev_id)) + 1:
            with contextlib.suppress(ValueError):
                stage_num = int(str(st_id)[len(str(ev_id)) : -1])
        if stage_num is None and (m := re.search(r"Stage\s*(\d+)", st_name, re.IGNORECASE)):
            stage_num = int(m.group(1))

        try:
            with console.status("[dim]Fetching stage missions from DokkanDB...[/dim]"):
                raw_missions = dokkandb.get_event_missions(ev_id)
        except Exception:
            return None

        if not raw_missions:
            return None

        parsed_missions = [MissionParser.parse(m) for m in raw_missions]
        restricted = [
            m for m in parsed_missions if m.applies_to_stage(stage_num) and m.is_restricted
        ]
        if not restricted:
            return None

        choices = [questionary.Choice(title=f"🎯 {m.display_title}", value=m) for m in restricted]
        selected = questionary.checkbox(
            "Select stage missions to target (Space to toggle, Enter to confirm/skip):",
            choices=choices,
            use_arrow_keys=True,
            use_jk_keys=False,
        ).ask()
        if not selected:
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
    with _ui_boundary(console):
        from dokkan_eza_link_farmer.ai.models import DokkanCard

        if not query:
            query = questionary.text(t("cli.ai.query_prompt")).ask()
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

        chosen_id = questionary.select(t("cli.ai.select_leader"), choices=choices).ask()
        if not chosen_id:
            return

        card_data = engine.dokkandb.get_card(int(chosen_id))
        if not card_data:
            console.print("[red]Could not retrieve card details.[/red]")
            return

        target_card = DokkanCard.from_dokkandb(card_data)
        catalog = engine.dokkandb.get_cards_catalog()
        candidate_pool = [
            DokkanCard.from_dokkandb(raw)
            for raw in catalog[:300]
            if int(raw.get("id") or 0) != target_card.id
        ]
        partners = engine.team_builder.find_best_partners_for_card(
            target_card, candidate_pool, top_k=7
        )
        render_linking_partners(target_card, partners, console=console)


def ai_build_team_for_stage(
    engine: BotEngine,
    console: Console,
    stage: Any,
    on_render: Callable[..., Any] | None = None,
) -> None:
    """Solves and optimizes the best team against a specific Challenge BossStage using the AI Teambuilder."""
    with _ui_boundary(console):
        from dokkan_eza_link_farmer.ai.models import DokkanCard

        render_ai_stage_synthesis_header(stage, console=console)
        mission_batch = prompt_stage_missions(stage, engine.dokkandb, console)

        candidate_pool = engine.team_builder.load_user_box()
        if len(candidate_pool) < 6:
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
            rec = engine.team_builder.build_team_plan(candidate_pool[:6], language=get_language())

        (on_render or render_team_presentation)(
            rec,
            title=f"🔄 AI Recommended Tactical Rotations for {stage.stage_name}",
            shortlist=shortlist,
        )


def ai_build_team(
    engine: BotEngine,
    console: Console,
    query: str = "",
    on_build_for_stage: Callable[..., Any] | None = None,
    on_render: Callable[..., Any] | None = None,
    on_select_stage: Callable[..., Any] | None = None,
) -> None:
    """Builds an optimized team and gets Qwen/DeepSeek-R1 tactical breakdown."""
    with _ui_boundary(console):
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
                select_fn = on_select_stage or (
                    lambda: select_challenge_boss_stage(engine, console)
                )
                stage = select_fn()
                if stage:
                    (
                        on_build_for_stage
                        or (
                            lambda st: ai_build_team_for_stage(
                                engine, console, st, on_render=on_render
                            )
                        )
                    )(stage)
                return

            query = questionary.text(t("cli.ai.query_prompt")).ask()
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

        leader_id = questionary.select(t("cli.ai.select_leader"), choices=choices).ask()
        if not leader_id:
            return

        leader_data = engine.dokkandb.get_card(int(leader_id))
        if not leader_data:
            console.print("[red]Could not load card details.[/red]")
            return

        leader_card = DokkanCard.from_dokkandb(leader_data)
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
        rec = engine.team_builder.build_team_plan(team_cards, language=get_language())
        (on_render or render_team_presentation)(rec, title="🔄 AI Recommended Tactical Rotations")


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
    if "ai" not in engine.config:
        engine.config["ai"] = {}

    engine.config["ai"]["enabled"] = True
    engine.config["ai"]["model_family"] = "qwen"
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
    with _ui_boundary(console):
        args_raw = list(args) if args else []
        filtered = [a for a in args_raw if str(a).lower() not in ("--ai", "--team", "ai", "team")]
        sub = (str(filtered[0]).lower() if filtered else "").strip()
        query = " ".join(str(a) for a in filtered[1:]) if len(filtered) > 1 else ""

        action = sub
        if not action:
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
            action = questionary.select(t("cli.ai.menu_title"), choices=choices).ask()
            if not action:
                return

        if action in ("status", "check"):
            (
                on_status
                or (
                    lambda: render_ai_status(
                        engine.ai_config, engine.ai_client.is_available(), console
                    )
                )
            )()
        elif action in ("partner", "link", "links"):
            (on_partner or (lambda q: ai_find_partners(engine, console, query=q)))(query)
        elif action in ("build", "team"):
            (on_build or (lambda q: ai_build_team(engine, console, query=q)))(query)
        elif action in ("config", "switch"):
            (on_config or (lambda: ai_configure_model(engine, console, on_status=on_status)))()
        elif action in ("run", "endgame", "ai-run"):
            stage_target = None
            skip_s = False
            for idx, a in enumerate(filtered[1:], 1):
                if skip_s:
                    skip_s = False
                    continue
                low_a = str(a).lower()
                if low_a in ("--stage", "-s") and idx + 1 < len(filtered):
                    stage_target = filtered[idx + 1]
                    skip_s = True
                elif low_a.startswith(("--stage=", "-s=")):
                    stage_target = a.split("=", 1)[1]
                elif not a.startswith("-"):
                    stage_target = a
                    break
            stage = (
                stage_target
                or (on_select_stage or (lambda: select_challenge_boss_stage(engine, console)))()
            )
            if stage and on_endgame:
                on_endgame(stage)
