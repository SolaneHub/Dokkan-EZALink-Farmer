from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from dokkan_eza_link_farmer.core.i18n import t


def render_stage_boss_info(
    boss_info: dict[str, Any],
    target_stage_name: str | None,
    target_stage_num: int,
    console: Console | None = None,
) -> None:
    """Renders stage boss telemetry table with phase info, typing, and immunities."""
    c = console or Console()
    if not boss_info or not boss_info.get("phases"):
        return
    t_boss = Table(
        title=f"{t('cli.challenge.stage_boss_info_title')} - {target_stage_name} (Stage {target_stage_num})",
        border_style="magenta",
        expand=True,
    )
    t_boss.add_column("Phase", style="bold cyan", justify="center", width=12, no_wrap=True)
    t_boss.add_column("Boss Enemy", style="bold", ratio=3, no_wrap=False)
    t_boss.add_column("Typing", style="bold yellow", width=15, no_wrap=True)
    t_boss.add_column("Key Mechanics & Immunities", style="dim", ratio=4, no_wrap=False)

    for ph in boss_info.get("phases") or []:
        if not ph:
            continue
        ph_num = ph.get("phase", 1) if isinstance(ph, dict) else 1
        raw_bosses = (ph.get("bosses") if isinstance(ph, dict) else []) or []
        for b in raw_bosses:
            if not b:
                continue
            b_name = b.get("name", "Unknown Boss") if isinstance(b, dict) else str(b)
            b_type = b.get("type_name", "Unknown") if isinstance(b, dict) else "Unknown"
            raw_mechs = (b.get("mechanics") if isinstance(b, dict) else []) or []
            mechs_list = []
            for m in raw_mechs:
                if isinstance(m, dict):
                    m_name = m.get("name")
                    if m_name:
                        mechs_list.append(str(m_name))
                elif isinstance(m, str) and m:
                    mechs_list.append(m)
            mechs = ", ".join(mechs_list) or "None"
            t_boss.add_row(f"Phase {ph_num}", str(b_name), str(b_type), mechs)
    c.print(t_boss)


def render_mission_batches(
    batches: list[Any],
    ev_name: str,
    target_stage_num: int,
    saved: int,
    total_missions: int,
    console: Console | None = None,
) -> None:
    """Renders bundled challenge mission batches table and savings badge."""
    c = console or Console()
    batches = batches or []
    if target_stage_num > 0:
        c.print(
            f"[bold cyan]{t('cli.challenge.stage_missions_found', stage=target_stage_num, total=total_missions, batches=len(batches))}[/bold cyan]"
        )
    else:
        c.print(
            f"[bold cyan]{t('cli.challenge.missions_found', total=total_missions, batches=len(batches))}[/bold cyan]"
        )

    if saved > 0:
        c.print(f"[bold green]{t('cli.challenge.savings_badge', saved=saved)}[/bold green]")

    t_batches = Table(
        title=f"🎯 Mission Batches for {ev_name} (Stage {target_stage_num})",
        border_style="green",
        expand=True,
    )
    t_batches.add_column("Batch #", style="bold cyan", width=14, no_wrap=True)
    t_batches.add_column("Combined Requirements", style="bold", ratio=4, no_wrap=False)
    t_batches.add_column("Missions Cleared in Batch", style="dim", ratio=3, no_wrap=False)

    for idx, b in enumerate(batches, 1):
        raw_missions = getattr(b, "missions", []) or []
        m_names = ", ".join(f"#{getattr(m, 'id', m)}" for m in raw_missions) or "Standard Clear"
        summary = str(getattr(b, "summary", "") or "Standard Clear")
        t_batches.add_row(f"Run Batch #{idx}", summary, m_names)

    c.print(t_batches)


