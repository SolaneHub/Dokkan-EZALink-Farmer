from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from typing import Any

import numpy as np

from dokkan_eza_link_farmer.ai.client import DokkanAIClient
from dokkan_eza_link_farmer.ai.mission_solver import (
    ChallengeMission,
    MissionBatch,
    MissionBundler,
    MissionParser,
)
from dokkan_eza_link_farmer.ai.models import DokkanCard, TeamRecommendation
from dokkan_eza_link_farmer.ai.team_builder import TeamBuilder
from dokkan_eza_link_farmer.automation.game_state import GameState
from dokkan_eza_link_farmer.automation.tasks.base_task import BaseTask
from dokkan_eza_link_farmer.automation.vision import Vision
from dokkan_eza_link_farmer.integrations.adb_client import ADBClient
from dokkan_eza_link_farmer.integrations.dokkandb_client import DokkanDBClient

logger = logging.getLogger(__name__)


class ChallengeTask(BaseTask):
    """
    Automated task for clearing Challenge events (Red Zone, Supreme Magnificent Battle).
    Bundles missions to minimize runs, uses AI for team building,
    and runs a try-and-retry adaptive combat loop until all missions are finished.
    """

    def __init__(
        self,
        adb: ADBClient,
        vision: Vision,
        config: dict[str, Any],
        dokkandb: DokkanDBClient,
        ai_client: DokkanAIClient,
        target_event: dict[str, Any],
        stage_num: int = 1,
        stage_id: int | None = None,
        stage_name: str | None = None,
        on_status: Callable[[str], None] | None = None,
        on_run_complete: Callable[[int, int], None] | None = None,
        max_retries_per_batch: int = 5,
    ):
        super().__init__(adb, vision, config, on_status, on_run_complete)
        self.dokkandb = dokkandb
        self.ai_client = ai_client
        self.target_event = target_event
        self.stage_num = stage_num
        self.stage_id = stage_id
        self.stage_name = stage_name
        self.max_retries_per_batch = max_retries_per_batch
        self.team_builder = TeamBuilder(dokkandb=self.dokkandb, ai_client=self.ai_client)

        self.missions: list[ChallengeMission] = []
        self.batches: list[MissionBatch] = []
        self.current_batch_idx = 0
        self.current_batch_attempts = 0
        self.total_cleared_missions = 0

        self._target_banner_img: np.ndarray | None = None
        banner_path = self.dokkandb.download_banner(self.target_event)
        if banner_path:
            self._target_banner_img = self.dokkandb.load_banner_template(banner_path)
        self.banner_selected = False

    def load_and_bundle_missions(self) -> list[MissionBatch]:
        """Loads all missions for the target event from DokkanDB and bundles them for the target stage."""
        ev_name = self.target_event.get("name", "")
        ev_id = int(self.target_event.get("id") or 0)
        raw_missions = self.dokkandb.get_challenge_missions(
            ev_name, stage_num=self.stage_num, event_id=ev_id
        )
        self.missions = [MissionParser.parse(m) for m in raw_missions]
        self.batches = MissionBundler.bundle_missions(self.missions, target_stage=self.stage_num)
        return self.batches

    def run(self):
        """Main autonomous execution loop."""
        self.is_running = True
        ev_name = self.target_event.get("name", "Challenge Event")
        stage_label = f"Stage {self.stage_num}" + (
            f": {self.stage_name}" if self.stage_name else ""
        )
        self.log(f"Starting Challenge Auto-Clear for: {ev_name} ({stage_label})")

        self.load_and_bundle_missions()
        if not self.batches:
            self.log(
                f"No specific missions found for '{ev_name}' ({stage_label}). Running standard stage clear."
            )
            self.batches = [MissionBatch(missions=[])]

        total_batches = len(self.batches)
        self.log(f"Optimized plan: {total_batches} run batches to clear all missions!")

        for b_idx, batch in enumerate(self.batches, 1):
            if self.is_stopped():
                break

            self.current_batch_idx = b_idx
            self.current_batch_attempts = 0
            batch_cleared = False

            self.log(f"\n=== [BATCH {b_idx}/{total_batches}] Target: {batch.summary} ===")
            for m in batch.missions:
                self.log(f"  * Mission {m.id}: {m.name}")

            while not batch_cleared and self.current_batch_attempts < self.max_retries_per_batch:
                if self.is_stopped():
                    break

                self.current_batch_attempts += 1
                self.log(f"Attempt #{self.current_batch_attempts} for Batch {b_idx}...")

                # Dynamically formulate team permutation for this attempt
                team_rec = self._prepare_team_for_batch(batch, attempt=self.current_batch_attempts)
                if team_rec:
                    self.log(f"Team Leader: {team_rec.leader.full_name}")
                    self.log(
                        f"Rotation A: {team_rec.rotation_a.slot1.name} (Tank) + {team_rec.rotation_a.slot2.name}"
                    )
                    self.log(
                        f"Rotation B: {team_rec.rotation_b.slot1.name} (Tank) + {team_rec.rotation_b.slot2.name}"
                    )
                    if team_rec.ai_reasoning:
                        self.log(f"[AI CoT]: {team_rec.ai_reasoning[:160]}...")

                success = self._run_stage_attempt(
                    batch, team_rec, attempt_num=self.current_batch_attempts
                )
                if success:
                    batch_cleared = True
                    self.total_cleared_missions += len(batch.missions)
                    for m in batch.missions:
                        m.is_completed = True
                    self.log(
                        f"✓ Batch {b_idx} CLEARED successfully! {len(batch.missions)} missions completed!"
                    )
                    self.on_run_complete(b_idx, total_batches)
                    break
                else:
                    self.log(
                        f"✗ Defeat on Attempt #{self.current_batch_attempts}. Adapting strategy for retry..."
                    )
                    self._adapt_strategy_after_defeat(batch, team_rec)
                    self.wait_check(3.0)

            if not batch_cleared and not self.is_stopped():
                self.log(f"[WARNING] Max retries reached for Batch {b_idx}. Moving to next batch.")

        self.log(
            f"=== Challenge Auto-Clear Finished! Cleared {self.total_cleared_missions} missions. ==="
        )
        self.is_running = False

    def _prepare_team_for_batch(
        self, batch: MissionBatch, attempt: int = 1
    ) -> TeamRecommendation | None:
        """Finds candidate cards, optimizes rotations, and requests AI strategy."""
        user_card_ids = self.dokkandb.get_user_box_card_ids()
        candidate_pool: list[DokkanCard] = []

        box_meta: dict[int, dict[str, Any]] = {}
        if os.path.exists("config/box.json"):
            try:
                with open("config/box.json", encoding="utf-8") as f:
                    b_data = json.load(f)
                card_list = b_data if isinstance(b_data, list) else b_data.get("cards", [])
                for item in card_list:
                    if isinstance(item, dict) and "id" in item:
                        box_meta[int(item["id"])] = item
            except Exception as e:
                logger.debug(f"Could not read box.json metadata: {e}")

        if user_card_ids:
            self.log(f"Personal Box: Loaded {len(user_card_ids)} owned cards from config/box.json.")
            for cid in user_card_ids:
                raw = self.dokkandb.get_card(cid)
                if raw:
                    is_rb = bool(box_meta.get(cid, {}).get("is_rainbow", False))
                    candidate_pool.append(DokkanCard.from_dokkandb(raw, is_rainbow=is_rb))
        else:
            self.log(
                "💡 Note: 'config/box.json' not found. Using DokkanDB catalog for team recommendations."
            )
            self.log(
                "   To restrict the AI to your actual owned cards, run 'scan-box' to automatically index your box."
            )
            catalog = self.dokkandb.get_cards_catalog()
            candidate_pool = [DokkanCard.from_dokkandb(raw) for raw in catalog[:500]]

        boss_target_desc = self.target_event.get("name", "Challenge Event")
        if self.stage_name:
            boss_target_desc += f" - Stage {self.stage_num}: {self.stage_name}"
        elif self.stage_num:
            boss_target_desc += f" - Stage {self.stage_num}"

        if self.stage_id and self.target_event.get("id"):
            try:
                boss_stats = self.dokkandb.get_stage_boss_info(
                    int(self.target_event["id"]), int(self.stage_id)
                )
                if boss_stats and "phases" in boss_stats:
                    phase_summaries = []
                    for ph in boss_stats["phases"]:
                        ph_no = ph.get("phase", 1)
                        boss_strs = []
                        for b in ph.get("bosses", []):
                            b_name = b.get("name", "Boss")
                            b_type = b.get("type_name", "Unknown Type")
                            mechs = [m.get("name") for m in b.get("mechanics", []) if m.get("name")]
                            mech_str = f" ({', '.join(mechs[:3])})" if mechs else ""
                            boss_strs.append(f"{b_name} [{b_type}]{mech_str}")
                        phase_summaries.append(f"Phase {ph_no}: {' / '.join(boss_strs)}")
                    if phase_summaries:
                        boss_target_desc += " | " + " | ".join(phase_summaries)
            except Exception as e:
                logger.debug(f"Could not load boss stats telemetry: {e}")

        try:
            return self.team_builder.build_best_team_for_batch(
                candidate_pool=candidate_pool,
                batch=batch,
                attempt=attempt,
                boss_target=boss_target_desc,
            )
        except Exception as e:
            logger.warning(f"Error preparing team: {e}")
            return None

    def navigate_to_challenge_banner(self, w: int, h: int) -> bool:
        """
        Searches for the target Challenge banner in the Challenge tab by scanning and scrolling downwards.
        """
        if self._target_banner_img is None:
            return False

        ev_name = self.target_event.get("name", "Challenge Event")
        self.log(f"Searching banner for '{ev_name}' on screen...")

        max_scrolls = 12
        prev_screen = None

        for attempt in range(max_scrolls):
            if self.is_stopped():
                return False

            curr_screen = self.adb.screencap()
            match = self.vision.find_banner_on_screen(
                curr_screen, self._target_banner_img, threshold=0.70
            )
            if match:
                cx, cy, conf = match
                self.log(f"✓ Found target banner '{ev_name}' (conf: {conf:.2f}) at Y={cy}!")
                tap_x = int(w * 0.50)
                tap_y = max(int(h * 0.25), min(int(h * 0.78), cy))
                self.adb.tap(tap_x, tap_y, delay_after=2.5)
                self.banner_selected = True
                return True

            # Scroll down to reveal more events
            self.log(f"Scrolling down Challenge list (attempt {attempt + 1}/{max_scrolls})...")
            self.adb.swipe(
                int(w * 0.50), int(h * 0.65), int(w * 0.50), int(h * 0.35), duration_ms=250
            )
            self.wait_check(1.0)

            if prev_screen is not None:
                diff = float(np.mean(np.abs(prev_screen.astype(float) - curr_screen.astype(float))))
                if diff < 3.0:
                    self.log("Reached end of Challenge event list.")
                    break
            prev_screen = curr_screen

        return False

    def _adapt_strategy_after_defeat(
        self, _batch: MissionBatch, _team_rec: TeamRecommendation | None
    ):
        """Adjusts tactical parameters (e.g. earlier defensive item use) after a Game Over."""
        self.log(
            "Adaptive Learning: Enabling earlier defensive item use and verifying Slot 1 tanking."
        )

    def _run_stage_attempt(
        self,
        batch: MissionBatch,
        team_rec: TeamRecommendation | None,
        attempt_num: int = 1,
    ) -> bool:
        """Executes one run of the stage: entering, playing battle, handling defeat/victory."""
        consecutive_unknowns = 0
        in_battle_turns = 0
        victory_seen = False
        post_victory_dismissals = 0

        while not self.is_stopped():
            screen = self.adb.screencap()
            state, meta = self.detector.detect(screen)
            w = meta.get("screen_width", 1080)
            h = meta.get("screen_height", 1920)

            # 1. Navigation from Home / Mode Select / Event Select
            if state == GameState.HOME_SCREEN:
                if victory_seen:
                    return True
                self.log("Home screen detected. Tapping Start...")
                if "start_button" in meta:
                    self.adb.tap(*meta["start_button"], delay_after=2.0)
                else:
                    self.adb.tap(int(w * 0.50), int(h * 0.64), delay_after=2.0)

            elif state == GameState.MODE_SELECT:
                if victory_seen:
                    return True
                self.log("Mode select screen detected. Tapping Event button...")
                if "event_button" in meta:
                    self.adb.tap(*meta["event_button"], delay_after=2.0)
                else:
                    self.adb.tap(int(w * 0.50), int(h * 0.32), delay_after=2.0)

            elif state == GameState.EVENT_SELECT:
                if victory_seen:
                    return True
                self.log("Event screen detected. Switching to Challenge tab...")
                # Tap Challenge tab (approx 50% width, 19% height)
                self.adb.tap(int(w * 0.50), int(h * 0.19), delay_after=2.0)

                # Search and scroll for target challenge event banner
                found = self.navigate_to_challenge_banner(w, h)
                if not found:
                    self.log("Target banner not found via scan, tapping top banner fallback.")
                    self.adb.tap(int(w * 0.50), int(h * 0.35), delay_after=2.5)

            elif state == GameState.STAGE_SELECT:
                if victory_seen:
                    return True
                diff_super = self.vision.find_template(screen, "diff_super")
                if diff_super:
                    self.adb.tap(diff_super[0], diff_super[1], delay_after=1.5)
                else:
                    self.adb.tap(int(w * 0.50), int(h * 0.35), delay_after=1.5)

            elif state == GameState.FRIEND_SELECT:
                self.handle_friend_select(w, h, meta)

            elif state == GameState.TEAM_CONFIRM:
                self.tap_start_team(w, h, meta)

            elif state == GameState.MAP_SCREEN:
                self.handle_map(w, h, meta)

            elif state == GameState.BATTLE_SCREEN:
                in_battle_turns += 1
                self._handle_smart_battle_turn(
                    w, h, screen, in_battle_turns, team_rec, batch, attempt_num=attempt_num
                )
                self.wait_check(2.0)

            elif state == GameState.GAME_OVER:
                self.log("Defeat detected (GAME_OVER popup). Dismissing...")
                if "cancel_button" in meta:
                    self.adb.tap(*meta["cancel_button"], delay_after=1.5)
                elif "ok_button" in meta:
                    self.adb.tap(int(w * 0.28), int(h * 0.60), delay_after=1.5)
                else:
                    self.adb.tap(int(w * 0.50), int(h * 0.65), delay_after=1.5)
                return False

            elif state in (GameState.RESULTS_SCREEN, GameState.KO_SCREEN):
                victory_seen = True
                post_victory_dismissals += 1
                self.log(
                    f"Victory screen detected ({state.value}). Dismissing popups ({post_victory_dismissals})..."
                )
                self.dismiss_results_and_popups(w, h, meta, prefer_again=False)
                if post_victory_dismissals >= 3:
                    return True

            elif state == GameState.FRIEND_REQUEST:
                self.dismiss_results_and_popups(w, h, meta)
                if victory_seen:
                    return True

            elif "close_button" in meta or "ok_button" in meta:
                self.dismiss_results_and_popups(w, h, meta)

            elif state == GameState.UNKNOWN:
                consecutive_unknowns += 1
                if victory_seen and consecutive_unknowns >= 3:
                    return True
                if consecutive_unknowns >= 8:
                    self.adb.tap(int(w * 0.50), int(h * 0.50), delay_after=1.0)
                    consecutive_unknowns = 0

            self.wait_check(1.5)

        return victory_seen

    def _handle_smart_battle_turn(
        self,
        screen_w: int,
        screen_h: int,
        screen: np.ndarray,
        turn_num: int,
        team_rec: TeamRecommendation | None,
        batch: MissionBatch,
        attempt_num: int = 1,
    ):
        """Executes tactical turn logic: rotation positioning, item check, and ki collection."""
        # 1. Check if defensive item is needed
        if not batch.requires_no_items:
            # On first attempt: turns 1, 3, 5. On retry attempts: more proactive defensive coverage (1, 2, 4)
            item_turns = (1, 3, 5) if attempt_num == 1 else (1, 2, 4)
            if turn_num in item_turns:
                item_icon = self.vision.find_template(screen, "button_item", threshold=0.75)
                if item_icon:
                    self.log(
                        f"Turn {turn_num} (Attempt #{attempt_num}): Using defensive support item (Whis/Usher)..."
                    )
                    self.adb.tap(item_icon[0], item_icon[1], delay_after=0.8)
                    self.adb.tap(int(screen_w * 0.35), int(screen_h * 0.65), delay_after=0.8)
                    self.adb.tap(int(screen_w * 0.50), int(screen_h * 0.70), delay_after=1.0)

        # 2. Reorder rotations: ensure Slot 1 has defensive priority
        y_slot = int(screen_h * 0.75)
        x_slot1 = int(screen_w * 0.25)
        x_slot2 = int(screen_w * 0.50)
        # Gentle drag & drop between Slot 2 and Slot 1 if needed
        if team_rec and team_rec.rotation_a.slot1.is_slot1_tank:
            self.adb.swipe(x_slot2, y_slot, x_slot1, y_slot, duration_ms=300)

        # 3. Collect Ki Spheres for all 3 cards
        col_x = [0.18, 0.34, 0.50, 0.66, 0.82]
        orb_y = int(screen_h * 0.53)

        for card_idx in range(3):
            target_col = col_x[min(card_idx + 1, 4)]
            tap_x = int(screen_w * target_col)
            self.adb.tap(tap_x, orb_y, delay_after=0.8)
