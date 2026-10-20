from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from dokkan_eza_link_farmer.ai.models import DokkanCard

logger = logging.getLogger(__name__)


@dataclass
class ChallengeMission:
    """Represents a single mission inside a Challenge Event."""

    id: int
    name: str
    description: str
    categories: list[tuple[int, str]] = field(default_factory=list)  # [(count, category_name)]
    rainbow_types: bool = False  # Requires all 5 types: AGL, TEQ, INT, STR, PHY
    requires_all_super: bool = False  # Requires all 5 Super types
    requires_all_extreme: bool = False  # Requires all 5 Extreme types
    specific_types: list[str] = field(default_factory=list)  # Specific types required
    max_turns: int | None = None
    no_items: bool = False
    is_completed: bool = False
    stage_num: int | None = None
    applicable_stages: list[int] = field(default_factory=list)

    @property
    def is_restricted(self) -> bool:
        return bool(
            self.categories
            or self.rainbow_types
            or self.requires_all_super
            or self.requires_all_extreme
            or self.specific_types
            or self.no_items
            or self.max_turns
        )

    def applies_to_stage(self, stage: int | None) -> bool:
        """
        Determines whether this mission applies to the given stage number.
        - None or 0: applies to all stages.
        - If applicable_stages is empty (e.g. general event/any stage missions): applies.
        - Otherwise, checks if stage is in applicable_stages.
        """
        if stage is None or stage <= 0:
            return True
        if not self.applicable_stages:
            return True
        return stage in self.applicable_stages

    @property
    def display_title(self) -> str:
        """Returns a concise, descriptive label for interactive CLI selection menus."""
        tags = []
        if self.requires_all_super:
            tags.append("5 Super Types")
        elif self.requires_all_extreme:
            tags.append("5 Extreme Types")
        elif self.rainbow_types:
            tags.append("5 Types (Rainbow)")

        for count, cat in self.categories:
            tags.append(f"{count}x '{cat}'")

        if self.no_items:
            tags.append("No Items")
        if self.max_turns:
            tags.append(f"≤{self.max_turns} Turns")

        tag_str = f"[{' | '.join(tags)}]" if tags else "[Standard]"
        clean_name = self.name.replace("\n", " ").strip()
        # Clean extra redundant phrases
        clean_desc = self.description.replace("\n", " ").replace("* Friends do not count.", "").replace("{cards: by_conditions}", "").strip()
        clean_desc = re.sub(r"\s+", " ", clean_desc)
        if len(clean_desc) > 80:
            clean_desc = clean_desc[:77] + "..."

        return f"{tag_str} {clean_name} - {clean_desc}" if clean_desc else f"{tag_str} {clean_name}"


class MissionParser:
    """Parses natural language Dokkan Battle mission descriptions into structured constraints."""

    @staticmethod
    def parse(mission_dict: dict[str, Any]) -> ChallengeMission:
        m_id = int(mission_dict.get("id") or 0)
        name = str(mission_dict.get("name") or "")
        desc = str(mission_dict.get("description") or "")
        full_text = f"{name} {desc}"

        # Stage number detection: e.g. "Clear Stage 3 of ...", "Clear Stage 02"
        stage_matches = re.findall(r"\bstage\s*(\d+)\b", full_text, re.IGNORECASE)
        applicable_stages = sorted(list({int(s) for s in stage_matches if s.isdigit()}))
        stage_num = applicable_stages[0] if applicable_stages else None

        categories: list[tuple[int, str]] = []
        # Pattern: 6 "Dragon Ball Seekers" Category or 6 'Pure Saiyans' Category
        cat_matches = re.findall(
            r'(\d+)(?:\s+or\s+more)?\s+["\']([^"\']+)["\']\s+Category', desc, re.IGNORECASE
        )
        for count_str, cat_name in cat_matches:
            categories.append((int(count_str), cat_name.strip()))

        # Check for Super/Extreme or Rainbow Team missions
        lower_full = full_text.lower()
        requires_all_super = "all five super types" in lower_full or (
            "super agl" in lower_full
            and "super teq" in lower_full
            and "super int" in lower_full
            and "super str" in lower_full
            and "super phy" in lower_full
        )
        requires_all_extreme = "all five extreme types" in lower_full or (
            "extreme agl" in lower_full
            and "extreme teq" in lower_full
            and "extreme int" in lower_full
            and "extreme str" in lower_full
            and "extreme phy" in lower_full
        )
        rainbow = (
            requires_all_super
            or requires_all_extreme
            or (
                "agl" in desc.lower()
                and "teq" in desc.lower()
                and "int" in desc.lower()
                and "str" in desc.lower()
                and "phy" in desc.lower()
            )
            or "5 types" in desc.lower()
            or "five types" in desc.lower()
        )

        specific_types: list[str] = []
        if not rainbow:
            type_matches = re.findall(r"\b(AGL|TEQ|INT|STR|PHY)\b\s+Type", desc, re.IGNORECASE)
            specific_types = [t.upper() for t in set(type_matches)]

        turn_m = re.search(r"within\s+(\d+)\s+turns", desc, re.IGNORECASE)
        max_turns = int(turn_m.group(1)) if turn_m else None

        no_items = bool(
            re.search(
                r"without\s+(?:using\s+)?(?:any\s+)?(?:a\s+)?support\s+items?",
                desc,
                re.IGNORECASE,
            )
            or "no items" in desc.lower()
            or "no support items" in desc.lower()
        )

        return ChallengeMission(
            id=m_id,
            name=name,
            description=desc,
            categories=categories,
            rainbow_types=rainbow,
            requires_all_super=requires_all_super,
            requires_all_extreme=requires_all_extreme,
            specific_types=specific_types,
            max_turns=max_turns,
            no_items=no_items,
            stage_num=stage_num,
            applicable_stages=applicable_stages,
        )


