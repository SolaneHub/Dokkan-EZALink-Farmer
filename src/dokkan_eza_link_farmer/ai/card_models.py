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
    from dokkan_eza_link_farmer.ai.passive_parser import (
        parse_dodge_percentage_from_text as _parse_dodge,
    )

    return _parse_dodge(text)


@dataclass
class TeamConditionalBuff:
    """Defensive buff conditionally activated by team composition or turn allies."""

    condition_type: str = "class_count"  # "class_count", "dual_orb_class", "turn_allies", "all_class", "category_count", "another_category", "per_name", "per_category"
    req_class: str | None = None  # "Extreme" or "Super"
    req_categories: list[str] = field(default_factory=list)
    name_substr: str | None = None
    min_allies: int = 1
    all_allies: bool = False
    same_turn: bool = False
    has_orb_alternative: bool = False
    orb_count: int = 0

    # Defensive values granted
    dr_percent: int = 0
    has_guard: bool = False
    dodge_percent: int = 0
    per_ally_dr: int = 0
    per_ally_dodge: int = 0
    max_dr: int = 0
    max_dodge: int = 0
    is_pre_attack: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "condition_type": self.condition_type,
            "req_class": self.req_class,
            "req_categories": list(self.req_categories),
            "name_substr": self.name_substr,
            "min_allies": self.min_allies,
            "all_allies": self.all_allies,
            "same_turn": self.same_turn,
            "has_orb_alternative": self.has_orb_alternative,
            "orb_count": self.orb_count,
            "dr_percent": self.dr_percent,
            "has_guard": self.has_guard,
            "dodge_percent": self.dodge_percent,
            "per_ally_dr": self.per_ally_dr,
            "per_ally_dodge": self.per_ally_dodge,
            "max_dr": self.max_dr,
            "max_dodge": self.max_dodge,
            "is_pre_attack": self.is_pre_attack,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | Any) -> TeamConditionalBuff:
        if isinstance(data, cls):
            return data
        if not isinstance(data, dict):
            return cls()
        return cls(
            condition_type=_safe_str(data.get("condition_type"), "class_count"),
            req_class=data.get("req_class"),
            req_categories=list(data.get("req_categories") or []),
            name_substr=data.get("name_substr"),
            min_allies=_safe_int(data.get("min_allies"), 1),
            all_allies=_safe_bool(data.get("all_allies"), False),
            same_turn=_safe_bool(data.get("same_turn"), False),
            has_orb_alternative=_safe_bool(data.get("has_orb_alternative"), False),
            orb_count=_safe_int(data.get("orb_count"), 0),
            dr_percent=_safe_int(data.get("dr_percent"), 0),
            has_guard=_safe_bool(data.get("has_guard"), False),
            dodge_percent=_safe_int(data.get("dodge_percent"), 0),
            per_ally_dr=_safe_int(data.get("per_ally_dr"), 0),
            per_ally_dodge=_safe_int(data.get("per_ally_dodge"), 0),
            max_dr=_safe_int(data.get("max_dr"), 0),
            max_dodge=_safe_int(data.get("max_dodge"), 0),
            is_pre_attack=_safe_bool(data.get("is_pre_attack"), True),
        )


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
    has_rainbow_orb_changing: bool = False
    has_orb_conditional_dr: bool = False
    has_orb_conditional_dodge: bool = False
    has_orb_conditional_guard: bool = False
    is_orb_hungry: bool = False
    has_on_hit_defense: bool = False
    has_on_hit_guard: bool = False
    has_on_hit_dr: bool = False
    has_on_hit_def: bool = False
    is_once_only_dr: bool = False
    has_pre_attack_only_dr: bool = False
    pre_attack_dr_percent: int = 0
    pre_attack_dr_ki_req: int | None = None
    has_pre_attack_only_guard: bool = False
    pre_hit_guard: bool = False
    pre_hit_dr_percent: int = 0
    has_slot_2_3_buff: bool = False
    has_slot_2_3_guard: bool = False
    has_slot_1_only_guard: bool = False
    has_slot_1_only_dr: bool = False
    has_slot_1_buff: bool = False
    has_slot_2_buff: bool = False
    has_slot_3_buff: bool = False
    is_slot_1_or_3_only: bool = False
    slot_1_dr_percent: int = 0
    slot_1_dodge_percent: int = 0
    slot_3_dr_percent: int = 0
    slot_3_dodge_percent: int = 0
    has_enemy_conditional_defense: bool = False
    enemy_conditional_categories: list[str] = field(default_factory=list)
    enemy_conditional_classes: list[str] = field(default_factory=list)
    enemy_conditional_dr: int = 0
    enemy_conditional_guard: bool = False
    enemy_conditional_dodge: int = 0
    team_conditional_buffs: list[TeamConditionalBuff] = field(default_factory=list)

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
            "has_rainbow_orb_changing": self.has_rainbow_orb_changing,
            "has_orb_conditional_dr": self.has_orb_conditional_dr,
            "has_orb_conditional_dodge": self.has_orb_conditional_dodge,
            "has_orb_conditional_guard": self.has_orb_conditional_guard,
            "is_orb_hungry": self.is_orb_hungry,
            "has_on_hit_defense": self.has_on_hit_defense,
            "has_on_hit_guard": self.has_on_hit_guard,
            "has_on_hit_dr": self.has_on_hit_dr,
            "has_on_hit_def": self.has_on_hit_def,
            "is_once_only_dr": self.is_once_only_dr,
            "has_pre_attack_only_dr": self.has_pre_attack_only_dr,
            "pre_attack_dr_percent": self.pre_attack_dr_percent,
            "pre_attack_dr_ki_req": self.pre_attack_dr_ki_req,
            "has_pre_attack_only_guard": self.has_pre_attack_only_guard,
            "pre_hit_guard": self.pre_hit_guard,
            "pre_hit_dr_percent": self.pre_hit_dr_percent,
            "has_slot_2_3_buff": self.has_slot_2_3_buff,
            "has_slot_2_3_guard": self.has_slot_2_3_guard,
            "has_slot_1_only_guard": self.has_slot_1_only_guard,
            "has_slot_1_only_dr": self.has_slot_1_only_dr,
            "has_slot_1_buff": self.has_slot_1_buff,
            "has_slot_2_buff": self.has_slot_2_buff,
            "has_slot_3_buff": self.has_slot_3_buff,
            "is_slot_1_or_3_only": self.is_slot_1_or_3_only,
            "slot_1_dr_percent": self.slot_1_dr_percent,
            "slot_1_dodge_percent": self.slot_1_dodge_percent,
            "slot_3_dr_percent": self.slot_3_dr_percent,
            "slot_3_dodge_percent": self.slot_3_dodge_percent,
            "has_enemy_conditional_defense": self.has_enemy_conditional_defense,
            "enemy_conditional_categories": list(self.enemy_conditional_categories),
            "enemy_conditional_classes": list(self.enemy_conditional_classes),
            "enemy_conditional_dr": self.enemy_conditional_dr,
            "enemy_conditional_guard": self.enemy_conditional_guard,
            "enemy_conditional_dodge": self.enemy_conditional_dodge,
            "team_conditional_buffs": [b.to_dict() for b in self.team_conditional_buffs],
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
            has_rainbow_orb_changing=_safe_bool(data.get("has_rainbow_orb_changing"), False),
            has_orb_conditional_dr=_safe_bool(data.get("has_orb_conditional_dr"), False),
            has_orb_conditional_dodge=_safe_bool(data.get("has_orb_conditional_dodge"), False),
            has_orb_conditional_guard=_safe_bool(data.get("has_orb_conditional_guard"), False),
            is_orb_hungry=_safe_bool(data.get("is_orb_hungry"), False),
            has_on_hit_defense=_safe_bool(data.get("has_on_hit_defense"), False),
            has_on_hit_guard=_safe_bool(data.get("has_on_hit_guard"), False),
            has_on_hit_dr=_safe_bool(data.get("has_on_hit_dr"), False),
            has_on_hit_def=_safe_bool(data.get("has_on_hit_def"), False),
            is_once_only_dr=_safe_bool(data.get("is_once_only_dr"), False),
            has_pre_attack_only_dr=_safe_bool(data.get("has_pre_attack_only_dr"), False),
            pre_attack_dr_percent=_safe_int(data.get("pre_attack_dr_percent"), 0),
            pre_attack_dr_ki_req=_safe_int(data.get("pre_attack_dr_ki_req"))
            if data.get("pre_attack_dr_ki_req") is not None
            else None,
            has_pre_attack_only_guard=_safe_bool(data.get("has_pre_attack_only_guard"), False),
            pre_hit_guard=_safe_bool(data.get("pre_hit_guard"), False),
            pre_hit_dr_percent=_safe_int(data.get("pre_hit_dr_percent"), 0),
            has_slot_2_3_buff=_safe_bool(data.get("has_slot_2_3_buff"), False),
            has_slot_2_3_guard=_safe_bool(data.get("has_slot_2_3_guard"), False),
            has_slot_1_only_guard=_safe_bool(data.get("has_slot_1_only_guard"), False),
            has_slot_1_only_dr=_safe_bool(data.get("has_slot_1_only_dr"), False),
            has_slot_1_buff=_safe_bool(data.get("has_slot_1_buff"), False),
            has_slot_2_buff=_safe_bool(data.get("has_slot_2_buff"), False),
            has_slot_3_buff=_safe_bool(data.get("has_slot_3_buff"), False),
            is_slot_1_or_3_only=_safe_bool(data.get("is_slot_1_or_3_only"), False),
            slot_1_dr_percent=_safe_int(data.get("slot_1_dr_percent"), 0),
            slot_1_dodge_percent=_safe_int(data.get("slot_1_dodge_percent"), 0),
            slot_3_dr_percent=_safe_int(data.get("slot_3_dr_percent"), 0),
            slot_3_dodge_percent=_safe_int(data.get("slot_3_dodge_percent"), 0),
            has_enemy_conditional_defense=_safe_bool(
                data.get("has_enemy_conditional_defense"), False
            ),
            enemy_conditional_categories=list(data.get("enemy_conditional_categories") or []),
            enemy_conditional_classes=list(data.get("enemy_conditional_classes") or []),
            enemy_conditional_dr=_safe_int(data.get("enemy_conditional_dr"), 0),
            enemy_conditional_guard=_safe_bool(data.get("enemy_conditional_guard"), False),
            enemy_conditional_dodge=_safe_int(data.get("enemy_conditional_dodge"), 0),
            team_conditional_buffs=[
                TeamConditionalBuff.from_dict(b) for b in (data.get("team_conditional_buffs") or [])
            ],
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
    def title(self) -> str:
        """Alias for subname, preserving compatibility with user_box.json schema."""
        return self.subname

    @property
    def rainbow(self) -> bool:
        """Alias for is_rainbow, preserving compatibility with user_box.json schema."""
        return self.is_rainbow

    @property
    def potential_percentage(self) -> int:
        """Alias for potential_percent, preserving compatibility with user_box.json schema."""
        return self.potential_percent

    @property
    def element_color(self) -> str:
        from dokkan_eza_link_farmer.ui.formatters import element_color as get_element_color

        return get_element_color(self.element, self.element_name)

    @property
    def type_tag(self) -> str:
        elem_name = (self.element_name or "").upper()
        for t in ("AGL", "TEQ", "INT", "STR", "PHY"):
            if t in elem_name:
                return t
        return TYPE_NAMES.get(self.element % 10, "AGL")

    @property
    def dokkan_colored_name(self) -> str:
        from dokkan_eza_link_farmer.ui.formatters import dokkan_colored_name as get_colored_name

        return get_colored_name(self)

    def rich_formatted_name(self, include_type: bool = True) -> Any:
        from dokkan_eza_link_farmer.ui.formatters import rich_formatted_name as get_rich_name

        return get_rich_name(self, include_type=include_type)

    @property
    def is_lr(self) -> bool:
        if isinstance(self.rarity, int):
            return self.rarity >= 5
        try:
            return int(self.rarity) >= 5
        except (ValueError, TypeError):
            return str(self.rarity).upper() == "LR"

    def _parse_defense_mechanics(self) -> dict[str, Any]:
        """Parses passive skill and super attack to extract permanent vs timed defense attributes."""
        from dokkan_eza_link_farmer.ai.passive_parser import parse_defense_mechanics

        return parse_defense_mechanics(self)

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
    def has_pre_attack_only_dr(self) -> bool:
        if self.base_form and getattr(self.base_form.passive_tags, "has_pre_attack_only_dr", False):
            return True
        return bool(self._parse_defense_mechanics().get("has_pre_attack_only_dr", False))

    @property
    def pre_attack_dr_percent(self) -> int:
        if self.base_form and getattr(self.base_form.passive_tags, "pre_attack_dr_percent", 0) > 0:
            return self.base_form.passive_tags.pre_attack_dr_percent
        return int(self._parse_defense_mechanics().get("pre_attack_dr", 0))

    @property
    def pre_attack_dr_ki_req(self) -> int | None:
        if (
            self.base_form
            and getattr(self.base_form.passive_tags, "pre_attack_dr_ki_req", None) is not None
        ):
            return self.base_form.passive_tags.pre_attack_dr_ki_req
        return self._parse_defense_mechanics().get("pre_attack_ki_req")

    @property
    def has_pre_attack_only_guard(self) -> bool:
        if self.base_form and getattr(
            self.base_form.passive_tags, "has_pre_attack_only_guard", False
        ):
            return True
        return bool(self._parse_defense_mechanics().get("has_pre_attack_only_guard", False))

    @property
    def has_slot_2_3_guard(self) -> bool:
        if self.base_form and getattr(self.base_form.passive_tags, "has_slot_2_3_guard", False):
            return True
        return bool(self._parse_defense_mechanics().get("has_slot_2_3_guard", False))

    @property
    def has_slot_1_only_guard(self) -> bool:
        if self.base_form and getattr(self.base_form.passive_tags, "has_slot_1_only_guard", False):
            return True
        return bool(self._parse_defense_mechanics().get("has_slot_1_only_guard", False))

    @property
    def has_slot_1_only_dr(self) -> bool:
        if self.base_form and getattr(self.base_form.passive_tags, "has_slot_1_only_dr", False):
            return True
        return bool(self._parse_defense_mechanics().get("has_slot_1_only_dr", False))

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
    def has_slot_1_buff(self) -> bool:
        if self.base_form and getattr(self.base_form.passive_tags, "has_slot_1_buff", False):
            return True
        return bool(self._parse_defense_mechanics().get("has_slot_1_buff", False))

    @property
    def has_slot_2_buff(self) -> bool:
        if self.base_form and getattr(self.base_form.passive_tags, "has_slot_2_buff", False):
            return True
        return bool(self._parse_defense_mechanics().get("has_slot_2_buff", False))

    @property
    def has_slot_3_buff(self) -> bool:
        if self.base_form and getattr(self.base_form.passive_tags, "has_slot_3_buff", False):
            return True
        return bool(self._parse_defense_mechanics().get("has_slot_3_buff", False))

    @property
    def is_slot_1_or_3_only(self) -> bool:
        if self.base_form and getattr(self.base_form.passive_tags, "is_slot_1_or_3_only", False):
            return True
        return bool(self._parse_defense_mechanics().get("is_slot_1_or_3_only", False))

    @property
    def slot_1_dr_percent(self) -> int:
        if self.base_form and getattr(self.base_form.passive_tags, "slot_1_dr_percent", 0) > 0:
            return self.base_form.passive_tags.slot_1_dr_percent
        return int(self._parse_defense_mechanics().get("slot_1_dr", 0))

    @property
    def slot_1_dodge_percent(self) -> int:
        if self.base_form and getattr(self.base_form.passive_tags, "slot_1_dodge_percent", 0) > 0:
            return self.base_form.passive_tags.slot_1_dodge_percent
        return int(self._parse_defense_mechanics().get("slot_1_dodge", 0))

    @property
    def slot_3_dr_percent(self) -> int:
        if self.base_form and getattr(self.base_form.passive_tags, "slot_3_dr_percent", 0) > 0:
            return self.base_form.passive_tags.slot_3_dr_percent
        return int(self._parse_defense_mechanics().get("slot_3_dr", 0))

    @property
    def slot_3_dodge_percent(self) -> int:
        if self.base_form and getattr(self.base_form.passive_tags, "slot_3_dodge_percent", 0) > 0:
            return self.base_form.passive_tags.slot_3_dodge_percent
        return int(self._parse_defense_mechanics().get("slot_3_dodge", 0))

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
        text = (self.passive_skill or "").lower()
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
    def has_rainbow_orb_changing(self) -> bool:
        if self.base_form and getattr(
            self.base_form.passive_tags, "has_rainbow_orb_changing", False
        ):
            return True
        text = (self.passive_skill or "").lower()
        return bool(
            re.search(r"changes?\s+.*to\s+rainbow\s+ki sphere", text)
            or re.search(r"randomly changes?\s+.*to\s+rainbow", text)
            or re.search(
                r"changes?\s+.*ki spheres?\s+(?:of\s+a\s+certain\s+type\s+)?to\s+rainbow", text
            )
        )

    @property
    def has_orb_changing(self) -> bool:
        if self.base_form and getattr(self.base_form.passive_tags, "has_orb_changing", False):
            return True
        text = (self.passive_skill or "").lower()
        return (
            "changes ki spheres" in text
            or "changes spheres" in text
            or "orb changing" in text
            or "rainbow ki sphere" in text
        )

    @property
    def has_orb_conditional_defense(self) -> bool:
        if self.base_form and self.base_form.passive_tags:
            t = self.base_form.passive_tags
            if (
                t.has_orb_conditional_dr
                or t.has_orb_conditional_dodge
                or t.has_orb_conditional_guard
            ):
                return True
        text = (self.passive_skill or "").lower()
        has_sphere = (
            "ki sphere" in text or "rainbow ki sphere" in text or "spheres obtained" in text
        )
        if not has_sphere:
            return False
        has_def = (
            "damage reduction" in text
            or "reduces damage" in text
            or "guard" in text
            or "evad" in text
            or "dodge" in text
        )
        return has_def and (
            "per ki sphere" in text or "spheres obtained" in text or "rainbow ki sphere" in text
        )

    @property
    def is_extreme(self) -> bool:
        return getattr(self, "element", 0) >= 20

    @property
    def is_super(self) -> bool:
        return 10 <= getattr(self, "element", 0) < 20

    def calculate_team_conditional_defense(self, team: list[Any] | None) -> dict[str, Any]:
        """Calculates dynamic DR, Guard, and Dodge activated by team composition."""
        from dokkan_eza_link_farmer.ai.passive_parser import calculate_team_conditional_defense

        return calculate_team_conditional_defense(self, team)

    @property
    def is_orb_hungry(self) -> bool:
        if self.base_form and getattr(self.base_form.passive_tags, "is_orb_hungry", False):
            return True
        return self.has_orb_conditional_defense

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
        from dokkan_eza_link_farmer.ai.card_heuristics import get_tactical_form_timeline

        return get_tactical_form_timeline(self)

    def evaluate_kit_power(self) -> tuple[float, dict[str, Any]]:
        from dokkan_eza_link_farmer.ai.card_heuristics import evaluate_kit_power

        return evaluate_kit_power(self)

    def is_covered_by_leader(self, leader: DokkanCard) -> tuple[bool, float, str]:
        from dokkan_eza_link_farmer.ai.card_heuristics import is_covered_by_leader

        return is_covered_by_leader(self, leader)

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
            subname=_safe_str(data.get("subname") or data.get("title"), ""),
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
            is_rainbow=_safe_bool(
                data.get("is_rainbow")
                if data.get("is_rainbow") is not None
                else data.get("rainbow"),
                False,
            ),
            potential_percent=_safe_int(
                data.get("potential_percent")
                if data.get("potential_percent") is not None
                else data.get("potential_percentage"),
                0,
            ),
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
        from dokkan_eza_link_farmer.ai.dokkandb_parser import parse_card_from_dokkandb

        return parse_card_from_dokkandb(
            cls=cls,
            data=data,
            is_rainbow=is_rainbow,
            is_eza=is_eza,
            is_seza=is_seza,
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
    "TeamConditionalBuff",
    "TeamRecommendation",
    "TYPE_NAMES",
    "parse_dodge_percentage_from_text",
]
