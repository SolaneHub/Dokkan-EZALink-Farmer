"""Autonomous End-to-End Orchestrator for Endgame Red Zone and Blue Zone challenge events.

Coordinates the 4-step live gameplay and trial-and-error state machine:
- Step A: Load ~/.dokkan-farmer/cache/user_box.json and ai_memory.json;
          generate optimal initial team via TeamBuilder & DokkanConstraintSolver.
- Step B: Check equipped team; if modified, invoke team_formation.py to apply in-game.
- Step C: Select Friend Leader (with refresh if needed), tap start, ensure Auto-Battle is active,
          and start observation telemetry loop (Ki spheres + 4-frame ring buffer).
- Step D: Detect outcome:
          * Stage Clear (button_ok.png / results): record Winning Team in ai_memory.json and exit.
          * Game Over (button_attempt_again.png): generate FailureReport, execute decision tree
            (InstantRetry, SurgicalReplace / SurgicalSwap, DemoteLeader / LeaderSwitch),
            and adapt team for next attempt up to max_attempts.
"""

from __future__ import annotations

import contextlib
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from dokkan_eza_link_farmer.ai.boss_catalog import get_boss_stage
from dokkan_eza_link_farmer.ai.client import DokkanAIClient
from dokkan_eza_link_farmer.ai.models import (
    BossPhase,
    BossStage,
    DokkanCard,
)
from dokkan_eza_link_farmer.ai.solver import DokkanConstraintSolver
from dokkan_eza_link_farmer.ai.team_builder import (
    TeamBuilder,
    format_team_summary_table,
)
from dokkan_eza_link_farmer.ai.telemetry import (
    DEFAULT_MEMORY_CACHE_PATH,
    CombatFrame,
    CombatRingBuffer,
    CombatTelemetryTracker,
    EpisodicMemory,
    FailureReport,
    PostDefeatDecision,
    TurnSnapshot,
)
from dokkan_eza_link_farmer.automation.game_state import GameState, StateDetector
from dokkan_eza_link_farmer.automation.tasks.box_scanner import DEFAULT_USER_BOX_PATH
from dokkan_eza_link_farmer.automation.team_formation import apply_team_in_game
from dokkan_eza_link_farmer.automation.vision import Vision
from dokkan_eza_link_farmer.integrations.adb_client import ADBClient
from dokkan_eza_link_farmer.integrations.dokkandb_client import DokkanDBClient

logger = logging.getLogger(__name__)


class EndgameStageOutcome(str, Enum):
    """Outcome of a single combat run."""

    VICTORY = "victory"
    DEFEAT = "defeat"
    ABORTED = "aborted"


class EndgameRunnerState(str, Enum):
    """Internal state machine states for EndgameRunner."""

    IDLE = "IDLE"
    STEP_A_INIT = "STEP_A_INIT"
    STEP_B_FORMATION = "STEP_B_FORMATION"
    STEP_C_START = "STEP_C_START"
    STEP_C_OBSERVE = "STEP_C_OBSERVE"
    STEP_D_OUTCOME = "STEP_D_OUTCOME"
    COMPLETED = "COMPLETED"
    MAX_ATTEMPTS_REACHED = "MAX_ATTEMPTS_REACHED"
    STOPPED = "STOPPED"


@dataclass
class EndgameResult:
    """Summary result of an autonomous EndgameRunner session."""

    success: bool
    attempts: int
    winning_team: list[DokkanCard] = field(default_factory=list)
    stage: BossStage | None = None
    decisions: list[PostDefeatDecision] = field(default_factory=list)
    failure_reports: list[FailureReport] = field(default_factory=list)
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "attempts": self.attempts,
            "winning_team_ids": [c.id for c in self.winning_team],
            "stage_id": self.stage.stage_id if self.stage else None,
            "stage_name": self.stage.stage_name if self.stage else "",
            "decisions": [d.to_dict() for d in self.decisions],
            "failure_reports": [r.to_dict() for r in self.failure_reports],
            "message": self.message,
        }


