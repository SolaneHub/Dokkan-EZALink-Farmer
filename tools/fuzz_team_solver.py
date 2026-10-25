"""Generative Fuzzer CLI tool for DokkanConstraintSolver robustness testing.

Procedurally generates user box configurations and mission constraints to stress-test
the constraint solver against invariant properties:
- Zero unexpected crashes (only graceful ValueError for mathematically impossible pools).
- Exactly 6 unique cards per recommended team (no duplicate IDs).
- Complete fulfillment of hard mission constraints when a team is successfully produced.
- Graceful degradation when candidate box cannot satisfy constraints.
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from dataclasses import dataclass

from dokkan_eza_link_farmer.ai.mission_solver import MissionBatch
from dokkan_eza_link_farmer.ai.models import (
    CardForm,
    DokkanCard,
    LeaderSkillSpec,
    PassiveTags,
)
from dokkan_eza_link_farmer.ai.solver import DokkanConstraintSolver

# Plausible Dokkan categories (name, standard category_id)
COMMON_CATEGORIES: list[tuple[str, int]] = [
    ("Realm of Gods", 8),
    ("Pure Saiyans", 1),
    ("Hybrid Saiyans", 2),
    ("Time Travelers", 17),
    ("Future Saga", 19),
    ("Universal Survival Saga", 15),
    ("Majin Buu Saga", 9),
    ("Androids/Cell Saga", 38),
    ("Movie Heroes", 29),
    ("Movie Bosses", 30),
]

# Elements: 10..14 (Super AGL, TEQ, INT, STR, PHY), 20..24 (Extreme AGL, TEQ, INT, STR, PHY)
ELEMENT_CLASSES = [
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


@dataclass
class FuzzResult:
    """Result summary of a single fuzz run."""

    run_index: int
    box_size: int
    mission_desc: str
    status: str  # "SOLVED", "UNSATISFIABLE"
    team_ids: list[int]
    error_message: str | None = None


def generate_random_card(card_id: int, rng: random.Random) -> DokkanCard:
    """Procedurally generates a DokkanCard with realistic Dokkan properties."""
    elem, c_class = rng.choice(ELEMENT_CLASSES)
    num_cats = rng.randint(1, 4)
    chosen_cats = rng.sample(COMMON_CATEGORIES, k=min(num_cats, len(COMMON_CATEGORIES)))
    cat_names = [c[0] for c in chosen_cats]
    cat_ids = [c[1] for c in chosen_cats]

    # ~35% chance to be a leader with 170% or 200% boost
    is_leader = rng.random() < 0.35
    leader_spec = None
    leader_skill_str = ""
    if is_leader:
        main_cat_ids = [rng.choice(cat_ids)]
        base_boost = rng.choice([170.0, 200.0, 220.0])
        extra_boost = 30.0 if base_boost < 220.0 and rng.random() < 0.5 else 0.0
        extra_cat_ids = [rng.choice(cat_ids)] if extra_boost > 0 else []
        leader_spec = LeaderSkillSpec(
            main_category_ids=main_cat_ids,
            extra_category_ids=extra_cat_ids,
            base_boost_pct=base_boost,
            extra_boost_pct=extra_boost,
        )
        leader_skill_str = f"Category Ki +3, HP, ATK & DEF +{int(base_boost)}%"

    # Defensive capabilities (guard, dr, dodge, slot 1)
    has_guard = rng.random() < 0.25
    dr_base = rng.choice([0, 0, 20, 30, 50, 70])
    dodge_chance = rng.choice([0, 0, 30, 50, 70])

    passive_text_parts: list[str] = []
    if has_guard:
        passive_text_parts.append("Guards all attacks")
    if dr_base > 0:
        passive_text_parts.append(f"Reduces damage received by {dr_base}%")
    if dodge_chance > 0:
        passive_text_parts.append(f"High chance of evading enemy's attack ({dodge_chance}%)")

    passive_text = "; ".join(passive_text_parts)

    return DokkanCard(
        id=card_id,
        name=f"Fuzz Warrior #{card_id}",
        element=elem,
        card_class=c_class,
        categories=cat_names,
        category_ids=cat_ids,
        leader_skill=leader_skill_str,
        leader_spec=leader_spec,
        passive_skill=passive_text,
        base_form=CardForm(
            form_id=card_id,
            form_index=0,
            form_name=f"Fuzz Warrior #{card_id}",
            element=elem,
            passive_tags=PassiveTags(
                has_guard=has_guard,
                dr_base_percent=dr_base,
                dodge_chance_percent=dodge_chance,
            ),
        ),
    )


def generate_random_box(size: int, rng: random.Random) -> list[DokkanCard]:
    """Generates a randomized box of unique DokkanCards."""
    start_id = rng.randint(1000, 900000)
    cards: list[DokkanCard] = []
    for i in range(size):
        cards.append(generate_random_card(start_id + i, rng))
    return cards


def generate_random_mission(rng: random.Random) -> tuple[MissionBatch | None, str]:
    """Generates random mission constraints including extreme and edge-case combinations."""
    mission_type = rng.choice(
        [
            "none",
            "category_partial",
            "category_full",
            "rainbow",
            "super_class",
            "extreme_class",
            "rainbow_super",
            "category_and_rainbow",
        ]
    )

    if mission_type == "none":
        return None, "No Mission Constraints"

    if mission_type == "category_partial":
        cat_name, _ = rng.choice(COMMON_CATEGORIES)
        req_count = rng.randint(1, 5)
        batch = MissionBatch(missions=[], required_categories=[(req_count, cat_name)])
        return batch, f"{req_count}x '{cat_name}'"

    if mission_type == "category_full":
        cat_name, _ = rng.choice(COMMON_CATEGORIES)
        batch = MissionBatch(missions=[], required_categories=[(6, cat_name)])
        return batch, f"6x '{cat_name}' (Full Team)"

    if mission_type == "rainbow":
        batch = MissionBatch(missions=[], requires_rainbow=True)
        return batch, "Rainbow (5 Types)"

    if mission_type == "super_class":
        batch = MissionBatch(missions=[], requires_all_super=True)
        return batch, "Super Class Only"

    if mission_type == "extreme_class":
        batch = MissionBatch(missions=[], requires_all_extreme=True)
        return batch, "Extreme Class Only"

    if mission_type == "rainbow_super":
        batch = MissionBatch(missions=[], requires_rainbow=True, requires_all_super=True)
        return batch, "Rainbow + Super Class"

    if mission_type == "category_and_rainbow":
        cat_name, _ = rng.choice(COMMON_CATEGORIES)
        req_count = rng.randint(2, 4)
        batch = MissionBatch(
            missions=[], required_categories=[(req_count, cat_name)], requires_rainbow=True
        )
        return batch, f"{req_count}x '{cat_name}' + Rainbow"

    return None, "Default"


def execute_fuzz_run(
    solver: DokkanConstraintSolver,
    run_idx: int,
    box_size: int,
    rng: random.Random,
) -> FuzzResult:
    """Executes a single fuzz cycle against black-box invariant checks."""
    box = generate_random_box(box_size, rng)
    mission_batch, mission_desc = generate_random_mission(rng)

    try:
        res = solver.solve(box, mission_batch=mission_batch)
    except ValueError as e:
        # Graceful degradation when pool cannot mathematically satisfy criteria
        return FuzzResult(
            run_index=run_idx,
            box_size=box_size,
            mission_desc=mission_desc,
            status="UNSATISFIABLE",
            team_ids=[],
            error_message=str(e),
        )

    # Invariant 1: Exactly 6 cards
    assert len(res.team_cards) == 6, f"Team must have exactly 6 cards, got {len(res.team_cards)}"

    # Invariant 2: Strictly unique cards (no duplicate IDs)
    team_ids = [c.id for c in res.team_cards]
    assert len(set(team_ids)) == 6, f"Duplicate card IDs detected in team: {team_ids}"

    # Invariant 3: Leader is the first card
    assert res.leader.id == res.team_cards[0].id, "First card in team must be the leader"

    # Invariant 4: If mission constraints were provided, verify compliance
    if mission_batch is not None:
        # Required categories
        for req_cnt, cat_name in getattr(mission_batch, "required_categories", []):
            c_name_lower = cat_name.strip().lower()
            matching_count = sum(
                1
                for c in res.team_cards
                if any(cat.strip().lower() == c_name_lower for cat in c.categories)
            )
            assert matching_count >= req_cnt, (
                f"Mission category constraint violated: expected >= {req_cnt} of '{cat_name}', "
                f"found {matching_count}"
            )

        # Rainbow requirement (5 distinct types)
        if getattr(mission_batch, "requires_rainbow", False):
            unique_types = {c.element % 10 for c in res.team_cards}
            assert len(unique_types) == 5, (
                f"Rainbow constraint violated: expected 5 distinct types, got {len(unique_types)}"
            )

        # Super Class requirement
        if getattr(mission_batch, "requires_all_super", False):
            assert all(getattr(c, "card_class", "") == "Super" for c in res.team_cards), (
                "Super Class mission violated: non-Super cards found in team"
            )

        # Extreme Class requirement
        if getattr(mission_batch, "requires_all_extreme", False):
            assert all(getattr(c, "card_class", "") == "Extreme" for c in res.team_cards), (
                "Extreme Class mission violated: non-Extreme cards found in team"
            )

    return FuzzResult(
        run_index=run_idx,
        box_size=box_size,
        mission_desc=mission_desc,
        status="SOLVED",
        team_ids=team_ids,
    )


def run_fuzzer(
    num_runs: int = 50,
    min_box: int = 10,
    max_box: int = 100,
    seed: int = 42,
    verbose: bool = False,
) -> tuple[int, int, float]:
    """Runs generative fuzzing across arbitrary box sizes and mission constraints."""
    rng = random.Random(seed)
    solver = DokkanConstraintSolver()

    start_time = time.perf_counter()
    solved_count = 0
    unsat_count = 0

    for i in range(num_runs):
        box_size = rng.randint(min_box, max_box)
        result = execute_fuzz_run(solver, i + 1, box_size, rng)

        if result.status == "SOLVED":
            solved_count += 1
        else:
            unsat_count += 1

        if verbose:
            print(
                f"Run {result.run_index:03d} | Box: {result.box_size:3d} | "
                f"Mission: {result.mission_desc:<30} | {result.status}"
            )

    elapsed = time.perf_counter() - start_time
    return solved_count, unsat_count, elapsed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generative Fuzzer for DokkanConstraintSolver robustness validation."
    )
    parser.add_argument("--runs", type=int, default=50, help="Number of fuzz iterations (50-100)")
    parser.add_argument(
        "--min-box", type=int, default=10, help="Minimum random box size (default: 10)"
    )
    parser.add_argument(
        "--max-box", type=int, default=100, help="Maximum random box size (default: 100)"
    )
    parser.add_argument("--seed", type=int, default=42, help="RNG seed for reproducibility")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print detailed run logs")

    args = parser.parse_args()

    print(
        f"[FUZZER] Starting {args.runs} generative stress runs (box sizes: {args.min_box}-{args.max_box}, seed: {args.seed})..."
    )
    solved, unsat, elapsed = run_fuzzer(
        num_runs=args.runs,
        min_box=args.min_box,
        max_box=args.max_box,
        seed=args.seed,
        verbose=args.verbose,
    )

    print(
        f"[FUZZER] Completed {args.runs} runs in {elapsed:.3f}s (Avg: {elapsed / args.runs * 1000:.1f}ms/run)"
    )
    print(f"[FUZZER] Results: {solved} Solved Teams, {unsat} Graceful Degradations, 0 Crashes.")

    if elapsed > 3.0:
        print(f"[FUZZER WARNING] Execution time {elapsed:.3f}s exceeded target threshold (3.0s)")
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
