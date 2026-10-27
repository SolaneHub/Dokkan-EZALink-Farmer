"""Boss domain models and mechanics for Dokkan Battle challenge events."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

TYPE_NAMES: dict[int, str] = {0: "AGL", 1: "TEQ", 2: "INT", 3: "STR", 4: "PHY"}


def _safe_int(val: Any, default: int = 0) -> int:
    if val is None:
        return default
    try:
        return int(val)
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


def infer_boss_categories_from_name(name: str) -> list[str]:
    """Infers canonical Dokkan categories from a boss character's name when not explicitly returned by API."""
    if not name:
        return []
    n = name.lower()
    cats: set[str] = set()

    # Pure Saiyans / Hybrid Saiyans
    saiyan_names = (
        "goku",
        "vegeta",
        "broly",
        "turles",
        "raditz",
        "nappa",
        "bardock",
        "paragus",
        "cabba",
        "caulifla",
        "kale",
        "kefla",
    )
    hybrid_names = ("gohan", "goten", "trunks", "pan", "bulli", "bra", "goku jr", "vegeta jr")
    if (
        any(k in n for k in saiyan_names)
        and not any(k in n for k in hybrid_names)
        and "goku black" not in n
        and "cell" not in n
    ):
        cats.add("Pure Saiyans")
    if any(k in n for k in hybrid_names):
        cats.add("Hybrid Saiyans")

    # Movie Bosses
    if any(
        k in n
        for k in (
            "broly",
            "cooler",
            "metal cooler",
            "janemba",
            "turles",
            "lord slug",
            "slug",
            "hirudegarn",
            "android 13",
            "android 14",
            "android 15",
            "fusion android 13",
            "garlic jr",
            "wheelo",
            "dr. wheelo",
            "bio-broly",
            "hatchiyack",
            "tapion",
        )
    ):
        cats.add("Movie Bosses")
    # Beerus & Whis from Z movies
    if "beerus" in n or "whis" in n:
        cats.add("Movie Bosses")
        cats.add("Realm of Gods")
        cats.add("Super Bosses")
    if "golden frieza" in n and not ("angel" in n or "tournament" in n or "universe" in n):
        cats.add("Movie Bosses")

    # Future Saga / Goku Black / Zamasu
    if "goku black" in n or "zamasu" in n:
        cats.update(
            [
                "Future Saga",
                "Realm of Gods",
                "Super Bosses",
                "Worldwide Chaos",
                "Time Travelers",
                "Inhuman Deeds",
            ]
        )
        if "fused" in n or "potara" in n or "fusion" in n:
            cats.add("Potara")

    # Universe Survival Saga / Universe 11
    if "toppo" in n:
        cats.update(
            [
                "Universe Survival Saga",
                "Realm of Gods",
                "Universe 11",
                "Defenders of Justice",
                "Special Pose",
                "Super Bosses",
            ]
        )
    if "jiren" in n:
        cats.update(
            [
                "Universe Survival Saga",
                "Realm of Gods",
                "Universe 11",
                "Defenders of Justice",
                "Super Bosses",
            ]
        )
    if "dyspo" in n:
        cats.update(
            [
                "Universe Survival Saga",
                "Universe 11",
                "Defenders of Justice",
                "Special Pose",
                "Super Bosses",
            ]
        )
    if "hit" in n:
        cats.update(
            ["Universe Survival Saga", "Universe 6", "Space-Traveling Warriors", "Super Bosses"]
        )
    if any(k in n for k in ("caulifla", "kale", "kefla", "cabba")):
        cats.update(["Universe Survival Saga", "Universe 6", "Pure Saiyans"])

    # Androids / Cell Saga
    if "cell" in n and "cell jr" not in n:
        cats.update(
            [
                "Androids/Cell Saga",
                "Androids",
                "Target: Goku",
                "Artificial Life Forms",
                "Time Travelers",
                "Power Absorption",
                "Sworn Enemies",
            ]
        )
    elif "cell jr" in n:
        cats.update(["Androids/Cell Saga", "Artificial Life Forms", "Sworn Enemies"])
    if any(
        k in n
        for k in ("android 16", "android 17", "android 18", "android 19", "android 20", "dr. gero")
    ):
        cats.update(["Androids", "Target: Goku"])

    # Majin Buu Saga / Buu
    if (
        "buu" in n
        or "majin buu" in n
        or "kid buu" in n
        or "super buu" in n
        or "buuhan" in n
        or "buutenks" in n
    ):
        cats.update(
            [
                "Majin Buu Saga",
                "Majin Power",
                "Sworn Enemies",
                "Artificial Life Forms",
                "Power Absorption",
            ]
        )

    # Wicked Bloodline / Frieza / Cooler
    if any(k in n for k in ("frieza", "cooler", "cold", "king cold", "chilled")):
        cats.update(["Wicked Bloodline", "Space-Traveling Warriors", "Terrifying Conquerors"])
        if "frieza" in n:
            cats.add("Sworn Enemies")

    # GT Bosses
    if any(
        k in n
        for k in (
            "omega shenron",
            "syn shenron",
            "eis shenron",
            "nuova shenron",
            "shadow dragon",
            "baby",
            "super 17",
            "rildo",
            "general rildo",
        )
    ):
        cats.add("GT Bosses")

    return sorted(list(cats))


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
    categories: list[str] = field(default_factory=list)
    category_ids: list[int] = field(default_factory=list)
    card_class: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "card_id": self.card_id,
            "name": self.name,
            "subname": self.subname,
            "element": self.element,
            "type_name": self.type_name,
            "hp": self.hp,
            "atk": self.atk,
            "def_stat": self.def_stat,
            "actions_per_turn": self.actions_per_turn,
            "categories": list(self.categories),
            "category_ids": list(self.category_ids),
            "card_class": self.card_class,
            "mechanics": [
                {"id": m.id, "name": m.name, "description": m.description} for m in self.mechanics
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | Any) -> BossEnemy:
        if isinstance(data, cls):
            return data
        if not data or not isinstance(data, dict):
            return cls(card_id=0, name="Unknown Boss")
        mechs = [
            BossMechanic(
                id=_safe_int(m.get("id"), 0),
                name=_safe_str(m.get("name"), ""),
                description=_safe_str(m.get("description"), ""),
            )
            for m in (data.get("mechanics") or [])
            if isinstance(m, dict)
        ]
        raw_def = data.get("def_stat")
        if raw_def is None:
            raw_def = data.get("defence", 0)
        raw_actions = data.get("actions_per_turn")
        if raw_actions is None:
            raw_actions = data.get("multi_atk_num", 0)

        cid = data.get("card_id")
        if cid is None:
            cid = data.get("id", 0)

        return cls(
            card_id=_safe_int(cid, 0),
            name=_safe_str(data.get("name"), "Unknown Boss") or "Unknown Boss",
            subname=_safe_str(data.get("subname"), ""),
            element=_safe_int(data.get("element"), 0),
            type_name=_safe_str(data.get("type_name"), ""),
            mechanics=mechs,
            hp=_safe_int(data.get("hp"), 0),
            atk=_safe_int(data.get("atk"), 0),
            def_stat=_safe_int(raw_def, 0),
            actions_per_turn=_safe_int(raw_actions, 0),
            categories=list(data.get("categories") or []),
            category_ids=list(data.get("category_ids") or []),
            card_class=_safe_str(data.get("card_class"), ""),
        )


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

    @property
    def enemy_categories(self) -> list[str]:
        """All unique categories across all enemies in this phase."""
        cats: set[str] = set()
        for b in self.bosses:
            if b.categories:
                cats.update(b.categories)
            else:
                cats.update(infer_boss_categories_from_name(b.name))
        return sorted(list(cats))

    @property
    def enemy_classes(self) -> list[str]:
        """All unique classes (Extreme, Super) across all enemies in this phase."""
        classes: set[str] = set()
        for b in self.bosses:
            if b.card_class:
                classes.add(b.card_class.title())
            elif b.element >= 20:
                classes.add("Extreme")
            elif b.element >= 10:
                classes.add("Super")
        return sorted(list(classes))

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
            "bosses": [b.to_dict() for b in self.bosses],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | Any) -> BossPhase:
        if isinstance(data, cls):
            return data
        if not data or not isinstance(data, dict):
            return cls()
        bosses = [
            BossEnemy.from_dict(b)
            for b in (data.get("bosses") or [])
            if isinstance(b, (dict, BossEnemy))
        ]
        idx_val = data.get("phase_index")
        if idx_val is None:
            idx_val = data.get("phase")
        idx = _safe_int(idx_val, 1) or 1
        r_idx = _safe_int(data.get("round_index"), idx)
        is_new_raw = data.get("is_new_battle")
        is_new_battle = (
            _safe_bool(is_new_raw, r_idx == 1) if is_new_raw is not None else (r_idx == 1)
        )

        return cls(
            phase_index=idx,
            phase=idx,
            battle_index=_safe_int(data.get("battle_index"), 1),
            round_index=r_idx,
            is_new_battle=is_new_battle,
            bosses=bosses,
            element=_safe_int(data.get("element"), 0),
            element_name=_safe_str(data.get("element_name"), ""),
            cancels_dodge=_safe_bool(data.get("cancels_dodge"), False),
            has_aoe=_safe_bool(data.get("has_aoe"), False),
            locks_slots=_safe_bool(data.get("locks_slots"), False),
            nullifies_stun_seal=_safe_bool(data.get("nullifies_stun_seal"), False),
            nullifies_atk_down=_safe_bool(data.get("nullifies_atk_down"), False),
            nullifies_def_down=_safe_bool(data.get("nullifies_def_down"), False),
            hp=_safe_int(data.get("hp"), 0),
            atk=_safe_int(data.get("atk"), 0),
            def_stat=_safe_int(data.get("def_stat"), 0),
            actions_per_turn=_safe_int(data.get("actions_per_turn"), 0),
            estimated_sa_damage=_safe_int(data.get("estimated_sa_damage"), 0),
            special_skills=list(data.get("special_skills") or []),
        )


