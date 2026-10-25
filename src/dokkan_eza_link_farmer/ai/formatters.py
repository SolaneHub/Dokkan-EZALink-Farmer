"""Formatting and rich rendering utilities for teams, rotations, and stage intelligence."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dokkan_eza_link_farmer.ai.models import DokkanCard

_GLOBAL_CATEGORIES_CACHE: dict[int, str] | None = None


def _get_global_category_map() -> dict[int, str]:
    global _GLOBAL_CATEGORIES_CACHE
    if _GLOBAL_CATEGORIES_CACHE is not None:
        return _GLOBAL_CATEGORIES_CACHE

    cat_map: dict[int, str] = {}
    cache_file = os.path.join(
        os.path.expanduser("~"), ".dokkan-farmer", "cache", "dokkandb_categories.json"
    )
    if os.path.exists(cache_file):
        try:
            with open(cache_file, encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and "id" in item and "name" in item:
                            cat_map[int(item["id"])] = str(item["name"])
        except Exception:
            pass

    _GLOBAL_CATEGORIES_CACHE = cat_map
    return cat_map


def _resolve_category_name(cid: int, card: DokkanCard, leader: DokkanCard) -> str:
    """Helper to map a category ID to human-readable name using card, leader, or global catalog metadata."""
    c_map = dict(zip(card.category_ids, card.categories, strict=False))
    lead_map = dict(zip(leader.category_ids, leader.categories, strict=False))
    global_map = _get_global_category_map()
    return c_map.get(cid) or lead_map.get(cid) or global_map.get(cid) or str(cid)


def format_team_summary_table(
    team_cards: list[DokkanCard], leader: DokkanCard | None = None, boss_stage: Any = None
) -> str:
    """Renders a clear tabular summary for the 6 team slots:

    [card_id] | [Element/Class] | Name (Subname) | Leader Boost (170% o 200%) | Categorie Condivise col Leader | Ruolo (Slot 1 Tank / Stacker / Floater) | Tag Difensivi (Guard / DR% / Dodge%)
    """
    if not team_cards:
        return "No team cards provided."

    from dokkan_eza_link_farmer.ai.solver import DokkanConstraintSolver
    from dokkan_eza_link_farmer.ai.synergy import optimize_rotations_for_team

    lead = leader or team_cards[0]
    headers = [
        "Slot",
        "Card ID",
        "Element/Class",
        "Name (Subname)",
        "Leader Boost",
        "Categorie Condivise col Leader",
        "Ruolo",
        "Tag Difensivi",
    ]

    rows: list[list[str]] = []

    # Pre-calculate designated battle rotation roles if 6-card team
    rot_role_map: dict[int, str] = {}
    if len(team_cards) == 6:
        try:
            rot_a, rot_b, floaters = optimize_rotations_for_team(team_cards)
            rot_role_map[rot_a.slot1.id] = "Slot 1 Tank (Rot A)"
            rot_role_map[rot_a.slot2.id] = (
                "Slot 2 Stacker (Rot A)"
                if rot_a.slot2.has_stacking_def
                or (
                    rot_a.slot2.base_form
                    and rot_a.slot2.base_form.sa_tags
                    and rot_a.slot2.base_form.sa_tags.stacks_def
                )
                else "Slot 2 DPS (Rot A)"
            )
            rot_role_map[rot_b.slot1.id] = "Slot 1 Tank (Rot B)"
            rot_role_map[rot_b.slot2.id] = (
                "Slot 2 Stacker (Rot B)"
                if rot_b.slot2.has_stacking_def
                or (
                    rot_b.slot2.base_form
                    and rot_b.slot2.base_form.sa_tags
                    and rot_b.slot2.base_form.sa_tags.stacks_def
                )
                else "Slot 2 DPS (Rot B)"
            )
            for fl in floaters:
                if fl.has_support or (
                    fl.base_form
                    and fl.base_form.passive_tags
                    and fl.base_form.passive_tags.has_support
                ):
                    fl_role = "Floater (Support)"
                elif fl.has_stacking_def or (
                    fl.base_form and fl.base_form.sa_tags and fl.base_form.sa_tags.stacks_def
                ):
                    fl_role = "Floater (Stacker)"
                else:
                    fl_role = "Floater (Slot 3)"
                rot_role_map[fl.id] = fl_role
        except Exception:
            pass

    for idx, c in enumerate(team_cards, start=1):
        slot_str = str(idx)
        cid_str = f"[{c.id}]"
        elem_str = f"[{c.element_name}]" if c.element_name else f"[{c.element}]"
        clean_name = " ".join(c.name.split())
        clean_sub = " ".join(c.subname.split()) if c.subname else ""
        name_str = f"{clean_name} ({clean_sub})" if clean_sub else clean_name

        # Leader Boost
        if idx == 1:
            is_cov, boost_val, _ = lead.is_covered_by_leader(lead)
            if is_cov:
                boost_str = f"{int(boost_val)}% (Lead)"
            elif lead.leader_spec:
                boost_str = f"{lead.leader_spec.base_boost_pct}% (Lead)"
            else:
                boost_str = "Leader"
        else:
            is_cov, boost_val, _ = c.is_covered_by_leader(lead)
            boost_str = f"{int(boost_val)}%" if is_cov else "0%"

        # Categorie Condivise col Leader
        if idx == 1:
            if lead.leader_spec and (
                lead.leader_spec.main_category_ids or lead.leader_spec.extra_category_ids
            ):
                main_names = [
                    _resolve_category_name(cid, lead, lead)
                    for cid in lead.leader_spec.main_category_ids
                ]
                extra_names = [
                    _resolve_category_name(cid, lead, lead)
                    for cid in lead.leader_spec.extra_category_ids
                ]
                main_str = f"Main: [{', '.join(main_names)}]" if main_names else "Main: Nessuna"
                extra_str = (
                    f"Extra: [{', '.join(extra_names)}]" if extra_names else "Extra: Nessuna"
                )
                shared_str = f"{main_str} | {extra_str}"
            else:
                shared_str = ", ".join(lead.categories[:2]) if lead.categories else "None"
        else:
            if lead.leader_spec and (
                lead.leader_spec.main_category_ids or lead.leader_spec.extra_category_ids
            ):
                main_set = set(lead.leader_spec.main_category_ids)
                extra_set = set(lead.leader_spec.extra_category_ids)

                shared_main = [
                    _resolve_category_name(cid, c, lead)
                    for cid in c.category_ids
                    if cid in main_set
                ]
                shared_extra = [
                    _resolve_category_name(cid, c, lead)
                    for cid in c.category_ids
                    if cid in extra_set
                ]

                if shared_main:
                    main_str = f"Main: [{', '.join(shared_main)}]"
                    extra_str = (
                        f"Extra: [{', '.join(shared_extra)}]" if shared_extra else "Extra: Nessuna"
                    )
                    shared_str = f"{main_str} | {extra_str}"
                else:
                    shared_str = "Main: Nessuna | Extra: Nessuna"
            else:
                shared_names = [cat for cat in c.categories if cat in lead.categories]
                shared_str = ", ".join(shared_names) if shared_names else "None"

        # Ruolo (Designated battle role or individual archetype)
        if c.id in rot_role_map:
            role_str = rot_role_map[c.id]
        else:
            is_s1 = DokkanConstraintSolver.is_slot1_viable(c)
            stacks = bool(
                (c.base_form and c.base_form.sa_tags and c.base_form.sa_tags.stacks_def)
                or c.has_stacking_def
            )
            if is_s1 and stacks:
                role_str = "Slot 1 Viable / Stacker"
            elif is_s1:
                role_str = "Slot 1 Viable"
            elif stacks:
                role_str = "Stacker"
            else:
                role_str = "Floater"

        # Tag Difensivi (Guard / DR% / Dodge%)
        has_guard = c.has_guard or bool(
            c.base_form and c.base_form.passive_tags and c.base_form.passive_tags.has_guard
        )
        is_guard_perm = getattr(c, "is_guard_permanent", False)
        is_guard_uncond = getattr(c, "is_guard_unconditional", False)
        guard_limit = getattr(c, "guard_turns_limit", None)
        if is_guard_perm and is_guard_uncond:
            guard_label = "Guard (Perm)"
        elif is_guard_perm:
            guard_label = "Guard (Cond)"
        elif guard_limit:
            guard_label = f"Guard ({guard_limit}T)"
        elif has_guard:
            guard_label = "Guard"
        else:
            guard_label = "No Guard"

        dr_pct = max(
            c.damage_reduction_percent,
            c.base_form.passive_tags.dr_base_percent
            if c.base_form and c.base_form.passive_tags
            else 0,
        )
        dr_limit = getattr(c, "dr_turns_limit", None)
        perm_dr = getattr(c, "permanent_damage_reduction_percent", 0)
        if dr_pct > 0:
            if perm_dr == dr_pct and getattr(c, "is_dr_permanent", False):
                dr_label = f"DR {dr_pct}% (Perm)"
            elif dr_limit:
                dr_label = f"DR {dr_pct}% ({dr_limit}T)"
            else:
                dr_label = f"DR {dr_pct}%"
        else:
            dr_label = "DR 0%"

        dodge_pct = c.dodge_chance_percent
        dodge_limit = getattr(c, "dodge_turns_limit", None)
        cancels_dodge_boss = bool(
            boss_stage
            and any(getattr(p, "cancels_dodge", False) for p in getattr(boss_stage, "phases", []))
        )
        if dodge_pct > 0:
            if cancels_dodge_boss:
                dodge_label = f"Dodge {dodge_pct}% [Nullificato]"
            elif dodge_limit:
                dodge_label = f"Dodge {dodge_pct}% ({dodge_limit}T)"
            else:
                dodge_label = f"Dodge {dodge_pct}%"
        else:
            dodge_label = "Dodge 0%"

        def_tags_str = f"{guard_label} / {dr_label} / {dodge_label}"

        rows.append(
            [
                slot_str,
                cid_str,
                elem_str,
                name_str,
                boost_str,
                shared_str,
                role_str,
                def_tags_str,
            ]
        )

    col_widths = [max(len(headers[i]), max(len(r[i]) for r in rows)) for i in range(len(headers))]
    header_line = " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    divider_line = "-+-".join("-" * col_widths[i] for i in range(len(headers)))
    data_lines = [" | ".join(col.ljust(col_widths[i]) for i, col in enumerate(row)) for row in rows]

    return "\n".join([header_line, divider_line] + data_lines)


def render_team_summary_table_rich(
    team_cards: list[DokkanCard], leader: DokkanCard | None = None, boss_stage: Any = None
) -> Any:
    """Renders a rich.table.Table summary for the 6 team slots with Dokkan type colors:

    - Slot (1 to 6)
    - Type (Super AGL, Extreme STR, etc. colored with Dokkan typing color)
    - Character (full name styled with Dokkan typing color)
    - Leader Boost (200%, 170%, etc.)
    - Ruolo (Slot 1 Tank, Stacker, Floater)
    - Tag Difensivi (Guard, DR %, Dodge %)
    """
    from rich.table import Table
    from rich.text import Text

    from dokkan_eza_link_farmer.ai.solver import DokkanConstraintSolver
    from dokkan_eza_link_farmer.ai.synergy import optimize_rotations_for_team

    lead = leader or (team_cards[0] if team_cards else None)
    t = Table(
        title="🛡️ Dokkan AI Optimal 6-Card Team Formation",
        border_style="green",
        expand=True,
    )
    t.add_column("Slot", style="bold cyan", justify="center", width=6, no_wrap=True)
    t.add_column("Type", justify="center", width=13, no_wrap=True)
    t.add_column("Character", ratio=5, no_wrap=False)
    t.add_column("Leader Boost", justify="center", width=13, no_wrap=True)
    t.add_column("Ruolo", justify="center", width=16, no_wrap=False)
    t.add_column("Tag Difensivi", ratio=3, no_wrap=False)

    if not team_cards:
        return t

    # Pre-calculate designated battle rotation roles if 6-card team
    rot_role_map: dict[int, str] = {}
    if len(team_cards) == 6:
        try:
            rot_a, rot_b, floaters = optimize_rotations_for_team(team_cards)
            rot_role_map[rot_a.slot1.id] = "Slot 1 Tank (Rot A)"
            rot_role_map[rot_a.slot2.id] = (
                "Slot 2 Stacker (Rot A)"
                if rot_a.slot2.has_stacking_def
                or (
                    rot_a.slot2.base_form
                    and rot_a.slot2.base_form.sa_tags
                    and rot_a.slot2.base_form.sa_tags.stacks_def
                )
                else "Slot 2 DPS (Rot A)"
            )
            rot_role_map[rot_b.slot1.id] = "Slot 1 Tank (Rot B)"
            rot_role_map[rot_b.slot2.id] = (
                "Slot 2 Stacker (Rot B)"
                if rot_b.slot2.has_stacking_def
                or (
                    rot_b.slot2.base_form
                    and rot_b.slot2.base_form.sa_tags
                    and rot_b.slot2.base_form.sa_tags.stacks_def
                )
                else "Slot 2 DPS (Rot B)"
            )
            for fl in floaters:
                if fl.has_support or (
                    fl.base_form
                    and fl.base_form.passive_tags
                    and fl.base_form.passive_tags.has_support
                ):
                    fl_role = "Floater (Support)"
                elif fl.has_stacking_def or (
                    fl.base_form and fl.base_form.sa_tags and fl.base_form.sa_tags.stacks_def
                ):
                    fl_role = "Floater (Stacker)"
                else:
                    fl_role = "Floater (Slot 3)"
                rot_role_map[fl.id] = fl_role
        except Exception:
            pass

    for idx, c in enumerate(team_cards, start=1):
        slot_str = str(idx)
        color = c.element_color
        type_str = c.element_name if c.element_name else c.type_tag

        clean_name = " ".join(c.name.split())
        clean_sub = " ".join(c.subname.split()) if c.subname else ""
        name_str = f"{clean_name} ({clean_sub})" if clean_sub else clean_name

        # Leader Boost
        if idx == 1:
            if lead:
                is_cov, boost_val, _ = lead.is_covered_by_leader(lead)
                if is_cov:
                    boost_style = "bold green" if boost_val >= 200 else "bold cyan"
                    boost_text = Text(f"{int(boost_val)}% (Lead)", style=boost_style)
                elif lead.leader_spec:
                    boost_style = (
                        "bold green" if lead.leader_spec.base_boost_pct >= 200 else "bold cyan"
                    )
                    boost_text = Text(
                        f"{lead.leader_spec.base_boost_pct}% (Lead)", style=boost_style
                    )
                else:
                    boost_text = Text("Leader", style="bold cyan")
            else:
                boost_text = Text("Leader", style="bold cyan")
        else:
            if lead:
                is_cov, boost_val, _ = c.is_covered_by_leader(lead)
                if is_cov:
                    boost_style = "bold green" if boost_val >= 200 else "cyan"
                    boost_text = Text(f"{int(boost_val)}%", style=boost_style)
                else:
                    boost_text = Text("0%", style="dim red")
            else:
                boost_text = Text("N/A", style="dim")

        # Ruolo (Designated battle role or individual archetype)
        if c.id in rot_role_map:
            role_label = rot_role_map[c.id]
            if "Slot 1 Tank" in role_label:
                role_text = Text(role_label, style="bold cyan")
            elif "Slot 2" in role_label:
                role_text = Text(role_label, style="bold green")
            else:
                role_text = Text(role_label, style="dim yellow")
        else:
            is_s1 = DokkanConstraintSolver.is_slot1_viable(c)
            stacks = bool(
                (c.base_form and c.base_form.sa_tags and c.base_form.sa_tags.stacks_def)
                or c.has_stacking_def
            )
            if is_s1 and stacks:
                role_text = Text("Slot 1 Viable / Stacker", style="bold cyan")
            elif is_s1:
                role_text = Text("Slot 1 Viable", style="bold cyan")
            elif stacks:
                role_text = Text("Stacker", style="bold yellow")
            else:
                role_text = Text("Floater", style="dim")

        # Tag Difensivi
        has_guard = c.has_guard or bool(
            c.base_form and c.base_form.passive_tags and c.base_form.passive_tags.has_guard
        )
        is_guard_perm = getattr(c, "is_guard_permanent", False)
        is_guard_uncond = getattr(c, "is_guard_unconditional", False)
        guard_limit = getattr(c, "guard_turns_limit", None)
        if is_guard_perm and is_guard_uncond:
            guard_part = "Guard (Perm)"
        elif is_guard_perm:
            guard_part = "Guard (Cond)"
        elif guard_limit:
            guard_part = f"Guard ({guard_limit}T)"
        elif has_guard:
            guard_part = "Guard"
        else:
            guard_part = "No Guard"

        dr_pct = max(
            c.damage_reduction_percent,
            c.base_form.passive_tags.dr_base_percent
            if c.base_form and c.base_form.passive_tags
            else 0,
        )
        dr_limit = getattr(c, "dr_turns_limit", None)
        perm_dr = getattr(c, "permanent_damage_reduction_percent", 0)
        if dr_pct > 0:
            if perm_dr == dr_pct and getattr(c, "is_dr_permanent", False):
                dr_part = f"DR {dr_pct}% (Perm)"
            elif dr_limit:
                dr_part = f"DR {dr_pct}% ({dr_limit}T)"
            else:
                dr_part = f"DR {dr_pct}%"
        else:
            dr_part = "DR 0%"

        dodge_pct = c.dodge_chance_percent
        dodge_limit = getattr(c, "dodge_turns_limit", None)
        cancels_dodge_boss = bool(
            boss_stage
            and any(getattr(p, "cancels_dodge", False) for p in getattr(boss_stage, "phases", []))
        )
        if dodge_pct > 0:
            if cancels_dodge_boss:
                dodge_part = f"Dodge {dodge_pct}% [Nullificato]"
            elif dodge_limit:
                dodge_part = f"Dodge {dodge_pct}% ({dodge_limit}T)"
            else:
                dodge_part = f"Dodge {dodge_pct}%"
        else:
            dodge_part = "Dodge 0%"

        def_tags_str = f"{guard_part} / {dr_part} / {dodge_part}"

        t.add_row(
            slot_str,
            Text(type_str, style=color),
            Text(name_str, style=color),
            boost_text,
            role_text,
            def_tags_str,
        )

    return t


def format_stage_tactical_briefing(boss_stage: Any, language: str = "it") -> str:
    """Formats complete multi-battle stage intelligence, HP, ATK, actions, immunities, and skills."""
    if not boss_stage:
        return ""
    lines: list[str] = []
    total_battles = getattr(boss_stage, "total_battles", 1)
    is_multi_battle = getattr(boss_stage, "is_multi_battle", False)
    phases = getattr(boss_stage, "phases", [])

    if language == "it":
        lines.append(
            f"**Evento**: {boss_stage.event_name} | **Stage**: {boss_stage.stage_name} (ID: {boss_stage.stage_id})"
        )
        lines.append(
            f"- **Struttura Evento**: {total_battles} Battagli{'a' if total_battles == 1 else 'e'} distinte ({len(phases)} Fasi totali)"
        )
        if is_multi_battle:
            lines.append(
                "> ⚠️ **AVVISO MECCANICA DI GIOCO (RESET STACKING)**: Questo evento è suddiviso in "
                f"{total_battles} battaglie separate! Lo stacking permanente di ATK e DEF "
                "NON si conserva tra una battaglia e l'altra (si azzera a 0 all'inizio di ogni battaglia). "
                "I bonus 'Entrance Animation' si riattivano all'inizio di ciascuna battaglia."
            )
        lines.append("\n**Scheda Dettagliata Battaglie & Fasi Boss**:")
        for p in phases:
            hp_val = getattr(p, "hp", 0)
            atk_val = getattr(p, "atk", 0)
            sa_est_val = getattr(p, "estimated_sa_damage", 0)
            actions_val = getattr(p, "actions_per_turn", 0)
            skills = getattr(p, "special_skills", [])

            hp_str = (
                f"{hp_val / 1_000_000:.0f}M"
                if hp_val >= 1_000_000
                else (f"{hp_val:,}" if hp_val else "N/A")
            )
            atk_str = (
                f"{atk_val / 1_000:.0f}k"
                if atk_val >= 1_000
                else (str(atk_val) if atk_val else "N/A")
            )
            sa_est = (
                f"~{sa_est_val / 1_000_000:.1f}M"
                if sa_est_val >= 1_000_000
                else (f"~{sa_est_val:,}" if sa_est_val else "N/A")
            )
            actions_str = f"{actions_val} attacchi/turno" if actions_val else "Attacchi standard"
            skills_str = ", ".join(skills) if skills else "Nessuna abilità speciale rilevata"
            stacking_note = (
                "Inizio evento (stacking da 0)"
                if getattr(p, "phase_index", 1) == 1
                else (
                    "⚠️ NUOVA BATTAGLIA (Stacking azzerato a 0!)"
                    if getattr(p, "is_new_battle", False)
                    else "Stacking conservato dalla fase precedente"
                )
            )

            is_multi = getattr(p, "is_multi_enemy", False)
            if is_multi:
                e_cnt = getattr(p, "enemy_count", len(getattr(p, "bosses", [])))
                header = (
                    f"- **Battaglia {getattr(p, 'battle_index', 1)} - Round {getattr(p, 'round_index', 1)} (Fase {getattr(p, 'phase_index', 1)})**: "
                    f"👥 {e_cnt} Nemici [{getattr(p, 'element_name', '')}]"
                )
                lines.append(header)
                lines.append(
                    f"  - **HP Totali**: {hp_str} | **ATK Base (Fase)**: {atk_str} (Super Attack stimata: {sa_est}) | **Azioni Totali**: {actions_str}"
                )
                lines.append(f"  - **Abilità & Gimmick**: {skills_str}")
                lines.append(f"  - **Stato Stacking**: {stacking_note}")
                lines.append("  - **Nemici Presenti**:")
                for b in getattr(p, "bosses", []):
                    b_sub = f" ({b.subname})" if getattr(b, "subname", None) else ""
                    b_hp = (
                        f"{b.hp / 1_000_000:.0f}M"
                        if b.hp >= 1_000_000
                        else (f"{b.hp:,}" if b.hp else "N/A")
                    )
                    b_atk = (
                        f"{b.atk / 1_000:.0f}k"
                        if b.atk >= 1_000
                        else (str(b.atk) if b.atk else "N/A")
                    )
                    lines.append(
                        f"    - **{b.name}{b_sub}** [{b.type_name}]: HP {b_hp}, ATK {b_atk}"
                    )
                lines.append(
                    f"  - 💡 CONSIGLIO TATTICO: La fase contiene {e_cnt} nemici simultanei. "
                    "Personaggi con Super Attacchi AoE o con Guardia incondizionata eccellono qui per ripulire rapidamente il campo!"
                )
            else:
                b = p.bosses[0] if getattr(p, "bosses", None) else None
                b_name = b.name if b else "Boss"
                sub = f" ({b.subname})" if b and getattr(b, "subname", None) else ""
                lines.append(
                    f"- **Battaglia {getattr(p, 'battle_index', 1)} - Round {getattr(p, 'round_index', 1)} (Fase {getattr(p, 'phase_index', 1)})**: "
                    f"**{b_name}{sub}** [{getattr(p, 'element_name', '')}]\n"
                    f"  - **HP**: {hp_str} | **ATK Base**: {atk_str} (Super Attack stimata: {sa_est}) | **Azioni**: {actions_str}\n"
                    f"  - **Abilità & Gimmick**: {skills_str}\n"
                    f"  - **Stato Stacking**: {stacking_note}"
                )
    else:
        lines.append(
            f"**Event**: {boss_stage.event_name} | **Stage**: {boss_stage.stage_name} (ID: {boss_stage.stage_id})"
        )
        lines.append(
            f"- **Event Structure**: {total_battles} Distinct Battle(s) ({len(phases)} Total Phases)"
        )
        if is_multi_battle:
            lines.append(
                "> ⚠️ **CRITICAL GAME MECHANIC (STACKING RESET)**: This stage consists of "
                f"{total_battles} separate battles! Permanent ATK & DEF stacking "
                "DOES NOT carry over between battles (it resets to 0 at the start of each battle). "
                "Entrance Animations re-trigger upon entry in each battle."
            )
        lines.append("\n**Detailed Battles, Phases, Damage & Boss Gimmicks**:")
        for p in phases:
            hp_val = getattr(p, "hp", 0)
            atk_val = getattr(p, "atk", 0)
            sa_est_val = getattr(p, "estimated_sa_damage", 0)
            actions_val = getattr(p, "actions_per_turn", 0)
            skills = getattr(p, "special_skills", [])

            hp_str = (
                f"{hp_val / 1_000_000:.0f}M"
                if hp_val >= 1_000_000
                else (f"{hp_val:,}" if hp_val else "N/A")
            )
            atk_str = (
                f"{atk_val / 1_000:.0f}k"
                if atk_val >= 1_000
                else (str(atk_val) if atk_val else "N/A")
            )
            sa_est = (
                f"~{sa_est_val / 1_000_000:.1f}M"
                if sa_est_val >= 1_000_000
                else (f"~{sa_est_val:,}" if sa_est_val else "N/A")
            )
            actions_str = f"{actions_val} attacks/turn" if actions_val else "Standard actions"
            skills_str = ", ".join(skills) if skills else "No special skills detected"
            stacking_note = (
                "Stage start (0 stacks)"
                if getattr(p, "phase_index", 1) == 1
                else (
                    "⚠️ NEW BATTLE: DEF stacks reset to 0!"
                    if getattr(p, "is_new_battle", False)
                    else "Stacks carried over from previous phase"
                )
            )

            is_multi = getattr(p, "is_multi_enemy", False)
            if is_multi:
                e_cnt = getattr(p, "enemy_count", len(getattr(p, "bosses", [])))
                header = (
                    f"- **Battle {getattr(p, 'battle_index', 1)} - Round {getattr(p, 'round_index', 1)} (Phase {getattr(p, 'phase_index', 1)})**: "
                    f"👥 {e_cnt} Enemies [{getattr(p, 'element_name', '')}]"
                )
                lines.append(header)
                lines.append(
                    f"  - **Total HP**: {hp_str} | **Phase Base ATK**: {atk_str} (Estimated Super Attack: {sa_est}) | **Total Actions**: {actions_str}"
                )
                lines.append(f"  - **Skills & Gimmicks**: {skills_str}")
                lines.append(f"  - **Stacking Status**: {stacking_note}")
                lines.append("  - **Enemies Present**:")
                for b in getattr(p, "bosses", []):
                    b_sub = f" ({b.subname})" if getattr(b, "subname", None) else ""
                    b_hp = (
                        f"{b.hp / 1_000_000:.0f}M"
                        if b.hp >= 1_000_000
                        else (f"{b.hp:,}" if b.hp else "N/A")
                    )
                    b_atk = (
                        f"{b.atk / 1_000:.0f}k"
                        if b.atk >= 1_000
                        else (str(b.atk) if b.atk else "N/A")
                    )
                    lines.append(
                        f"    - **{b.name}{b_sub}** [{b.type_name}]: HP {b_hp}, ATK {b_atk}"
                    )
                lines.append(
                    f"  - 💡 TACTICAL ADVICE: Phase contains {e_cnt} simultaneous enemies. "
                    "AoE Super Attack units and unconditional Guard units excel here to wipe out targets quickly!"
                )
            else:
                b = p.bosses[0] if getattr(p, "bosses", None) else None
                b_name = b.name if b else "Boss"
                sub = f" ({b.subname})" if b and getattr(b, "subname", None) else ""
                lines.append(
                    f"- **Battle {getattr(p, 'battle_index', 1)} - Round {getattr(p, 'round_index', 1)} (Phase {getattr(p, 'phase_index', 1)})**: "
                    f"**{b_name}{sub}** [{getattr(p, 'element_name', '')}]\n"
                    f"  - **HP**: {hp_str} | **Normal ATK**: {atk_str} (Estimated Super Attack: {sa_est}) | **Actions**: {actions_str}\n"
                    f"  - **Skills & Gimmicks**: {skills_str}\n"
                    f"  - **Stacking Status**: {stacking_note}"
                )
    return "\n".join(lines)


def render_stage_intel_rich(boss_stage: Any) -> Any:
    """Renders a rich table of complete stage intelligence: Battles, HP, ATK, Actions, Immunities, and Stacking."""
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    total_battles = getattr(boss_stage, "total_battles", 1)
    is_multi_battle = getattr(boss_stage, "is_multi_battle", False)
    phases = getattr(boss_stage, "phases", [])

    title = f"🎯 Stage Intelligence: {boss_stage.event_name} - {boss_stage.stage_name} ({total_battles} Battagli{'e' if total_battles > 1 else 'a'})"
    t = Table(show_header=True, header_style="bold magenta", expand=True)
    t.add_column("Fase", style="bold cyan", width=12, no_wrap=True)
    t.add_column("Boss Nemico", style="bold", ratio=4, no_wrap=False)
    t.add_column("HP", justify="right", style="green", width=7, no_wrap=True)
    t.add_column("ATK / Super", justify="right", style="yellow", width=13, no_wrap=True)
    t.add_column("Azioni", justify="center", width=7, no_wrap=True)
    t.add_column("Gimmick & Immunità", style="white", ratio=4, no_wrap=False)
    t.add_column("Stacking DEF", justify="center", width=12, no_wrap=False)

    for p in phases:
        phase_label = f"B{getattr(p, 'battle_index', 1)} - R{getattr(p, 'round_index', 1)} (F{getattr(p, 'phase_index', 1)})"

        elem_name = getattr(p, "element_name", "")
        elem_color = (
            "bold green"
            if "TEQ" in elem_name
            else (
                "bold blue"
                if "AGL" in elem_name
                else (
                    "bold red"
                    if "STR" in elem_name
                    else ("bold yellow" if "PHY" in elem_name else "bold magenta")
                )
            )
        )

        is_multi = getattr(p, "is_multi_enemy", False)
        if is_multi:
            e_cnt = getattr(p, "enemy_count", len(getattr(p, "bosses", [])))
            boss_text = Text()
            boss_text.append(f"👥 {e_cnt} Nemici ({elem_name})\n", style="bold cyan")
            for idx, b in enumerate(getattr(p, "bosses", [])):
                b_color = (
                    "green"
                    if "TEQ" in b.type_name
                    else (
                        "blue"
                        if "AGL" in b.type_name
                        else (
                            "red"
                            if "STR" in b.type_name
                            else ("yellow" if "PHY" in b.type_name else "magenta")
                        )
                    )
                )
                boss_text.append(f"• [{b.type_name}] {b.name}", style=b_color)
                if idx < len(p.bosses) - 1:
                    boss_text.append("\n")
        else:
            b = p.bosses[0] if getattr(p, "bosses", None) else None
            b_name = b.name if b else "Boss"
            boss_text = Text(f"[{elem_name}] {b_name}", style=elem_color)

        hp_val = getattr(p, "hp", 0)
        atk_val = getattr(p, "atk", 0)
        sa_val = getattr(p, "estimated_sa_damage", 0)
        act_val = getattr(p, "actions_per_turn", 0)
        skills = getattr(p, "special_skills", [])

        hp_str = (
            f"{hp_val / 1_000_000:.0f}M"
            if hp_val >= 1_000_000
            else (f"{hp_val:,}" if hp_val else "-")
        )
        atk_str = f"{atk_val / 1_000:.0f}k / ~{sa_val / 1_000_000:.1f}M" if atk_val else "-"
        act_str = f"{act_val}/t" if act_val else "-"
        gimmicks_str = ", ".join(skills) if skills else "Nessuna"

        p_idx = getattr(p, "phase_index", 1)
        is_new = getattr(p, "is_new_battle", False)
        if p_idx == 1:
            stack_text = Text("Inizio (0)", style="dim")
        elif is_new:
            stack_text = Text("⚠️ Reset a 0!", style="bold red")
        else:
            stack_text = Text("Mantiene", style="bold green")

        t.add_row(
            phase_label,
            boss_text,
            hp_str,
            atk_str,
            act_str,
            gimmicks_str,
            stack_text,
        )

    if is_multi_battle:
        from rich.console import Group

        warning_text = (
            "[bold yellow]⚠️ NOTA MULTI-BATTAGLIA:[/bold yellow] "
            "[bold red]Lo Stacking di ATK e DEF si AZZERA all'inizio di ciascuna nuova battaglia "
            "(i buff accumulati NON si trasferiscono tra Battaglia 1, 2 e 3)![/bold red]\n"
            "[dim]Le rotazioni A e B sono coppie d'ancoraggio sinergiche: puoi e devi adattarle "
            "dinamicamente in base ai tipi e agli attacchi di ogni fase.[/dim]\n"
        )
        content = Group(warning_text, t)
    else:
        content = t

    return Panel(
        content,
        title=title,
        subtitle=f"[dim]Fasi totali: {len(phases)} | Difficoltà: {getattr(boss_stage, 'difficulty', 1)}[/dim]",
        border_style="cyan",
    )


def format_card_for_strategy(card: DokkanCard) -> str:
    """Formats card name and key kit mechanics for tactical strategy analysis."""
    tags = []
    if card.has_guard:
        tags.append("Guardia garantita")
    dr_pct = getattr(card, "damage_reduction_percent", 0)
    if dr_pct > 0:
        tags.append(f"Riduzione danno {dr_pct}%")
    elif getattr(card, "has_damage_reduction", False):
        tags.append("Riduzione danno")
    if getattr(card, "has_stacking_def", False):
        tags.append("Stacking DEF")
    if getattr(card, "has_target_taunt", False):
        tags.append("Taunt/Bersaglio")
    if getattr(card, "has_dodge", False):
        tags.append("Schivata")
    if getattr(card, "has_active_skill", False):
        tags.append("Active Skill")
    if getattr(card, "has_standby", False):
        tags.append("Standby")
    if getattr(card, "has_revive", False):
        tags.append("Revive")
    if getattr(card, "has_support", False):
        tags.append("Supporto alleati")
    if getattr(card, "has_orb_changing", False):
        tags.append("Cambia-orbi")

    kit_desc = f" [Kit: {', '.join(tags)}]" if tags else ""
    return f"{card.full_name}{kit_desc}"


def generate_deterministic_tactical_guide(
    rot_a: Any,
    rot_b: Any,
    floaters: list[DokkanCard],
    leader: DokkanCard,
    friend: DokkanCard,
) -> str:
    """Generates the clean algorithmic fallback guide adhering to standard tactical structure."""

    def _name_with_badge(c: DokkanCard) -> str:
        badge = ""
        if c is friend or getattr(c, "is_friend_leader", False):
            badge = " [Friend Leader]"
        elif c is leader:
            badge = " [Leader]"
        return f"{c.name}{badge}"

    return (
        f"### 🛡️ Piano Tattico Deterministico - Rotazioni\n"
        f"- **Rotazione A**: Mantieni **{_name_with_badge(rot_a.slot1)}** in Slot 1 come difensore primario. **{_name_with_badge(rot_a.slot2)}** in Slot 2 attiva {len(rot_a.shared_links)} link e massimizza i danni.\n"
        f"- **Rotazione B**: **{_name_with_badge(rot_b.slot1)}** in Slot 1 assorbe i colpi diretti. **{_name_with_badge(rot_b.slot2)}** in Slot 2 guida la fase offensiva.\n"
        f"- **Floaters (Slot 3)**: Fai ruotare **{', '.join(_name_with_badge(f) for f in floaters)}** in Slot 3 per Ki support, gestione orbi e rotazione difensiva.\n\n"
        f"### 💊 Gestione Oggetti di Supporto\n"
        f"- **Whis**: Attivalo nei turni ad alto rischio o contro la Super Attack nemica per ridurre il danno del 40% per 2 turni.\n"
        f"- **Ghost Usher**: Usalo se il floater in Slot 3 subisce troppi attacchi o per saltare un turno critico del boss.\n"
        f"- **Princess Snake**: Usalo per recuperare il 55% di HP e ottenere il 30% di riduzione danno nei turni di emergenza."
    )


__all__ = [
    "format_team_summary_table",
    "render_team_summary_table_rich",
    "format_stage_tactical_briefing",
    "render_stage_intel_rich",
    "format_card_for_strategy",
    "generate_deterministic_tactical_guide",
    "_get_global_category_map",
    "_resolve_category_name",
]
