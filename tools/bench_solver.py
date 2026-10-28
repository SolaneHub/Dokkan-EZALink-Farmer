#!/usr/bin/env python3
"""Micro-benchmark standalone CLI tool for DokkanConstraintSolver latency & throughput.

Measures:
1. Average solve latency for synthesizing a complete 6-card team from a synthetic 100-card box
   (target: < 15.0 ms).
2. Damage calculation throughput using calculate_damage_taken (target: > 100,000 calcs/sec).

Exits with code 0 if all performance targets are met, 1 otherwise.
"""

from __future__ import annotations

import sys
import time

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from dokkan_eza_link_farmer.ai.models import (
    CardForm,
    DokkanCard,
    LeaderSkillSpec,
    PassiveTags,
)
from dokkan_eza_link_farmer.ai.solver import DokkanConstraintSolver, calculate_damage_taken

TARGET_SOLVE_MS = 15.0
TARGET_THROUGHPUT_CALCS_PER_SEC = 100_000.0


def generate_benchmark_box(size: int = 100, seed: int = 42) -> list[DokkanCard]:
    """Generates a synthetic, deterministic box of Dokkan cards with realistic properties."""
    del seed
    categories_pool = [
        ("Pure Saiyans", 1),
        ("Hybrid Saiyans", 2),
        ("Realm of Gods", 8),
        ("Majin Buu Saga", 9),
        ("Movie Heroes", 29),
        ("Future Saga", 19),
        ("Universal Survival Saga", 15),
        ("Androids/Cell Saga", 38),
        ("Movie Bosses", 30),
        ("Time Travelers", 17),
    ]

    element_classes = [
        (10, "Super"),
        (11, "Super"),
        (12, "Super"),
        (13, "Super"),
        (14, "Super"),
        (20, "Extreme"),
        (21, "Extreme"),
        (22, "Extreme"),
        (23, "Extreme"),
        (24, "Extreme"),
    ]

    cards: list[DokkanCard] = []

    for i in range(size):
        card_id = 1000 + i
        elem, c_class = element_classes[i % len(element_classes)]

        # Category assignment: 1 primary category + 1 secondary
        primary_cat = categories_pool[i % len(categories_pool)]
        sec_idx = (i * 3 + 1) % len(categories_pool)
        secondary_cat = categories_pool[sec_idx]

        cat_names = [primary_cat[0]]
        cat_ids = [primary_cat[1]]
        if secondary_cat[1] != primary_cat[1]:
            cat_names.append(secondary_cat[0])
            cat_ids.append(secondary_cat[1])

        # Top 10 cards act as category leaders
        is_leader = i < 10
        leader_spec = None
        leader_skill_str = ""
        if is_leader:
            leader_spec = LeaderSkillSpec(
                main_category_ids=[primary_cat[1]],
                extra_category_ids=[],
                base_boost_pct=200.0,
                extra_boost_pct=0.0,
            )
            leader_skill_str = f"{primary_cat[0]} Category Ki +3, HP, ATK & DEF +200%"

        # Distribute defensive viability
        has_guard = (i % 3 == 0) or is_leader
        dr_base = 50 if (i % 4 == 0) else (30 if i % 2 == 0 else 0)
        dodge_chance = 50 if (i % 5 == 0) else 0

        # Structured domain card representation (base form tags pre-populated)
        card = DokkanCard(
            id=card_id,
            name=f"Bench Warrior #{card_id}",
            element=elem,
            card_class=c_class,
            categories=cat_names,
            category_ids=cat_ids,
            leader_skill=leader_skill_str,
            leader_spec=leader_spec,
            passive_skill="",
            base_form=CardForm(
                form_id=card_id,
                form_index=0,
                form_name=f"Bench Warrior #{card_id}",
                element=elem,
                passive_tags=PassiveTags(
                    slot1_viable=has_guard and dr_base >= 30,
                    has_guard=has_guard,
                    pre_hit_guard=has_guard,
                    dr_base_percent=dr_base,
                    pre_hit_dr_percent=dr_base,
                    dodge_chance_percent=dodge_chance,
                    team_conditional_buffs=[],
                ),
            ),
        )
        cards.append(card)

    return cards


