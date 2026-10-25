from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from dokkan_eza_link_farmer.ai.llm_advisor import (
    AIConfig,
    AIModelFamily,
    FailureReport,
    SupportedAIModel,
)
from dokkan_eza_link_farmer.ai.synergy import RotationPair

TYPE_NAMES: dict[int, str] = {0: "AGL", 1: "TEQ", 2: "INT", 3: "STR", 4: "PHY"}


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
    for m in re.finditer(r"\(up to (\d+)%\)", clean_text):
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
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> PassiveTags:
        if not data:
            return cls()
        return cls(
            slot1_viable=bool(data.get("slot1_viable", False)),
            dr_base_percent=int(data.get("dr_base_percent", 0)),
            permanent_dr_percent=int(data.get("permanent_dr_percent", 0)),
            dr_turns_limit=int(data["dr_turns_limit"])
            if data.get("dr_turns_limit") is not None
            else None,
            is_dr_permanent=bool(data.get("is_dr_permanent", False)),
            dodge_chance_percent=int(data.get("dodge_chance_percent", 0)),
            dodge_turns_limit=int(data["dodge_turns_limit"])
            if data.get("dodge_turns_limit") is not None
            else None,
            is_dodge_permanent=bool(data.get("is_dodge_permanent", True)),
            has_guard=bool(data.get("has_guard", False)),
            is_guard_permanent=bool(data.get("is_guard_permanent", False)),
            is_guard_unconditional=bool(data.get("is_guard_unconditional", False)),
            guard_turns_limit=int(data["guard_turns_limit"])
            if data.get("guard_turns_limit") is not None
            else None,
            has_revive=bool(data.get("has_revive", False)),
            has_taunt=bool(data.get("has_taunt", False)),
            has_support=bool(data.get("has_support", False)),
            has_standby=bool(data.get("has_standby", False)),
            has_domain=bool(data.get("has_domain", False)),
            has_orb_changing=bool(data.get("has_orb_changing", False)),
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
    def from_dict(cls, data: dict[str, Any] | None) -> SATags:
        if not data:
            return cls()
        return cls(
            stacks_def=bool(data.get("stacks_def", False)),
            stacks_atk=bool(data.get("stacks_atk", False)),
            raise_def_turns=int(data.get("raise_def_turns", 0)),
            raise_atk_turns=int(data.get("raise_atk_turns", 0)),
            is_aoe=bool(data.get("is_aoe", False)),
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
    def from_dict(cls, data: dict[str, Any] | None) -> LeaderSkillSpec:
        if not data:
            return cls()
        return cls(
            main_category_ids=list(data.get("main_category_ids", [])),
            extra_category_ids=list(data.get("extra_category_ids", [])),
            sub_elements_classes=list(data.get("sub_elements_classes", [])),
            base_boost_pct=int(data.get("base_boost_pct", 170)),
            extra_boost_pct=int(data.get("extra_boost_pct", 30)),
            sub_boost_pct=int(data.get("sub_boost_pct", 0)),
            hp_stat_pct=int(data.get("hp_stat_pct", 170)),
            atk_stat_pct=int(data.get("atk_stat_pct", 170)),
            def_stat_pct=int(data.get("def_stat_pct", 170)),
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
    def from_dict(cls, data: dict[str, Any] | None) -> CardForm:
        if not data:
            return cls()
        return cls(
            form_id=int(data.get("form_id", 0)),
            form_index=int(data.get("form_index", 0)),
            form_name=str(data.get("form_name", "")),
            element=int(data.get("element", 0)),
            links=list(data.get("links", [])),
            link_ids=list(data.get("link_ids", [])),
            passive_skill_text=str(data.get("passive_skill_text", "")),
            super_attack_text=str(data.get("super_attack_text", "")),
            passive_tags=PassiveTags.from_dict(data.get("passive_tags")),
            sa_tags=SATags.from_dict(data.get("sa_tags")),
            min_turn=int(data.get("min_turn", 1)),
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

        max_dr = 0
        permanent_dr = 0
        dr_turn_limits: list[int] = []

        has_guard = False
        is_guard_permanent = False
        is_guard_unconditional = False
        guard_turn_limits: list[int] = []

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
            is_conditional_header = (
                "ki spheres obtained" in header
                or "collecting" in header
                or "when hp is" in header
                or "when attacking" in header
                or "as the 2nd or 3rd attacker" in header
                or "when receiving an attack" in header
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

                # Damage Reduction
                dr_m = re.findall(
                    r"(?:damage reduction (?:rate|of)?|damage received by(?:\s+up to)?|reduces damage(?: received)? by(?:\s+up to)?(?:\s+an additional)?|damage received\s*-\s*)\s*(\d+)%",
                    line,
                )
                for d in dr_m:
                    val = int(d)
                    if val > max_dr:
                        max_dr = val
                    if line_timed:
                        if line_turns:
                            dr_turn_limits.append(line_turns)
                    elif (is_basic or not is_conditional_header) and val > permanent_dr:
                        permanent_dr = val

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
                    if line_timed:
                        if line_turns:
                            guard_turn_limits.append(line_turns)
                    else:
                        is_guard_permanent = True
                        if is_basic or not is_conditional_header:
                            is_guard_unconditional = True

                # Dodge
                if any(k in line for k in ("evad", "evasion", "dodge")):
                    has_dodge = True
                    line_val = parse_dodge_percentage_from_text(line)

                    if line_timed:
                        if line_turns:
                            dodge_turn_limits.append(line_turns)
                    elif (is_basic or not is_conditional_header) and line_val > base_dodge:
                        base_dodge = line_val

        if not has_guard and re.search(r"guard(?:s|ing)?\s+(?:against\s+)?all", sa.lower()):
            has_guard = True
            is_guard_permanent = True

        if has_guard and not guard_turn_limits:
            is_guard_permanent = True
        elif has_guard and guard_turn_limits and not is_guard_permanent:
            is_guard_permanent = False

        if self.base_form and self.base_form.passive_tags:
            bt = self.base_form.passive_tags
            if bt.has_guard:
                has_guard = True
            if bt.is_guard_permanent:
                is_guard_permanent = True
            if bt.is_guard_unconditional:
                is_guard_unconditional = True
            if bt.permanent_dr_percent > permanent_dr:
                permanent_dr = bt.permanent_dr_percent
            if bt.dr_base_percent > max_dr:
                max_dr = bt.dr_base_percent

        res = {
            "max_dr": max_dr,
            "permanent_dr": permanent_dr,
            "is_dr_permanent": permanent_dr > 0,
            "dr_turns_limit": min(dr_turn_limits) if dr_turn_limits else None,
            "has_guard": has_guard,
            "is_guard_permanent": is_guard_permanent,
            "guard_turns_limit": min(guard_turn_limits) if guard_turn_limits else None,
            "is_guard_unconditional": is_guard_unconditional,
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
        cid = int(data.get("id") or data.get("card_id") or 0)
        leader_spec_data = data.get("leader_spec")
        leader_spec = LeaderSkillSpec.from_dict(leader_spec_data) if leader_spec_data else None

        base_form_data = data.get("base_form")
        base_form = CardForm.from_dict(base_form_data) if base_form_data else None

        transforms_data = data.get("transformations") or []
        transformations = [CardForm.from_dict(t) for t in transforms_data if isinstance(t, dict)]

        return cls(
            id=cid,
            name=str(data.get("name") or "Unknown"),
            subname=str(data.get("subname") or ""),
            rarity=int(data.get("rarity") or 4),
            element=int(data.get("element") or 0),
            element_name=str(data.get("element_name") or ""),
            card_class=str(data.get("card_class") or ""),
            leader_skill=str(data.get("leader_skill") or ""),
            leader_spec=leader_spec,
            passive_skill=str(data.get("passive_skill") or ""),
            super_attack=str(data.get("super_attack") or ""),
            categories=list(data.get("categories", [])),
            category_ids=list(data.get("category_ids", [])),
            links=list(data.get("links", [])),
            link_ids=list(data.get("link_ids", [])),
            thumb_url=str(data.get("thumb_url") or ""),
            has_eza=bool(data.get("has_eza", False)),
            is_eza=bool(data.get("is_eza", False)),
            is_seza=bool(data.get("is_seza", False)),
            is_rainbow=bool(data.get("is_rainbow", False)),
            potential_percent=int(data.get("potential_percent", 0)),
            swipe_page=int(data.get("swipe_page", 0)),
            grid_slot=int(data.get("grid_slot", 0)),
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
    def from_dict(cls, data: dict[str, Any]) -> TeamRecommendation:
        boss_data = data.get("boss_stage")
        boss_stage = (
            BossStage.from_dict(boss_data)
            if isinstance(boss_data, dict) and "stage_id" in boss_data
            else boss_data
        )
        return cls(
            leader=DokkanCard.from_dict(data["leader"]),
            friend_leader=DokkanCard.from_dict(data["friend_leader"]),
            rotation_a=RotationPair.from_dict(data["rotation_a"]),
            rotation_b=RotationPair.from_dict(data["rotation_b"]),
            floaters=[DokkanCard.from_dict(c) for c in data.get("floaters", [])],
            all_cards=[DokkanCard.from_dict(c) for c in data.get("all_cards", [])],
            tactical_analysis=str(data.get("tactical_analysis", "")),
            recommended_items=list(data.get("recommended_items", [])),
            turn_plan=list(data.get("turn_plan", [])),
            ai_reasoning=data.get("ai_reasoning"),
            target_missions=list(data.get("target_missions", [])),
            mission_summary=data.get("mission_summary"),
            boss_stage=boss_stage,
        )


@dataclass
class BossMechanic:
    """Boss skill or special mechanic (immunities, damage reduction, buffs)."""

    id: int
    name: str
    description: str = ""


@dataclass
class BossEnemy:
    """Individual enemy or boss in a phase."""

    card_id: int
    name: str
    subname: str = ""
    element: int = 0
    type_name: str = ""
    mechanics: list[BossMechanic] = field(default_factory=list)
    hp: int = 0
    atk: int = 0
    def_stat: int = 0
    actions_per_turn: int = 0


@dataclass
class BossPhase:
    """Single round / phase in an event stage with telemetry on immunities & lethal mechanics."""

    phase_index: int = 1
    phase: int = 1  # Backward compatibility alias
    battle_index: int = 1
    round_index: int = 1
    is_new_battle: bool = True
    bosses: list[BossEnemy] = field(default_factory=list)
    element: int = 0
    element_name: str = ""
    cancels_dodge: bool = False
    has_aoe: bool = False
    locks_slots: bool = False
    nullifies_stun_seal: bool = False
    nullifies_atk_down: bool = False
    nullifies_def_down: bool = False
    hp: int = 0
    atk: int = 0
    def_stat: int = 0
    actions_per_turn: int = 0
    estimated_sa_damage: int = 0
    special_skills: list[str] = field(default_factory=list)

    @property
    def enemy_count(self) -> int:
        return len(self.bosses) if self.bosses else 1

    @property
    def is_multi_enemy(self) -> bool:
        return self.enemy_count > 1

    @property
    def enemy_elements(self) -> list[int]:
        return [b.element for b in self.bosses]

    @property
    def is_rainbow(self) -> bool:
        return {b.element % 10 for b in self.bosses} >= {0, 1, 2, 3, 4}

    @property
    def all_type_names(self) -> list[str]:
        names: list[str] = []
        for b in self.bosses:
            t = b.type_name
            if t and t not in names:
                names.append(t)
        return names

    def __post_init__(self) -> None:
        if self.phase_index == 1 and self.phase != 1:
            self.phase_index = self.phase
        elif self.phase == 1 and self.phase_index != 1:
            self.phase = self.phase_index

        if self.atk > 0 and not self.estimated_sa_damage:
            self.estimated_sa_damage = int(self.atk * 2.5)

        if self.bosses and not self.element:
            primary = self.bosses[0]
            self.element = primary.element
            if not self.element_name:
                self.element_name = primary.type_name

        if not self.element_name and self.element:
            base_type = TYPE_NAMES.get(self.element % 10, "AGL")
            if self.element >= 20:
                self.element_name = f"Extreme {base_type}"
            elif self.element >= 10:
                self.element_name = f"Super {base_type}"
            else:
                self.element_name = base_type

        if self.is_multi_enemy:
            if self.is_rainbow:
                if (
                    not self.element_name
                    or "Rainbow" not in self.element_name
                    or ("(" not in self.element_name and "All 5 Types" not in self.element_name)
                ):
                    self.element_name = f"Rainbow ({self.enemy_count} Enemies: All 5 Types)"
            else:
                if not self.element_name or (
                    "Multi-Type" not in self.element_name and "Enemies" not in self.element_name
                ):
                    self.element_name = f"Multi-Type ({len(self.bosses)} Enemies)"

        if self.actions_per_turn == 0 and any(b.actions_per_turn > 0 for b in self.bosses):
            self.actions_per_turn = sum(b.actions_per_turn for b in self.bosses)

        if self.bosses:
            skill_tags: list[str] = list(self.special_skills)
            for b in self.bosses:
                for m in b.mechanics:
                    m_desc = f"{m.name} {m.description}".lower()
                    if (
                        "cancel" in m_desc
                        or "disable" in m_desc
                        or "nullif" in m_desc
                        or "cannot be" in m_desc
                        or "guaranteed hit" in m_desc
                    ) and (
                        "dodge" in m_desc
                        or "evasion" in m_desc
                        or "evaded" in m_desc
                        or "dodged" in m_desc
                    ):
                        self.cancels_dodge = True
                        if "Guaranteed Hit (Cancels Dodge)" not in skill_tags:
                            skill_tags.append("Guaranteed Hit (Cancels Dodge)")

                    if (
                        "all enemies" in m_desc
                        or "all targets" in m_desc
                        or "aoe" in m_desc
                        or "hits all" in m_desc
                        or "entire party" in m_desc
                    ):
                        self.has_aoe = True
                        if "AoE Super Attack" not in skill_tags:
                            skill_tags.append("AoE Super Attack")

                    if ("lock" in m_desc or "coercion" in m_desc) and (
                        "slot" in m_desc
                        or "position" in m_desc
                        or "switch" in m_desc
                        or "target" in m_desc
                        or "character" in m_desc
                        or "cannot switch" in m_desc
                    ):
                        self.locks_slots = True
                        if "Coercion (Locks Slot)" not in skill_tags:
                            skill_tags.append("Coercion (Locks Slot)")

                    if (
                        "immune" in m_desc
                        or "nullif" in m_desc
                        or "cannot be" in m_desc
                        or "disable" in m_desc
                        or "cancel" in m_desc
                    ):
                        if "stun" in m_desc or "seal" in m_desc:
                            self.nullifies_stun_seal = True
                        if "atk" in m_desc and (
                            "reduction" in m_desc or "lower" in m_desc or "down" in m_desc
                        ):
                            self.nullifies_atk_down = True
                        if "def" in m_desc and (
                            "reduction" in m_desc or "lower" in m_desc or "down" in m_desc
                        ):
                            self.nullifies_def_down = True

                    if "goku" in m_desc and "atk" in m_desc:
                        if "ATK +30% vs 'Goku'" not in skill_tags:
                            skill_tags.append("ATK +30% vs 'Goku'")
                    elif "super attack" in m_desc and (
                        "each super attack" in m_desc
                        or "per super attack" in m_desc
                        or "each sa" in m_desc
                    ):
                        if "ATK/DEF +10% per SA" not in skill_tags:
                            skill_tags.append("ATK/DEF +10% per SA")
                    elif "attack received" in m_desc and ("each" in m_desc or "per" in m_desc):
                        if "ATK/DEF +6% per hit (max 60%)" not in skill_tags:
                            skill_tags.append("ATK/DEF +6% per hit (max 60%)")
                    elif (
                        "after receiving" in m_desc or "7 attacks" in m_desc
                    ) and "ATK/DEF +30% after 7 hits" not in skill_tags:
                        skill_tags.append("ATK/DEF +30% after 7 hits")

            if self.nullifies_stun_seal and "Stun & Seal Immune" not in skill_tags:
                skill_tags.append("Stun & Seal Immune")
            if (
                self.nullifies_atk_down
                and self.nullifies_def_down
                and "ATK & DEF Debuff Immune" not in skill_tags
            ):
                skill_tags.append("ATK & DEF Debuff Immune")
            elif (
                self.nullifies_def_down
                and not self.nullifies_atk_down
                and "DEF Debuff Immune" not in skill_tags
            ):
                skill_tags.append("DEF Debuff Immune")

            self.special_skills = skill_tags

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase_index": self.phase_index,
            "phase": self.phase,
            "battle_index": self.battle_index,
            "round_index": self.round_index,
            "is_new_battle": self.is_new_battle,
            "element": self.element,
            "element_name": self.element_name,
            "cancels_dodge": self.cancels_dodge,
            "has_aoe": self.has_aoe,
            "locks_slots": self.locks_slots,
            "nullifies_stun_seal": self.nullifies_stun_seal,
            "nullifies_atk_down": self.nullifies_atk_down,
            "nullifies_def_down": self.nullifies_def_down,
            "hp": self.hp,
            "atk": self.atk,
            "def_stat": self.def_stat,
            "actions_per_turn": self.actions_per_turn,
            "estimated_sa_damage": self.estimated_sa_damage,
            "special_skills": self.special_skills,
            "bosses": [
                {
                    "card_id": b.card_id,
                    "name": b.name,
                    "subname": b.subname,
                    "element": b.element,
                    "type_name": b.type_name,
                    "hp": b.hp,
                    "atk": b.atk,
                    "def_stat": b.def_stat,
                    "actions_per_turn": b.actions_per_turn,
                    "mechanics": [
                        {"id": m.id, "name": m.name, "description": m.description}
                        for m in b.mechanics
                    ],
                }
                for b in self.bosses
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> BossPhase:
        if not data:
            return cls()
        bosses = []
        for b in data.get("bosses", []):
            mechs = [
                BossMechanic(
                    id=m.get("id", 0), name=m.get("name", ""), description=m.get("description", "")
                )
                for m in b.get("mechanics", [])
            ]
            bosses.append(
                BossEnemy(
                    card_id=b.get("card_id", 0),
                    name=b.get("name", "Unknown Boss"),
                    subname=b.get("subname", ""),
                    element=b.get("element", 0),
                    type_name=b.get("type_name", ""),
                    mechanics=mechs,
                    hp=int(b.get("hp", 0)),
                    atk=int(b.get("atk", 0)),
                    def_stat=int(
                        b.get("def_stat") if b.get("def_stat") is not None else b.get("defence", 0)
                    ),
                    actions_per_turn=int(
                        b.get("actions_per_turn")
                        if b.get("actions_per_turn") is not None
                        else b.get("multi_atk_num", 0)
                    ),
                )
            )
        idx = int(data.get("phase_index") or data.get("phase") or 1)
        return cls(
            phase_index=idx,
            phase=idx,
            battle_index=int(data.get("battle_index", 1)),
            round_index=int(data.get("round_index", idx)),
            is_new_battle=bool(data.get("is_new_battle", int(data.get("round_index", 1)) == 1)),
            bosses=bosses,
            element=int(data.get("element", 0)),
            element_name=str(data.get("element_name", "")),
            cancels_dodge=bool(data.get("cancels_dodge", False)),
            has_aoe=bool(data.get("has_aoe", False)),
            locks_slots=bool(data.get("locks_slots", False)),
            nullifies_stun_seal=bool(data.get("nullifies_stun_seal", False)),
            nullifies_atk_down=bool(data.get("nullifies_atk_down", False)),
            nullifies_def_down=bool(data.get("nullifies_def_down", False)),
            hp=int(data.get("hp", 0)),
            atk=int(data.get("atk", 0)),
            def_stat=int(data.get("def_stat", 0)),
            actions_per_turn=int(data.get("actions_per_turn", 0)),
            estimated_sa_damage=int(data.get("estimated_sa_damage", 0)),
            special_skills=list(data.get("special_skills", [])),
        )


@dataclass
class BossStage:
    """Complete challenge stage telemetry with full BossPhase sequences."""

    stage_id: int
    event_id: int
    stage_name: str
    event_name: str
    difficulty: int = 1
    phases: list[BossPhase] = field(default_factory=list)
    total_battles: int = 1

    @property
    def is_multi_battle(self) -> bool:
        return self.total_battles > 1 or any(p.battle_index > 1 for p in self.phases)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage_id": self.stage_id,
            "event_id": self.event_id,
            "stage_name": self.stage_name,
            "event_name": self.event_name,
            "difficulty": self.difficulty,
            "total_battles": self.total_battles,
            "is_multi_battle": self.is_multi_battle,
            "phases": [p.to_dict() for p in self.phases],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> BossStage:
        if not data:
            return cls(stage_id=0, event_id=0, stage_name="", event_name="")
        return cls(
            stage_id=int(data.get("stage_id", 0)),
            event_id=int(data.get("event_id", 0)),
            stage_name=str(data.get("stage_name", "")),
            event_name=str(data.get("event_name", "")),
            difficulty=int(data.get("difficulty", 1)),
            total_battles=int(data.get("total_battles") or 1),
            phases=[BossPhase.from_dict(p) for p in data.get("phases", [])],
        )

    @classmethod
    def from_dokkandb(cls, stage_data: dict[str, Any]) -> BossStage:
        phases: list[BossPhase] = []
        for p in stage_data.get("phases", []):
            phases.append(BossPhase.from_dict(p))
        total_battles = int(stage_data.get("total_battles") or 1)
        if not total_battles and phases:
            total_battles = max((p.battle_index for p in phases), default=1)
        return cls(
            stage_id=int(stage_data.get("stage_id", 0)),
            event_id=int(stage_data.get("event_id", 0)),
            stage_name=str(stage_data.get("stage_name", "")),
            event_name=str(stage_data.get("event_name", "")),
            difficulty=int(stage_data.get("difficulty", 1)),
            total_battles=total_battles,
            phases=phases,
        )


@dataclass
class ChallengeStageInfo:
    """Complete stage boss telemetry and mechanics (backward compatible model)."""

    event_id: int
    stage_id: int
    event_name: str
    stage_name: str
    difficulty: int = 1
    phases: list[BossPhase] = field(default_factory=list)


__all__ = [
    "AIModelFamily",
    "SupportedAIModel",
    "AIConfig",
    "PassiveTags",
    "SATags",
    "LeaderSkillSpec",
    "CardForm",
    "DokkanCard",
    "RotationPair",
    "TeamRecommendation",
    "BossMechanic",
    "BossEnemy",
    "BossPhase",
    "BossStage",
    "ChallengeStageInfo",
    "FailureReport",
    "TYPE_NAMES",
    "parse_dodge_percentage_from_text",
]
