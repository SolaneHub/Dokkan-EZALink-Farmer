"""High-performance pure mathematical damage and guard calculation engine for Dokkan Battle.

Decoupled from solver.py to provide zero-overhead evaluation of incoming damage,
cyclic type wheel matchups, and guard mechanics.
"""

from __future__ import annotations

# Dokkan cyclic type effectiveness mapping: Base type ID % 10 (0: AGL, 1: TEQ, 2: INT, 3: STR, 4: PHY)
# Attacker element beats defender element:
# AGL (0) beats STR (3)
# STR (3) beats PHY (4)
# PHY (4) beats INT (2)
# INT (2) beats TEQ (1)
# TEQ (1) beats AGL (0)
ELEMENT_ADVANTAGE: dict[int, int] = {
    0: 3,  # AGL > STR
    3: 4,  # STR > PHY
    4: 2,  # PHY > INT
    2: 1,  # INT > TEQ
    1: 0,  # TEQ > AGL
}

ELEMENT_DISADVANTAGE: dict[int, int] = {
    0: 1,  # AGL < TEQ
    1: 2,  # TEQ < INT
    2: 4,  # INT < PHY
    3: 0,  # STR < AGL
    4: 3,  # PHY < STR
}


def check_type_matchup(attacker_type: int, defender_type: int) -> int:
    """Determines Dokkan Battle cyclic type effectiveness:
    AGL (0) > STR (3) > PHY (4) > INT (2) > TEQ (1) > AGL (0)

    Returns:
        +1: Attacker has type advantage
        -1: Attacker has type disadvantage
         0: Neutral matchup
    """
    attacker = attacker_type % 10
    defender = defender_type % 10

    if ELEMENT_ADVANTAGE.get(attacker) == defender:
        return 1
    if ELEMENT_DISADVANTAGE.get(attacker) == defender:
        return -1
    return 0


def calculate_damage_taken(
    enemy_atk: int,
    type_matchup: int = 0,
    has_passive_guard: bool = False,
    dr_pct: int | float = 0,
    def_stat: int | float = 0,
    is_super_vs_extreme: bool = True,
    variance: float = 1.0,
) -> int:
    """Calculates exact Dokkan Battle incoming damage using the official order of operations:
    Damage = {[(Enemy ATK * Variance * Type Modifier) * (1 - DR%)] - Ally DEF} * Guard Reduction

    Order of Operations & Mechanics:
    1. Type Modifier:
       - Passive Guard: Always 0.8 regardless of enemy typing or class.
       - Natural Advantage (Natural Guard): 0.9 (Super vs Extreme) or 1.0 (Same Class).
       - Neutral: 1.15 (Super vs Extreme) or 1.0 (Same Class).
       - Disadvantage: 1.5 (Super vs Extreme) or 1.25 (Same Class).
    2. Damage Reduction (DR%):
       - Multiplied BEFORE Ally DEF subtraction: compresses raw incoming boss attack.
    3. Ally DEF Subtraction:
       - Post-DEF = max(0, damage_before_def - def_stat).
    4. Guard Reduction:
       - If Passive Guard OR Natural Type Advantage: Guard Reduction = 0.5 (halving remainder).
       - Else: Guard Reduction = 1.0.
       - Final Damage = int(Post-DEF * Guard Reduction).
    """
    if has_passive_guard:
        type_mod = 0.8
        guard_reduction = 0.5
    elif type_matchup > 0:
        type_mod = 0.9 if is_super_vs_extreme else 1.0
        guard_reduction = 0.5
    elif type_matchup < 0:
        type_mod = 1.5 if is_super_vs_extreme else 1.25
        guard_reduction = 1.0
    else:
        type_mod = 1.15 if is_super_vs_extreme else 1.0
        guard_reduction = 1.0

    effective_dr = max(0.0, min(1.0, float(dr_pct) / 100.0))
    damage_before_def = enemy_atk * variance * type_mod * (1.0 - effective_dr)
    damage_after_def = max(0.0, damage_before_def - float(max(0, def_stat)))
    return int(damage_after_def * guard_reduction)


__all__ = [
    "ELEMENT_ADVANTAGE",
    "ELEMENT_DISADVANTAGE",
    "calculate_damage_taken",
    "check_type_matchup",
]