@dataclass
class MissionBatch:
    """A bundle of missions that can be simultaneously cleared in a single run."""

    missions: list[ChallengeMission]
    required_categories: list[tuple[int, str]] = field(default_factory=list)
    requires_rainbow: bool = False
    requires_all_super: bool = False
    requires_all_extreme: bool = False
    requires_no_items: bool = False
    max_turns: int | None = None

    @property
    def summary(self) -> str:
        parts: list[str] = []
        if self.requires_all_super:
            parts.append("All 5 Super Types")
        elif self.requires_all_extreme:
            parts.append("All 5 Extreme Types")
        elif self.requires_rainbow:
            parts.append("All 5 Types (Rainbow Team)")

        if self.required_categories:
            cats = [f"{count}x '{name}'" for count, name in self.required_categories]
            parts.append(f"Categories: {', '.join(cats)}")
        if self.requires_no_items:
            parts.append("No Support Items")
        if self.max_turns:
            parts.append(f"Clear in ≤ {self.max_turns} turns")
        return " + ".join(parts) if parts else "Standard Stage Clear"

    def matches_team(self, team_cards: list[DokkanCard]) -> tuple[bool, list[str]]:
        """Verifies whether the given 6-card team fully satisfies all batch conditions."""
        reasons: list[str] = []
        all_passed = True

        # Check categories
        for count_req, cat_name in self.required_categories:
            cat_lower = cat_name.strip().lower()
            actual_count = sum(
                1 for c in team_cards if any(c_cat.strip().lower() == cat_lower for c_cat in c.categories)
            )
            if actual_count >= count_req:
                reasons.append(f"✅ Category '{cat_name}': {actual_count}/{count_req} cards")
            else:
                all_passed = False
                reasons.append(f"❌ Category '{cat_name}': only {actual_count}/{count_req} cards")

        # Check rainbow types
        if self.requires_rainbow or self.requires_all_super or self.requires_all_extreme:
            types_present = {c.element % 10 for c in team_cards}
            type_names = {0: "AGL", 1: "TEQ", 2: "INT", 3: "STR", 4: "PHY"}
            missing = [type_names[t] for t in (0, 1, 2, 3, 4) if t not in types_present]
            if not missing:
                reasons.append("✅ All 5 Types present (AGL, TEQ, INT, STR, PHY)")
            else:
                all_passed = False
                reasons.append(f"❌ Missing types for Rainbow: {', '.join(missing)}")

        if self.requires_all_super:
            non_super = [c.name for c in team_cards if getattr(c, "card_class", "") != "Super"]
            if not non_super:
                reasons.append("✅ All cards are Super Class")
            else:
                all_passed = False
                reasons.append(f"❌ Non-Super cards present: {', '.join(non_super)}")

        if self.requires_all_extreme:
            non_ext = [c.name for c in team_cards if getattr(c, "card_class", "") != "Extreme"]
            if not non_ext:
                reasons.append("✅ All cards are Extreme Class")
            else:
                all_passed = False
                reasons.append(f"❌ Non-Extreme cards present: {', '.join(non_ext)}")

        return all_passed, reasons