# Type signature for optional injected battle simulator (used in unit/integration testing)
BattleSimulatorFn = Callable[
    [int, list[DokkanCard], BossStage],
    tuple[str, TurnSnapshot | None, list[CombatFrame] | None],
]


class EndgameRunner:
    """Coordinates autonomous trial-and-error gameplay for Red Zone / Blue Zone events."""

    def __init__(
        self,
        adb: ADBClient | None = None,
        vision: Vision | None = None,
        detector: StateDetector | None = None,
        dokkandb: DokkanDBClient | None = None,
        ai_client: DokkanAIClient | None = None,
        team_builder: TeamBuilder | None = None,
        memory: EpisodicMemory | None = None,
        telemetry_tracker: CombatTelemetryTracker | None = None,
        user_box_path: str | Path | None = None,
        memory_path: str | Path | None = None,
        boss_stage: BossStage | None = None,
        max_attempts: int = 10,
        dry_run: bool = False,
        force_solve: bool = False,
        mission_batch: Any | None = None,
        battle_simulator: BattleSimulatorFn | None = None,
        on_status: Callable[[str], None] | None = None,
        on_run_complete: Callable[[int, int], None] | None = None,
    ):
        self.adb = adb
        self.vision = vision
        self.detector = detector
        self.dokkandb = dokkandb or DokkanDBClient()
        self.ai_client = ai_client
        self.solver = DokkanConstraintSolver()
        self.team_builder = team_builder or TeamBuilder(
            dokkandb=self.dokkandb,
            ai_client=self.ai_client,
            solver=self.solver,
        )

        self.memory_path = Path(memory_path or DEFAULT_MEMORY_CACHE_PATH)
        self.user_box_path = Path(user_box_path or DEFAULT_USER_BOX_PATH)
        self.memory = memory or EpisodicMemory(cache_path=self.memory_path, ephemeral=dry_run)
        self.telemetry_tracker = telemetry_tracker or CombatTelemetryTracker(
            ring_buffer=CombatRingBuffer(capacity=4),
            episodic_memory=self.memory,
        )

        self.boss_stage = boss_stage
        self.max_attempts = max(1, max_attempts)
        self.dry_run = dry_run
        self.force_solve = force_solve
        self.mission_batch = mission_batch
        self.battle_simulator = battle_simulator
        self.on_status = on_status
        self.on_run_complete = on_run_complete

        # Runtime session state
        self.current_state = EndgameRunnerState.IDLE
        self.current_attempt = 0
        self.user_box: list[DokkanCard] = []
        self.current_team: list[DokkanCard] = []
        self.equipped_team_ids: list[int] = []
        self.decisions_history: list[PostDefeatDecision] = []
        self.failure_reports_history: list[FailureReport] = []
        self._stopped = False

    def log(self, message: str) -> None:
        """Emits message to logger and status callback."""
        logger.info(message)
        if self.on_status:
            with contextlib.suppress(Exception):
                self.on_status(message)

    def stop(self) -> None:
        """Signals graceful termination of the loop."""
        self._stopped = True
        self.current_state = EndgameRunnerState.STOPPED

    def is_stopped(self) -> bool:
        return self._stopped

    # =========================================================================
    # STEP A: LOAD INVENTORY, MEMORY, & SYNTHESIZE INITIAL TEAM
    # =========================================================================

    def load_user_box(self) -> list[DokkanCard]:
        """Loads cards from user_box.json or falls back to canonical config/box.json."""
        from dokkan_eza_link_farmer.automation.tasks.box_scanner import resolve_box_path

        resolved = resolve_box_path(str(self.user_box_path) if self.user_box_path else None)
        resolved_path: Path | None = Path(resolved) if resolved and Path(resolved).exists() else None

        loaded_cards: list[DokkanCard] = []

        if resolved_path:
            try:
                with open(resolved_path, encoding="utf-8") as f:
                    content = json.load(f)
                items = content if isinstance(content, list) else content.get("cards", [])

                needs_enrichment = any(
                    isinstance(it, dict)
                    and (it.get("leader_spec") is None or it.get("category_ids") is None)
                    for it in items
                )
                if needs_enrichment:
                    self.log(
                        f"[Step A] Detected un-enriched cards in {resolved_path}. Running automatic Box Enrichment..."
                    )
                    from dokkan_eza_link_farmer.ai.syncer import DokkanSyncer

                    syncer = DokkanSyncer(cache_dir=str(self.user_box_path.parent))
                    loaded_cards = syncer.sync_box_details(
                        box_file=str(resolved_path),
                        save_to_file=True,
                    )
                else:
                    for it in items:
                        if not isinstance(it, dict):
                            continue
                        loaded_cards.append(DokkanCard.from_dict(it))

                self.log(
                    f"[Step A] Loaded {len(loaded_cards)} cards from user box: {resolved_path}"
                )
            except Exception as exc:
                logger.warning("Error reading user box file %s: %s", resolved_path, exc)

        if len(loaded_cards) < 6:
            self.log(
                f"[Step A] User box has only {len(loaded_cards)} cards (< 6). Consulting DokkanDB catalog fallback."
            )
            catalog = self.dokkandb.get_cards_catalog() if self.dokkandb else []
            for raw_item in catalog[:200]:
                loaded_cards.append(DokkanCard.from_dokkandb(raw_item))

        self.user_box = loaded_cards
        return loaded_cards

    def step_a_initialize(self, stage: BossStage) -> list[DokkanCard]:
        """Loads box & memory, then generates optimal initial team."""
        self.current_state = EndgameRunnerState.STEP_A_INIT
        self.log(f"[Step A] Initializing Endgame Session for: {stage.stage_name}")

        self.load_user_box()
        self.memory.load()

        if len(self.user_box) < 6:
            raise ValueError(
                f"Cannot build team: Candidate pool requires >= 6 cards, found {len(self.user_box)}"
            )

        # Check if memory already has a recorded winning team for this stage
        # When dry_run, force_solve or mission constraints are active, ignore cached winning teams
        has_mission_restrictions = bool(
            self.mission_batch
            and (
                getattr(self.mission_batch, "required_categories", None)
                or getattr(self.mission_batch, "requires_rainbow", False)
                or getattr(self.mission_batch, "requires_all_super", False)
                or getattr(self.mission_batch, "requires_all_extreme", False)
            )
        )
        winning_ids = (
            None
            if (self.dry_run or self.force_solve or has_mission_restrictions)
            else self.memory.get_winning_team(stage.stage_id)
        )
        if winning_ids and len(winning_ids) >= 6:
            box_map = {c.id: c for c in self.user_box}
            if all(cid in box_map for cid in winning_ids[:6]):
                self.current_team = [box_map[cid] for cid in winning_ids[:6]]
                self.log(
                    f"[Step A] Loaded previously successful Winning Team ({[c.name for c in self.current_team]})."
                )
                table_str = format_team_summary_table(self.current_team)
                self.log(f"\n[Step A] Loaded Winning Team Summary Table:\n{table_str}\n")
                return self.current_team

        # Synthesize optimal initial team using TeamBuilder & Constraint Solver
        if has_mission_restrictions and self.mission_batch is not None:
            summary_str = getattr(self.mission_batch, "summary", "")
            self.log(f"[Step A] Synthesizing mission-tailored 6-card team ({summary_str})...")
        else:
            self.log("[Step A] Synthesizing optimal 6-card team with TeamBuilder & Solver...")

        rec, _shortlist = self.team_builder.select_best_team_for_boss(
            candidate_pool=self.user_box,
            boss_stage=stage,
            generate_tactics=False,
            mission_batch=self.mission_batch,
        )
        self.current_team = list(rec.all_cards)
        table_str = format_team_summary_table(self.current_team)
        self.log(
            f"[Step A] Generated Team: Leader={self.current_team[0].name} | "
            f"Rotations=({rec.rotation_a.slot1.name} & {rec.rotation_a.slot2.name} / "
            f"{rec.rotation_b.slot1.name} & {rec.rotation_b.slot2.name})"
        )
        self.log(f"\n[Step A] Synthesized Team Summary Table:\n{table_str}\n")
        return self.current_team

    # =========================================================================
    # STEP B: IN-GAME TEAM FORMATION
    # =========================================================================

    def step_b_apply_formation_if_needed(self) -> bool:
        """Applies current_team in-game via team_formation.py if different from equipped."""
        self.current_state = EndgameRunnerState.STEP_B_FORMATION
        current_ids = [c.id for c in self.current_team]

        if current_ids == self.equipped_team_ids:
            self.log(
                f"[Step B] Team already equipped in-game ({len(current_ids)} cards). Skipping formation."
            )
            return True

        self.log(
            f"[Step B] Team modified ({[c.name for c in self.current_team]}). Applying team formation in-game..."
        )
        ok = apply_team_in_game(
            adb=self.adb,
            vision=self.vision,
            detector=self.detector,
            team_cards=self.current_team,
            user_box_path=str(self.user_box_path),
            dry_run=self.dry_run,
            previous_team_ids=self.equipped_team_ids,
        )
        if ok:
            self.equipped_team_ids = list(current_ids)
            self.log("[Step B] Team formation confirmed successfully.")
        else:
            self.log("[Step B] Team formation returned False; proceeding with caution.")
        return ok

    # =========================================================================
    # STEP C: FRIEND SELECTION, AUTO-BATTLE ON, & OBSERVATION TELEMETRY LOOP
    # =========================================================================

    def step_c_start_and_observe(
        self,
        attempt_num: int,
        stage: BossStage,
    ) -> tuple[EndgameStageOutcome, TurnSnapshot | None, list[CombatFrame]]:
        """Coordinates Friend Leader selection, Auto-Battle check, and telemetry observation."""
        self.current_state = EndgameRunnerState.STEP_C_START
        self.log(
            f"\n--- [Attempt {attempt_num}/{self.max_attempts}] Starting Battle against {stage.stage_name} ---"
        )

        # 1. Custom / Injected Battle Simulator (used in testing & mock scenarios)
        if self.battle_simulator:
            self.log("[Step C] Invoking Battle Simulator...")
            outcome_str, snapshot, frames = self.battle_simulator(
                attempt_num, self.current_team, stage
            )
            outcome = (
                EndgameStageOutcome.VICTORY
                if outcome_str == "victory"
                else EndgameStageOutcome.DEFEAT
            )

            # Record turn snapshot and frames into tracker
            if snapshot:
                self.telemetry_tracker.last_snapshot = snapshot
                self.telemetry_tracker.current_turn = snapshot.turn_number
                self.telemetry_tracker.current_phase_index = snapshot.boss_phase_index
            if frames:
                self.telemetry_tracker.ring_buffer.clear()
                for fr in frames:
                    self.telemetry_tracker.record_frame(fr)

            return outcome, snapshot, frames or []

        # 2. Dry-Run / Simulated Hardware Mode (when ADB is not connected)
        is_connected = False
        if self.adb:
            try:
                is_connected = bool(self.adb.is_connected())
            except Exception:
                is_connected = False

        if self.dry_run or not is_connected or not self.vision or not self.detector:
            self.log(f"[Step C] Simulating live combat in Dry-Run mode (attempt {attempt_num})...")
            self.log("  1. Selecting Friend Leader (checking button_friend_refresh.png)...")
            self.log("  2. Tapping button_start.png...")
            self.log("  3. Verifying Auto-Battle is ON (btn_auto_battle_on.png)...")
            self.log("  4. Running observation telemetry ring buffer...")

            # In dry run, simulate clear on first attempt unless max_attempts > 1
            last_phase = stage.phases[-1] if stage.phases else BossPhase()
            rot = self.current_team[:3]
            snap = self.telemetry_tracker.start_turn(
                turn_number=3,
                boss_phase_index=len(stage.phases) or 1,
                boss_element=last_phase.element,
                boss_element_name=last_phase.element_name,
                boss_hp_percent=0.0,
                player_hp_percent=100.0,
                active_rotation=rot,
            )
            return EndgameStageOutcome.VICTORY, snap, []

        # 3. Live Hardware Execution Loop via ADB & Vision
        return self._run_live_combat_loop(attempt_num, stage)

    def _run_live_combat_loop(
        self,
        _attempt_num: int,
        stage: BossStage,
    ) -> tuple[EndgameStageOutcome, TurnSnapshot | None, list[CombatFrame]]:
        """Executes the live combat observation loop on device screen."""
        assert self.adb is not None
        assert self.vision is not None
        assert self.detector is not None

        turn_count = 0
        phase_idx = 1
        last_snapshot: TurnSnapshot | None = None
        consecutive_unknowns = 0

        self.telemetry_tracker.ring_buffer.clear()

        while not self.is_stopped():
            screen = self.adb.screencap()
            state, meta = self.detector.detect(screen)
            w = meta.get("screen_width", 1080)
            h = meta.get("screen_height", 1920)

            # Step C-1: Friend Selection Screen
            if state == GameState.FRIEND_SELECT:
                self.log("[Step C] Screen: FRIEND_SELECT. Selecting optimal Friend Leader...")
                refresh_match = self.vision.find_template(screen, "button_friend_refresh")
                if refresh_match:
                    logger.debug("Friend refresh button visible at %s", refresh_match)
                # Tap top friend candidate
                self.adb.tap(int(w * 0.50), int(h * 0.38), delay_after=2.0)

            # Step C-2: Team Confirm Screen
            elif state == GameState.TEAM_CONFIRM:
                self.log("[Step C] Screen: TEAM_CONFIRM. Tapping button_start...")
                start_btn = meta.get("start_button") or self.vision.find_template(
                    screen, "button_start"
                )
                if start_btn:
                    self.adb.tap(start_btn[0], start_btn[1], delay_after=3.0)
                else:
                    self.adb.tap(int(w * 0.88), int(h * 0.88), delay_after=3.0)

            # Step C-3: Map Screen
            elif state == GameState.MAP_SCREEN:
                self.log("[Step C] Screen: MAP_SCREEN. Advancing on board...")
                self.adb.tap(int(w * 0.50), int(h * 0.80), delay_after=1.5)

            # Step C-4: Battle Screen (Turn Telemetry & Auto-Battle check)
            elif state == GameState.BATTLE_SCREEN:
                turn_count += 1
                self.current_state = EndgameRunnerState.STEP_C_OBSERVE
                self.log(f"[Step C] Screen: BATTLE_SCREEN (Turn {turn_count})...")

                # Ensure Auto-Battle is active
                auto_on = self.vision.find_template(screen, "btn_auto_battle_on")
                if not auto_on:
                    auto_off = self.vision.find_template(screen, "btn_auto_battle_off")
                    if auto_off:
                        self.log("[Step C] Auto-Battle is OFF. Tapping to toggle ON...")
                        self.adb.tap(auto_off[0], auto_off[1], delay_after=0.8)
                else:
                    self.log("[Step C] Auto-Battle is ON (btn_auto_battle_on confirmed).")

                # Ki spheres snapshot & telemetry observation
                orb_y = int(h * 0.53)
                self.log(
                    f"[Step C] Capturing Ki sphere board snapshot (y~{orb_y}) & updating telemetry..."
                )

                # Capture Turn Snapshot
                active_rot = self.current_team[:3]
                cur_phase = (
                    stage.phases[min(phase_idx - 1, len(stage.phases) - 1)]
                    if stage.phases
                    else BossPhase()
                )
                last_snapshot = self.telemetry_tracker.start_turn(
                    turn_number=turn_count,
                    boss_phase_index=phase_idx,
                    boss_element=cur_phase.element,
                    boss_element_name=cur_phase.element_name,
                    boss_hp_percent=100.0,
                    player_hp_percent=100.0,
                    active_rotation=active_rot,
                )

                # Record combat frame into ring buffer
                self.telemetry_tracker.record_action(
                    active_slot=1,
                    target_card_id=active_rot[0].id if active_rot else None,
                    incoming_damage=0,
                    player_hp_after=100.0,
                    is_lethal=False,
                )

                # Collect Ki Spheres or let Auto-Battle play
                time.sleep(2.0)

            # Step D: Victory Check (Results / OK Button)
            elif state in (
                GameState.RESULTS_SCREEN,
                GameState.KO_SCREEN,
            ) or self.vision.find_template(screen, "button_ok"):
                ok_btn = self.vision.find_template(screen, "button_ok")
                if ok_btn:
                    self.adb.tap(ok_btn[0], ok_btn[1], delay_after=1.5)
                return (
                    EndgameStageOutcome.VICTORY,
                    last_snapshot,
                    self.telemetry_tracker.ring_buffer.get_pre_ko_frames(),
                )

            # Step D: Game Over Check (Attempt Again Button)
            elif state == GameState.GAME_OVER or self.vision.find_template(
                screen, "button_attempt_again"
            ):
                self.log("[Step D] Game Over screen detected!")
                again_btn = self.vision.find_template(screen, "button_attempt_again")
                if again_btn:
                    self.adb.tap(again_btn[0], again_btn[1], delay_after=1.5)
                return (
                    EndgameStageOutcome.DEFEAT,
                    last_snapshot,
                    self.telemetry_tracker.ring_buffer.get_pre_ko_frames(),
                )

            elif state == GameState.UNKNOWN:
                consecutive_unknowns += 1
                if consecutive_unknowns >= 6:
                    self.adb.tap(int(w * 0.50), int(h * 0.50), delay_after=1.0)
                    consecutive_unknowns = 0

            time.sleep(1.0)

        return (
            EndgameStageOutcome.ABORTED,
            last_snapshot,
            self.telemetry_tracker.ring_buffer.get_pre_ko_frames(),
        )

    # =========================================================================
    # STEP D: OUTCOME EVALUATION & ADAPTIVE DECISION TREE
    # =========================================================================

    def step_d_handle_outcome(
        self,
        outcome: EndgameStageOutcome,
        stage: BossStage,
    ) -> bool:
        """Processes victory or defeat. Returns True if stage is cleared and loop should end."""
        self.current_state = EndgameRunnerState.STEP_D_OUTCOME

        if outcome == EndgameStageOutcome.VICTORY:
            self.log(f"\n🎉 [Step D] STAGE CLEARED! Victory confirmed against {stage.stage_name}!")
            self.telemetry_tracker.handle_victory(
                stage_id=stage.stage_id,
                winning_team=self.current_team,
                boss_stage=stage,
            )
            if self.dry_run:
                self.log(
                    "[Step D] [Dry-Run] Simulated victory; skipped saving Winning Team to disk."
                )
            else:
                self.log(
                    f"[Step D] Registered Winning Team in ai_memory.json: {[c.name for c in self.current_team]}"
                )
            table_str = format_team_summary_table(self.current_team)
            self.log(f"\n🏆 Final Winning Team Summary Table:\n{table_str}\n")
            return True

        if outcome == EndgameStageOutcome.DEFEAT:
            self.log("\n💀 [Step D] Defeat detected. Evaluating Episodic Decision Tree...")
            is_final = False
            if stage.phases:
                cur_phase_idx = self.telemetry_tracker.current_phase_index
                is_final = cur_phase_idx >= len(stage.phases)

            attrib, report, decision = self.telemetry_tracker.handle_defeat(
                stage_id=stage.stage_id,
                current_team=self.current_team,
                user_box=self.user_box,
                friend_leader=None,
                boss_stage=stage,
                solver=self.solver,
                is_final_phase=is_final,
            )

            self.failure_reports_history.append(report)
            self.decisions_history.append(decision)

            self.log(
                f"[Step D] Failure Classification: {report.classification} | Reason: {report.reason}"
            )
            self.log(f"[Step D] Decision Tree Action: {decision.action} -> {decision.reason}")

            # Apply Decision Tree Team Modification
            if (
                decision.action
                in ("SurgicalReplace", "SurgicalSwap", "DemoteLeader", "LeaderSwitch")
                and decision.team
            ):
                self.current_team = list(decision.team)
                self.log(
                    f"[Step D] Adapted Team for next attempt: {[c.name for c in self.current_team]}"
                )
                table_str = format_team_summary_table(self.current_team)
                self.log(f"\n[Step D] Adapted Team Summary Table for next attempt:\n{table_str}\n")
            elif decision.action in ("InstantRetry", "instant_retry"):
                self.log(
                    "[Step D] Tactical RNG / Friend Leader defeat: Retrying with unchanged team."
                )

            return False

        # Aborted or stopped
        return False

    # =========================================================================
    # MAIN COORDINATION LOOP
    # =========================================================================

    def run(self, stage_or_id: BossStage | int | str | None = None) -> EndgameResult:
        """Main autonomous execution loop running Trial & Error until stage clear or max_attempts."""
        # Resolve target BossStage
        if isinstance(stage_or_id, BossStage):
            target_stage = stage_or_id
        elif stage_or_id is not None:
            target_stage = get_boss_stage(stage_or_id, dokkandb=self.dokkandb)
        elif self.boss_stage is not None:
            target_stage = self.boss_stage
        else:
            target_stage = get_boss_stage(10101)  # Default: Red Zone Broly

        self.boss_stage = target_stage
        if self._stopped:
            msg = "Execution stopped by user."
            self.log(f"[EndgameRunner] {msg}")
            return EndgameResult(
                success=False,
                attempts=0,
                winning_team=[],
                stage=target_stage,
                message=msg,
            )

        self.current_attempt = 0
        self.decisions_history.clear()
        self.failure_reports_history.clear()

        self.log(
            f"=== Launching Endgame Autonomous Runner: {target_stage.stage_name} (Max Attempts: {self.max_attempts}) ==="
        )

        # Step A: Load inventory, memory, and initial team
        self.step_a_initialize(target_stage)

        stage_cleared = False

        while not stage_cleared and self.current_attempt < self.max_attempts:
            if self.is_stopped():
                self.log("[EndgameRunner] Execution stopped by user.")
                break

            self.current_attempt += 1

            # Step B: Apply formation in-game if team changed
            self.step_b_apply_formation_if_needed()

            # Step C: Select Friend Leader, start, ensure auto-battle, run telemetry
            outcome, _snap, _frames = self.step_c_start_and_observe(
                attempt_num=self.current_attempt,
                stage=target_stage,
            )

            if self.on_run_complete:
                with contextlib.suppress(Exception):
                    self.on_run_complete(self.current_attempt, self.max_attempts)

            # Step D: Outcome handling & adaptive decision tree
            stage_cleared = self.step_d_handle_outcome(outcome, target_stage)

        # Session finished
        if stage_cleared:
            self.current_state = EndgameRunnerState.COMPLETED
            msg = f"Stage {target_stage.stage_name} cleared in {self.current_attempt} attempt(s)!"
            self.log(f"\n🏆 SUCCESS: {msg}")
            return EndgameResult(
                success=True,
                attempts=self.current_attempt,
                winning_team=self.current_team,
                stage=target_stage,
                decisions=self.decisions_history,
                failure_reports=self.failure_reports_history,
                message=msg,
            )
        else:
            self.current_state = EndgameRunnerState.MAX_ATTEMPTS_REACHED
            msg = f"Failed to clear stage after {self.current_attempt} attempts."
            self.log(f"\n❌ LIMIT REACHED: {msg}")
            return EndgameResult(
                success=False,
                attempts=self.current_attempt,
                winning_team=[],
                stage=target_stage,
                decisions=self.decisions_history,
                failure_reports=self.failure_reports_history,
                message=msg,
            )


__all__ = [
    "BattleSimulatorFn",
    "EndgameResult",
    "EndgameRunner",
    "EndgameRunnerState",
    "EndgameStageOutcome",
]