DIFFICULTY_NAMES: dict[int, str] = {
    0: "Normal",
    1: "Hard",
    2: "Z-Hard",
    3: "Super",
    4: "Super2",
    5: "Super3",
}

DIFFICULTY_CODES: dict[str, int] = {
    "normal": 0,
    "hard": 1,
    "z-hard": 2,
    "zhard": 2,
    "super": 3,
    "super1": 3,
    "super2": 4,
    "super3": 5,
}


def parse_difficulty_code(val: Any) -> int | None:
    """Parses difficulty string, flag, or integer into standard Dokkan difficulty code (0-5)."""
    if val is None:
        return None
    if isinstance(val, int):
        return val if val in DIFFICULTY_NAMES else None
    s = str(val).strip().lower().lstrip("-")
    if s.isdigit():
        code = int(s)
        return code if code in DIFFICULTY_NAMES else None
    return DIFFICULTY_CODES.get(s)


def infer_difficulty_from_stage_id(stage_id: Any) -> int | None:
    """Infers difficulty code (0-5) from standard 8-digit Dokkan stage_id (last digit)."""
    if not stage_id:
        return None
    s = str(stage_id).strip()
    if s and s[-1].isdigit():
        digit = int(s[-1])
        if digit in DIFFICULTY_NAMES:
            return digit
    return None


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
    def difficulty_name(self) -> str:
        return DIFFICULTY_NAMES.get(self.difficulty, f"Difficulty {self.difficulty}")

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
    def from_dict(cls, data: dict[str, Any] | Any) -> BossStage:
        if isinstance(data, cls):
            return data
        if not data or not isinstance(data, dict):
            return cls(stage_id=0, event_id=0, stage_name="", event_name="")
        return cls(
            stage_id=_safe_int(data.get("stage_id"), 0),
            event_id=_safe_int(data.get("event_id"), 0),
            stage_name=_safe_str(data.get("stage_name"), ""),
            event_name=_safe_str(data.get("event_name"), ""),
            difficulty=_safe_int(data.get("difficulty"), 1),
            total_battles=_safe_int(data.get("total_battles"), 1) or 1,
            phases=[
                BossPhase.from_dict(p)
                for p in (data.get("phases") or [])
                if isinstance(p, (dict, BossPhase))
            ],
        )

    @classmethod
    def from_dokkandb(cls, stage_data: dict[str, Any]) -> BossStage:
        phases: list[BossPhase] = []
        for p in stage_data.get("phases") or []:
            phases.append(BossPhase.from_dict(p))
        total_battles = _safe_int(stage_data.get("total_battles"), 0)
        if not total_battles and phases:
            total_battles = max((p.battle_index for p in phases), default=1)
        if not total_battles:
            total_battles = 1
        raw_diff = stage_data.get("difficulty")
        if raw_diff is not None:
            diff = _safe_int(raw_diff, 1)
        else:
            inferred = infer_difficulty_from_stage_id(stage_data.get("stage_id"))
            diff = inferred if inferred is not None else 1
        return cls(
            stage_id=_safe_int(stage_data.get("stage_id"), 0),
            event_id=_safe_int(stage_data.get("event_id"), 0),
            stage_name=_safe_str(stage_data.get("stage_name"), ""),
            event_name=_safe_str(stage_data.get("event_name"), ""),
            difficulty=diff,
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

    @property
    def difficulty_name(self) -> str:
        return DIFFICULTY_NAMES.get(self.difficulty, f"Difficulty {self.difficulty}")


__all__ = [
    "BossEnemy",
    "BossMechanic",
    "BossPhase",
    "BossStage",
    "ChallengeStageInfo",
    "DIFFICULTY_CODES",
    "DIFFICULTY_NAMES",
    "TYPE_NAMES",
    "infer_boss_categories_from_name",
    "infer_difficulty_from_stage_id",
    "parse_difficulty_code",
]