def render_endgame_header(
    stage: Any,
    dry_run: bool = False,
    force_solve: bool = False,
    mission_batch: Any | None = None,
    console: Console | None = None,
) -> None:
    """Renders autonomous AI Endgame Runner tactical banner."""
    c = console or Console()
    dry_badge = " [bold magenta][DRY-RUN SIMULATION][/bold magenta]" if dry_run else ""
    force_badge = " [bold red][FORCE-SOLVE][/bold red]" if force_solve else ""
    batch_summary = getattr(mission_batch, "summary", str(mission_batch)) if mission_batch else ""
    mission_line = (
        f"\n[bold yellow]Target Missions:[/bold yellow] [green]{batch_summary}[/green]"
        if batch_summary
        else ""
    )
    event_name = getattr(stage, "event_name", "Challenge Event")
    stage_name = getattr(stage, "stage_name", "Stage")
    stage_id = getattr(stage, "stage_id", "?")
    phases = getattr(stage, "phases", []) or []
    c.print(
        Panel.fit(
            f"[bold cyan]⚔️ Dokkan AI Endgame Autonomous Runner[/bold cyan]{dry_badge}{force_badge}\n"
            f"[bold yellow]Event:[/bold yellow] {event_name}\n"
            f"[bold yellow]Stage:[/bold yellow] {stage_name} (ID: {stage_id}){mission_line}\n"
            f"[bold yellow]Phases:[/bold yellow] {len(phases)} sequential battles\n"
            f"[dim]Adaptive Trial & Error loop with Episodic Memory & Surgical Team Swapping[/dim]",
            border_style="cyan",
        )
    )


def render_endgame_result(res: Any, console: Console | None = None) -> None:
    """Renders stage clear or defeat summary card."""
    c = console or Console()
    attempts = getattr(res, "attempts", 1)
    if getattr(res, "success", False):
        c.print(f"\n[bold green]🏆 STAGE CLEARED in {attempts} attempt(s)![/bold green]")
        winning_team = getattr(res, "winning_team", []) or []
        if winning_team:
            winning_cards_str = ", ".join(
                f"[{getattr(card, 'element_color', 'white')}][{getattr(card, 'element_name', '')}] {getattr(card, 'name', '')}[/]"
                for card in winning_team
            )
        else:
            winning_cards_str = "Team N/A"
        c.print(f"[bold]Winning Team:[/bold] {winning_cards_str}")
    else:
        c.print(
            f"\n[bold red]❌ Run finished without clear ({attempts} attempts reached).[/bold red]"
        )


def render_ai_stage_synthesis_header(stage: Any, console: Console | None = None) -> None:
    """Renders stage briefing panel before AI team synthesis."""
    c = console or Console()

    def _fmt_phase(p: Any) -> str:
        if isinstance(p, dict):
            en = str(p.get("element_name") or p.get("type_name") or "Boss")
        else:
            en = str(getattr(p, "element_name", None) or "Boss")
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

    def _get_flag(p: Any, flag: str) -> bool:
        if isinstance(p, dict):
            return bool(p.get(flag))
        return bool(getattr(p, flag, False))

    raw_phases = getattr(stage, "phases", []) or []
    phases_str = " -> ".join(_fmt_phase(p) for p in raw_phases) if raw_phases else "Standard Boss"
    gimmicks = []
    if any(_get_flag(p, "cancels_dodge") for p in raw_phases):
        gimmicks.append("Cancels Dodge")
    if any(_get_flag(p, "has_aoe") for p in raw_phases):
        gimmicks.append("AoE Attack")
    if any(_get_flag(p, "locks_slots") for p in raw_phases):
        gimmicks.append("Locks Slots")
    gimmicks_str = f" [{', '.join(gimmicks)}]" if gimmicks else ""

    total_battles = getattr(stage, "total_battles", 1)
    battles_str = f"{total_battles} battagli{'e' if total_battles > 1 else 'a'}"
    stack_warn = (
        "\n[bold red]⚠️ Stacking ATK/DEF: Si azzera a inizio di ciascuna nuova battaglia separata![/bold red]"
        if getattr(stage, "is_multi_battle", False)
        else ""
    )

    ev_name = getattr(stage, "event_name", "Challenge Event")
    st_name = getattr(stage, "stage_name", "Stage")
    st_id = getattr(stage, "stage_id", "?")

    c.print(
        Panel.fit(
            f"[bold cyan]🎯 AI Team Synthesis for: {ev_name}[/bold cyan]\n"
            f"[bold yellow]Stage:[/bold yellow] {st_name} (ID: {st_id})\n"
            f"[bold yellow]Struttura:[/bold yellow] {battles_str} ({len(raw_phases)} Fasi: {phases_str}){gimmicks_str}{stack_warn}\n"
            f"[dim]Consulting Constraint Solver & AI Tactical Advisor against lethal boss gimmicks...[/dim]",
            border_style="cyan",
        )
    )


