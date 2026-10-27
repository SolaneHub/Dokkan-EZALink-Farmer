import pytest

from dokkan_eza_link_farmer.ai.card_models import DokkanCard
from dokkan_eza_link_farmer.ai.solver import DokkanConstraintSolver
from dokkan_eza_link_farmer.ai.syncer import parse_passive_tags
from dokkan_eza_link_farmer.ai.synergy import (
    calculate_slot1_anchor_weight,
    calculate_slot2_partner_weight,
    optimize_rotations_for_team,
)


@pytest.fixture
def pui_pui_card() -> DokkanCard:
    passive_text = (
        "*Basic effect(s)*\n"
        "- Ki +1 and ATK & DEF 100%{passiveImg:up_g}\n"
        "- Great chance of performing a critical hit\n"
        "- Medium chance of evading enemy's attack\n"
        "*When receiving an attack*\n"
        "- DEF 100%{passiveImg:up_g}\n"
        "*As the 1st attacker in a turn*\n"
        "- Great chance of ATK & DEF 713%{passiveImg:up_g}\n"
        "- Medium chance of DEF 4410%{passiveImg:up_g}\n"
        "- Damage reduction rate & chance of evading enemy's attack 40%{passiveImg:up_g}\n"
        "*As the 3rd attacker in a turn*\n"
        "- Chance of performing a critical hit, chance of evading enemy's\n"
        "attack & damage reduction rate 30%{passiveImg:up_g}\n"
        "- Great chance of ATK & DEF 713%{passiveImg:up_g} when attacking\n"
        "- High chance of ATK 4410%{passiveImg:up_g} when attacking with 12 or more Ki\n"
        '*When 4 or more "Majin Buu Saga" Category allies are on the team,\n'
        "or when all allies are Extreme Class characters*\n"
        "- Foresees enemy's Super Attack\n"
        "- Randomly changes Ki Spheres of a certain Type to Rainbow Ki Spheres\n"
        "- Chance of evading enemy's attack 10%{passiveImg:up_g}\n"
        "- Guards all attacks"
    )
    return DokkanCard(
        id=1033031,
        name="Pui Pui",
        subname="Warrior of Planet Zun",
        rarity=4,  # UR
        element=4,  # Extreme INT
        passive_skill=passive_text,
        categories=["Majin Buu Saga", "Space-Traveling Warriors", "Terrifying Conquerors"],
        category_ids=[24, 62, 53],
        links=["Brutal Beatdown", "Shocking Speed", "Nightmare", "Infighter"],
    )


@pytest.fixture
def gotenks_eza_card() -> DokkanCard:
    passive_text = (
        "*Basic effect(s)*\n"
        "- Ki +3 and ATK & DEF 150%{passiveImg:up_g}\n"
        "- Great chance of evading enemy's attack\n"
        "*As the 2nd or 3rd attacker in a turn*\n"
        "- Plus an additional ATK & DEF 100%{passiveImg:up_g}\n"
        "- Launches an additional attack that has a high chance of becoming a Super Attack"
    )
    return DokkanCard(
        id=1028831,
        name="Gotenks",
        subname="Double the Power",
        rarity=4,  # UR
        element=13,  # Super INT
        passive_skill=passive_text,
        categories=["Majin Buu Saga", "Fused Fighters", "Hybrid Saiyans"],
        category_ids=[24, 76, 12],
        links=["Super Saiyan", "Fused Fighter", "Shocking Speed", "Over in a Flash"],
    )


@pytest.fixture
def fat_buu_eza_card() -> DokkanCard:
    passive_text = (
        "*When HP is 50% or more*\n"
        "- Guards all attacks\n"
        "*When the character is KO'd*\n"
        "- Revives with HP fully recovered\n"
        "*After the character's or an ally's Revival Skill is activated*\n"
        "- Guards all attacks\n"
        "- Survives a K.O. attack when receiving an attack"
    )
    return DokkanCard(
        id=1028811,
        name="Majin Buu (Good)",
        subname="Innocent Monster",
        rarity=4,  # UR
        element=11,  # Extreme TEQ
        passive_skill=passive_text,
        categories=["Majin Buu Saga", "Majin Power", "Artificial Life Forms"],
        category_ids=[24, 52, 42],
        links=["Majin", "Infinite Regeneration", "The Wall Standing Tall", "Fierce Battle"],
    )


def test_pui_pui_slot_tags_and_mechanics(pui_pui_card: DokkanCard):
    """Verify that Pui Pui's slot-specific passives are accurately parsed."""
    tags = parse_passive_tags(pui_pui_card.passive_skill)
    assert tags.has_slot_1_buff is True
    assert tags.has_slot_2_buff is False
    assert tags.has_slot_3_buff is True
    assert tags.is_slot_1_or_3_only is True

    # Slot 1: 40% DR & 40% Dodge
    assert tags.slot_1_dr_percent == 40
    assert tags.slot_1_dodge_percent == 40

    # Slot 3: 30% DR & 30% Dodge
    assert tags.slot_3_dr_percent == 30
    assert tags.slot_3_dodge_percent == 30

    # DokkanCard properties mirror parsed tags
    assert pui_pui_card.has_slot_1_buff is True
    assert pui_pui_card.has_slot_2_buff is False
    assert pui_pui_card.has_slot_3_buff is True
    assert pui_pui_card.is_slot_1_or_3_only is True
    assert pui_pui_card.slot_1_dr_percent == 40
    assert pui_pui_card.slot_3_dr_percent == 30
    assert pui_pui_card.slot_1_dodge_percent == 40
    assert pui_pui_card.slot_3_dodge_percent == 30


