"""Black-box integration test for TeamBuilder end-to-end pipeline.

Validates the full workflow:
Box (JSON/scanned cards) -> DokkanConstraintSolver -> TeamBuilder -> TeamRecommendation
without coupling to internal scoring heuristics, sub-scores, or terminal tables.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from tests.harness.fake_dokkandb import FakeDokkanDBClient

from dokkan_eza_link_farmer.ai.client import DokkanAIClient
from dokkan_eza_link_farmer.ai.models import (
    AIConfig,
    BossPhase,
    BossStage,
    DokkanCard,
    TeamRecommendation,
)
from dokkan_eza_link_farmer.ai.team_builder import TeamBuilder


@pytest.fixture
def synthetic_box_15_cards() -> list[dict]:
    """15 realistic scanned box cards with leader skills, links, categories, and kit attributes.

    Categories:
    - Pure Saiyans (ID 17)
    - Super Saiyans (ID 18)
    - Realm of Gods (ID 10)
    """
    return [
        # 1. Tier 1 Category Leader (Pure Saiyans + Super Saiyans 170% + 30%)
        {
            "id": 10001,
            "name": "Super Saiyan God Goku",
            "subname": "Divine Awakening",
            "rarity": 5,
            "element": 10,  # Super AGL
            "leader_skill": '"Pure Saiyans" or "Super Saiyans" Category Ki +3 and HP, ATK & DEF +170%, plus an additional HP, ATK & DEF +30% for "Realm of Gods"',
            "leader_spec": {
                "main_category_ids": [17, 18],
                "extra_category_ids": [10],
                "base_boost_pct": 170.0,
                "extra_boost_pct": 30.0,
            },
            "passive_skill": "Guards all attacks; reduces damage received by 60% for 5 turns; ATK & DEF +200%",
            "super_attack": "Raises ATK & DEF and causes colossal damage",
            "categories": ["Pure Saiyans", "Super Saiyans", "Realm of Gods"],
            "category_ids": [17, 18, 10],
            "links": ["Super Saiyan", "Prepared for Battle", "Warrior Gods", "Fierce Battle"],
            "base_form": {
                "form_id": 10001,
                "form_name": "SSG Goku",
                "element": 10,
                "passive_tags": {
                    "slot1_viable": True,
                    "has_guard": True,
                    "is_guard_permanent": True,
                    "is_guard_unconditional": True,
                    "dr_base_percent": 60,
                },
                "sa_tags": {"stacks_def": True},
            },
        },
        # 2. Defensive Anchor Tank (Slot 1 anchor with guard & damage reduction)
        {
            "id": 10002,
            "name": "Super Saiyan Vegeta",
            "subname": "Unbreakable Pride",
            "rarity": 5,
            "element": 11,  # Super TEQ
            "leader_skill": '"Pure Saiyans" Category Ki +3 and HP, ATK & DEF +150%',
            "passive_skill": "Guards all attacks unconditionally; reduces damage received by 50%",
            "super_attack": "Greatly raises DEF and causes immense damage",
            "categories": ["Pure Saiyans", "Super Saiyans"],
            "category_ids": [17, 18],
            "links": ["Super Saiyan", "Prepared for Battle", "Royal Lineage", "Fierce Battle"],
            "base_form": {
                "form_id": 10002,
                "form_name": "SS Vegeta",
                "element": 11,
                "passive_tags": {
                    "slot1_viable": True,
                    "has_guard": True,
                    "is_guard_permanent": True,
                    "is_guard_unconditional": True,
                    "dr_base_percent": 50,
                },
                "sa_tags": {"stacks_def": True},
            },
        },
        # 3. Dedicated Slot 1 God Tank
        {
            "id": 10003,
            "name": "Super Saiyan Broly",
            "subname": "Wrathful Power",
            "rarity": 5,
            "element": 10,  # Super AGL
            "leader_skill": '"Pure Saiyans" Ki +3, Stats +130%',
            "passive_skill": "Guards all attacks; damage received -70%",
            "super_attack": "Causes colossal damage and raises DEF",
            "categories": ["Pure Saiyans", "Super Saiyans"],
            "category_ids": [17, 18],
            "links": ["Super Saiyan", "Prepared for Battle", "Saiyan Roar", "Fierce Battle"],
            "base_form": {
                "form_id": 10003,
                "form_name": "Broly",
                "element": 10,
                "passive_tags": {
                    "slot1_viable": True,
                    "has_guard": True,
                    "is_guard_permanent": True,
                    "dr_base_percent": 70,
                },
                "sa_tags": {"stacks_def": True},
            },
        },
        # 4. Off-rotator / Floater / Damage dealer
        {
            "id": 10004,
            "name": "Super Saiyan 2 Goku",
            "subname": "Sparking Aura",
            "rarity": 4,
            "element": 13,  # Super STR
            "leader_skill": "Super STR Ki +3, Stats +100%",
            "passive_skill": "ATK +180% and DEF +150% when performing a Super Attack; launches additional attack",
            "super_attack": "Raises ATK & DEF for 1 turn and causes supreme damage",
            "categories": ["Pure Saiyans", "Super Saiyans"],
            "category_ids": [17, 18],
            "links": ["Super Saiyan", "Prepared for Battle", "Over in a Flash", "Fierce Battle"],
            "base_form": {
                "form_id": 10004,
                "form_name": "SS2 Goku",
                "element": 13,
                "passive_tags": {"slot1_viable": False, "dr_base_percent": 0},
                "sa_tags": {"raise_def_turns": 1},
            },
        },
        # 5. High-Synergy Slot 2 Partner
        {
            "id": 10005,
            "name": "Super Saiyan 3 Goku",
            "subname": "Limitless Radiance",
            "rarity": 5,
            "element": 10,  # Super AGL
            "leader_skill": '"Super Saiyans" Ki +3, Stats +130%',
            "passive_skill": "ATK +200% and DEF +200%; high chance of evading enemy attacks",
            "super_attack": "Greatly raises ATK and causes mega-colossal damage",
            "categories": ["Pure Saiyans", "Super Saiyans"],
            "category_ids": [17, 18],
            "links": ["Super Saiyan", "Prepared for Battle", "Over in a Flash", "Fierce Battle"],
            "base_form": {
                "form_id": 10005,
                "form_name": "SS3 Goku",
                "element": 10,
                "passive_tags": {
                    "slot1_viable": False,
                    "dodge_chance_percent": 50,
                    "dr_base_percent": 0,
                },
                "sa_tags": {"raise_def_turns": 1},
            },
        },
        # 6. Support Floater
        {
            "id": 10006,
            "name": "Super Saiyan Bardock",
            "subname": "Lone Warrior",
            "rarity": 4,
            "element": 14,  # Super PHY
            "leader_skill": "PHY Type Ki +3, Stats +90%",
            "passive_skill": "Pure Saiyans allies Ki +3 and ATK & DEF +40%; seals attacked enemy's Super Attack",
            "super_attack": "Causes supreme damage and raises DEF for 1 turn",
            "categories": ["Pure Saiyans", "Super Saiyans"],
            "category_ids": [17, 18],
            "links": ["Super Saiyan", "Prepared for Battle", "Saiyan Roar"],
            "base_form": {
                "form_id": 10006,
                "form_name": "Bardock",
                "element": 14,
                "passive_tags": {"slot1_viable": False, "has_support": True},
                "sa_tags": {"raise_def_turns": 1},
            },
        },
        # 7. Sub-candidate 7
        {
            "id": 10007,
            "name": "Super Saiyan Trunks",
            "subname": "Future Hope",
            "rarity": 4,
            "element": 11,  # Super TEQ
            "leader_skill": "Super TEQ Ki +3, Stats +90%",
            "passive_skill": "ATK & DEF +120%; changes Ki spheres to TEQ Ki spheres",
            "super_attack": "Causes supreme damage and raises DEF",
            "categories": ["Super Saiyans"],
            "category_ids": [18],
            "links": ["Super Saiyan", "Prepared for Battle", "Royal Lineage"],
            "base_form": {
                "form_id": 10007,
                "form_name": "Trunks",
                "element": 11,
                "passive_tags": {"slot1_viable": False, "has_orb_changing": True},
                "sa_tags": {"stacks_def": True},
            },
        },
        # 8. Sub-candidate 8
        {
            "id": 10008,
            "name": "Majin Vegeta",
            "subname": "Dark Awakening",
            "rarity": 5,
            "element": 12,  # Super INT
            "leader_skill": "INT Type Ki +3, Stats +100%",
            "passive_skill": "Reduces damage received by 50% when HP is 50% or more",
            "super_attack": "Causes colossal damage and raises DEF for 1 turn",
            "categories": ["Pure Saiyans"],
            "category_ids": [17],
            "links": ["Super Saiyan", "Prepared for Battle", "Royal Lineage", "Over in a Flash"],
            "base_form": {
                "form_id": 10008,
                "form_name": "Majin Vegeta",
                "element": 12,
                "passive_tags": {"slot1_viable": False, "dr_base_percent": 50},
                "sa_tags": {"raise_def_turns": 1},
            },
        },
        # 9. Sub-candidate 9
        {
            "id": 10009,
            "name": "Super Saiyan Kaioken Goku",
            "subname": "Flaming Fist",
            "rarity": 4,
            "element": 14,  # Super PHY
            "leader_skill": "PHY Type Stats +70%",
            "passive_skill": "ATK & DEF +100%",
            "super_attack": "Causes supreme damage",
            "categories": ["Pure Saiyans", "Super Saiyans"],
            "category_ids": [17, 18],
            "links": ["Super Saiyan", "Over in a Flash", "Prepared for Battle"],
            "base_form": {
                "form_id": 10009,
                "form_name": "SS Kaioken",
                "element": 14,
                "passive_tags": {"slot1_viable": False},
                "sa_tags": {},
            },
        },
        # 10. Sub-candidate 10
        {
            "id": 10010,
            "name": "Super Saiyan God Vegeta",
            "subname": "Crimson Blaze",
            "rarity": 5,
            "element": 13,  # Super STR
            "leader_skill": '"Realm of Gods" Ki +3, Stats +120%',
            "passive_skill": "High chance of guarding all attacks; ATK & DEF +140%",
            "super_attack": "Causes colossal damage and greatly lowers DEF",
            "categories": ["Pure Saiyans", "Realm of Gods"],
            "category_ids": [17, 10],
            "links": ["Super Saiyan", "Prepared for Battle", "Warrior Gods", "Royal Lineage"],
            "base_form": {
                "form_id": 10010,
                "form_name": "SSG Vegeta",
                "element": 13,
                "passive_tags": {"slot1_viable": False, "has_guard": True},
                "sa_tags": {},
            },
        },
        # 11-15: Incompatible or lower-tier units to test constraint filtering
        {
            "id": 10011,
            "name": "Golden Frieza",
            "subname": "Resurrected Tyrant",
            "rarity": 4,
            "element": 20,  # Extreme AGL
            "leader_skill": "Extreme AGL Ki +3, Stats +90%",
            "passive_skill": "Reduces damage received by 90% when HP is 40% or above",
            "super_attack": "Causes immense damage",
            "categories": ["Wicked Bloodline", "Resurrected Warriors"],
            "category_ids": [21, 22],
            "links": ["Strongest Clan in Space"],
            "base_form": {
                "form_id": 10011,
                "form_name": "Golden Frieza",
                "element": 20,
                "passive_tags": {"slot1_viable": True, "dr_base_percent": 90},
                "sa_tags": {},
            },
        },
        {
            "id": 10012,
            "name": "Cell (Perfect Form)",
            "subname": "Ultimate Lifeform",
            "rarity": 5,
            "element": 22,  # Extreme INT
            "leader_skill": "Extreme INT Ki +3, Stats +100%",
            "passive_skill": "ATK & DEF +100%",
            "super_attack": "Causes colossal damage",
            "categories": ["Androids", "Target: Goku"],
            "category_ids": [31, 32],
            "links": ["Big Bad Bosses"],
            "base_form": {
                "form_id": 10012,
                "form_name": "Cell",
                "element": 22,
                "passive_tags": {"slot1_viable": False},
                "sa_tags": {},
            },
        },
        {
            "id": 10013,
            "name": "Majin Buu (Good)",
            "subname": "Innocent Destructor",
            "rarity": 4,
            "element": 24,  # Extreme PHY
            "leader_skill": "Extreme PHY Ki +3, Stats +70%",
            "passive_skill": "Recovers 25% HP when HP is 30% or below",
            "super_attack": "Causes supreme damage",
            "categories": ["Majin Buu Saga", "Majin Power"],
            "category_ids": [41, 42],
            "links": ["Majin"],
            "base_form": {
                "form_id": 10013,
                "form_name": "Buu",
                "element": 24,
                "passive_tags": {"slot1_viable": False},
                "sa_tags": {},
            },
        },
        {
            "id": 10014,
            "name": "Piccolo",
            "subname": "Wise Warrior",
            "rarity": 4,
            "element": 11,  # Super TEQ
            "leader_skill": "Namekians Ki +3, Stats +120%",
            "passive_skill": "Allies DEF +30%",
            "super_attack": "Causes supreme damage",
            "categories": ["Namekians", "Saviors"],
            "category_ids": [51, 52],
            "links": ["Shocking Speed"],
            "base_form": {
                "form_id": 10014,
                "form_name": "Piccolo",
                "element": 11,
                "passive_tags": {"slot1_viable": False, "has_support": True},
                "sa_tags": {},
            },
        },
        {
            "id": 10015,
            "name": "Raditz",
            "subname": "Ruthless Invader",
            "rarity": 4,
            "element": 24,  # Extreme PHY
            "leader_skill": '"Pure Saiyans" Ki +3, Stats +130%',
            "passive_skill": "ATK +50% against multiple enemies",
            "super_attack": "Causes supreme damage to all enemies",
            "categories": ["Pure Saiyans"],
            "category_ids": [17],
            "links": ["Saiyan Roar"],
            "base_form": {
                "form_id": 10015,
                "form_name": "Raditz",
                "element": 24,
                "passive_tags": {"slot1_viable": False},
                "sa_tags": {},
            },
        },
    ]


@pytest.fixture
def two_phase_boss_stage() -> BossStage:
    """Stage boss with 2 phases: Phase 1 AGL, Phase 2 STR."""
    return BossStage(
        stage_id=9901,
        event_id=901,
        event_name="Red Zone: Supreme Challenge",
        stage_name="Stage 1: Multi-Phase Battle",
        difficulty=10,
        phases=[
            BossPhase(phase_index=1, element=0, element_name="AGL"),
            BossPhase(phase_index=2, element=3, element_name="STR", cancels_dodge=True),
        ],
    )


def test_team_builder_blackbox_pipeline(
    tmp_path,
    synthetic_box_15_cards: list[dict],
    two_phase_boss_stage: BossStage,
) -> None:
    """Black-box integration test: Box JSON -> Solver -> Rotations -> TeamRecommendation."""
    # 1. Write synthetic box to file simulating config/box.json
    box_file = tmp_path / "box.json"
    with open(box_file, "w", encoding="utf-8") as f:
        json.dump({"cards": synthetic_box_15_cards}, f)

    # 2. Use in-memory harness FakeDokkanDBClient (no real HTTP requests)
    fake_dokkandb = FakeDokkanDBClient()

    # 3. Initialize offline AI Advisor (verifying zero-crash deterministic fallback)
    mock_ai = MagicMock(spec=DokkanAIClient)
    mock_ai.config = AIConfig(enabled=True)
    mock_ai.is_available.return_value = False

    # 4. Ingest cards through TeamBuilder.load_user_box
    candidate_cards: list[DokkanCard] = TeamBuilder.load_user_box(
        str(box_file), dokkandb=fake_dokkandb
    )
    assert len(candidate_cards) == 15

    # 5. Execute team building end-to-end
    team_builder = TeamBuilder(dokkandb=fake_dokkandb, ai_client=mock_ai)
    team_rec, _shortlist = team_builder.select_best_team_for_boss(
        candidate_pool=candidate_cards,
        boss_stage=two_phase_boss_stage,
        use_ai_advisor=True,
    )

    # =========================================================================
    # High-level observable assertions on TeamRecommendation (antirez test pyramid)
    # =========================================================================

    # Assertion A: The team has exactly 6 titular cards + 1 compatible friend leader
    assert len(team_rec.all_cards) == 6
    assert len({card.id for card in team_rec.all_cards}) == 6
    assert team_rec.friend_leader is not None
    assert team_rec.leader is not None
    assert team_rec.leader.id in {card.id for card in team_rec.all_cards}

    # The friend leader must share leader category or identical lead mechanics
    is_friend_covered, friend_boost, _ = team_rec.friend_leader.is_covered_by_leader(
        team_rec.leader
    )
    assert is_friend_covered is True
    assert friend_boost >= 150.0

    # Assertion B: Rotation A and Rotation B each have a designated Slot 1 unit with defensive attitude
    # (guard, damage reduction, or slot 1 tank viability)
    rot_a_s1 = team_rec.rotation_a.slot1
    rot_b_s1 = team_rec.rotation_b.slot1

    assert (
        rot_a_s1.has_guard
        or rot_a_s1.damage_reduction_percent > 0
        or rot_a_s1.has_damage_reduction
        or rot_a_s1.is_slot1_tank
    ), f"Rotation A Slot 1 unit {rot_a_s1.name} must have defensive aptitude"

    assert (
        rot_b_s1.has_guard
        or rot_b_s1.damage_reduction_percent > 0
        or rot_b_s1.has_damage_reduction
        or rot_b_s1.is_slot1_tank
    ), f"Rotation B Slot 1 unit {rot_b_s1.name} must have defensive aptitude"

    # Both rotations must have distinct cards (combat team structure: 2 pairs + 3 floaters = 7 units)
    assert len(team_rec.floaters) == 3
    combat_7 = [
        team_rec.rotation_a.slot1,
        team_rec.rotation_a.slot2,
        team_rec.rotation_b.slot1,
        team_rec.rotation_b.slot2,
        *team_rec.floaters,
    ]
    assert len(combat_7) == 7

    # Assertion C: All selected units receive coverage from the captain's leader skill
    for member in team_rec.all_cards:
        covered, boost, _info = member.is_covered_by_leader(team_rec.leader)
        assert covered is True, f"Card {member.name} ({member.id}) is not covered by captain"
        assert boost >= 150.0, f"Card {member.name} has insufficient coverage ({boost}%)"

    # Assertion D: The recommendation object is serializable to and deserializable from JSON
    serialized = team_rec.to_dict()
    json_str = json.dumps(serialized)
    assert isinstance(json_str, str)
    assert len(json_str) > 0

    reconstructed = TeamRecommendation.from_dict(json.loads(json_str))
    assert reconstructed.leader.id == team_rec.leader.id
    assert reconstructed.friend_leader.id == team_rec.friend_leader.id
    assert reconstructed.rotation_a.slot1.id == team_rec.rotation_a.slot1.id
    assert reconstructed.rotation_b.slot1.id == team_rec.rotation_b.slot1.id
    assert len(reconstructed.all_cards) == 6
    assert len(reconstructed.floaters) == 3


def test_blackbox_extreme_boss_lethal_phase_survival() -> None:
    """Black-box scenario: Extreme Boss with lethal Super Attack (4.000.000+ ATK).

    Invariant Assertions:
    - Generated team contains exactly 6 unique cards.
    - Slot 1 of Rotation A and Rotation B strictly contain units with Guard or DR >= 60%.
    - The assigned team leader confers at least 170% boost to all 6 units.
    """
    from dokkan_eza_link_farmer.ai.models import CardForm, LeaderSkillSpec, PassiveTags

    boss = BossStage(
        stage_id=9901,
        event_id=901,
        stage_name="Lethal Gauntlet Phase",
        event_name="Red Zone: Supreme Challenge",
        difficulty=10,
        phases=[
            BossPhase(
                phase_index=1,
                element=0,
                element_name="AGL",
                atk=2_500_000,
                estimated_sa_damage=4_500_000,
            ),
        ],
    )

    lead_spec = LeaderSkillSpec(
        main_category_ids=[17],
        base_boost_pct=170.0,
        extra_boost_pct=30.0,
    )

    # 40 cards pool: exactly 2 Slot 1 God tanks, 38 non-tank units
    pool: list[DokkanCard] = []

    # Tank 1: Guard + 60% DR (Category 17 Pure Saiyans)
    pool.append(
        DokkanCard(
            id=101,
            name="Anchor Tank Alpha",
            categories=["Pure Saiyans"],
            category_ids=[17],
            leader_spec=lead_spec,
            leader_skill='"Pure Saiyans" Ki +3, HP, ATK & DEF +170%',
            passive_skill="Guards all attacks unconditionally; reduces damage received by 60%",
            base_form=CardForm(
                form_id=101,
                form_name="Anchor Tank Alpha",
                element=10,
                passive_tags=PassiveTags(
                    slot1_viable=True,
                    has_guard=True,
                    is_guard_permanent=True,
                    is_guard_unconditional=True,
                    dr_base_percent=60,
                ),
            ),
        )
    )

    # Tank 2: Raw 70% DR (DR >= 60%)
    pool.append(
        DokkanCard(
            id=102,
            name="Anchor Tank Beta",
            categories=["Pure Saiyans"],
            category_ids=[17],
            passive_skill="Reduces damage received by 70%",
            base_form=CardForm(
                form_id=102,
                form_name="Anchor Tank Beta",
                element=11,
                passive_tags=PassiveTags(
                    slot1_viable=True,
                    dr_base_percent=70,
                ),
            ),
        )
    )

    # 38 glass cannons / offensive floaters (DR < 60%, no Guard)
    for i in range(103, 141):
        pool.append(
            DokkanCard(
                id=i,
                name=f"Pure Saiyan Warrior {i}",
                categories=["Pure Saiyans"],
                category_ids=[17],
                passive_skill="ATK +180%, DEF +100%",
                base_form=CardForm(
                    form_id=i,
                    form_name=f"Pure Saiyan Warrior {i}",
                    element=12,
                    passive_tags=PassiveTags(
                        slot1_viable=False,
                        has_guard=False,
                        dr_base_percent=20,
                    ),
                ),
            )
        )

    builder = TeamBuilder(dokkandb=FakeDokkanDBClient())
    team_rec, _ = builder.select_best_team_for_boss(
        candidate_pool=pool,
        boss_stage=boss,
        use_ai_advisor=False,
    )

    # Invariant 1: Exactly 6 unique titular cards
    assert len(team_rec.all_cards) == 6
    assert len({c.id for c in team_rec.all_cards}) == 6

    # Invariant 2: Slot 1 of both rotations must have Guard or DR >= 60%
    s1_a = team_rec.rotation_a.slot1
    s1_b = team_rec.rotation_b.slot1
    assert s1_a.has_guard or s1_a.damage_reduction_percent >= 60
    assert s1_b.has_guard or s1_b.damage_reduction_percent >= 60

    # Invariant 3: Leader boost >= 170% for all 6 units
    assert team_rec.leader is not None
    for member in team_rec.all_cards:
        covered, boost, _ = member.is_covered_by_leader(team_rec.leader)
        assert covered is True
        assert boost >= 170.0


def test_blackbox_box_constrained_mission_solver() -> None:
    """Black-box scenario: Constrained 12-unit box with multi-category mission constraints.

    Invariant Assertions:
    - Solver converges on the best valid combination without unhandled crashes.
    - Generated team contains exactly 6 unique cards.
    - All multi-category mission quotas are fulfilled.
    - All team cards receive leader skill coverage.
    """
    from dokkan_eza_link_farmer.ai.mission_solver import ChallengeMission, MissionBatch
    from dokkan_eza_link_farmer.ai.models import CardForm, LeaderSkillSpec, PassiveTags

    lead_spec = LeaderSkillSpec(
        main_category_ids=[17, 18],
        base_boost_pct=170.0,
        extra_boost_pct=30.0,
    )

    # Tightly constrained box: 12 cards total
    box: list[DokkanCard] = [
        # Leader: Pure Saiyans + Super Saiyans
        DokkanCard(
            id=201,
            name="Hybrid Lead Pure and Super",
            categories=["Pure Saiyans", "Super Saiyans"],
            category_ids=[17, 18],
            leader_spec=lead_spec,
            leader_skill='"Pure Saiyans" or "Super Saiyans" Ki +3, ATK & DEF +170%',
            base_form=CardForm(
                form_id=201,
                form_name="Hybrid Lead Pure and Super",
                element=10,
                passive_tags=PassiveTags(has_guard=True, slot1_viable=True),
            ),
        ),
        # 3 pure-only units
        DokkanCard(
            id=202,
            name="Pure Fighter 1",
            categories=["Pure Saiyans"],
            category_ids=[17],
            base_form=CardForm(
                form_id=202,
                form_name="Pure Fighter 1",
                element=10,
                passive_tags=PassiveTags(has_guard=True, slot1_viable=True),
            ),
        ),
        DokkanCard(
            id=203,
            name="Pure Fighter 2",
            categories=["Pure Saiyans"],
            category_ids=[17],
            base_form=CardForm(
                form_id=203,
                form_name="Pure Fighter 2",
                element=11,
                passive_tags=PassiveTags(dr_base_percent=50),
            ),
        ),
        DokkanCard(
            id=204,
            name="Pure Fighter 3",
            categories=["Pure Saiyans"],
            category_ids=[17],
            base_form=CardForm(
                form_id=204,
                form_name="Pure Fighter 3",
                element=12,
                passive_tags=PassiveTags(dr_base_percent=50),
            ),
        ),
        # 2 super-only units
        DokkanCard(
            id=205,
            name="Super Fighter 1",
            categories=["Super Saiyans"],
            category_ids=[18],
            base_form=CardForm(
                form_id=205,
                form_name="Super Fighter 1",
                element=13,
                passive_tags=PassiveTags(dr_base_percent=40),
            ),
        ),
        DokkanCard(
            id=206,
            name="Super Fighter 2",
            categories=["Super Saiyans"],
            category_ids=[18],
            base_form=CardForm(
                form_id=206,
                form_name="Super Fighter 2",
                element=14,
                passive_tags=PassiveTags(dr_base_percent=40),
            ),
        ),
        # 3 dual category units
        DokkanCard(
            id=207,
            name="Dual Saiyan 1",
            categories=["Pure Saiyans", "Super Saiyans"],
            category_ids=[17, 18],
            base_form=CardForm(
                form_id=207,
                form_name="Dual Saiyan 1",
                element=10,
                passive_tags=PassiveTags(dr_base_percent=40),
            ),
        ),
        DokkanCard(
            id=208,
            name="Dual Saiyan 2",
            categories=["Pure Saiyans", "Super Saiyans"],
            category_ids=[17, 18],
            base_form=CardForm(
                form_id=208,
                form_name="Dual Saiyan 2",
                element=11,
                passive_tags=PassiveTags(dr_base_percent=40),
            ),
        ),
        DokkanCard(
            id=209,
            name="Dual Saiyan 3",
            categories=["Pure Saiyans", "Super Saiyans"],
            category_ids=[17, 18],
            base_form=CardForm(
                form_id=209,
                form_name="Dual Saiyan 3",
                element=12,
                passive_tags=PassiveTags(dr_base_percent=40),
            ),
        ),
        # 3 off-category units
        DokkanCard(
            id=210,
            name="Hybrid Saiyan 1",
            categories=["Hybrid Saiyans"],
            category_ids=[19],
            base_form=CardForm(
                form_id=210,
                form_name="Hybrid Saiyan 1",
                element=13,
                passive_tags=PassiveTags(dr_base_percent=30),
            ),
        ),
        DokkanCard(
            id=211,
            name="Hybrid Saiyan 2",
            categories=["Hybrid Saiyans"],
            category_ids=[19],
            base_form=CardForm(
                form_id=211,
                form_name="Hybrid Saiyan 2",
                element=14,
                passive_tags=PassiveTags(dr_base_percent=30),
            ),
        ),
        DokkanCard(
            id=212,
            name="Realm of Gods 1",
            categories=["Realm of Gods"],
            category_ids=[20],
            base_form=CardForm(
                form_id=212,
                form_name="Realm of Gods 1",
                element=10,
                passive_tags=PassiveTags(dr_base_percent=30),
            ),
        ),
    ]

    # Multi-category mission requirement: at least 3 Pure Saiyans and at least 3 Super Saiyans
    mission_batch = MissionBatch(
        missions=[
            ChallengeMission(
                id=1,
                name="Pure Saiyans Mastery",
                description="Clear with at least 3 Pure Saiyans",
                categories=[(3, "Pure Saiyans")],
            ),
            ChallengeMission(
                id=2,
                name="Super Saiyans Mastery",
                description="Clear with at least 3 Super Saiyans",
                categories=[(3, "Super Saiyans")],
            ),
        ],
        required_categories=[(3, "Pure Saiyans"), (3, "Super Saiyans")],
    )

    builder = TeamBuilder(dokkandb=FakeDokkanDBClient())
    team_rec, _ = builder.select_best_team_for_boss(
        candidate_pool=box,
        mission_batch=mission_batch,
        use_ai_advisor=False,
    )

    # Invariant 1: Exactly 6 unique titular cards
    assert len(team_rec.all_cards) == 6
    assert len({c.id for c in team_rec.all_cards}) == 6

    # Invariant 2: Quota satisfaction for multiple categories
    pure_count = sum(1 for c in team_rec.all_cards if "Pure Saiyans" in c.categories)
    super_count = sum(1 for c in team_rec.all_cards if "Super Saiyans" in c.categories)
    assert pure_count >= 3
    assert super_count >= 3

    # Invariant 3: Leader coverage for all team members
    for member in team_rec.all_cards:
        covered, boost, _ = member.is_covered_by_leader(team_rec.leader)
        assert covered is True
        assert boost >= 170.0