def render_team_presentation(
    rec: Any,
    console: Console | None = None,
    title: str = "",
    shortlist: list[Any] | None = None,
) -> None:
    """Displays rich team representation with Dokkan typing colors for all cards."""
    c = console or Console()

    from dokkan_eza_link_farmer.ai.support_catalog import (
        get_recommended_support_items,
        get_recommended_support_memory,
    )
    from dokkan_eza_link_farmer.ai.team_builder import (
        render_stage_intel_rich,
        render_team_summary_table_rich,
    )

    # 0. Complete Stage Intelligence (Battles, HP, ATK, Actions, Immunities, Stacking Status)
    stage_obj = getattr(rec, "boss_stage", None)
    if stage_obj and getattr(stage_obj, "phases", None):
        c.print(render_stage_intel_rich(stage_obj))

    # 0.1. Mission Completion Banner if targeted
    if getattr(rec, "mission_summary", None):
        c.print(
            Panel(
                f"[bold green]🎯 Solved for Stage Missions:[/bold green] [bold yellow]{rec.mission_summary}[/bold yellow]\n"
                f"[bold cyan]All 6 team members strictly comply with mission requirements![/bold cyan]",
                border_style="green",
                expand=True,
            )
        )

    # 1. 6-Card Team Summary Table with Dokkan Colors
    c.print(
        render_team_summary_table_rich(
            rec.all_cards, rec.leader, boss_stage=getattr(rec, "boss_stage", None)
        )
    )

    # 2. Rotations Breakdown Table with Dokkan Colors (7 combat units: Rot A, Rot B, Floaters)
    def _get_card_badge(card: Any, leader: Any, friend: Any, is_floater: bool = False) -> Any:
        base = (
            card.rich_formatted_name()
            if hasattr(card, "rich_formatted_name")
            else str(getattr(card, "name", card))
        )
        loc_label = "Floater" if is_floater else "Rotazione"
        # 1. Distinguish between Friend Leader and Player Leader even if card.id == friend.id
        if getattr(card, "is_friend_leader", False) or (friend is not None and card is friend):
            badge = Text(f" [Friend • {loc_label}]", style="bold cyan")
            return Text.assemble(base, badge)
        elif (leader is not None and card is leader) or (
            leader is not None
            and getattr(card, "id", None) is not None
            and getattr(card, "id", None) == getattr(leader, "id", None)
        ):
            badge = Text(f" [Leader • {loc_label}]", style="bold green")
            return Text.assemble(base, badge)
        return base

    def _get_card_tactical_role(card: Any, is_slot1: bool = False) -> str:
        if card is None:
            return "🛡️ Difesa solida" if is_slot1 else "💥 Attaccante"
        tags = []
        if getattr(card, "has_guard", False):
            tags.append("🛡️ Guardia")
        dr = getattr(card, "damage_reduction_percent", 0)
        if dr > 0:
            tags.append(f"DR {dr}%")
        elif getattr(card, "has_damage_reduction", False):
            tags.append("DR")
        if getattr(card, "has_target_taunt", False):
            tags.append("🎯 Taunt")
        if getattr(card, "has_stacking_def", False):
            tags.append("📈 Stack DEF")
        if getattr(card, "has_dodge", False):
            tags.append("💨 Schivata")
        if getattr(card, "has_active_skill", False):
            tags.append("💥 Active")
        if getattr(card, "has_standby", False):
            tags.append("⏳ Standby")
        if getattr(card, "has_support", False):
            tags.append("✨ Supporto")
        if getattr(card, "has_orb_changing", False):
            tags.append("🔮 Orbi")

        if not tags:
            return "🛡️ Difesa solida" if is_slot1 else "💥 Attaccante"
        return " | ".join(tags[:3])

    t_team = Table(
        title=title or f"🔄 {t('cli.ai.rotations_title')}",
        title_style="bold yellow",
        border_style="bright_blue",
        header_style="bold cyan",
        expand=True,
    )
    t_team.add_column("Rotazione", style="bold cyan", justify="center", width=14, no_wrap=True)
    t_team.add_column("Posizione", justify="center", width=16, no_wrap=True)
    t_team.add_column("Personaggio", ratio=5, no_wrap=False)
    t_team.add_column("Ruolo Tattico & Kit", style="green", ratio=3, no_wrap=False)
    t_team.add_column("Sinergia Link & Note", style="dim", ratio=3, no_wrap=False)

    # Rotazione A
    t_team.add_row(
        "Rotazione A",
        "[bold red]Slot 1 (Tank)[/bold red]",
        _get_card_badge(rec.rotation_a.slot1, rec.leader, rec.friend_leader, is_floater=False),
        _get_card_tactical_role(rec.rotation_a.slot1, is_slot1=True),
        f"🔗 {', '.join(rec.rotation_a.shared_links[:4])}"
        if rec.rotation_a.shared_links
        else "Difensore principale",
    )
    t_team.add_row(
        "",
        "[bold yellow]Slot 2 (DPS)[/bold yellow]",
        _get_card_badge(rec.rotation_a.slot2, rec.leader, rec.friend_leader, is_floater=False),
        _get_card_tactical_role(rec.rotation_a.slot2, is_slot1=False),
        f"⭐ Sinergia: {rec.rotation_a.synergy_score:.1f} ({len(rec.rotation_a.shared_links)} link)",
    )

    t_team.add_section()

    # Rotazione B
    t_team.add_row(
        "Rotazione B",
        "[bold red]Slot 1 (Tank)[/bold red]",
        _get_card_badge(rec.rotation_b.slot1, rec.leader, rec.friend_leader, is_floater=False),
        _get_card_tactical_role(rec.rotation_b.slot1, is_slot1=True),
        f"🔗 {', '.join(rec.rotation_b.shared_links[:4])}"
        if rec.rotation_b.shared_links
        else "Difensore principale",
    )
    t_team.add_row(
        "",
        "[bold yellow]Slot 2 (DPS)[/bold yellow]",
        _get_card_badge(rec.rotation_b.slot2, rec.leader, rec.friend_leader, is_floater=False),
        _get_card_tactical_role(rec.rotation_b.slot2, is_slot1=False),
        f"⭐ Sinergia: {rec.rotation_b.synergy_score:.1f} ({len(rec.rotation_b.shared_links)} link)",
    )

    t_team.add_section()

    # Floaters (Slot 3)
    for idx, fl in enumerate(rec.floaters, 1):
        t_team.add_row(
            "Floaters" if idx == 1 else "",
            f"[dim]Slot 3 (#{idx})[/dim]",
            _get_card_badge(fl, rec.leader, rec.friend_leader, is_floater=True),
            _get_card_tactical_role(fl, is_slot1=False),
            "Ruota ogni 3 turni (Support / Flex)",
        )

    c.print(t_team)

    # Support Items & Support Memory Tables
    items = get_recommended_support_items(max_items=4)
    if items:
        t_items = Table(
            title="💊 Oggetti di Supporto Consigliati",
            title_style="bold green",
            border_style="green",
            expand=True,
        )
        t_items.add_column(
            "Priorità", justify="center", style="bold yellow", width=10, no_wrap=True
        )
        t_items.add_column("Oggetto", style="bold white", width=18, no_wrap=False)
        t_items.add_column("Effetto Tattico", style="cyan", ratio=4, no_wrap=False)
        t_items.add_column("Utilizzo Consigliato", style="dim", ratio=4, no_wrap=False)
        for it in items:
            t_items.add_row(
                f"#{it.get('rank', 1)}",
                str(it.get("name", "")),
                str(it.get("effect", "")),
                str(it.get("usage", "")),
            )
        c.print(t_items)

    mem = get_recommended_support_memory(rec.all_cards)
    if mem:
        t_mem = Table(
            title="🎞️ Support Memory Consigliata",
            title_style="bold magenta",
            border_style="magenta",
            expand=True,
        )
        t_mem.add_column("Nome Memory", style="bold white", width=22, no_wrap=False)
        t_mem.add_column("Durata", justify="center", style="bold cyan", width=12, no_wrap=True)
        t_mem.add_column("Effetto Tattico", style="yellow", ratio=4, no_wrap=False)
        t_mem.add_column("Condizione / Categoria", style="dim", ratio=4, no_wrap=False)
        t_mem.add_row(
            str(mem.get("name", "")),
            str(mem.get("duration", "")),
            str(mem.get("effect", "")),
            str(mem.get("condition", "")),
        )
        c.print(t_mem)

    # 3. Top-5 Substitutes Shortlist with Dokkan Colors
    if shortlist:
        t_short = Table(
            title="🔄 Top-5 Recommended Substitutes (Shortlist)",
            border_style="cyan",
            expand=True,
        )
        t_short.add_column("Rank", style="bold cyan", justify="center", width=8, no_wrap=True)
        t_short.add_column("Candidate Character", ratio=5, no_wrap=False)
        t_short.add_column("Score", justify="right", style="yellow", width=10, no_wrap=True)
        t_short.add_column("Key Strengths", style="dim", ratio=5, no_wrap=False)
        for idx, cand in enumerate(shortlist[:5], 1):
            reason_str = getattr(cand, "reasoning", "")
            if not reason_str and getattr(cand, "counter_points", None):
                reason_str = "; ".join(cand.counter_points)
            cand_card = getattr(cand, "card", None)
            if not reason_str and cand_card and getattr(cand_card, "categories", None):
                reason_str = ", ".join(cand_card.categories[:3])
            c_name = (
                cand_card.rich_formatted_name()
                if cand_card is not None and hasattr(cand_card, "rich_formatted_name")
                else str(getattr(cand_card, "name", cand_card))
            )
            score_val = getattr(cand, "score", 0.0)
            score_str = (
                f"{score_val:.1f}" if isinstance(score_val, (int, float)) else str(score_val)
            )
            t_short.add_row(
                f"#{idx}",
                c_name,
                score_str,
                reason_str or "Synergy pick",
            )
        c.print(t_short)

    if rec.ai_reasoning:
        c.print(
            Panel(
                f"[italic dim cyan]{rec.ai_reasoning}[/italic dim cyan]",
                title=f"🧠 {t('cli.ai.reasoning_title')}",
                border_style="magenta",
                expand=True,
            )
        )

    if rec.tactical_analysis:
        c.print(
            Panel(
                Markdown(rec.tactical_analysis),
                title=f"⚔️ {t('cli.ai.tactical_title')}",
                border_style="yellow",
                expand=True,
            )
        )


def render_linking_partners(
    target_card: Any,
    partners: list[tuple[Any, float, list[str]]],
    console: Console | None = None,
) -> None:
    """Renders table of top linking partners for a card."""
    c = console or Console()
    full_name = getattr(target_card, "full_name", None) or getattr(
        target_card, "name", str(target_card)
    )
    table = Table(
        title=f"Top Linking Partners for {full_name}",
        border_style="green",
        expand=True,
    )
    table.add_column("Rank", style="bold cyan", width=8, no_wrap=True)
    table.add_column("Partner Card", ratio=4, no_wrap=False)
    table.add_column("Synergy", justify="right", style="yellow", width=10, no_wrap=True)
    table.add_column("Shared Links", style="dim", ratio=4, no_wrap=False)

    for idx, (p_card, score, shared) in enumerate(partners, 1):
        p_name = (
            p_card.rich_formatted_name()
            if hasattr(p_card, "rich_formatted_name")
            else str(getattr(p_card, "name", p_card))
        )
        table.add_row(
            f"#{idx}",
            p_name,
            f"{score:.1f}",
            ", ".join(shared),
        )

    c.print(table)