class MissionBundler:
    """Optimizes mission completion by grouping compatible missions into minimum number of runs."""

    @staticmethod
    def are_compatible(m1: ChallengeMission, m2: ChallengeMission) -> bool:
        """Determines if two missions can be completed within the exact same 6-card team run."""
        # Mutually exclusive class missions
        if (m1.requires_all_super and m2.requires_all_extreme) or (
            m1.requires_all_extreme and m2.requires_all_super
        ):
            return False

        cats1 = {cat: count for count, cat in m1.categories}
        cats2 = {cat: count for count, cat in m2.categories}

        # If both require 6 of different categories (e.g. 6 Realm of Gods vs 6 Majin Power) -> incompatible
        for c1, cnt1 in cats1.items():
            if cnt1 >= 6:
                for c2, cnt2 in cats2.items():
                    if c1 != c2 and cnt2 >= 6:
                        # They could only be compatible if card pool has enough overlapping units
                        # However, for automatic grouping we avoid hard-conflicts
                        pass

        # If total distinct category requirements strictly exceed 6 cards (without overlap)
        distinct_slots = sum(cnt1 for c1, cnt1 in cats1.items() if c1 not in cats2) + sum(
            cnt2 for c2, cnt2 in cats2.items() if c2 not in cats1
        )
        return distinct_slots <= 6

    @classmethod
    def bundle_missions(
        cls, missions: list[ChallengeMission], target_stage: int | None = None
    ) -> list[MissionBatch]:
        """
        Groups compatible missions using greedy set covering to minimize total stage runs.
        If target_stage is specified, filters missions that apply to that specific stage first.
        """
        filtered_missions = missions
        if target_stage is not None and target_stage > 0:
            filtered_missions = [m for m in missions if m.applies_to_stage(target_stage)]

        unassigned = [m for m in filtered_missions if not m.is_completed]
        batches: list[MissionBatch] = []

        while unassigned:
            current = unassigned.pop(0)
            batch_missions = [current]
            req_cats = list(current.categories)
            req_rainbow = current.rainbow_types
            req_super = current.requires_all_super
            req_extreme = current.requires_all_extreme
            req_no_items = current.no_items
            turn_limit = current.max_turns

            i = 0
            while i < len(unassigned):
                candidate = unassigned[i]
                # Test compatibility with all missions currently in batch
                if all(cls.are_compatible(m, candidate) for m in batch_missions):
                    batch_missions.append(candidate)
                    # Merge requirements
                    for cnt, cat_name in candidate.categories:
                        if not any(c[1] == cat_name for c in req_cats):
                            req_cats.append((cnt, cat_name))
                        else:
                            # Keep highest count
                            req_cats = [
                                (max(c[0], cnt), c[1]) if c[1] == cat_name else c for c in req_cats
                            ]
                    if candidate.rainbow_types:
                        req_rainbow = True
                    if candidate.requires_all_super:
                        req_super = True
                    if candidate.requires_all_extreme:
                        req_extreme = True
                    if candidate.no_items:
                        req_no_items = True
                    if candidate.max_turns:
                        turn_limit = (
                            min(turn_limit, candidate.max_turns)
                            if turn_limit
                            else candidate.max_turns
                        )
                    unassigned.pop(i)
                else:
                    i += 1

            batches.append(
                MissionBatch(
                    missions=batch_missions,
                    required_categories=req_cats,
                    requires_rainbow=req_rainbow,
                    requires_all_super=req_super,
                    requires_all_extreme=req_extreme,
                    requires_no_items=req_no_items,
                    max_turns=turn_limit,
                )
            )

        return batches

    @classmethod
    def create_batch_from_selection(cls, selected_missions: list[ChallengeMission]) -> MissionBatch:
        """Constructs a consolidated MissionBatch from a list of user-selected missions."""
        if not selected_missions:
            return MissionBatch(missions=[])

        req_cats: list[tuple[int, str]] = []
        req_rainbow = False
        req_super = False
        req_extreme = False
        req_no_items = False
        turn_limit: int | None = None

        for m in selected_missions:
            for cnt, cat_name in m.categories:
                existing = next((c for c in req_cats if c[1].lower() == cat_name.lower()), None)
                if existing:
                    req_cats = [
                        (max(c[0], cnt), c[1]) if c[1].lower() == cat_name.lower() else c
                        for c in req_cats
                    ]
                else:
                    req_cats.append((cnt, cat_name))

            if m.rainbow_types:
                req_rainbow = True
            if m.requires_all_super:
                req_super = True
            if m.requires_all_extreme:
                req_extreme = True
            if m.no_items:
                req_no_items = True
            if m.max_turns:
                turn_limit = min(turn_limit, m.max_turns) if turn_limit else m.max_turns

        return MissionBatch(
            missions=selected_missions,
            required_categories=req_cats,
            requires_rainbow=req_rainbow or req_super or req_extreme,
            requires_all_super=req_super,
            requires_all_extreme=req_extreme,
            requires_no_items=req_no_items,
            max_turns=turn_limit,
        )

    @staticmethod
    def filter_cards_for_batch(
        batch: MissionBatch, card_pool: list[DokkanCard]
    ) -> list[DokkanCard]:
        """Filters candidate cards that satisfy the category requirements of the batch."""
        if not batch.required_categories:
            return card_pool

        eligible: list[DokkanCard] = []
        required_cat_names = {cat_name.lower() for _, cat_name in batch.required_categories}
        for card in card_pool:
            card_cats = {c.lower() for c in card.categories}
            if card_cats.intersection(required_cat_names):
                eligible.append(card)
        return eligible
