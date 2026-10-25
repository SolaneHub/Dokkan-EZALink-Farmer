"""Dokkan Battle card domain definitions, tactical tags, and team recommendations."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from dokkan_eza_link_farmer.ai.boss_models import (
    TYPE_NAMES,
    BossStage,
    infer_boss_categories_from_name,
)
from dokkan_eza_link_farmer.ai.synergy import RotationPair


def _safe_int(val: Any, default: int = 0) -> int:
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _safe_str(val: Any, default: str = "") -> str:
    if val is None:
        return default
    return str(val)


def _safe_bool(val: Any, default: bool = False) -> bool:
    if val is None:
        return default
    if isinstance(val, str):
        return val.strip().lower() in ("true", "1")
    return bool(val)


def parse_dodge_percentage_from_text(text: str) -> int:
    """Extracts dodge / evasion percentage from passive skill or SA description."""
    clean_text = " ".join(text.lower().split())
    if not any(k in clean_text for k in ("evad", "evasion", "dodge")):
        return 0

    named = 0
    if (
        "guaranteed to evade" in clean_text
        or "guaranteed to dodge" in clean_text
        or "guaranteed evasion" in clean_text
    ):
        named = 100
    elif "great chance" in clean_text:
        named = 70
    elif "high chance" in clean_text:
        named = 50
    elif "medium chance" in clean_text or "med chance" in clean_text:
        named = 30
    elif "rare chance" in clean_text:
        named = 20
    elif re.search(
        r"(?<!chance of )(?<!chance to )(?<!great )(?<!high )(?<!medium )(?<!rare )(?<!med )(?<!guaranteed to )evades?\s+enemy(?:'s)?\s+attacks?",
        clean_text,
    ):
        named = 100

    explicit_vals: list[int] = []
    for m in re.finditer(r"(\d+)%\s*chance of evading", clean_text):
        explicit_vals.append(int(m.group(1)))
    for m in re.finditer(
        r"(?:chance of evading|chance to evade|chance of dodging|chance to dodge|evasion rate)\s*(?:enemy(?:'s)?\s+attacks?)?\s*(?:\([^)]*\))?\s*(?:rate\s*)?\+?\s*(\d+)%",
        clean_text,
    ):
        explicit_vals.append(int(m.group(1)))
    for m in re.finditer(
        r"(?:evad\w*|dodge\w*)[^.\n\*\-]{0,60}\(up to (\d+)%\)",
        clean_text,
    ):
        explicit_vals.append(int(m.group(1)))

    valid_explicit = [v for v in explicit_vals if v <= 100]
    if valid_explicit:
        return max(named, max(valid_explicit))

    return named if named > 0 else 30


@dataclass
class PassiveTags:
    """Tactical tags extracted from passive skill description."""

    slot1_viable: bool = False
    dr_base_percent: int = 0
    permanent_dr_percent: int = 0
    dr_turns_limit: int | None = None
    is_dr_permanent: bool = False
    dodge_chance_percent: int = 0
    dodge_turns_limit: int | None = None
    is_dodge_permanent: bool = True
    has_guard: bool = False
    is_guard_permanent: bool = False
    is_guard_unconditional: bool = False
    guard_turns_limit: int | None = None
    has_revive: bool = False
    has_taunt: bool = False
    has_support: bool = False
    has_standby: bool = False
    has_domain: bool = False
    has_orb_changing: bool = False
    has_on_hit_defense: bool = False
    has_on_hit_guard: bool = False
    has_on_hit_dr: bool = False
    has_on_hit_def: bool = False
    is_once_only_dr: bool = False
    pre_hit_guard: bool = False
    pre_hit_dr_percent: int = 0
    has_slot_2_3_buff: bool = False
    has_enemy_conditional_defense: bool = False
    enemy_conditional_categories: list[str] = field(default_factory=list)
    enemy_conditional_classes: list[str] = field(default_factory=list)
    enemy_conditional_dr: int = 0
    enemy_conditional_guard: bool = False
    enemy_conditional_dodge: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot1_viable": self.slot1_viable,
            "dr_base_percent": self.dr_base_percent,
            "permanent_dr_percent": self.permanent_dr_percent,
            "dr_turns_limit": self.dr_turns_limit,
            "is_dr_permanent": self.is_dr_permanent,
            "dodge_chance_percent": self.dodge_chance_percent,
            "dodge_turns_limit": self.dodge_turns_limit,
            "is_dodge_permanent": self.is_dodge_permanent,
            "has_guard": self.has_guard,
            "is_guard_permanent": self.is_guard_permanent,
            "is_guard_unconditional": self.is_guard_unconditional,
            "guard_turns_limit": self.guard_turns_limit,
            "has_revive": self.has_revive,
            "has_taunt": self.has_taunt,
            "has_support": self.has_support,
            "has_standby": self.has_standby,
            "has_domain": self.has_domain,
            "has_orb_changing": self.has_orb_changing,
            "has_on_hit_defense": self.has_on_hit_defense,
            "has_on_hit_guard": self.has_on_hit_guard,
            "has_on_hit_dr": self.has_on_hit_dr,
            "has_on_hit_def": self.has_on_hit_def,
            "is_once_only_dr": self.is_once_only_dr,
            "pre_hit_guard": self.pre_hit_guard,
            "pre_hit_dr_percent": self.pre_hit_dr_percent,
            "has_slot_2_3_buff": self.has_slot_2_3_buff,
            "has_enemy_conditional_defense": self.has_enemy_conditional_defense,
            "enemy_conditional_categories": list(self.enemy_conditional_categories),
            "enemy_conditional_classes": list(self.enemy_conditional_classes),
            "enemy_conditional_dr": self.enemy_conditional_dr,
            "enemy_conditional_guard": self.enemy_conditional_guard,
            "enemy_conditional_dodge": self.enemy_conditional_dodge,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | Any) -> PassiveTags:
        if isinstance(data, cls):
            return data
        if not data or not isinstance(data, dict):
            return cls()
        raw_dr_limit = data.get("dr_turns_limit")
        raw_dodge_limit = data.get("dodge_turns_limit")
        raw_guard_limit = data.get("guard_turns_limit")
        return cls(
            slot1_viable=_safe_bool(data.get("slot1_viable"), False),
            dr_base_percent=_safe_int(data.get("dr_base_percent"), 0),
            permanent_dr_percent=_safe_int(data.get("permanent_dr_percent"), 0),
            dr_turns_limit=_safe_int(raw_dr_limit) if raw_dr_limit is not None else None,
            is_dr_permanent=_safe_bool(data.get("is_dr_permanent"), False),
            dodge_chance_percent=_safe_int(data.get("dodge_chance_percent"), 0),
            dodge_turns_limit=_safe_int(raw_dodge_limit) if raw_dodge_limit is not None else None,
            is_dodge_permanent=_safe_bool(data.get("is_dodge_permanent"), True),
            has_guard=_safe_bool(data.get("has_guard"), False),
            is_guard_permanent=_safe_bool(data.get("is_guard_permanent"), False),
            is_guard_unconditional=_safe_bool(data.get("is_guard_unconditional"), False),
            guard_turns_limit=_safe_int(raw_guard_limit) if raw_guard_limit is not None else None,
            has_revive=_safe_bool(data.get("has_revive"), False),
            has_taunt=_safe_bool(data.get("has_taunt"), False),
            has_support=_safe_bool(data.get("has_support"), False),
            has_standby=_safe_bool(data.get("has_standby"), False),
            has_domain=_safe_bool(data.get("has_domain"), False),
            has_orb_changing=_safe_bool(data.get("has_orb_changing"), False),
            has_on_hit_defense=_safe_bool(data.get("has_on_hit_defense"), False),
            has_on_hit_guard=_safe_bool(data.get("has_on_hit_guard"), False),
            has_on_hit_dr=_safe_bool(data.get("has_on_hit_dr"), False),
            has_on_hit_def=_safe_bool(data.get("has_on_hit_def"), False),
            is_once_only_dr=_safe_bool(data.get("is_once_only_dr"), False),
            pre_hit_guard=_safe_bool(data.get("pre_hit_guard"), False),
            pre_hit_dr_percent=_safe_int(data.get("pre_hit_dr_percent"), 0),
            has_slot_2_3_buff=_safe_bool(data.get("has_slot_2_3_buff"), False),
            has_enemy_conditional_defense=_safe_bool(
                data.get("has_enemy_conditional_defense"), False
            ),
            enemy_conditional_categories=list(data.get("enemy_conditional_categories") or []),
            enemy_conditional_classes=list(data.get("enemy_conditional_classes") or []),
            enemy_conditional_dr=_safe_int(data.get("enemy_conditional_dr"), 0),
            enemy_conditional_guard=_safe_bool(data.get("enemy_conditional_guard"), False),
            enemy_conditional_dodge=_safe_int(data.get("enemy_conditional_dodge"), 0),
        )


@dataclass
class SATags:
    """Tactical tags extracted from Super Attack description."""

    stacks_def: bool = False
    stacks_atk: bool = False
    raise_def_turns: int = 0
    raise_atk_turns: int = 0
    is_aoe: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "stacks_def": self.stacks_def,
            "stacks_atk": self.stacks_atk,
            "raise_def_turns": self.raise_def_turns,
            "raise_atk_turns": self.raise_atk_turns,
            "is_aoe": self.is_aoe,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | Any) -> SATags:
        if isinstance(data, cls):
            return data
        if not data or not isinstance(data, dict):
            return cls()
        return cls(
            stacks_def=_safe_bool(data.get("stacks_def"), False),
            stacks_atk=_safe_bool(data.get("stacks_atk"), False),
            raise_def_turns=_safe_int(data.get("raise_def_turns"), 0),
            raise_atk_turns=_safe_int(data.get("raise_atk_turns"), 0),
            is_aoe=_safe_bool(data.get("is_aoe"), False),
        )


@dataclass
class LeaderSkillSpec:
    """Structured representation of Leader Skill for algorithmic O(1) set operations."""

    main_category_ids: list[int] = field(default_factory=list)
    extra_category_ids: list[int] = field(default_factory=list)
    sub_elements_classes: list[int] = field(default_factory=list)
    base_boost_pct: float = 170.0
    extra_boost_pct: float = 30.0
    sub_boost_pct: float = 0.0
    hp_stat_pct: float = 170.0
    atk_stat_pct: float = 170.0
    def_stat_pct: float = 170.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "main_category_ids": self.main_category_ids,
            "extra_category_ids": self.extra_category_ids,
            "sub_elements_classes": self.sub_elements_classes,
            "base_boost_pct": self.base_boost_pct,
            "extra_boost_pct": self.extra_boost_pct,
            "sub_boost_pct": self.sub_boost_pct,
            "hp_stat_pct": self.hp_stat_pct,
            "atk_stat_pct": self.atk_stat_pct,
            "def_stat_pct": self.def_stat_pct,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | Any) -> LeaderSkillSpec:
        if isinstance(data, cls):
            return data
        if not data or not isinstance(data, dict):
            return cls()
        return cls(
            main_category_ids=list(data.get("main_category_ids") or []),
            extra_category_ids=list(data.get("extra_category_ids") or []),
            sub_elements_classes=list(data.get("sub_elements_classes") or []),
            base_boost_pct=_safe_float(data.get("base_boost_pct"), 170.0),
            extra_boost_pct=_safe_float(data.get("extra_boost_pct"), 30.0),
            sub_boost_pct=_safe_float(data.get("sub_boost_pct"), 0.0),
            hp_stat_pct=_safe_float(data.get("hp_stat_pct"), 170.0),
            atk_stat_pct=_safe_float(data.get("atk_stat_pct"), 170.0),
            def_stat_pct=_safe_float(data.get("def_stat_pct"), 170.0),
        )


@dataclass
class CardForm:
    """Represents an individual character form or in-battle transformation."""

    form_id: int = 0
    form_index: int = 0  # 0 = base form
    form_name: str = ""
    element: int = 0
    links: list[str] = field(default_factory=list)
    link_ids: list[int] = field(default_factory=list)
    passive_skill_text: str = ""
    super_attack_text: str = ""
    passive_tags: PassiveTags = field(default_factory=PassiveTags)
    sa_tags: SATags = field(default_factory=SATags)
    min_turn: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "form_id": self.form_id,
            "form_index": self.form_index,
            "form_name": self.form_name,
            "element": self.element,
            "links": self.links,
            "link_ids": self.link_ids,
            "passive_skill_text": self.passive_skill_text,
            "super_attack_text": self.super_attack_text,
            "passive_tags": self.passive_tags.to_dict(),
            "sa_tags": self.sa_tags.to_dict(),
            "min_turn": self.min_turn,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | Any) -> CardForm:
        if isinstance(data, cls):
            return data
        if not data or not isinstance(data, dict):
            return cls()
        fid = data.get("form_id")
        if fid is None:
            fid = data.get("id", 0)
        return cls(
            form_id=_safe_int(fid, 0),
            form_index=_safe_int(data.get("form_index"), 0),
            form_name=_safe_str(data.get("form_name"), ""),
            element=_safe_int(data.get("element"), 0),
            links=list(data.get("links") or []),
            link_ids=list(data.get("link_ids") or []),
            passive_skill_text=_safe_str(data.get("passive_skill_text"), ""),
            super_attack_text=_safe_str(data.get("super_attack_text"), ""),
            passive_tags=PassiveTags.from_dict(data.get("passive_tags")),
            sa_tags=SATags.from_dict(data.get("sa_tags")),
            min_turn=_safe_int(data.get("min_turn"), 1),
        )


@dataclass
class DokkanCard:
    """Structured representation of a Dokkan Battle character."""

    id: int
    name: str
    subname: str = ""
    rarity: int = 4  # 4 = UR, 5 = LR
    element: int = 0
    element_name: str = ""
    card_class: str = ""  # "Super" or "Extreme"
    leader_skill: str = ""
    leader_spec: LeaderSkillSpec | None = None
    passive_skill: str = ""
    super_attack: str = ""
    categories: list[str] = field(default_factory=list)
    category_ids: list[int] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    link_ids: list[int] = field(default_factory=list)
    thumb_url: str = ""
    has_eza: bool = False
    is_eza: bool = False
    is_seza: bool = False
    is_rainbow: bool = False
    potential_percent: int = 0
    swipe_page: int = 0
    grid_slot: int = 0
    is_tank_override: bool | None = None
    is_friend_leader: bool = False
    standby_skill_name: str = ""
    standby_skill_condition: str = ""
    standby_skill_effect: str = ""
    active_skill_name: str = ""
    active_skill_condition: str = ""
    active_skill_effect: str = ""
    base_form: CardForm | None = None
    transformations: list[CardForm] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Sync has_eza and is_eza flags
        if self.is_eza or self.is_seza:
            self.has_eza = True
        elif self.has_eza:
            self.is_eza = True

        # Sync rainbow status and potential percent
        if self.is_rainbow and self.potential_percent == 0:
            self.potential_percent = 100
        elif self.potential_percent >= 100:
            self.is_rainbow = True

        # Resolve element_name and card_class if not populated
        if not self.element_name:
            base_type = TYPE_NAMES.get(self.element % 10, "AGL")
            if self.element >= 20:
                self.element_name = f"Extreme {base_type}"
                self.card_class = "Extreme"
            elif self.element >= 10:
                self.element_name = f"Super {base_type}"
                self.card_class = "Super"
            else:
                self.element_name = base_type
                self.card_class = "Super" if self.element >= 10 else ""

        if self.links is None:
            self.links = []
        if self.link_ids is None:
            self.link_ids = []
        if self.categories is None:
            self.categories = []
        if self.category_ids is None:
            self.category_ids = []

        # Default base_form if omitted
        if self.base_form is None:
            self.base_form = CardForm(
                form_id=self.id,
                form_index=0,
                form_name=self.name,
                element=self.element,
                links=list(self.links or []),
                link_ids=list(self.link_ids or []),
                passive_skill_text=self.passive_skill,
                super_attack_text=self.super_attack,
                min_turn=1,
            )

    @property
    def card_id(self) -> int:
        return self.id

    @property
    def full_name(self) -> str:
        return f"{self.name} - {self.subname}" if self.subname else self.name

    @property
    def element_color(self) -> str:
        elem_name = (self.element_name or "").upper()
        if "AGL" in elem_name:
            return "bold cyan"
        if "TEQ" in elem_name:
            return "bold green"
        if "INT" in elem_name:
            return "bold magenta"
        if "STR" in elem_name:
            return "bold red"
        if "PHY" in elem_name:
            return "bold yellow"

        type_colors = {
            0: "bold cyan",  # AGL
            1: "bold green",  # TEQ
            2: "bold magenta",  # INT
            3: "bold red",  # STR
            4: "bold yellow",  # PHY
        }
        return type_colors.get(self.element % 10, "bold white")

    @property
    def type_tag(self) -> str:
        elem_name = (self.element_name or "").upper()
        for t in ("AGL", "TEQ", "INT", "STR", "PHY"):
            if t in elem_name:
                return t
        return TYPE_NAMES.get(self.element % 10, "AGL")

    @property
    def dokkan_colored_name(self) -> str:
        type_prefix = f"[{self.element_name}] " if self.element_name else ""
        clean_name = self.full_name.replace("[", "(").replace("]", ")")
        color = self.element_color
        return f"[{color}]{type_prefix}{clean_name}[/{color}]"

    def rich_formatted_name(self, include_type: bool = True) -> Any:
        from rich.text import Text

        prefix = f"[{self.element_name}] " if (include_type and self.element_name) else ""
        return Text(f"{prefix}{self.full_name}", style=self.element_color)

    @property
    def is_lr(self) -> bool:
        return self.rarity >= 5

    def _parse_defense_mechanics(self) -> dict[str, Any]:
        """Parses passive skill and super attack to extract permanent vs timed defense attributes."""
        cached = getattr(self, "_cached_defense_mechanics", None)
        if cached is not None:
            return cached

        passive = self.passive_skill or ""
        sa = self.super_attack or ""

        blocks = re.split(r"\*([^*]+)\*", passive)
        sections = []
        if len(blocks) == 1:
            sections.append(("", blocks[0].lower()))
        else:
            sections.append(("", blocks[0].lower()))
            for i in range(1, len(blocks), 2):
                header = blocks[i].lower().strip()
                content = blocks[i + 1].lower().strip() if i + 1 < len(blocks) else ""
                sections.append((header, content))

        ON_HIT_PATTERNS = (
            "when receiving an attack",
            "after receiving an attack",
            "after receiving attack",
            "for every attack received",
            "for each attack received",
            "with each attack received",
            "per attack received",
            "when receiving a super attack",
            "when receiving a normal attack",
            "starting from the turn in which the character receives an attack",
            "starting from the turn in which the character receives a super attack",
            "when receiving damage",
            "after receiving damage",
        )
        ONCE_ONLY_PATTERNS = (
            "{passiveimg:once}",
            "(once only)",
            "once only",
        )
        SLOT_2_3_PATTERNS = (
            "as the 2nd or 3rd attacker",
            "as the 2nd attacker",
            "as the 3rd attacker",
            "in the 2nd or 3rd slot",
            "in the 2nd slot",
            "in the 3rd slot",
        )
        ALLY_CONDITIONAL_PATTERNS = (
            "allies attacking in the same turn",
            "when there are",
            "when there is another",
            "extreme class allies",
            "super class allies",
            "category ally",
            "category allies",
        )

        max_dr = 0
        permanent_dr = 0
        pre_hit_dr = 0
        dr_turn_limits: list[int] = []

        has_guard = False
        is_guard_permanent = False
        is_guard_unconditional = False
        pre_hit_guard = False
        guard_turn_limits: list[int] = []

        has_on_hit_guard = False
        has_on_hit_dr = False
        has_on_hit_def = False
        is_once_only_dr = False
        has_slot_2_3_buff = False

        has_enemy_conditional_defense = False
        enemy_conditional_categories: list[str] = []
        enemy_conditional_classes: list[str] = []
        enemy_conditional_dr = 0
        enemy_conditional_guard = False
        enemy_conditional_dodge = 0

        has_dodge = False
        base_dodge = 0
        is_dodge_permanent = True
        dodge_turn_limits: list[int] = []

        for header, content in sections:
            is_timed_header = False
            header_turns = None
            m_ht = re.search(r"for\s+(\d+)\s+turns?", header)
            if m_ht:
                is_timed_header = True
                header_turns = int(m_ht.group(1))
            elif "for 1 turn" in header or "within the character's next attacking turn" in header:
                is_timed_header = True
                header_turns = 1

            is_entrance = "entrance animation" in header or "upon the character's entry" in header

            header_is_on_hit = any(p in header for p in ON_HIT_PATTERNS)
            header_is_once_only = any(p in header for p in ONCE_ONLY_PATTERNS)
            header_is_slot_2_3 = any(p in header for p in SLOT_2_3_PATTERNS)
            header_is_ally_conditional = any(p in header for p in ALLY_CONDITIONAL_PATTERNS)

            header_clean = " ".join(header.split())
            header_is_enemy_conditional = (
                any(
                    p in header_clean
                    for p in ("category enemy", "category enemies", "class enemy", "class enemies")
                )
                or (
                    "when facing" in header_clean
                    and any(k in header_clean for k in ("enemy", "enemies"))
                )
                or (
                    "when there is a" in header_clean
                    and any(k in header_clean for k in ("enemy", "enemies"))
                )
                or (
                    "against" in header_clean
                    and any(k in header_clean for k in ("enemy", "enemies"))
                )
            )
            header_req_cats: list[str] = []
            header_req_classes: list[str] = []
            if header_is_enemy_conditional:
                cats_found = [x.title() for x in re.findall(r'"([^"]+)"', header_clean)]
                header_req_cats = [c for c in cats_found if "class" not in c.lower()]
                class_m = re.search(r"(extreme|super)\s+class", header_clean, re.I)
                if class_m:
                    header_req_classes.append(class_m.group(1).title())
                for c in cats_found:
                    if "extreme" in c.lower() and "Extreme" not in header_req_classes:
                        header_req_classes.append("Extreme")
                    elif "super" in c.lower() and "Super" not in header_req_classes:
                        header_req_classes.append("Super")

            is_conditional_header = (
                "ki spheres obtained" in header
                or "collecting" in header
                or "when hp is" in header
                or "when attacking" in header
                or header_is_slot_2_3
                or header_is_on_hit
                or header_is_ally_conditional
                or header_is_enemy_conditional
                or "starting from" in header
                or "after the character's" in header
                or is_timed_header
                or is_entrance
            )
            is_basic = "basic effect" in header or header == ""

            lines = [line.strip() for line in content.split("\n") if line.strip()]
            for line in lines:
                line_timed = is_timed_header
                line_turns = header_turns

                m_lt = re.search(r"for\s+(\d+)\s+turns?", line)
                if m_lt:
                    line_timed = True
                    line_turns = int(m_lt.group(1))
                elif (
                    "for 1 turn" in line
                    or "within the same turn" in line
                    or "within the character's next attacking turn" in line
                ):
                    line_timed = True
                    line_turns = 1
                elif is_entrance and not line_timed:
                    line_timed = True
                    line_turns = 4

                line_is_on_hit = header_is_on_hit or any(p in line for p in ON_HIT_PATTERNS)
                line_is_once_only = header_is_once_only or any(
                    p in line for p in ONCE_ONLY_PATTERNS
                )
                line_is_slot_2_3 = header_is_slot_2_3 or any(p in line for p in SLOT_2_3_PATTERNS)
                line_is_ally_conditional = header_is_ally_conditional or any(
                    p in line for p in ALLY_CONDITIONAL_PATTERNS
                )

                line_clean = " ".join(line.split())
                line_is_enemy_conditional = header_is_enemy_conditional or (
                    any(
                        p in line_clean
                        for p in (
                            "category enemy",
                            "category enemies",
                            "class enemy",
                            "class enemies",
                        )
                    )
                    or (
                        "when facing" in line_clean
                        and any(k in line_clean for k in ("enemy", "enemies"))
                    )
                    or (
                        "when there is a" in line_clean
                        and any(k in line_clean for k in ("enemy", "enemies"))
                    )
                    or (
                        "against" in line_clean
                        and any(k in line_clean for k in ("enemy", "enemies"))
                    )
                )
                line_req_cats = list(header_req_cats)
                line_req_classes = list(header_req_classes)
                if line_is_enemy_conditional and not line_req_cats and not line_req_classes:
                    cats_found = [x.title() for x in re.findall(r'"([^"]+)"', line_clean)]
                    line_req_cats = [c for c in cats_found if "class" not in c.lower()]
                    class_m = re.search(r"(extreme|super)\s+class", line_clean, re.I)
                    if class_m:
                        line_req_classes.append(class_m.group(1).title())
                    for c in cats_found:
                        if "extreme" in c.lower() and "Extreme" not in line_req_classes:
                            line_req_classes.append("Extreme")
                        elif "super" in c.lower() and "Super" not in line_req_classes:
                            line_req_classes.append("Super")

                if line_is_slot_2_3:
                    has_slot_2_3_buff = True

                # Check on-hit DEF
                if line_is_on_hit and re.search(r"def\s*\+?\s*(\d+)%", line):
                    has_on_hit_def = True

                # Damage Reduction
                dr_m = re.findall(
                    r"(?:damage reduction (?:rate|of)?|damage received by(?:\s+up to)?|reduces damage(?: received)? by(?:\s+up to)?(?:\s+an additional)?|damage received\s*-\s*)\s*(\d+)%",
                    line,
                )
                for d in dr_m:
                    val = int(d)
                    if val > max_dr:
                        max_dr = val
                    if line_is_on_hit:
                        has_on_hit_dr = True
                    if line_is_once_only:
                        is_once_only_dr = True
                    if line_is_enemy_conditional:
                        has_enemy_conditional_defense = True
                        if val > enemy_conditional_dr:
                            enemy_conditional_dr = val
                        for c in line_req_cats:
                            if c not in enemy_conditional_categories:
                                enemy_conditional_categories.append(c)
                        for cl in line_req_classes:
                            if cl not in enemy_conditional_classes:
                                enemy_conditional_classes.append(cl)

                    if line_timed:
                        if line_turns:
                            dr_turn_limits.append(line_turns)
                    elif (
                        (is_basic or not is_conditional_header)
                        and not line_is_on_hit
                        and not line_is_once_only
                        and not line_is_slot_2_3
                        and not line_is_enemy_conditional
                    ):
                        if val > permanent_dr:
                            permanent_dr = val
                        if val > pre_hit_dr:
                            pre_hit_dr = val

                # Guard
                if (
                    "guard" in line
                    and "chance of guarding" not in line
                    and "disables enemy" not in line
                    and any(
                        k in line
                        for k in (
                            "guards all attacks",
                            "guards against all attacks",
                            "all attacks guarded",
                            "guaranteed to guard",
                        )
                    )
                ):
                    has_guard = True
                    if line_is_on_hit:
                        has_on_hit_guard = True
                    if line_is_enemy_conditional:
                        has_enemy_conditional_defense = True
                        enemy_conditional_guard = True
                        for c in line_req_cats:
                            if c not in enemy_conditional_categories:
                                enemy_conditional_categories.append(c)
                        for cl in line_req_classes:
                            if cl not in enemy_conditional_classes:
                                enemy_conditional_classes.append(cl)

                    if line_timed:
                        if line_turns:
                            guard_turn_limits.append(line_turns)
                    else:
                        if not line_is_enemy_conditional:
                            is_guard_permanent = True
                        if (
                            (is_basic or not is_conditional_header)
                            and not line_is_on_hit
                            and not line_is_once_only
                            and not line_is_ally_conditional
                            and not line_is_slot_2_3
                            and not line_is_enemy_conditional
                        ):
                            is_guard_unconditional = True
                            pre_hit_guard = True

                # Dodge
                if any(k in line for k in ("evad", "evasion", "dodge")):
                    has_dodge = True
                    line_val = parse_dodge_percentage_from_text(line)

                    if line_is_enemy_conditional:
                        has_enemy_conditional_defense = True
                        if line_val > enemy_conditional_dodge:
                            enemy_conditional_dodge = line_val
                        for c in line_req_cats:
                            if c not in enemy_conditional_categories:
                                enemy_conditional_categories.append(c)
                        for cl in line_req_classes:
                            if cl not in enemy_conditional_classes:
                                enemy_conditional_classes.append(cl)

                    if line_timed:
                        if line_turns:
                            dodge_turn_limits.append(line_turns)
                    elif (
                        (is_basic or not is_conditional_header)
                        and not line_is_enemy_conditional
                        and line_val > base_dodge
                    ):
                        base_dodge = line_val

        if not has_guard and re.search(r"guard(?:s|ing)?\s+(?:against\s+)?all", sa.lower()):
            has_guard = True
            is_guard_permanent = True
            pre_hit_guard = False

        if has_guard and not guard_turn_limits and not has_on_hit_guard:
            is_guard_permanent = True
        elif has_guard and (guard_turn_limits or has_on_hit_guard) and not is_guard_permanent:
            is_guard_permanent = False

        if self.base_form and self.base_form.passive_tags:
            bt = self.base_form.passive_tags
            if bt.has_guard:
                has_guard = True
            if bt.is_guard_permanent:
                is_guard_permanent = True
            if bt.is_guard_unconditional:
                is_guard_unconditional = True
            if bt.pre_hit_guard:
                pre_hit_guard = True
            if bt.permanent_dr_percent > permanent_dr:
                permanent_dr = bt.permanent_dr_percent
            if bt.pre_hit_dr_percent > pre_hit_dr:
                pre_hit_dr = bt.pre_hit_dr_percent
            if bt.dr_base_percent > max_dr:
                max_dr = bt.dr_base_percent
            if bt.has_on_hit_defense:
                has_on_hit_def = True
            if bt.has_on_hit_guard:
                has_on_hit_guard = True
            if bt.has_on_hit_dr:
                has_on_hit_dr = True
            if bt.has_on_hit_def:
                has_on_hit_def = True
            if bt.is_once_only_dr:
                is_once_only_dr = True
            if getattr(bt, "has_slot_2_3_buff", False):
                has_slot_2_3_buff = True
            if getattr(bt, "has_enemy_conditional_defense", False):
                has_enemy_conditional_defense = True
                for c in getattr(bt, "enemy_conditional_categories", []):
                    if c not in enemy_conditional_categories:
                        enemy_conditional_categories.append(c)
                for cl in getattr(bt, "enemy_conditional_classes", []):
                    if cl not in enemy_conditional_classes:
                        enemy_conditional_classes.append(cl)
                enemy_conditional_dr = max(
                    enemy_conditional_dr, getattr(bt, "enemy_conditional_dr", 0)
                )
                if getattr(bt, "enemy_conditional_guard", False):
                    enemy_conditional_guard = True
                enemy_conditional_dodge = max(
                    enemy_conditional_dodge, getattr(bt, "enemy_conditional_dodge", 0)
                )

        res = {
            "max_dr": max_dr,
            "permanent_dr": permanent_dr,
            "pre_hit_dr": pre_hit_dr,
            "is_dr_permanent": permanent_dr > 0,
            "dr_turns_limit": min(dr_turn_limits) if dr_turn_limits else None,
            "has_guard": has_guard,
            "pre_hit_guard": pre_hit_guard,
            "is_guard_permanent": is_guard_permanent,
            "guard_turns_limit": min(guard_turn_limits) if guard_turn_limits else None,
            "is_guard_unconditional": is_guard_unconditional,
            "has_on_hit_guard": has_on_hit_guard,
            "has_on_hit_dr": has_on_hit_dr,
            "has_on_hit_def": has_on_hit_def,
            "is_once_only_dr": is_once_only_dr,
            "has_slot_2_3_buff": has_slot_2_3_buff
            or any(p in self.passive_skill.lower() for p in SLOT_2_3_PATTERNS),
            "has_enemy_conditional_defense": has_enemy_conditional_defense,
            "enemy_conditional_categories": enemy_conditional_categories,
            "enemy_conditional_classes": enemy_conditional_classes,
            "enemy_conditional_dr": enemy_conditional_dr,
            "enemy_conditional_guard": enemy_conditional_guard,
            "enemy_conditional_dodge": enemy_conditional_dodge,
            "has_dodge": has_dodge,
            "base_dodge": base_dodge,
            "is_dodge_permanent": is_dodge_permanent and (not dodge_turn_limits or base_dodge > 0),
            "dodge_turns_limit": min(dodge_turn_limits) if dodge_turn_limits else None,
        }
        self._cached_defense_mechanics = res
        return res

    @property
    def permanent_damage_reduction_percent(self) -> int:
        return self._parse_defense_mechanics()["permanent_dr"]

    @property
    def is_dr_permanent(self) -> bool:
        return self._parse_defense_mechanics()["is_dr_permanent"]

    @property
    def dr_turns_limit(self) -> int | None:
        return self._parse_defense_mechanics()["dr_turns_limit"]

    @property
    def is_guard_permanent(self) -> bool:
        return self._parse_defense_mechanics()["is_guard_permanent"]

    @property
    def is_guard_unconditional(self) -> bool:
        return self._parse_defense_mechanics()["is_guard_unconditional"]

    @property
    def guard_turns_limit(self) -> int | None:
        return self._parse_defense_mechanics()["guard_turns_limit"]

    @property
    def is_dodge_permanent(self) -> bool:
        return self._parse_defense_mechanics()["is_dodge_permanent"]

    @property
    def dodge_turns_limit(self) -> int | None:
        return self._parse_defense_mechanics()["dodge_turns_limit"]

    @property
    def pre_hit_guard(self) -> bool:
        if self.base_form and self.base_form.passive_tags.pre_hit_guard:
            return True
        return bool(self._parse_defense_mechanics().get("pre_hit_guard", False))

    @property
    def pre_hit_dr_percent(self) -> int:
        if self.base_form and self.base_form.passive_tags.pre_hit_dr_percent > 0:
            return self.base_form.passive_tags.pre_hit_dr_percent
        return int(self._parse_defense_mechanics().get("pre_hit_dr", 0))

    @property
    def has_on_hit_defense(self) -> bool:
        """Indicates that character defense (Guard, DR, or DEF) triggers or stacks only after receiving attacks."""
        if self.base_form and self.base_form.passive_tags.has_on_hit_defense:
            return True
        mech = self._parse_defense_mechanics()
        return bool(
            mech.get("has_on_hit_guard")
            or mech.get("has_on_hit_dr")
            or (
                mech.get("has_on_hit_def")
                and mech.get("pre_hit_dr", 0) < 50
                and not mech.get("pre_hit_guard")
            )
            or (mech.get("is_once_only_dr") and mech.get("pre_hit_dr", 0) < 50)
        )

    @property
    def has_on_hit_guard(self) -> bool:
        if self.base_form and self.base_form.passive_tags.has_on_hit_guard:
            return True
        return bool(self._parse_defense_mechanics().get("has_on_hit_guard", False))

    @property
    def has_on_hit_dr(self) -> bool:
        if self.base_form and self.base_form.passive_tags.has_on_hit_dr:
            return True
        return bool(self._parse_defense_mechanics().get("has_on_hit_dr", False))

    @property
    def has_on_hit_def(self) -> bool:
        if self.base_form and self.base_form.passive_tags.has_on_hit_def:
            return True
        return bool(self._parse_defense_mechanics().get("has_on_hit_def", False))

    @property
    def is_once_only_dr(self) -> bool:
        if self.base_form and self.base_form.passive_tags.is_once_only_dr:
            return True
        return bool(self._parse_defense_mechanics().get("is_once_only_dr", False))

    @property
    def has_enemy_conditional_defense(self) -> bool:
        if self.base_form and getattr(
            self.base_form.passive_tags, "has_enemy_conditional_defense", False
        ):
            return True
        return bool(self._parse_defense_mechanics().get("has_enemy_conditional_defense", False))

    @property
    def enemy_conditional_categories(self) -> list[str]:
        if self.base_form and getattr(
            self.base_form.passive_tags, "enemy_conditional_categories", None
        ):
            return list(self.base_form.passive_tags.enemy_conditional_categories)
        return list(self._parse_defense_mechanics().get("enemy_conditional_categories", []))

    @property
    def enemy_conditional_classes(self) -> list[str]:
        if self.base_form and getattr(
            self.base_form.passive_tags, "enemy_conditional_classes", None
        ):
            return list(self.base_form.passive_tags.enemy_conditional_classes)
        return list(self._parse_defense_mechanics().get("enemy_conditional_classes", []))

    @property
    def enemy_conditional_dr(self) -> int:
        if self.base_form and getattr(self.base_form.passive_tags, "enemy_conditional_dr", 0) > 0:
            return self.base_form.passive_tags.enemy_conditional_dr
        return int(self._parse_defense_mechanics().get("enemy_conditional_dr", 0))

    @property
    def enemy_conditional_guard(self) -> bool:
        if self.base_form and getattr(
            self.base_form.passive_tags, "enemy_conditional_guard", False
        ):
            return True
        return bool(self._parse_defense_mechanics().get("enemy_conditional_guard", False))

    @property
    def enemy_conditional_dodge(self) -> int:
        if (
            self.base_form
            and getattr(self.base_form.passive_tags, "enemy_conditional_dodge", 0) > 0
        ):
            return self.base_form.passive_tags.enemy_conditional_dodge
        return int(self._parse_defense_mechanics().get("enemy_conditional_dodge", 0))

    def check_enemy_conditions_match_phase(self, phase: Any) -> bool:
        """Returns True if this card has no enemy conditions, or if the given phase satisfies them."""
        if not self.has_enemy_conditional_defense:
            return True
        if not phase:
            return False

        bosses = getattr(phase, "bosses", [])
        if not bosses:
            return False

        req_cats = [c.lower() for c in self.enemy_conditional_categories]
        req_classes = [c.lower() for c in self.enemy_conditional_classes]

        for b in bosses:
            b_cats = [c.lower() for c in getattr(b, "categories", [])]
            if not b_cats:
                b_cats = [
                    c.lower() for c in infer_boss_categories_from_name(getattr(b, "name", ""))
                ]

            b_elem = getattr(b, "element", 0)
            b_class = "extreme" if b_elem >= 20 else ("super" if b_elem >= 10 else "")
            if not b_class and getattr(b, "card_class", ""):
                b_class = getattr(b, "card_class", "").lower()

            cat_match = any(rc in b_cats for rc in req_cats) if req_cats else True
            class_match = (b_class in req_classes) if req_classes else True

            if (req_cats or req_classes) and cat_match and class_match:
                return True

        return False

    def check_enemy_conditions_match_all_phases(self, boss_stage: Any) -> tuple[bool, list[int]]:
        """Checks if enemy conditions are satisfied across ALL phases of boss_stage.
        Returns (all_matched: bool, failing_phase_indices: list[int]).
        """
        if not self.has_enemy_conditional_defense:
            return True, []
        if not boss_stage or not getattr(boss_stage, "phases", None):
            return False, []

        failing: list[int] = []
        for p in boss_stage.phases:
            p_idx = getattr(p, "phase_index", 1)
            if not self.check_enemy_conditions_match_phase(p):
                failing.append(p_idx)

        return len(failing) == 0, failing

    @property
    def has_guard(self) -> bool:
        if self.base_form and self.base_form.passive_tags.has_guard:
            return True
        return bool(self._parse_defense_mechanics()["has_guard"])

    @property
    def has_damage_reduction(self) -> bool:
        if self.base_form and self.base_form.passive_tags.dr_base_percent > 0:
            return True
        return bool(self._parse_defense_mechanics()["max_dr"] > 0)

    @property
    def damage_reduction_percent(self) -> int:
        if self.base_form and self.base_form.passive_tags.dr_base_percent > 0:
            return self.base_form.passive_tags.dr_base_percent
        return int(self._parse_defense_mechanics()["max_dr"])

    @property
    def has_dodge(self) -> bool:
        if self.base_form and self.base_form.passive_tags.dodge_chance_percent > 0:
            return True
        text = f"{self.passive_skill} {self.super_attack}".lower()
        return (
            "evades enemy" in text
            or "evade enemy" in text
            or "chance of evading" in text
            or "chance of dodging" in text
            or "chance to evade" in text
            or "chance to dodge" in text
            or "evasion" in text
            or "dodge" in text
            or self._parse_defense_mechanics()["has_dodge"]
        )

    @property
    def dodge_chance_percent(self) -> int:
        if (
            self.base_form
            and self.base_form.passive_tags
            and self.base_form.passive_tags.dodge_chance_percent > 0
        ):
            return self.base_form.passive_tags.dodge_chance_percent

        if not self.has_dodge:
            return 0

        return parse_dodge_percentage_from_text(f"{self.passive_skill} {self.super_attack}")

    @property
    def has_stacking_def(self) -> bool:
        if self.base_form and self.base_form.sa_tags.stacks_def:
            return True
        sa = self.super_attack.lower()
        clean_sa = re.sub(
            r"(?:greatly|massively)?\s*raises\s+(?:atk\s*(?:and|&)\s*def|def\s*(?:and|&)\s*atk|def|atk)\s+for\s+\d+\s+turns?",
            "",
            sa,
        )
        return bool(
            re.search(r"raises\s+(?:atk\s*(?:and|&)\s*)?def", clean_sa)
            or re.search(r"raises\s+def\s*(?:and|&)\s*atk", clean_sa)
        )

    @property
    def raises_def_on_sa(self) -> bool:
        """Indicates whether character raises DEF on Super Attack (temporary 1-turn or permanent stack)."""
        if self.has_stacking_def:
            return True
        if (
            self.base_form
            and self.base_form.sa_tags
            and (self.base_form.sa_tags.stacks_def or self.base_form.sa_tags.raise_def_turns > 0)
        ):
            return True
        sa = (self.super_attack or "").lower()
        return bool(
            re.search(r"raises\s+(?:atk\s*(?:and|&)\s*)?def", sa) or re.search(r"raises\s+def", sa)
        )

    @property
    def has_slot_2_3_buff(self) -> bool:
        """Indicates character receives specific passive bonuses when positioned in 2nd or 3rd slot."""
        if self.base_form and getattr(self.base_form.passive_tags, "has_slot_2_3_buff", False):
            return True
        return bool(self._parse_defense_mechanics().get("has_slot_2_3_buff", False))

    @property
    def has_stacking_atk(self) -> bool:
        if self.base_form and self.base_form.sa_tags.stacks_atk:
            return True
        sa = self.super_attack.lower()
        clean_sa = re.sub(
            r"(?:greatly|massively)?\s*raises\s+(?:atk\s*(?:and|&)\s*def|def\s*(?:and|&)\s*atk|def|atk)\s+for\s+\d+\s+turns?",
            "",
            sa,
        )
        return bool(
            re.search(r"raises\s+(?:def\s*(?:and|&)\s*)?atk", clean_sa)
            or re.search(r"raises\s+atk\s*(?:and|&)\s*def", clean_sa)
        )

    @property
    def has_revive(self) -> bool:
        if self.base_form and self.base_form.passive_tags.has_revive:
            return True
        text = f"{self.passive_skill} {self.super_attack}".lower()
        return "revive" in text or "revival" in text

    @property
    def has_standby(self) -> bool:
        if self.base_form and self.base_form.passive_tags.has_standby:
            return True
        text = f"{self.passive_skill} {self.super_attack}".lower()
        return "standby" in text

    @property
    def has_active_skill(self) -> bool:
        text = f"{self.passive_skill} {self.super_attack}".lower()
        return "active skill" in text or "can be activated" in text or "ultimate attack" in text

    @property
    def has_domain(self) -> bool:
        if self.base_form and self.base_form.passive_tags.has_domain:
            return True
        text = f"{self.passive_skill} {self.super_attack}".lower()
        return "domain" in text

    @property
    def has_target_taunt(self) -> bool:
        if self.base_form and self.base_form.passive_tags.has_taunt:
            return True
        text = f"{self.passive_skill} {self.super_attack}".lower()
        return (
            "target of enemy" in text
            or "directs enemy" in text
            or "redirects enemy" in text
            or "taunt" in text
        )

    @property
    def has_support(self) -> bool:
        if self.base_form and self.base_form.passive_tags.has_support:
            return True
        text = self.passive_skill.lower()
        return (
            "allies' ki" in text
            or "allies' atk" in text
            or "allies' def" in text
            or "allies ki" in text
            or "allies atk" in text
            or "allies def" in text
            or "super class allies" in text
            or "extreme class allies" in text
            or "category allies" in text
            or "for all allies" in text
            or "to all allies" in text
            or "for allies" in text
        )

    @property
    def has_orb_changing(self) -> bool:
        if self.base_form and self.base_form.passive_tags.has_orb_changing:
            return True
        text = self.passive_skill.lower()
        return (
            "changes ki spheres" in text
            or "changes spheres" in text
            or "orb changing" in text
            or "rainbow ki sphere" in text
        )

    @property
    def has_additionals_or_crit(self) -> bool:
        text = f"{self.passive_skill} {self.super_attack}".lower()
        return (
            "additional super attack" in text
            or "launches an additional" in text
            or "critical hit" in text
            or "effective against all types" in text
        )

    @property
    def is_slot1_tank(self) -> bool:
        from dokkan_eza_link_farmer.ai.solver import DokkanConstraintSolver

        return DokkanConstraintSolver.is_slot1_viable(self)

    @property
    def has_aoe(self) -> bool:
        if self.base_form and self.base_form.sa_tags and self.base_form.sa_tags.is_aoe:
            return True
        text = f"{self.super_attack} {self.passive_skill}".lower()
        aoe_pattern = r"(?:causes\s+(?:mass|destructive|colossal|mega-colossal|extreme|supreme)\s+damage\s+to\s+all\s+enemies|attacks\s+all\s+enemies|damage\s+to\s+all\s+enemies)"
        return bool(re.search(aoe_pattern, text))

    @property
    def lowers_enemy_atk(self) -> bool:
        text = f"{self.super_attack} {self.passive_skill}".lower()
        debuff_pattern = r"(?:greatly\s+lowers?\s+atk|massively\s+lowers?\s+atk|lowers?\s+atk|reduces?\s+enemy(?:'s)?\s+atk)"
        return bool(re.search(debuff_pattern, text))

    def get_tactical_form_timeline(self) -> list[dict[str, str]]:
        events: list[dict[str, str]] = []

        # 1. Standby Skill
        if self.standby_skill_name or self.has_standby:
            name = self.standby_skill_name or "Standby Mode"
            cond = (self.standby_skill_condition or "").lower()
            timing = (
                "Turno 4 (HP <= 50%)"
                if "4" in cond
                else ("Turno 3+" if "3" in cond else "Turno 4+")
            )
            eff = self.standby_skill_effect or "Enters Standby Mode"
            events.append(
                {
                    "type": "Standby Mode",
                    "name": name,
                    "timing": timing,
                    "condition": self.standby_skill_condition,
                    "effect": eff,
                }
            )

        # 2. Active Skill (Exchange, Switch, or standard Active)
        if self.active_skill_name or self.has_active_skill:
            name = self.active_skill_name or "Active Skill"
            name_lower = name.lower()
            eff_lower = (self.active_skill_effect or "").lower()
            cond_lower = (self.active_skill_condition or "").lower()

            if "switch" in name_lower or "switch" in eff_lower:
                events.append(
                    {
                        "type": "Scambio Reversibile (Switch)",
                        "name": name,
                        "timing": "Turno 1+ (Ogni Turno)",
                        "condition": self.active_skill_condition,
                        "effect": self.active_skill_effect,
                    }
                )
            elif "exchange" in name_lower or "exchange" in eff_lower:
                timing = (
                    "Turno 3"
                    if "3" in cond_lower
                    else ("Turno 4+" if "4" in cond_lower else "Turno 3+")
                )
                events.append(
                    {
                        "type": "Scambio (Exchange)",
                        "name": name,
                        "timing": timing,
                        "condition": self.active_skill_condition,
                        "effect": self.active_skill_effect,
                    }
                )

        # 3. Transformations
        if self.transformations:
            for form in self.transformations:
                turn = form.min_turn if form.min_turn > 1 else 4
                events.append(
                    {
                        "type": "Trasformazione",
                        "name": form.form_name or f"Form {form.form_index}",
                        "timing": f"Fase Finale (Turno {turn}+)",
                        "condition": f"A partire dal Turno {turn}",
                        "effect": form.passive_skill_text,
                    }
                )

        return events

    def evaluate_kit_power(self) -> tuple[float, dict[str, Any]]:
        def_score = 0.0
        breakdown: dict[str, Any] = {}

        has_guard = self.has_guard
        dr_pct = self.damage_reduction_percent
        has_stack_def = self.has_stacking_def
        dodge_chance = self.dodge_chance_percent
        is_guaranteed_dodge = bool(dodge_chance >= 100)

        # Base defensive attributes
        if has_guard:
            def_score += 15.0
            breakdown["guard"] = 15.0

        if dr_pct >= 50:
            def_score += 16.0
            breakdown["dr"] = f"{dr_pct}% (+16.0)"
        elif dr_pct >= 30 or self.has_damage_reduction:
            def_score += 12.0
            breakdown["dr"] = f"{dr_pct or 'present'}% (+12.0)"

        if has_stack_def:
            def_score += 12.0
            breakdown["stack_def"] = 12.0

        if self.has_dodge or dodge_chance > 0:
            if dodge_chance >= 100 or is_guaranteed_dodge:
                def_score += 16.0
                breakdown["dodge_tier"] = "100% Guaranteed (+16.0)"
            elif dodge_chance >= 70:
                def_score += 12.0
                breakdown["dodge_tier"] = "70% Great Chance (+12.0)"
            elif dodge_chance >= 50:
                def_score += 9.0
                breakdown["dodge_tier"] = "50% High Chance (+9.0)"
            elif dodge_chance >= 30:
                def_score += 6.0
                breakdown["dodge_tier"] = "30% Medium Chance (+6.0)"
            else:
                def_score += 4.0
                breakdown["dodge_tier"] = f"{dodge_chance}% Tier (+4.0)"

        if self.is_slot1_tank:
            def_score += 10.0
            breakdown["slot1_tank"] = 10.0

        # Composite Defense Survival Thresholds
        is_true_god_tank = (
            self.is_guard_permanent
            and self.is_guard_unconditional
            and (self.permanent_damage_reduction_percent >= 30 or dr_pct >= 50)
        )
        if is_true_god_tank:
            def_score += 35.0
            breakdown["composite_god_tank_guard_dr"] = 35.0
        elif has_guard and dr_pct >= 30:
            def_score += 18.0
            breakdown["composite_conditional_guard_dr"] = 18.0

        if self.permanent_damage_reduction_percent >= 70:
            def_score += 30.0
            breakdown["composite_heavy_dr_70"] = 30.0
        elif dr_pct >= 70:
            def_score += 20.0
            breakdown["composite_timed_heavy_dr"] = 20.0

        has_great_or_guaranteed_dodge = (self.has_dodge or dodge_chance > 0) and (
            dodge_chance >= 70 or is_guaranteed_dodge
        )
        if has_great_or_guaranteed_dodge:
            if self.is_dodge_permanent:
                def_score += 28.0
                breakdown["composite_great_or_guaranteed_dodge"] = 28.0
            else:
                def_score += 16.0
                breakdown["composite_timed_dodge"] = 16.0

        # 2. Game-Changing Mechanics (Revive, Standby, Taunt, Domain)
        mech_score = 0.0
        if self.has_revive:
            mech_score += 10.0
            breakdown["revive"] = 10.0
        if self.has_standby:
            mech_score += 8.0
            breakdown["standby"] = 8.0
        if self.has_target_taunt:
            mech_score += 10.0
            breakdown["taunt"] = 10.0
        if self.has_domain:
            mech_score += 6.0
            breakdown["domain"] = 6.0

        # 3. Utility & Team Support
        util_score = 0.0
        if self.has_support:
            util_score += 8.0
            breakdown["support"] = 8.0
        if self.has_orb_changing:
            util_score += 6.0
            breakdown["orb_changing"] = 6.0

        # 4. Offense & Multipliers
        atk_score = 0.0
        if self.has_additionals_or_crit:
            atk_score += 6.0
            breakdown["additionals_crit"] = 6.0
        if self.has_stacking_atk:
            atk_score += 4.0
            breakdown["stack_atk"] = 4.0
        if self.has_active_skill:
            atk_score += 4.0
            breakdown["active_skill"] = 4.0

        # 5. Base Card Tier & Progression
        tier_score = 0.0
        if self.is_lr:
            tier_score += 5.0
            breakdown["lr"] = 5.0
        if self.has_eza:
            tier_score += 4.0
            breakdown["eza"] = 4.0
        if self.is_rainbow:
            tier_score += 4.0
            breakdown["rainbow"] = 4.0

        total_score = def_score + mech_score + util_score + atk_score + tier_score
        return total_score, breakdown

    def is_covered_by_leader(self, leader: DokkanCard) -> tuple[bool, float, str]:
        # Fast path: check leader_spec if available
        if leader.leader_spec and (
            leader.leader_spec.main_category_ids
            or leader.leader_spec.extra_category_ids
            or leader.leader_spec.sub_elements_classes
        ):
            spec = leader.leader_spec
            my_cats = set(self.category_ids)
            has_main = bool(my_cats & set(spec.main_category_ids))
            has_extra = bool(my_cats & set(spec.extra_category_ids))

            if has_main:
                if has_extra and spec.extra_boost_pct > 0:
                    total_pct = float(spec.base_boost_pct + spec.extra_boost_pct)
                    label = "200%" if int(total_pct) == 200 else f"{int(total_pct)}%"
                    return (
                        True,
                        total_pct,
                        f"{label} ({spec.base_boost_pct}+{spec.extra_boost_pct}%) Leader Spec Match",
                    )
                return True, float(spec.base_boost_pct), f"{spec.base_boost_pct}% Leader Spec Match"

            if spec.sub_elements_classes and (
                self.element in spec.sub_elements_classes
                or (self.element % 10) in spec.sub_elements_classes
            ):
                boost = (
                    float(spec.sub_boost_pct)
                    if spec.sub_boost_pct > 0
                    else (float(spec.base_boost_pct) if not spec.main_category_ids else 90.0)
                )
                return True, boost, f"{int(boost)}% Sub-Element/Class Leader Spec Match"

            return False, 0.0, "No matching main category or sub-element on Leader Skill"

        lead_text = leader.leader_skill.strip()
        if not lead_text:
            return False, 0.0, "No leader skill"

        lead_lower = lead_text.lower()

        # Case A: Category Leader Skill
        matched_base_cat = None
        matched_extra_cat = None

        parts = re.split(r"plus an (?:additional|extra)", lead_text, flags=re.IGNORECASE)
        base_part = parts[0]
        extra_part = parts[1] if len(parts) > 1 else ""

        for cat in self.categories:
            if cat.lower() in base_part.lower():
                matched_base_cat = cat
                break

        if matched_base_cat:
            for cat in self.categories:
                if cat.lower() in extra_part.lower():
                    matched_extra_cat = cat
                    break

            if "200%" in base_part:
                return True, 200.0, f"Flat 200% on '{matched_base_cat}'"
            elif matched_extra_cat:
                extra_pct = 50.0 if "50%" in extra_part else 30.0
                total_pct = 170.0 + extra_pct
                label = f"{int(total_pct)}%"
                return (
                    True,
                    total_pct,
                    f"170%+{int(extra_pct)}% ({label}) on '{matched_base_cat}' & '{matched_extra_cat}'",
                )
            elif "170%" in base_part:
                return True, 170.0, f"170% on '{matched_base_cat}'"
            elif "150%" in base_part:
                return True, 150.0, f"150% on '{matched_base_cat}'"
            elif "130%" in base_part:
                return True, 130.0, f"130% on '{matched_base_cat}'"
            else:
                return True, 120.0, f"Category lead on '{matched_base_cat}'"

        # Case B: All Types / Super Class / Extreme Class Leader
        is_super = 10 <= self.element < 20
        is_extreme = self.element >= 20

        if "all types" in lead_lower:
            pct = 150.0 if "150%" in lead_lower else (130.0 if "130%" in lead_lower else 100.0)
            return True, pct, "All Types Leader"

        if ("super class" in lead_lower or "super type" in lead_lower) and is_super:
            pct = 150.0 if "150%" in lead_lower else (130.0 if "130%" in lead_lower else 120.0)
            return True, pct, "Super Class Leader"

        if ("extreme class" in lead_lower or "extreme type" in lead_lower) and is_extreme:
            pct = 150.0 if "150%" in lead_lower else (130.0 if "130%" in lead_lower else 120.0)
            return True, pct, "Extreme Class Leader"

        # Case C: Mono-Type Leader
        card_type_idx = self.element % 10
        card_type_name = TYPE_NAMES.get(card_type_idx, "").lower()

        if card_type_name and f"{card_type_name} type" in lead_lower:
            pct = 130.0 if "130%" in lead_lower else (120.0 if "120%" in lead_lower else 100.0)
            return True, pct, f"Mono-{card_type_name.upper()} Type Leader"

        return False, 0.0, "No matching category or type on Leader Skill"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "subname": self.subname,
            "rarity": self.rarity,
            "element": self.element,
            "element_name": self.element_name,
            "card_class": self.card_class,
            "leader_skill": self.leader_skill,
            "leader_spec": self.leader_spec.to_dict() if self.leader_spec else None,
            "passive_skill": self.passive_skill,
            "super_attack": self.super_attack,
            "categories": self.categories,
            "category_ids": self.category_ids,
            "links": self.links,
            "link_ids": self.link_ids,
            "thumb_url": self.thumb_url,
            "has_eza": self.has_eza,
            "is_eza": self.is_eza,
            "is_seza": self.is_seza,
            "is_rainbow": self.is_rainbow,
            "potential_percent": self.potential_percent,
            "swipe_page": self.swipe_page,
            "grid_slot": self.grid_slot,
            "is_tank_override": self.is_tank_override,
            "is_friend_leader": self.is_friend_leader,
            "standby_skill_name": self.standby_skill_name,
            "standby_skill_condition": self.standby_skill_condition,
            "standby_skill_effect": self.standby_skill_effect,
            "active_skill_name": self.active_skill_name,
            "active_skill_condition": self.active_skill_condition,
            "active_skill_effect": self.active_skill_effect,
            "base_form": self.base_form.to_dict() if self.base_form else None,
            "transformations": [t.to_dict() for t in self.transformations],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | Any) -> DokkanCard:
        if isinstance(data, DokkanCard):
            return data
        if not isinstance(data, dict):
            raise TypeError(f"Expected dict for DokkanCard.from_dict, got {type(data)}")
        cid_val = data.get("id")
        if cid_val is None:
            cid_val = data.get("card_id", 0)
        cid = _safe_int(cid_val, 0)
        leader_spec_data = data.get("leader_spec")
        leader_spec = LeaderSkillSpec.from_dict(leader_spec_data) if leader_spec_data else None

        base_form_data = data.get("base_form")
        base_form = CardForm.from_dict(base_form_data) if base_form_data else None

        transforms_data = data.get("transformations") or []
        transformations = [
            CardForm.from_dict(t) for t in transforms_data if isinstance(t, (dict, CardForm))
        ]

        raw_tank_override = data.get("is_tank_override")
        if raw_tank_override is not None:
            if isinstance(raw_tank_override, str):
                is_tank_override = raw_tank_override.strip().lower() in ("true", "1")
            else:
                is_tank_override = bool(raw_tank_override)
        else:
            is_tank_override = None

        return cls(
            id=cid,
            name=_safe_str(data.get("name"), "Unknown") or "Unknown",
            subname=_safe_str(data.get("subname"), ""),
            rarity=_safe_int(data.get("rarity"), 4),
            element=_safe_int(data.get("element"), 0),
            element_name=_safe_str(data.get("element_name"), ""),
            card_class=_safe_str(data.get("card_class"), ""),
            leader_skill=_safe_str(data.get("leader_skill"), ""),
            leader_spec=leader_spec,
            passive_skill=_safe_str(data.get("passive_skill"), ""),
            super_attack=_safe_str(data.get("super_attack"), ""),
            categories=list(data.get("categories") or []),
            category_ids=list(data.get("category_ids") or []),
            links=list(data.get("links") or []),
            link_ids=list(data.get("link_ids") or []),
            thumb_url=_safe_str(data.get("thumb_url"), ""),
            has_eza=_safe_bool(data.get("has_eza"), False),
            is_eza=_safe_bool(data.get("is_eza"), False),
            is_seza=_safe_bool(data.get("is_seza"), False),
            is_rainbow=_safe_bool(data.get("is_rainbow"), False),
            potential_percent=_safe_int(data.get("potential_percent"), 0),
            swipe_page=_safe_int(data.get("swipe_page"), 0),
            grid_slot=_safe_int(data.get("grid_slot"), 0),
            is_tank_override=is_tank_override,
            is_friend_leader=_safe_bool(data.get("is_friend_leader"), False),
            standby_skill_name=_safe_str(data.get("standby_skill_name"), ""),
            standby_skill_condition=_safe_str(data.get("standby_skill_condition"), ""),
            standby_skill_effect=_safe_str(data.get("standby_skill_effect"), ""),
            active_skill_name=_safe_str(data.get("active_skill_name"), ""),
            active_skill_condition=_safe_str(data.get("active_skill_condition"), ""),
            active_skill_effect=_safe_str(data.get("active_skill_effect"), ""),
            base_form=base_form,
            transformations=transformations,
        )

    @classmethod
    def from_dokkandb(
        cls,
        data: dict[str, Any],
        is_rainbow: bool = False,
        is_eza: bool | None = None,
        is_seza: bool | None = None,
    ) -> DokkanCard:
        has_seza_data = bool(
            data.get("eza_passive_skill_description_pre")
            or data.get("passive_skills_rows_eza_pre")
            or data.get("eza_leader_skill_set_id_pre")
        )
        has_eza_data = bool(
            data.get("eza_leader_skill")
            or data.get("passive_skills_rows_eza")
            or data.get("eza_leader_skill_set_id")
        )

        if is_seza is not None:
            card_is_seza = bool(is_seza)
        elif is_eza is not None:
            card_is_seza = False
        else:
            card_is_seza = has_seza_data

        if is_eza is not None:
            card_is_eza = bool(is_eza) or card_is_seza
        else:
            card_is_eza = has_eza_data or card_is_seza

        if card_is_seza and has_seza_data:
            leader = data.get("eza_leader_skill") or data.get("leader_skill") or ""
            passive_text = (
                data.get("eza_passive_skill_description")
                or data.get("passive_skill_description")
                or ""
            )
            special_descs = (
                data.get("special_descriptions_eza") or data.get("special_descriptions") or []
            )
        elif card_is_eza and has_eza_data:
            if has_seza_data:
                leader = (
                    data.get("eza_leader_skill_pre")
                    or data.get("eza_leader_skill")
                    or data.get("leader_skill")
                    or ""
                )
                passive_text = (
                    data.get("eza_passive_skill_description_pre")
                    or data.get("eza_passive_skill_description")
                    or data.get("passive_skill_description")
                    or ""
                )
            else:
                leader = data.get("eza_leader_skill") or data.get("leader_skill") or ""
                passive_text = (
                    data.get("eza_passive_skill_description")
                    or data.get("passive_skill_description")
                    or ""
                )
            special_descs = (
                data.get("special_descriptions_eza") or data.get("special_descriptions") or []
            )
        else:
            leader = data.get("leader_skill") or ""
            passive_text = data.get("passive_skill_description") or ""
            special_descs = data.get("special_descriptions") or []

        if not passive_text:
            if card_is_eza:
                p_rows = (
                    (
                        data.get("passive_skills_rows_eza_pre")
                        if (card_is_eza and not card_is_seza and has_seza_data)
                        else data.get("passive_skills_rows_eza")
                    )
                    or data.get("passive_skills_rows")
                    or []
                )
            else:
                p_rows = data.get("passive_skills_rows") or []
            p_parts = [r.get("name", "") for r in p_rows if isinstance(r, dict)]
            passive_text = " / ".join(p for p in p_parts if p) or (
                data.get("passive_skill_name") or ""
            )

        special_text = " | ".join(str(s) for s in special_descs if s)

        categories = data.get("category_names") or []
        cat_ids = data.get("category_ids") or []
        links: list[str] = []
        for i in range(1, 8):
            link_name = data.get(f"link_skill_name_{i}")
            if link_name:
                links.append(str(link_name).strip())
        link_ids = [lid for lid in (data.get("link_ids") or []) if lid is not None]

        try:
            cid = int(data.get("id") or data.get("real_id") or 0)
        except (ValueError, TypeError):
            cid = 0

        thumb_id = str(cid)[:-1] + "0" if cid else "0"
        thumb_url = f"https://enaskhebnjtktdfszdcb.supabase.co/storage/v1/object/public/assets/character/thumb/card_{thumb_id}_thumb_folder/card_{thumb_id}_thumb.png"

        try:
            rarity = int(data.get("rarity") or 4)
        except (ValueError, TypeError):
            rarity = 4

        try:
            element = int(data.get("element") or 0)
        except (ValueError, TypeError):
            element = 0

        def _safe_int_list(raw: Any) -> list[int]:
            if not isinstance(raw, (list, tuple, set)):
                return []
            res: list[int] = []
            for item in raw:
                try:
                    if item is not None:
                        res.append(int(item))
                except (ValueError, TypeError):
                    continue
            return res

        category_ids = _safe_int_list(cat_ids)
        parsed_link_ids = _safe_int_list(link_ids)

        return cls(
            id=cid,
            name=str(data.get("name") or "Unknown"),
            subname=str(data.get("subname") or ""),
            rarity=rarity,
            element=element,
            leader_skill=leader,
            passive_skill=passive_text,
            super_attack=special_text,
            categories=categories if isinstance(categories, list) else [],
            category_ids=category_ids,
            links=links,
            link_ids=parsed_link_ids,
            thumb_url=thumb_url,
            has_eza=bool(card_is_eza),
            is_eza=bool(card_is_eza),
            is_seza=bool(card_is_seza),
            is_rainbow=is_rainbow,
            potential_percent=100 if is_rainbow else 0,
        )


@dataclass
class TeamRecommendation:
    """Complete team build suggestion with tactical instructions."""

    leader: DokkanCard
    friend_leader: DokkanCard
    rotation_a: RotationPair
    rotation_b: RotationPair
    floaters: list[DokkanCard]
    all_cards: list[DokkanCard]
    tactical_analysis: str
    recommended_items: list[str] = field(default_factory=list)
    turn_plan: list[str] = field(default_factory=list)
    ai_reasoning: str | None = None
    target_missions: list[Any] = field(default_factory=list)
    mission_summary: str | None = None
    boss_stage: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "leader": self.leader.to_dict(),
            "friend_leader": self.friend_leader.to_dict(),
            "rotation_a": self.rotation_a.to_dict(),
            "rotation_b": self.rotation_b.to_dict(),
            "floaters": [c.to_dict() for c in self.floaters],
            "all_cards": [c.to_dict() for c in self.all_cards],
            "tactical_analysis": self.tactical_analysis,
            "recommended_items": list(self.recommended_items),
            "turn_plan": list(self.turn_plan),
            "ai_reasoning": self.ai_reasoning,
            "target_missions": self.target_missions,
            "mission_summary": self.mission_summary,
            "boss_stage": self.boss_stage.to_dict()
            if hasattr(self.boss_stage, "to_dict")
            else self.boss_stage,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | Any) -> TeamRecommendation:
        if isinstance(data, cls):
            return data
        if not isinstance(data, dict):
            raise TypeError(f"Expected dict for TeamRecommendation.from_dict, got {type(data)}")
        boss_data = data.get("boss_stage")
        boss_stage = BossStage.from_dict(boss_data) if boss_data else None
        return cls(
            leader=DokkanCard.from_dict(data["leader"]),
            friend_leader=DokkanCard.from_dict(data["friend_leader"]),
            rotation_a=RotationPair.from_dict(data["rotation_a"]),
            rotation_b=RotationPair.from_dict(data["rotation_b"]),
            floaters=[DokkanCard.from_dict(c) for c in (data.get("floaters") or [])],
            all_cards=[DokkanCard.from_dict(c) for c in (data.get("all_cards") or [])],
            tactical_analysis=_safe_str(data.get("tactical_analysis"), ""),
            recommended_items=list(data.get("recommended_items") or []),
            turn_plan=list(data.get("turn_plan") or []),
            ai_reasoning=data.get("ai_reasoning"),
            target_missions=list(data.get("target_missions") or []),
            mission_summary=data.get("mission_summary"),
            boss_stage=boss_stage,
        )


__all__ = [
    "CardForm",
    "DokkanCard",
    "LeaderSkillSpec",
    "PassiveTags",
    "RotationPair",
    "SATags",
    "TeamRecommendation",
    "TYPE_NAMES",
    "parse_dodge_percentage_from_text",
]
