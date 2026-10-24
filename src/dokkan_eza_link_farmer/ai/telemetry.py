"""Combat Telemetry, Credit Assignment and Episodic Memory for Dokkan AI Teambuilder.

Provides:
- TurnSnapshot & CombatFrame telemetry models.
- CombatRingBuffer maintaining a rolling FIFO buffer of the last 3-4 pre-KO frames.
- Culprit attribution with direct slot detection, friend leader immunity (Slot 7),
  and distributed vulnerability sharing (0.33 each or elemental-weighted).
- EpisodicMemory with atomic persistence in ~/.dokkan-farmer/cache/ai_memory.json:
  * Rule 1: Boss HP < 20% in Final Phase -> InstantRetry (Tactical RNG).
  * Rule 2: 3 consecutive defeats on Turns 1-2 -> Leader Demotion to 2nd best leader in box.
  * Rule 3: Surgical single-card replacement of unit with maximum death_penalty,
    including Orphan Partner link check: if shared links < 3, force replacement with
    >= 4 links or execute a Pair Swap fallback.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dokkan_eza_link_farmer.ai.models import (
    BossPhase,
    BossStage,
    DokkanCard,
)
from dokkan_eza_link_farmer.ai.solver import (
    DokkanConstraintSolver,
)

logger = logging.getLogger(__name__)

DEFAULT_MEMORY_CACHE_PATH = os.path.expanduser("~/.dokkan-farmer/cache/ai_memory.json")

# Global flag to control extended memory telemetry tracking.
# In standard farming runs (EZA 999, Link Leveling), extended frame recording in CombatTelemetryTracker is frozen.
_DEBUG_TELEMETRY: bool = False


def is_debug_telemetry_enabled() -> bool:
    """Returns True if extended telemetry observation is enabled."""
    return _DEBUG_TELEMETRY or (os.environ.get("DEBUG_TELEMETRY", "").lower() in ("1", "true", "yes"))


def set_debug_telemetry(enabled: bool) -> None:
    """Explicitly enables or disables extended telemetry observation."""
    global _DEBUG_TELEMETRY
    _DEBUG_TELEMETRY = enabled



@dataclass
class TurnSnapshot:
    """Turn-start snapshot capturing combat state before action execution."""

    turn_number: int
    boss_phase_index: int
    boss_element: int
    boss_element_name: str
    boss_hp_percent: float  # 0.0 to 100.0
    player_hp_percent: float  # 0.0 to 100.0
    active_rotation: list[DokkanCard]  # Exactly 3 units (Slot 1, Slot 2, Slot 3)
    active_item: str | None = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_number": self.turn_number,
            "boss_phase_index": self.boss_phase_index,
            "boss_element": self.boss_element,
            "boss_element_name": self.boss_element_name,
            "boss_hp_percent": self.boss_hp_percent,
            "player_hp_percent": self.player_hp_percent,
            "active_rotation_ids": [c.id for c in self.active_rotation],
            "active_item": self.active_item,
            "timestamp": self.timestamp,
        }


@dataclass
class CombatFrame:
    """Atomic combat frame recorded during turn execution."""

    frame_id: int
    timestamp: float = field(default_factory=time.time)
    active_slot: int | None = None  # 1, 2, 3 (or 7 for Friend Leader)
    target_card_id: int | None = None
    incoming_damage: int | None = None
    player_hp_after: float = 0.0
    is_lethal: bool = False
    action_type: str = "normal"  # "normal", "super_attack", "aoe"

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame_id": self.frame_id,
            "timestamp": self.timestamp,
            "active_slot": self.active_slot,
            "target_card_id": self.target_card_id,
            "incoming_damage": self.incoming_damage,
            "player_hp_after": self.player_hp_after,
            "is_lethal": self.is_lethal,
            "action_type": self.action_type,
        }


@dataclass
class CulpritAttribution:
    """Attribution of defeat to a direct culprit or distributed vulnerability."""

    direct_culprit_id: int | None = None
    direct_culprit_slot: int | None = None  # 1, 2, 3, or 7
    is_friend_leader: bool = False
    is_ambiguous: bool = False
    vulnerability_shares: dict[int, float] = field(default_factory=dict)
    lethal_frame: CombatFrame | None = None
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "direct_culprit_id": self.direct_culprit_id,
            "direct_culprit_slot": self.direct_culprit_slot,
            "is_friend_leader": self.is_friend_leader,
            "is_ambiguous": self.is_ambiguous,
            "vulnerability_shares": {str(k): v for k, v in self.vulnerability_shares.items()},
            "reason": self.reason,
        }


@dataclass
class FailureReport:
    """Structured report of combat defeat for AI telemetry and Advisor."""

    defeat_turn: int
    phase_index: int
    boss_element: int
    boss_hp_percent: float
    culprit_card_id: int | None
    classification: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "defeat_turn": self.defeat_turn,
            "phase_index": self.phase_index,
            "boss_element": self.boss_element,
            "boss_hp_percent": self.boss_hp_percent,
            "culprit_card_id": self.culprit_card_id,
            "classification": self.classification,
            "reason": self.reason,
        }


@dataclass
class PostDefeatDecision:
    """Decision produced by EpisodicMemory post-defeat evaluation."""

    action: str  # "InstantRetry", "DemoteLeader", "SurgicalReplace"
    team: list[DokkanCard] = field(default_factory=list)
    replaced_card_ids: list[int] = field(default_factory=list)
    new_card_ids: list[int] = field(default_factory=list)
    reason: str = ""
    demoted_leader_id: int | None = None
    new_leader_id: int | None = None
    modified_team: list[DokkanCard] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.team and self.modified_team:
            self.team = list(self.modified_team)
        elif not self.modified_team and self.team:
            self.modified_team = list(self.team)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "team_card_ids": [c.id for c in self.team],
            "replaced_card_ids": self.replaced_card_ids,
            "new_card_ids": self.new_card_ids,
            "reason": self.reason,
            "demoted_leader_id": self.demoted_leader_id,
            "new_leader_id": self.new_leader_id,
        }


class CombatRingBuffer:
    """Maintains a rolling FIFO window of the last 3-4 frames prior to KO/defeat."""

    def __init__(self, capacity: int = 4) -> None:
        if capacity <= 0:
            raise ValueError(f"CombatRingBuffer capacity must be > 0, got {capacity}")
        self._capacity = capacity
        self._buffer: deque[CombatFrame] = deque(maxlen=capacity)

    @property
    def capacity(self) -> int:
        return self._capacity

    def record_frame(self, frame: CombatFrame) -> None:
        self._buffer.append(frame)

    def get_pre_ko_frames(self) -> list[CombatFrame]:
        return list(self._buffer)

    def clear(self) -> None:
        self._buffer.clear()

    def __len__(self) -> int:
        return len(self._buffer)


def attribute_culprit(
    ring_buffer: CombatRingBuffer,
    snapshot: TurnSnapshot,
    friend_leader: DokkanCard | None = None,
    boss_phase: BossPhase | None = None,
) -> CulpritAttribution:
    """
    Identifies direct culprit from lethal frame slot or distributes vulnerability shares.
    - Slot 7 (Friend Leader): triggers Friend Leader immunity (0 penalty, Bad RNG).
    - Slot 1, 2, 3: direct attribution to unit in that slot with 1.0 death penalty.
    - Ambiguous / AoE: equal distribution (0.33 each) or elemental disadvantage weighted (0.60 / 0.20).
    """
    frames = ring_buffer.get_pre_ko_frames()

    # Search for lethal frame: explicit is_lethal, or HP dropped to <= 0, or last frame in buffer
    lethal_frame: CombatFrame | None = None
    for f in reversed(frames):
        if f.is_lethal:
            lethal_frame = f
            break
    if lethal_frame is None:
        for f in reversed(frames):
            if f.player_hp_after <= 0.0:
                lethal_frame = f
                break
    if lethal_frame is None and frames:
        lethal_frame = frames[-1]

    # Check for AoE attack or missing slot -> Ambiguous attribution
    is_aoe = lethal_frame is not None and lethal_frame.action_type.lower() == "aoe"
    has_isolated_slot = lethal_frame is not None and lethal_frame.active_slot in (1, 2, 3, 7)

    if lethal_frame is not None and has_isolated_slot and not is_aoe:
        slot = lethal_frame.active_slot
        if slot == 7:
            # Friend Leader immunity: Slot 7
            friend_id = friend_leader.id if friend_leader else (lethal_frame.target_card_id or 7)
            return CulpritAttribution(
                direct_culprit_id=friend_id,
                direct_culprit_slot=7,
                is_friend_leader=True,
                is_ambiguous=False,
                vulnerability_shares={},  # 0 penalty to player cards
                lethal_frame=lethal_frame,
                reason="Defeat attributed to Friend Leader (Slot 7) — classified as Bad RNG",
            )
        elif slot in (1, 2, 3):
            # Direct attribution to player rotation unit
            culprit_card: DokkanCard | None = None
            if len(snapshot.active_rotation) >= slot:
                culprit_card = snapshot.active_rotation[slot - 1]
            culprit_id = lethal_frame.target_card_id or (culprit_card.id if culprit_card else None)

            shares: dict[int, float] = {}
            if culprit_id is not None:
                shares[culprit_id] = 1.0

            card_name = culprit_card.name if culprit_card else f"Slot {slot}"
            return CulpritAttribution(
                direct_culprit_id=culprit_id,
                direct_culprit_slot=slot,
                is_friend_leader=False,
                is_ambiguous=False,
                vulnerability_shares=shares,
                lethal_frame=lethal_frame,
                reason=f"Lethal hit sustained by Slot {slot} ({card_name})",
            )

    # Ambiguous or AoE defeat: distribute vulnerability across active rotation
    if not snapshot.active_rotation:
        return CulpritAttribution(
            direct_culprit_id=None,
            direct_culprit_slot=None,
            is_friend_leader=False,
            is_ambiguous=True,
            vulnerability_shares={},
            lethal_frame=lethal_frame,
            reason="Ambiguous defeat with empty active rotation",
        )

    boss_elem = boss_phase.element if boss_phase else snapshot.boss_element

    # Check for elemental disadvantage weighting refinement
    disadvantaged_units: list[DokkanCard] = []
    for c in snapshot.active_rotation:
        matchup = DokkanConstraintSolver.check_type_matchup(c.element, boss_elem)
        if matchup < 0:
            has_guard = c.has_guard or (
                c.base_form is not None
                and c.base_form.passive_tags is not None
                and c.base_form.passive_tags.has_guard
            )
            dr = c.damage_reduction_percent
            if (
                c.base_form is not None
                and c.base_form.passive_tags is not None
                and c.base_form.passive_tags.dr_base_percent > dr
            ):
                dr = c.base_form.passive_tags.dr_base_percent
            if not has_guard and dr < 60:
                disadvantaged_units.append(c)

    shares = {}
    rot_len = len(snapshot.active_rotation)
    if len(disadvantaged_units) == 1 and rot_len == 3:
        # Weight unshielded type disadvantaged unit at 0.60, others at 0.20
        disadv_id = disadvantaged_units[0].id
        for c in snapshot.active_rotation:
            shares[c.id] = 0.60 if c.id == disadv_id else 0.20
    else:
        # Standard equal sharing: exactly 0.33 each for 3 units
        equal_share = round(1.0 / rot_len, 2)
        for c in snapshot.active_rotation:
            shares[c.id] = equal_share

    return CulpritAttribution(
        direct_culprit_id=None,
        direct_culprit_slot=None,
        is_friend_leader=False,
        is_ambiguous=True,
        vulnerability_shares=shares,
        lethal_frame=lethal_frame,
        reason="Ambiguous / AoE damage: vulnerability shared across active rotation",
    )


def create_failure_report(
    snapshot: TurnSnapshot,
    attribution: CulpritAttribution,
    decision: PostDefeatDecision,
) -> FailureReport:
    """Builds a FailureReport based on combat telemetry and episodic decision."""
    if attribution.is_friend_leader:
        classification = "Bad RNG"
    elif decision.action == "InstantRetry":
        classification = "Tactical RNG"
    elif decision.action == "DemoteLeader":
        classification = "Early Loss"
    else:
        classification = "Card Vulnerability"

    return FailureReport(
        defeat_turn=snapshot.turn_number,
        phase_index=snapshot.boss_phase_index,
        boss_element=snapshot.boss_element,
        boss_hp_percent=snapshot.boss_hp_percent,
        culprit_card_id=attribution.direct_culprit_id,
        classification=classification,
        reason=decision.reason or attribution.reason,
    )


class EpisodicMemory:
    """
    Episodic memory tracking stage attempts, defeats, culprit death penalties,
    consecutive early defeat streaks, and executing the 3-tier post-defeat decision tree.
    Persisted atomically in ~/.dokkan-farmer/cache/ai_memory.json.
    """

    def __init__(self, cache_path: str | Path | None = None, ephemeral: bool = False) -> None:
        self.cache_path = Path(cache_path or DEFAULT_MEMORY_CACHE_PATH)
        self.ephemeral = ephemeral
        self._data: dict[str, Any] = {"updated_at": "", "stages": {}}
        self.load()

    def load(self) -> dict[str, Any]:
        """Loads memory from cache_path if it exists."""
        if not self.cache_path.exists():
            self._data = {
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "stages": {},
            }
            return self._data
        try:
            with open(self.cache_path, encoding="utf-8") as f:
                content = json.load(f)
                if isinstance(content, dict) and "stages" in content:
                    self._data = content
                else:
                    self._data = {
                        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "stages": {},
                    }
        except Exception as e:
            logger.warning("Failed to load episodic memory from %s: %s", self.cache_path, e)
            self._data = {
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "stages": {},
            }
        return self._data

    def save(self) -> None:
        """Atomically saves memory cache to JSON file (no-op if ephemeral)."""
        if self.ephemeral:
            return
        self._data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temp_file = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.cache_path.parent,
                delete=False,
                suffix=".tmp",
            ) as tf:
                temp_file = tf.name
                json.dump(self._data, tf, indent=2)
            os.replace(temp_file, self.cache_path)
        except Exception as e:
            logger.error("Failed to atomically write episodic memory: %s", e)
            if temp_file and os.path.exists(temp_file):
                with contextlib.suppress(OSError):
                    os.remove(temp_file)
            raise

    def get_stage_data(self, stage_id: int) -> dict[str, Any]:
        """Returns the dictionary for a specific stage, initializing if absent."""
        s_id = str(stage_id)
        if s_id not in self._data.setdefault("stages", {}):
            self._data["stages"][s_id] = {
                "stage_id": stage_id,
                "event_name": "",
                "stage_name": "",
                "attempts": 0,
                "defeats": 0,
                "consecutive_early_defeats": 0,
                "current_leader_id": None,
                "card_death_penalties": {},
                "history": [],
            }
        return self._data["stages"][s_id]

    def get_death_penalties(self, stage_id: int) -> dict[int, float]:
        """Returns card death penalties mapping {card_id: float}."""
        stage_data = self.get_stage_data(stage_id)
        raw = stage_data.get("card_death_penalties", {})
        return {int(k): float(v) for k, v in raw.items()}

    def get_consecutive_early_defeats(self, stage_id: int) -> int:
        """Returns count of consecutive defeats on Turns 1-2."""
        stage_data = self.get_stage_data(stage_id)
        return int(stage_data.get("consecutive_early_defeats", 0))

    def record_defeat(
        self,
        stage_id: int,
        snapshot: TurnSnapshot,
        attribution: CulpritAttribution,
        decision: PostDefeatDecision,
        boss_stage: BossStage | None = None,
    ) -> None:
        """Records defeat in history and updates attempts/defeats stats."""
        stage_data = self.get_stage_data(stage_id)
        stage_data["attempts"] = stage_data.get("attempts", 0) + 1
        stage_data["defeats"] = stage_data.get("defeats", 0) + 1
        if boss_stage:
            stage_data["event_name"] = boss_stage.event_name
            stage_data["stage_name"] = boss_stage.stage_name

        history_entry = {
            "attempt": stage_data["attempts"],
            "turn": snapshot.turn_number,
            "phase": snapshot.boss_phase_index,
            "boss_hp_percent": snapshot.boss_hp_percent,
            "culprit_card_id": attribution.direct_culprit_id,
            "is_friend_leader": attribution.is_friend_leader,
            "decision": decision.action,
            "reason": decision.reason,
        }
        stage_data.setdefault("history", []).append(history_entry)
        self.save()

    def record_victory(
        self,
        stage_id: int,
        team: list[DokkanCard],
        boss_stage: BossStage | None = None,
        turns: int | None = None,
    ) -> None:
        """Records winning team and stage clear telemetry in episodic memory."""
        stage_data = self.get_stage_data(stage_id)
        stage_data["attempts"] = stage_data.get("attempts", 0) + 1
        stage_data["victories"] = stage_data.get("victories", 0) + 1
        stage_data["cleared"] = True
        stage_data["consecutive_early_defeats"] = 0
        stage_data["winning_team"] = [c.id for c in team]
        stage_data["winning_team_details"] = [
            {"id": c.id, "name": c.name, "element": c.element} for c in team
        ]
        if boss_stage:
            stage_data["event_name"] = boss_stage.event_name
            stage_data["stage_name"] = boss_stage.stage_name

        history_entry = {
            "attempt": stage_data["attempts"],
            "result": "Victory",
            "turns": turns,
            "team": [c.id for c in team],
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        stage_data.setdefault("history", []).append(history_entry)
        self.save()

    def get_winning_team(self, stage_id: int) -> list[int] | None:
        """Returns the list of winning card IDs if previously cleared."""
        stage_data = self.get_stage_data(stage_id)
        return stage_data.get("winning_team")

    def _find_second_best_leader(
        self,
        user_box: list[DokkanCard],
        current_leader: DokkanCard,
        solver: DokkanConstraintSolver | None = None,
        boss_stage: BossStage | None = None,
    ) -> DokkanCard | None:
        """Finds the 2nd best leader in user_box excluding the demoted current_leader."""
        eligible_leaders = [c for c in user_box if c.id != current_leader.id]
        if not eligible_leaders:
            return None

        scored_leaders: list[tuple[DokkanCard, float]] = []
        for c in eligible_leaders:
            l_score = 0.0
            if c.leader_spec:
                l_score += c.leader_spec.base_boost_pct * 0.2 + c.leader_spec.extra_boost_pct * 0.1
            else:
                if "200%" in c.leader_skill:
                    l_score += 40.0
                elif "170%" in c.leader_skill:
                    l_score += 34.0
                elif "150%" in c.leader_skill:
                    l_score += 20.0

            kit_power, _ = c.evaluate_kit_power()
            l_score += kit_power * 0.1

            if (solver and solver.is_slot1_viable(c)) or c.is_slot1_tank:
                l_score += 10.0

            # Consideration for boss stage matchup if stage is known
            if boss_stage and boss_stage.phases:
                final_elem = boss_stage.phases[-1].element
                l_score += DokkanConstraintSolver.check_type_matchup(c.element, final_elem) * 5.0

            # Count box coverage
            cov_count = 0
            for o in user_box:
                if o.id != c.id:
                    is_cov, boost, _ = o.is_covered_by_leader(c)
                    if is_cov and boost >= 150.0:
                        cov_count += 1
            l_score += min(cov_count, 5) * 5.0
            scored_leaders.append((c, l_score))

        scored_leaders.sort(key=lambda item: item[1], reverse=True)
        return scored_leaders[0][0] if scored_leaders else None

    def evaluate_post_defeat(
        self,
        stage_id: int,
        snapshot: TurnSnapshot,
        attribution: CulpritAttribution,
        current_team: list[DokkanCard],
        user_box: list[DokkanCard],
        solver: DokkanConstraintSolver | None = None,
        boss_stage: BossStage | None = None,
        is_final_phase: bool | None = None,
    ) -> PostDefeatDecision:
        """
        Executes the 3-tier post-defeat decision tree in strict hierarchy:
        1. Friend Leader (Slot 7) Bad RNG -> InstantRetry with unchanged team.
        2. Final Phase & Boss HP < 20% -> InstantRetry (Tactical RNG).
        3. 3 consecutive Turn 1-2 defeats -> Demote Leader & switch to 2nd best leader.
        4. Surgical Single-Card Replacement of unit with max death penalty:
           - Floater replacement with >= 170% lead boost, type advantage, or Guard/DR >= 60%.
           - Core Rotation replacement with Orphan Partner link check (<3 links):
             * Strategy 3b-1: Substitute sharing >= 4 links with partner.
             * Strategy 3b-2: Pair Swap of both culprit & partner with pre-linked pair.
        """
        stage_data = self.get_stage_data(stage_id)

        # Rule 0: Friend Leader Immunity (Slot 7)
        if attribution.is_friend_leader or attribution.direct_culprit_slot == 7:
            decision = PostDefeatDecision(
                action="InstantRetry",
                team=list(current_team),
                modified_team=list(current_team),
                replaced_card_ids=[],
                new_card_ids=[],
                reason="Defeat attributed to Friend Leader (Slot 7) — classified as Bad RNG",
            )
            self.record_defeat(stage_id, snapshot, attribution, decision, boss_stage=boss_stage)
            return decision

        # Rule 1: Final Phase & Boss HP < 20%
        final_phase_flag = False
        if is_final_phase is not None:
            final_phase_flag = is_final_phase
        elif boss_stage and boss_stage.phases:
            final_phase_flag = snapshot.boss_phase_index >= len(boss_stage.phases)
        else:
            final_phase_flag = True

        if final_phase_flag and snapshot.boss_hp_percent < 20.0:
            if snapshot.turn_number > 2:
                stage_data["consecutive_early_defeats"] = 0
            decision = PostDefeatDecision(
                action="InstantRetry",
                team=list(current_team),
                modified_team=list(current_team),
                replaced_card_ids=[],
                new_card_ids=[],
                reason=f"Final Phase Boss HP < 20% ({snapshot.boss_hp_percent:.1f}%) — classified as Tactical RNG",
            )
            self.record_defeat(stage_id, snapshot, attribution, decision, boss_stage=boss_stage)
            return decision

        # Early defeat counter tracking
        if snapshot.turn_number <= 2:
            stage_data["consecutive_early_defeats"] = (
                stage_data.get("consecutive_early_defeats", 0) + 1
            )
        else:
            stage_data["consecutive_early_defeats"] = 0

        # Rule 2: 3 consecutive defeats on Turns 1-2 -> Leader Demotion
        if stage_data.get("consecutive_early_defeats", 0) >= 3:
            current_leader = current_team[0]
            stage_data["consecutive_early_defeats"] = 0
            second_leader = self._find_second_best_leader(
                user_box, current_leader, solver, boss_stage
            )

            new_team: list[DokkanCard] = []
            if solver and second_leader:
                try:
                    res = solver.solve(user_box, boss_stage=boss_stage, forced_leader=second_leader)
                    new_team = res.team_cards
                except Exception as e:
                    logger.warning("Solver failed during leader demotion: %s", e)
                    new_team = [second_leader] + [
                        c
                        for c in current_team
                        if c.id != current_leader.id and c.id != second_leader.id
                    ]
            elif second_leader:
                new_team = [second_leader] + [
                    c
                    for c in current_team
                    if c.id != current_leader.id and c.id != second_leader.id
                ]
            else:
                new_team = list(current_team)

            # Ensure exactly 6 cards
            if len(new_team) < 6:
                for c in user_box:
                    if c.id not in {x.id for x in new_team}:
                        new_team.append(c)
                        if len(new_team) == 6:
                            break

            stage_data["current_leader_id"] = (
                second_leader.id if second_leader else current_leader.id
            )
            decision = PostDefeatDecision(
                action="DemoteLeader",
                team=new_team,
                modified_team=new_team,
                replaced_card_ids=[current_leader.id],
                new_card_ids=[second_leader.id] if second_leader else [],
                demoted_leader_id=current_leader.id,
                new_leader_id=second_leader.id if second_leader else None,
                reason=f"3 consecutive early defeats on Turns 1-2: Demoted leader {current_leader.name} -> switched to {second_leader.name if second_leader else 'Unknown'}",
            )
            self.record_defeat(stage_id, snapshot, attribution, decision, boss_stage=boss_stage)
            return decision

        # Rule 3: Surgical Replacement of Card with Maximum death_penalty
        penalties = stage_data.setdefault("card_death_penalties", {})
        for card_id, share in attribution.vulnerability_shares.items():
            s_cid = str(card_id)
            penalties[s_cid] = round(penalties.get(s_cid, 0.0) + share, 2)

        def get_card_penalty(card: DokkanCard) -> float:
            return float(penalties.get(str(card.id), penalties.get(card.id, 0.0)))

        # Identify culprit card in current_team with maximum death penalty
        culprit_candidate: DokkanCard | None = None
        max_pen = -1.0
        for c in current_team:
            pen = get_card_penalty(c)
            if pen > max_pen:
                max_pen = pen
                culprit_candidate = c

        if max_pen <= 0.0 and attribution.direct_culprit_id is not None:
            for c in current_team:
                if c.id == attribution.direct_culprit_id:
                    culprit_candidate = c
                    break

        culprit = culprit_candidate or current_team[-1]
        leader = current_team[0]

        # Check role of culprit: Floater (Slot 3) or Core Rotation (Slot 1/2)
        is_floater = False
        partner: DokkanCard | None = None

        if snapshot.active_rotation and len(snapshot.active_rotation) >= 3:
            if culprit.id == snapshot.active_rotation[2].id:
                is_floater = True
            elif culprit.id == snapshot.active_rotation[0].id:
                partner = snapshot.active_rotation[1]
            elif culprit.id == snapshot.active_rotation[1].id:
                partner = snapshot.active_rotation[0]

        if not is_floater and partner is None:
            best_partner = None
            best_links = 0
            for c in current_team:
                if c.id != culprit.id:
                    shared = len(set(c.links) & set(culprit.links))
                    if shared > best_links:
                        best_links = shared
                        best_partner = c
            if best_links >= 3:
                partner = best_partner
            else:
                is_floater = True

        available_box = [c for c in user_box if c.id not in {x.id for x in current_team}]

        def get_boost(card: DokkanCard) -> float:
            if solver:
                filtered = solver.filter_by_leader_skill([card], leader, min_pct=170.0)
                if filtered:
                    return filtered[0][1]
            is_cov, boost, _ = card.is_covered_by_leader(leader)
            return boost if is_cov else 0.0

        main_lead_cats = (
            set(leader.leader_spec.main_category_ids)
            if leader.leader_spec and leader.leader_spec.main_category_ids
            else set()
        )
        candidates_170 = [
            c
            for c in available_box
            if get_boost(c) >= 170.0
            and (not main_lead_cats or bool(set(c.category_ids) & main_lead_cats))
        ]
        if not candidates_170 and available_box:
            candidates_170 = available_box

        # Case 3B: Core Rotation with Orphan Partner Link Check
        if not is_floater and partner is not None:
            # Check highest-scoring candidate without link constraint
            top_general_sub = (
                max(candidates_170, key=lambda c: c.evaluate_kit_power()[0])
                if candidates_170
                else None
            )
            shared_with_general = (
                len(set(top_general_sub.links) & set(partner.links)) if top_general_sub else 0
            )

            # Orphan Partner Check: if shared links drop below 3 (< 3)
            if shared_with_general < 3:
                # Strategy 3b-1: Search for replacement card sharing >= 4 links with partner
                qualifying_subs = [
                    c for c in candidates_170 if len(set(c.links) & set(partner.links)) >= 4
                ]
                if qualifying_subs:
                    qualifying_subs.sort(
                        key=lambda c: (
                            DokkanConstraintSolver.check_type_matchup(
                                c.element, snapshot.boss_element
                            ),
                            c.damage_reduction_percent,
                            c.evaluate_kit_power()[0],
                        ),
                        reverse=True,
                    )
                    chosen_sub = qualifying_subs[0]
                    new_team = [chosen_sub if c.id == culprit.id else c for c in current_team]
                    decision = PostDefeatDecision(
                        action="SurgicalReplace",
                        team=new_team,
                        modified_team=new_team,
                        replaced_card_ids=[culprit.id],
                        new_card_ids=[chosen_sub.id],
                        reason=(
                            f"Orphan link check: partner {partner.name} had < 3 links with sub; "
                            f"forced replacement {chosen_sub.name} sharing "
                            f"{len(set(chosen_sub.links) & set(partner.links))} links."
                        ),
                    )
                    self.record_defeat(
                        stage_id, snapshot, attribution, decision, boss_stage=boss_stage
                    )
                    return decision

                # Strategy 3b-2: Pair Swap Fallback
                # Replace BOTH culprit and partner with pre-linked pair sharing >= 4 links
                candidate_pairs: list[tuple[DokkanCard, DokkanCard, float]] = []
                remaining_team_ids = {
                    c.id for c in current_team if c.id not in (culprit.id, partner.id)
                }
                pair_pool = [c for c in candidates_170 if c.id not in remaining_team_ids]

                for i in range(len(pair_pool)):
                    for j in range(i + 1, len(pair_pool)):
                        u1 = pair_pool[i]
                        u2 = pair_pool[j]
                        shared_l = len(set(u1.links) & set(u2.links))
                        if shared_l >= 4:
                            synergy = (
                                shared_l * 5.0
                                + u1.evaluate_kit_power()[0]
                                + u2.evaluate_kit_power()[0]
                            )
                            candidate_pairs.append((u1, u2, synergy))

                if candidate_pairs:
                    candidate_pairs.sort(key=lambda item: item[2], reverse=True)
                    u1, u2, _ = candidate_pairs[0]
                    new_team = []
                    for c in current_team:
                        if c.id == culprit.id:
                            new_team.append(u1)
                        elif c.id == partner.id:
                            new_team.append(u2)
                        else:
                            new_team.append(c)

                    decision = PostDefeatDecision(
                        action="SurgicalReplace",
                        team=new_team,
                        modified_team=new_team,
                        replaced_card_ids=[culprit.id, partner.id],
                        new_card_ids=[u1.id, u2.id],
                        reason=(
                            f"Orphan link check fallback: no single sub with >= 4 links for {partner.name}; "
                            f"executed Pair Swap with {u1.name} & {u2.name}."
                        ),
                    )
                    self.record_defeat(
                        stage_id, snapshot, attribution, decision, boss_stage=boss_stage
                    )
                    return decision

        # Case 3A: Floater replacement (or core rotation with no link deficiency)
        def floater_defense_score(c: DokkanCard) -> float:
            score = 0.0
            matchup = DokkanConstraintSolver.check_type_matchup(c.element, snapshot.boss_element)
            if matchup > 0:
                score += 30.0
            elif matchup < 0 and not c.has_guard and c.damage_reduction_percent < 60:
                score -= 30.0

            if c.has_guard:
                score += 25.0
            if c.damage_reduction_percent >= 60:
                score += 25.0
            elif c.damage_reduction_percent >= 40:
                score += 15.0

            kit, _ = c.evaluate_kit_power()
            score += kit * 0.2
            return score

        candidates_170.sort(key=floater_defense_score, reverse=True)
        chosen_sub = candidates_170[0] if candidates_170 else culprit
        new_team = [chosen_sub if c.id == culprit.id else c for c in current_team]

        decision = PostDefeatDecision(
            action="SurgicalReplace",
            team=new_team,
            modified_team=new_team,
            replaced_card_ids=[culprit.id],
            new_card_ids=[chosen_sub.id] if chosen_sub.id != culprit.id else [],
            reason=f"Surgically replaced floater {culprit.name} with {chosen_sub.name} (>= 170% lead boost, defensive viability).",
        )
        self.record_defeat(stage_id, snapshot, attribution, decision, boss_stage=boss_stage)
        return decision


class CombatTelemetryTracker:
    """Live observation tracker maintaining a rolling FIFO ring-buffer and turn snapshots."""

    def __init__(
        self,
        ring_buffer: CombatRingBuffer | None = None,
        episodic_memory: EpisodicMemory | None = None,
        capacity: int = 4,
        debug_telemetry: bool | None = None,
    ) -> None:
        self.ring_buffer = ring_buffer if ring_buffer is not None else CombatRingBuffer(capacity=capacity)
        self.episodic_memory = episodic_memory or EpisodicMemory()
        self.current_turn: int = 1
        self.current_phase_index: int = 1
        self.last_snapshot: TurnSnapshot | None = None
        self._debug_telemetry = (
            debug_telemetry if debug_telemetry is not None else is_debug_telemetry_enabled()
        )

    def start_turn(
        self,
        turn_number: int,
        boss_phase_index: int,
        boss_element: int,
        boss_element_name: str,
        boss_hp_percent: float,
        player_hp_percent: float,
        active_rotation: list[DokkanCard],
        active_item: str | None = None,
    ) -> TurnSnapshot:
        """Records turn-start snapshot before combat execution."""
        self.current_turn = turn_number
        self.current_phase_index = boss_phase_index
        self.last_snapshot = TurnSnapshot(
            turn_number=turn_number,
            boss_phase_index=boss_phase_index,
            boss_element=boss_element,
            boss_element_name=boss_element_name,
            boss_hp_percent=boss_hp_percent,
            player_hp_percent=player_hp_percent,
            active_rotation=active_rotation,
            active_item=active_item,
        )
        return self.last_snapshot

    def record_frame(self, frame: CombatFrame) -> None:
        """Records an atomic combat frame into the rolling FIFO ring buffer."""
        self.ring_buffer.record_frame(frame)

    def record_action(
        self,
        active_slot: int | None = None,
        target_card_id: int | None = None,
        incoming_damage: int | None = None,
        player_hp_after: float = 0.0,
        is_lethal: bool = False,
        action_type: str = "normal",
    ) -> CombatFrame:
        """Constructs and appends a CombatFrame to the rolling ring buffer."""
        frame = CombatFrame(
            frame_id=len(self.ring_buffer) + 1,
            active_slot=active_slot,
            target_card_id=target_card_id,
            incoming_damage=incoming_damage,
            player_hp_after=player_hp_after,
            is_lethal=is_lethal,
            action_type=action_type,
        )
        # In standard mode, skip adding non-lethal observation frames if debug telemetry is disabled
        if self._debug_telemetry or is_debug_telemetry_enabled() or is_lethal:
            self.record_frame(frame)
        return frame

    def handle_defeat(
        self,
        stage_id: int,
        current_team: list[DokkanCard],
        user_box: list[DokkanCard],
        friend_leader: DokkanCard | None = None,
        boss_stage: BossStage | None = None,
        solver: DokkanConstraintSolver | None = None,
        is_final_phase: bool | None = None,
    ) -> tuple[CulpritAttribution, FailureReport, PostDefeatDecision]:
        """Processes defeat: attributes culprit, runs decision tree, records in memory."""
        snapshot = self.last_snapshot or TurnSnapshot(
            turn_number=self.current_turn,
            boss_phase_index=self.current_phase_index,
            boss_element=boss_stage.phases[-1].element if boss_stage and boss_stage.phases else 0,
            boss_element_name=(
                boss_stage.phases[-1].element_name if boss_stage and boss_stage.phases else ""
            ),
            boss_hp_percent=100.0,
            player_hp_percent=0.0,
            active_rotation=current_team[:3] if len(current_team) >= 3 else [],
        )

        boss_phase = None
        if boss_stage and 1 <= snapshot.boss_phase_index <= len(boss_stage.phases):
            boss_phase = boss_stage.phases[snapshot.boss_phase_index - 1]

        attribution = attribute_culprit(
            self.ring_buffer,
            snapshot,
            friend_leader=friend_leader,
            boss_phase=boss_phase,
        )
        decision = self.episodic_memory.evaluate_post_defeat(
            stage_id=stage_id,
            snapshot=snapshot,
            attribution=attribution,
            current_team=current_team,
            user_box=user_box,
            solver=solver,
            boss_stage=boss_stage,
            is_final_phase=is_final_phase,
        )
        report = create_failure_report(snapshot, attribution, decision)
        return attribution, report, decision

    def handle_victory(
        self,
        stage_id: int,
        winning_team: list[DokkanCard],
        boss_stage: BossStage | None = None,
        turns: int | None = None,
    ) -> None:
        """Processes stage clear and stores winning team in episodic memory."""
        self.episodic_memory.record_victory(
            stage_id=stage_id,
            team=winning_team,
            boss_stage=boss_stage,
            turns=turns or self.current_turn,
        )


EpisodicMemoryManager = EpisodicMemory

__all__ = [
    "CombatFrame",
    "CombatRingBuffer",
    "CombatTelemetryTracker",
    "CulpritAttribution",
    "DEFAULT_MEMORY_CACHE_PATH",
    "EpisodicMemory",
    "EpisodicMemoryManager",
    "FailureReport",
    "PostDefeatDecision",
    "TurnSnapshot",
    "attribute_culprit",
    "create_failure_report",
    "is_debug_telemetry_enabled",
    "set_debug_telemetry",
]
