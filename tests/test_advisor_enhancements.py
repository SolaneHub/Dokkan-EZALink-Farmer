from __future__ import annotations

from unittest.mock import MagicMock

from dokkan_eza_link_farmer.ai.models import (
    CardForm,
    DokkanCard,
    LeaderSkillSpec,
    PassiveTags,
)
from dokkan_eza_link_farmer.ai.support_catalog import (
    get_recommended_support_items,
    get_recommended_support_memory,
)
from dokkan_eza_link_farmer.ai.team_builder import TeamBuilder


class TestAdvisorEnhancements:
    """Tests the new AI Advisor features:

    - Support Items ranking & max 4
    - Permanent Support Memory matching
    - Flexible, non-linear Friend Leader in Rotations
    - Unified Rotations without duplicate Leader row
    - Tactical Timeline for Standby, Transformations, Exchange, and Reversible Switch
    """

    def test_support_items_ranking_and_max_4(self):
        items = get_recommended_support_items(max_items=4)
        assert len(items) == 4

        # Rank 1 must be Whis, Rank 2 Ghost Usher, Rank 3 Icarus, Rank 4 Princess Snake
        assert items[0]["name"] == "Whis"
        assert items[0]["rank"] == 1
        assert "40%" in items[0]["effect"]

        assert items[1]["name"] == "Ghost Usher"
        assert items[1]["rank"] == 2

        assert items[2]["name"] == "Icarus"
        assert items[2]["rank"] == 3

        assert items[3]["name"] == "Princess Snake"
        assert items[3]["rank"] == 4
        assert "55%" in items[3]["effect"]

    def test_permanent_support_memory_selection(self):
        # Team with Movie Heroes category
        movie_heroes_team = [
            DokkanCard(id=1, name="Gogeta", categories=["Movie Heroes", "Fused Fighters"]),
            DokkanCard(id=2, name="Piccolo", categories=["Movie Heroes"]),
            DokkanCard(id=3, name="Gohan", categories=["Movie Heroes", "Hybrid Saiyans"]),
            DokkanCard(id=4, name="Gamma 1", categories=["Movie Heroes", "Super Heroes"]),
            DokkanCard(id=5, name="Gamma 2", categories=["Movie Heroes", "Super Heroes"]),
            DokkanCard(id=6, name="Beast Gohan", categories=["Movie Heroes", "Super Heroes"]),
        ]

        mem = get_recommended_support_memory(movie_heroes_team)
        assert mem is not None
        assert "Permanente" in mem["duration"]
        assert mem["name"] in ("Kakarot", "Super Hero Fading Away")

        # Team with Majin Buu Saga
        buu_team = [
            DokkanCard(id=10, name="Buu", categories=["Majin Buu Saga"]),
            DokkanCard(id=11, name="Gotenks", categories=["Majin Buu Saga"]),
            DokkanCard(id=12, name="Vegito", categories=["Majin Buu Saga"]),
            DokkanCard(id=13, name="Goku", categories=["Majin Buu Saga"]),
            DokkanCard(id=14, name="Vegeta", categories=["Majin Buu Saga"]),
            DokkanCard(id=15, name="Gohan", categories=["Majin Buu Saga"]),
        ]
        mem_buu = get_recommended_support_memory(buu_team)
        assert mem_buu["name"] == "Buu's Slumber"
        assert "Permanente" in mem_buu["duration"]

    def test_tactical_form_timeline_standby_exchange_switch(self):
        # 1. Standby card
        standby_card = DokkanCard(
            id=1025731,
            name="SSJ3 Goku & SSJ2 Vegeta",
            standby_skill_name="Enters Standby Mode",
            standby_skill_condition="Can be activated when HP is 50% or less, or from 4th turn",
            standby_skill_effect="Stands by for 5 turns, charge count increases with Ki",
        )
        timeline_sb = standby_card.get_tactical_form_timeline()
        assert len(timeline_sb) >= 1
        assert timeline_sb[0]["type"] == "Standby Mode"
        assert "Turno 4" in timeline_sb[0]["timing"]

        # 2. Exchange card
        exchange_card = DokkanCard(
            id=1017661,
            name="Super Vegeta/Super Trunks",
            active_skill_name="Exchange",
            active_skill_condition="Can be activated from the 3rd turn",
            active_skill_effect="Exchange with Super Trunks",
        )
        timeline_ex = exchange_card.get_tactical_form_timeline()
        assert len(timeline_ex) >= 1
        assert timeline_ex[0]["type"] == "Scambio (Exchange)"

        # 3. Reversible Switch card
        switch_card = DokkanCard(
            id=1099999,
            name="Gamma 1 & Gamma 2",
            active_skill_name="Switch Core",
            active_skill_condition="Can switch back and forth each turn",
            active_skill_effect="Switches between offensive and defensive mode",
        )
        timeline_sw = switch_card.get_tactical_form_timeline()
        assert len(timeline_sw) >= 1
        assert timeline_sw[0]["type"] == "Scambio Reversibile (Switch)"

        # 4. Transforming card
        trans_card = DokkanCard(
            id=1030431,
            name="Angel Goku & Vegeta",
            transformations=[
                CardForm(
                    form_id=1030432,
                    form_name="Super Gogeta",
                    min_turn=4,
                    passive_skill_text="Super effective against all types; high chance of critical hit",
                )
            ],
        )
        timeline_tr = trans_card.get_tactical_form_timeline()
        assert len(timeline_tr) >= 1
        assert timeline_tr[0]["type"] == "Trasformazione"
        assert "Fase Finale" in timeline_tr[0]["timing"]

    def test_friend_leader_flexible_position_and_non_linear(self):
        tb = TeamBuilder()

        main_leader = DokkanCard(
            id=1001,
            name="Main Leader",
            element=0,
            leader_skill="Super Heroes Ki +3 HP, ATK & DEF +200%",
            leader_spec=LeaderSkillSpec(main_category_ids=[88], base_boost_pct=200),
            categories=["Super Heroes"],
            links=["Super Saiyan", "Prepared for Battle"],
        )

        # High-def Slot 1 Tank candidate as complementary Friend Leader (Beast Gohan)
        beast_friend = DokkanCard(
            id=1002,
            name="Beast Gohan Friend",
            element=1,
            leader_skill="Super Heroes Ki +3 HP, ATK & DEF +200%",
            leader_spec=LeaderSkillSpec(main_category_ids=[88], base_boost_pct=200),
            categories=["Super Heroes"],
            passive_skill="Guards all attacks; reduces damage received by 58%",
            base_form=CardForm(
                form_id=1002,
                passive_tags=PassiveTags(slot1_viable=True, has_guard=True, dr_base_percent=58),
            ),
            links=["Super Saiyan", "Prepared for Battle", "Fierce Battle"],
        )

        sub_cards = [
            main_leader,
            DokkanCard(
                id=1003,
                name="Sub 1",
                categories=["Super Heroes"],
                links=["Super Saiyan", "Prepared for Battle"],
            ),
            DokkanCard(
                id=1004,
                name="Sub 2",
                categories=["Super Heroes"],
                links=["Super Saiyan", "Prepared for Battle"],
            ),
            DokkanCard(
                id=1005,
                name="Sub 3",
                categories=["Super Heroes"],
                links=["Prepared for Battle"],
            ),
            DokkanCard(
                id=1006,
                name="Sub 4",
                categories=["Super Heroes"],
                links=["Prepared for Battle"],
            ),
            DokkanCard(
                id=1007,
                name="Sub 5",
                categories=["Super Heroes"],
                links=["Prepared for Battle"],
            ),
        ]

        # Select best friend leader from candidate pool containing Beast Gohan
        selected_friend = tb.select_best_friend_leader(sub_cards, candidate_pool=[beast_friend])
        assert selected_friend.id == beast_friend.id

        # Build full plan with 7 units
        rec = tb.build_team_plan(sub_cards, candidate_pool=[beast_friend])
        assert rec.friend_leader.id == beast_friend.id
        assert len(rec.floaters) == 3

        # Because beast_friend has godly slot 1 defense (Guard + 58% DR), they must be in main rotation (Slot 1)
        rot_cards = [
            rec.rotation_a.slot1,
            rec.rotation_a.slot2,
            rec.rotation_b.slot1,
            rec.rotation_b.slot2,
        ]
        assert any(c.id == beast_friend.id for c in rot_cards)
        assert (
            rec.rotation_a.slot1.id == beast_friend.id or rec.rotation_b.slot1.id == beast_friend.id
        )

    def test_rotations_no_duplicate_leader_row(self):
        from rich.console import Console

        from dokkan_eza_link_farmer.ui.cli import TerminalCLI

        mock_engine = MagicMock()
        cli = TerminalCLI(mock_engine)
        cli.console = Console(record=True, width=120)

        main_lead = DokkanCard(
            id=5001,
            name="Ultra Gogeta Lead",
            leader_skill="Fusion Ki +3, ATK & DEF +200%",
            categories=["Fusion"],
            links=["Super Saiyan", "Fierce Battle"],
        )
        friend_lead = DokkanCard(
            id=5002,
            name="Ultra Vegito Friend",
            leader_skill="Potara Ki +3, ATK & DEF +200%",
            categories=["Fusion"],
            links=["Super Saiyan", "Fierce Battle"],
        )

        team = [
            main_lead,
            DokkanCard(id=5003, name="Sub A", categories=["Fusion"], links=["Super Saiyan"]),
            DokkanCard(id=5004, name="Sub B", categories=["Fusion"], links=["Super Saiyan"]),
            DokkanCard(id=5005, name="Sub C", categories=["Fusion"], links=["Super Saiyan"]),
            DokkanCard(id=5006, name="Sub D", categories=["Fusion"], links=["Super Saiyan"]),
            DokkanCard(id=5007, name="Sub E", categories=["Fusion"], links=["Super Saiyan"]),
        ]

        tb = TeamBuilder()
        rec = tb.build_team_plan(team, candidate_pool=[friend_lead])
        cli._render_team_presentation(rec, title="Test Rotations Presentation")

        rendered_text = cli.console.export_text()

        # Verify that Leader and Friend are unified with their rotation slots (no duplicate standalone Leader row)
        assert "Leader • Rotazione" in rendered_text or "Leader • Floater" in rendered_text
        assert "Friend • Rotazione" in rendered_text or "Friend • Floater" in rendered_text
        assert "Oggetti di Supporto Consigliati" in rendered_text
        assert "Support Memory Consigliata" in rendered_text

    def test_multi_battle_stage_structure_and_stacking_reset(self):
        from dokkan_eza_link_farmer.ai.models import (
            BossEnemy,
            BossMechanic,
            BossPhase,
            BossStage,
        )
        from dokkan_eza_link_farmer.ai.team_builder import (
            format_stage_tactical_briefing,
            render_stage_intel_rich,
        )

        p1 = BossPhase(
            phase_index=1,
            battle_index=1,
            round_index=1,
            is_new_battle=True,
            element=21,
            hp=210_000_000,
            atk=800_000,
            actions_per_turn=5,
            bosses=[
                BossEnemy(
                    card_id=93023521,
                    name="Vegeta (Giant Ape)",
                    element=21,
                    type_name="Extreme TEQ",
                    mechanics=[
                        BossMechanic(
                            id=526480, name="Coercion", description="Locks character switching"
                        ),
                        BossMechanic(
                            id=600104,
                            name="Stun Immunity",
                            description="Grants immunity to being stunned",
                        ),
                    ],
                )
            ],
        )
        p2 = BossPhase(
            phase_index=2,
            battle_index=2,
            round_index=1,
            is_new_battle=True,
            element=20,
            hp=250_000_000,
            atk=800_000,
            actions_per_turn=7,
            bosses=[
                BossEnemy(
                    card_id=9422751,
                    name="Frieza (Full Power)",
                    element=20,
                    type_name="Extreme AGL",
                    mechanics=[
                        BossMechanic(
                            id=526510, name="ATK Boost", description="ATK +30% when Goku present"
                        ),
                    ],
                )
            ],
        )
        p3 = BossPhase(
            phase_index=3,
            battle_index=3,
            round_index=1,
            is_new_battle=True,
            element=10,
            hp=270_000_000,
            atk=1_200_000,
            actions_per_turn=5,
            bosses=[
                BossEnemy(
                    card_id=9429091,
                    name="Jiren",
                    element=10,
                    type_name="Super AGL",
                    mechanics=[],
                )
            ],
        )
        p4 = BossPhase(
            phase_index=4,
            battle_index=3,
            round_index=2,
            is_new_battle=False,  # Same battle, stacking carries over!
            element=10,
            hp=300_000_000,
            atk=1_500_000,
            actions_per_turn=8,
            cancels_dodge=True,
            bosses=[
                BossEnemy(
                    card_id=9529111,
                    name="Jiren (Full Power)",
                    element=10,
                    type_name="Super AGL",
                    mechanics=[
                        BossMechanic(
                            id=600106, name="Guaranteed Hit", description="Disables Evasion"
                        ),
                    ],
                )
            ],
        )

        stage = BossStage(
            stage_id=17280164,
            event_id=1728,
            stage_name="Pure Saiyans [5 Required]",
            event_name="Union Master",
            difficulty=4,
            phases=[p1, p2, p3, p4],
            total_battles=3,
        )

        assert stage.total_battles == 3
        assert stage.is_multi_battle is True
        assert p1.is_new_battle is True
        assert p2.is_new_battle is True
        assert p3.is_new_battle is True
        assert p4.is_new_battle is False
        assert p1.locks_slots is True
        assert p4.cancels_dodge is True

        briefing = format_stage_tactical_briefing(stage, language="it")
        assert "3 Battaglie distinte" in briefing
        assert "RESET STACKING" in briefing
        assert "210M" in briefing
        assert "250M" in briefing
        assert "270M" in briefing
        assert "300M" in briefing
        assert "800k" in briefing
        assert "1500k" in briefing

        panel = render_stage_intel_rich(stage)
        assert panel is not None

    def test_solver_multi_battle_stacking_reset_penalty_and_turn1_bonus(self):
        from dokkan_eza_link_farmer.ai.models import BossPhase, BossStage
        from dokkan_eza_link_farmer.ai.solver import DokkanConstraintSolver

        stage = BossStage(
            stage_id=17280164,
            event_id=1728,
            stage_name="Pure Saiyans",
            event_name="Union Master",
            total_battles=3,
            phases=[
                BossPhase(
                    phase_index=1, battle_index=1, round_index=1, is_new_battle=True, element=21
                ),
                BossPhase(
                    phase_index=2, battle_index=2, round_index=1, is_new_battle=True, element=20
                ),
                BossPhase(
                    phase_index=3, battle_index=3, round_index=1, is_new_battle=True, element=10
                ),
                BossPhase(
                    phase_index=4, battle_index=3, round_index=2, is_new_battle=False, element=10
                ),
            ],
        )

        solver = DokkanConstraintSolver()

        # Pure slow stacker without guard or DR
        stacker_card = DokkanCard(
            id=7001,
            name="Fragile Slow Stacker",
            element=1,  # TEQ
            super_attack="Raises DEF and causes supreme damage",
            passive_skill="ATK & DEF +100%",
        )
        assert stacker_card.has_stacking_def is True
        assert stacker_card.has_guard is False
        assert stacker_card.damage_reduction_percent == 0

        delta_s, _, pen_s = solver.evaluate_boss_gimmicks(stacker_card, stage)
        assert any("Stacking Reset Vulnerability" in p for p in pen_s)
        assert delta_s <= -15.0

        # Turn 1 Immediate Tank (Guard or 50% DR)
        tank_card = DokkanCard(
            id=7002,
            name="Turn 1 Solid Tank",
            element=1,  # TEQ
            passive_skill="Guards all attacks; reduces damage received by 50%",
        )
        assert tank_card.has_guard is True
        assert tank_card.damage_reduction_percent == 50

        delta_t, count_t, _ = solver.evaluate_boss_gimmicks(tank_card, stage)
        assert any("Multi-Battle Reliability" in c for c in count_t)
        assert delta_t >= 15.0

    def test_defensive_expiration_and_dodge_cancellation_awareness(self):
        from dokkan_eza_link_farmer.ai.models import BossPhase, BossStage
        from dokkan_eza_link_farmer.ai.solver import DokkanConstraintSolver
        from dokkan_eza_link_farmer.ai.team_builder import TeamBuilder, format_team_summary_table

        stage = BossStage(
            stage_id=17280164,
            event_id=1728,
            stage_name="Pure Saiyans",
            event_name="Union Master",
            total_battles=3,
            phases=[
                BossPhase(
                    phase_index=1, battle_index=1, round_index=1, is_new_battle=True, element=21
                ),
                BossPhase(
                    phase_index=2, battle_index=2, round_index=1, is_new_battle=True, element=20
                ),
                BossPhase(
                    phase_index=3, battle_index=3, round_index=1, is_new_battle=True, element=10
                ),
                BossPhase(
                    phase_index=4,
                    battle_index=3,
                    round_index=2,
                    is_new_battle=False,
                    element=10,
                    cancels_dodge=True,
                ),
            ],
        )

        solver = DokkanConstraintSolver()

        # Unit with intro guard (6 turns) and high dodge (70%) but no permanent guard/DR
        god_goku = DokkanCard(
            id=1034461,
            name="Super Saiyan God Goku",
            element=4,  # PHY
            passive_skill="Guards all attacks for 6 turns from start of turn; great chance of evading enemy attacks",
            categories=["Pure Saiyans"],
            category_ids=[17],
        )

        # 1. When evaluated against boss that cancels dodge in late phase:
        # Dodge is neutralized, guard expires in multi-battle stage -> NOT Slot 1 viable!
        assert solver.is_slot1_viable(god_goku, boss_stage=stage) is False

        # 2. Slot 1 def priority must give 0 points for dodge when boss cancels dodge
        tb = TeamBuilder()
        pri_with_boss = tb.calculate_slot1_def_priority(god_goku, boss_stage=stage)
        pri_no_boss = tb.calculate_slot1_def_priority(god_goku, boss_stage=None)
        assert pri_with_boss < pri_no_boss

        # 3. Solver evaluates severe glass cannon / guard expiration penalties
        delta, _, penalties = solver.evaluate_boss_gimmicks(god_goku, stage)
        assert delta < 0.0
        assert any("Cancels Dodge" in p for p in penalties)
        assert any("Guard Expiration" in p for p in penalties)

        # 4. Table renders nuanced tags: Guard (6T), Dodge 70% [Nullificato]
        table = format_team_summary_table([god_goku], boss_stage=stage)
        assert "Guard (6T)" in table
        assert "Dodge 70% [Nullificato]" in table
