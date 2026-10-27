"""Tactical Dokkan Battle Keywords & Slot Optimization Rules (Post-10th Anniversary Meta).

Auto-generated from DokkanDB data analysis (353 cards released >= 2025-01-28).
Provides structured rules and prompt fragments for Qwen LLM advisor and rotation optimizer.
"""

TACTICAL_DAMAGE_FORMULA = (
    "{[(Enemy_ATK x Variance x Type_Modifier) x (1 - DR)] - Ally_DEF} x Guard_Reduction"
)

SLOT_1_MANDATORY_CRITERIA = [
    "Pre-attack Guard (Unconditional or Active on turn start without attacking)",
    "Damage Reduction >= 50% (prior to DEF subtraction)",
    "High start-of-turn DEF (>= 400k) with Guard, or >= 70% Damage Reduction",
    "Pre-attack high/great evasion (>= 70%)",
]

SLOT_1_ANTI_PATTERNS = [
    "Guards all attacks ONLY as 2nd or 3rd attacker in a turn",
    "DEF boost applied ONLY 'When attacking' or 'When performing a Super Attack'",
    "Guard/DR/Dodge conditional on Ki Spheres obtained ('with X or more Ki Spheres' / 'per Ki Sphere') - INACTIVE pre-attack in Slot 1!",
    "Heavy ramp-up dependency ('with each attack performed') with low base turn-1 stats",
    "Intro/entry-turn shield expired (Turn 5+ after a 3-turn intro)",
]

# Cards confirmed to have conditional guard/DR restricted to Slot 2/3
SLOT_2_3_LOCKED_IDS: set[int] = {1034271, 1034481, 1032331, 1030971, 1030481, 1030431}


def get_qwen_system_prompt_tactical_rules() -> str:
    """Returns compact tactical Dokkan rules to inject into Qwen system/user prompts."""
    return """### CRITICAL DOKKAN BATTLE TACTICAL RULES & SLOT ALLOCATION:
1. ORDER OF OPERATIONS DAMAGE FORMULA:
   Damage Taken = {[(Enemy ATK x Variance x Type_Mod) x (1 - DR)] - Ally DEF} x Guard_Mod
   - Damage Reduction (DR) applies BEFORE Ally DEF is subtracted.
   - Ally DEF is subtracted AFTER Damage Reduction.
   - Guard applies at the END (Type_Mod = 0.8, Guard_Mod = 0.5).
   - NAKED GUARD IS NOT ENOUGH: Against a 3M+ Boss Super Attack, a unit with Guard but NO DR and only 300k DEF will still take over 1,000,000 LETHAL damage!

2. SLOT 1 VIABILITY CRITERIA:
   - Must have PRE-ATTACK DEFENSE: Unconditional Guard, high DR (>= 50%), or pre-attack evasion (>= 70%).
   - NEVER put a card in Slot 1 if its Guard or DR is conditional on:
     * 'As the 2nd or 3rd attacker in a turn'
     * 'When attacking' / 'When performing a Super Attack'
     * 'With X or more Ki Spheres obtained' / 'Per Ki Sphere obtained' (INACTIVE pre-attack before collecting spheres!)
   - Watch out for Intro Turn Expiration: Units with 'For 3 turns from entry turn' lose their shield on Turn 5!

3. ROTATION ASSIGNMENTS:
   - Slot 1: Pure Wall / Pre-attack Tank / Taunt / Scouter.
   - Slot 2: Main Attacker / Heavy Link Partner / Stacker (protected by Slot 1).
   - Slot 3: Floater / Support (Allies' Ki & DEF) / High Evasion.

4. KI SPHERE CONDITIONAL DEFENSE & ORB HUNGER:
   - Ki Spheres are collected WHEN THE UNIT ATTACKS.
   - Therefore, Damage Reduction, Guard, or Dodge requiring Ki Spheres is INACTIVE pre-attack in Slot 1.
   - Orb-dependent units MUST be placed in Slot 2 or 3 to collect orbs first, and MUST be paired with Orb Changers (especially Rainbow Ki Sphere Changers) to guarantee their defensive buffs activate every turn without orb starvation.
"""