def test_pui_pui_disqualified_from_slot_2(pui_pui_card: DokkanCard):
    """Verify that Pui Pui is heavily penalized / disqualified from Slot 2 partner role."""
    s2_weight = calculate_slot2_partner_weight(pui_pui_card)
    assert s2_weight == -100.0, f"Expected -100.0 for Slot 2, got {s2_weight}"


def test_pui_pui_slot_1_viability(pui_pui_card: DokkanCard):
    """Verify that Pui Pui's Guard + 40% DR + 80% Dodge in Slot 1 qualifies him as Slot 1 viable."""
    assert DokkanConstraintSolver.is_slot1_viable(pui_pui_card) is True
    s1_weight = calculate_slot1_anchor_weight(pui_pui_card)
    assert s1_weight > 0.0, f"Expected positive Slot 1 weight, got {s1_weight}"


def test_gotenks_slot_2_and_3_retention(gotenks_eza_card: DokkanCard):
    """Verify Gotenks with 'as the 2nd or 3rd attacker' retains Slot 2 buff and is NOT slot_1_or_3_only."""
    tags = parse_passive_tags(gotenks_eza_card.passive_skill)
    assert tags.has_slot_2_buff is True
    assert tags.has_slot_3_buff is True
    assert tags.is_slot_1_or_3_only is False

    assert gotenks_eza_card.has_slot_2_buff is True
    assert gotenks_eza_card.has_slot_3_buff is True
    assert gotenks_eza_card.is_slot_1_or_3_only is False

    s2_weight = calculate_slot2_partner_weight(gotenks_eza_card)
    assert s2_weight > 0.0, f"Gotenks should have positive Slot 2 weight, got {s2_weight}"


def test_fat_buu_guard_and_revival_slot1_viability(fat_buu_eza_card: DokkanCard):
    """Verify Fat Buu EZA with permanent Guard and Revival is recognized as Slot 1 viable."""
    assert DokkanConstraintSolver.is_slot1_viable(fat_buu_eza_card) is True


def test_optimize_rotations_never_places_pui_pui_in_slot_2(
    pui_pui_card: DokkanCard,
    gotenks_eza_card: DokkanCard,
    fat_buu_eza_card: DokkanCard,
):
    """Verify optimize_rotations_for_team places Pui Pui strictly into Slot 1 or Floater (Slot 3)."""
    # Create 3 generic partner/leader cards to form a 6-man team
    card_lead = DokkanCard(
        id=1033061,
        name="Majin Vegeta & SS2 Goku",
        rarity=5,
        element=14,
        passive_skill="Ki +3, ATK & DEF 200%",
        categories=["Majin Buu Saga"],
        category_ids=[24],
        links=["Super Saiyan", "Prepared for Battle", "Fierce Battle"],
    )
    card_partner = DokkanCard(
        id=1030431,
        name="Super Vegito",
        rarity=5,
        element=12,
        passive_skill="Ki +3, ATK & DEF 200%",
        categories=["Majin Buu Saga"],
        category_ids=[24],
        links=["Super Saiyan", "Prepared for Battle", "Fierce Battle"],
    )
    card_support = DokkanCard(
        id=1025731,
        name="Buu Boys",
        rarity=5,
        element=10,
        passive_skill="Ki +3, ATK & DEF 180%",
        categories=["Majin Buu Saga"],
        category_ids=[24],
        links=["Super Saiyan", "Prepared for Battle", "Fierce Battle"],
    )

    team = [card_lead, card_partner, fat_buu_eza_card, gotenks_eza_card, pui_pui_card, card_support]
    rot_a, rot_b, floaters = optimize_rotations_for_team(team)

    # CRITICAL INVARIANT: Pui Pui MUST NEVER BE IN SLOT 2
    assert rot_a.slot2.id != 1033031, "Pui Pui was placed in Slot 2 of Rotation A!"
    assert rot_b.slot2.id != 1033031, "Pui Pui was placed in Slot 2 of Rotation B!"

    # Pui Pui should either be in Slot 1 or in Floaters (Slot 3)
    pui_pui_in_s1 = rot_a.slot1.id == 1033031 or rot_b.slot1.id == 1033031
    pui_pui_in_floaters = any(fl.id == 1033031 for fl in floaters)
    assert pui_pui_in_s1 or pui_pui_in_floaters, "Pui Pui must be in Slot 1 or Floaters (Slot 3)"