def run_benchmark() -> int:
    """Executes the micro-benchmark and prints a Rich summary table."""
    console = Console()
    console.print(
        Panel.fit(
            "[bold cyan]Dokkan Battle AI Constraint Solver Micro-Benchmark[/bold cyan]\n"
            "[dim]Measures mathematical synthesis latency & damage calculation throughput[/dim]",
            border_style="cyan",
        )
    )

    # 1. Setup benchmark box
    box = generate_benchmark_box(size=100, seed=42)
    solver = DokkanConstraintSolver()

    # Warmup solver
    for _ in range(5):
        solver.solve(box)

    # Measure solver latency
    solve_iterations = 40
    solve_times: list[float] = []
    res = solver.solve(box)
    for _ in range(solve_iterations):
        t0 = time.perf_counter()
        res = solver.solve(box)
        solve_times.append(time.perf_counter() - t0)

    avg_solve_ms = (sum(solve_times) / len(solve_times)) * 1000.0
    min_solve_ms = min(solve_times) * 1000.0
    max_solve_ms = max(solve_times) * 1000.0

    # 2. Measure damage simulation throughput
    sim_iterations = 250_000
    # Warmup
    for _ in range(2_000):
        calculate_damage_taken(
            2_500_000,
            type_matchup=0,
            dr_pct=50,
            def_stat=300_000,
            has_passive_guard=True,
        )

    t0_sim = time.perf_counter()
    for _ in range(sim_iterations):
        calculate_damage_taken(
            2_500_000,
            type_matchup=0,
            dr_pct=50,
            def_stat=300_000,
            has_passive_guard=True,
        )
    sim_elapsed = time.perf_counter() - t0_sim
    throughput = sim_iterations / sim_elapsed if sim_elapsed > 0 else 0.0

    # Evaluate results against target criteria
    solve_passed = avg_solve_ms < TARGET_SOLVE_MS
    throughput_passed = throughput > TARGET_THROUGHPUT_CALCS_PER_SEC
    all_passed = solve_passed and throughput_passed

    table = Table(title="Micro-Benchmark Performance Metrics", border_style="blue")
    table.add_column("Benchmark Metric", style="bold white")
    table.add_column("Target Spec", justify="right")
    table.add_column("Measured Value", justify="right")
    table.add_column("Status", justify="center")

    table.add_row(
        "Team Solver Latency (Avg)",
        f"< {TARGET_SOLVE_MS:.1f} ms",
        f"{avg_solve_ms:.2f} ms [dim](min: {min_solve_ms:.2f}ms, max: {max_solve_ms:.2f}ms)[/dim]",
        "[bold green]PASS[/bold green]" if solve_passed else "[bold red]FAIL[/bold red]",
    )

    table.add_row(
        "Damage Engine Throughput",
        f"> {TARGET_THROUGHPUT_CALCS_PER_SEC:,.0f} calcs/s",
        f"{throughput:,.0f} calcs/s",
        "[bold green]PASS[/bold green]" if throughput_passed else "[bold red]FAIL[/bold red]",
    )

    table.add_row(
        "Synthesized Team Size",
        "6 unique units",
        f"{len(res.team_cards)} units (Leader: {res.leader.name})",
        "[bold green]PASS[/bold green]"
        if len(res.team_cards) == 6
        else "[bold red]FAIL[/bold red]",
    )

    console.print(table)

    if all_passed:
        console.print(
            "\n[bold green]✔ All mathematical solver performance targets satisfied successfully.[/bold green]\n"
        )
        return 0
    else:
        console.print(
            "\n[bold red]✖ Performance targets breached. Micro-benchmark failed.[/bold red]\n"
        )
        return 1


def main() -> None:
    code = run_benchmark()
    sys.exit(code)


if __name__ == "__main__":
    main()
