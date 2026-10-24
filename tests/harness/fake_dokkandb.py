from __future__ import annotations

import copy
import os
import re
import tempfile
from typing import Any

import cv2
import numpy as np

from dokkan_eza_link_farmer.integrations.dokkandb_client import DokkanDBClient


class FakeDokkanDBClient(DokkanDBClient):
    """In-memory test harness simulating DokkanDBClient and DokkanDB API endpoints.

    Provides a realistic, static, minimal in-memory catalog of Extreme Z-Battles,
    events, stages, cards, and categories with zero network I/O and zero HTTP requests.
    Can be used either directly as a mock/drop-in replacement for DokkanDBClient,
    or as a context manager / fixture that intercepts requests.get calls.
    """

    SAMPLE_ZBATTLES: list[dict[str, Any]] = [
        {
            "id": 101,
            "name": "Extreme Z-Battle: Super Saiyan 3 Goku",
            "active": "normal",
            "start_at": "2020-01-01T00:00:00Z",
            "end_at": "2030-01-01T00:00:00Z",
            "event_priority": 100,
            "banner_image_path": "japan/event/banner/event_101.png",
            "listbutton_image_path": "japan/event/banner/event_button_101.png",
        },
        {
            "id": 102,
            "name": "Extreme Z-Battle: Broly",
            "active": "normal",
            "start_at": "2020-01-01T00:00:00Z",
            "end_at": "2030-01-01T00:00:00Z",
            "event_priority": 90,
            "banner_image_path": "japan/event/banner/event_102.png",
            "listbutton_image_path": "japan/event/banner/event_button_102.png",
        },
    ]

    SAMPLE_EVENTS: list[dict[str, Any]] = [
        {
            "id": 501,
            "name": "Ultimate Leveling Up! Chamber of Spirit and Time",
            "category": 2,  # Growth
            "active": "normal",
            "start_at": "2020-01-01T00:00:00Z",
            "end_at": "2030-01-01T00:00:00Z",
            "event_priority": 50,
            "banner_image_path": "japan/event/banner/event_501.png",
            "listbutton_image_path": "japan/event/banner/event_button_501.png",
        },
        {
            "id": 502,
            "name": "Study Hard, Play Hard! Turtle School's Intensive Training",
            "category": 2,
            "active": "normal",
            "start_at": "2020-01-01T00:00:00Z",
            "end_at": "2030-01-01T00:00:00Z",
            "event_priority": 40,
            "banner_image_path": "japan/event/banner/event_502.png",
            "listbutton_image_path": "japan/event/banner/event_button_502.png",
        },
        {
            "id": 601,
            "name": "Red Zone [Movie Edition]",
            "category": 20,  # Challenge
            "active": "normal",
            "start_at": "2020-01-01T00:00:00Z",
            "end_at": "2030-01-01T00:00:00Z",
            "event_priority": 95,
            "banner_image_path": "japan/event/banner/event_601.png",
            "listbutton_image_path": "japan/event/banner/event_button_601.png",
        },
    ]

    SAMPLE_CATEGORIES: list[dict[str, Any]] = [
        {"id": 1, "name": "Pure Saiyans"},
        {"id": 14, "name": "Hybrid Saiyans"},
        {"id": 18, "name": "Movie Heroes"},
        {"id": 65, "name": "Super Heroes"},
        {"id": 2, "name": "Super Saiyan 3"},
        {"id": 3, "name": "Potara"},
    ]

    SAMPLE_LINKS: list[dict[str, Any]] = [
        {"id": 1, "name": "Super Saiyan"},
        {"id": 2, "name": "Kamehameha"},
        {"id": 3, "name": "Prepared for Battle"},
        {"id": 4, "name": "Over in a Flash"},
        {"id": 5, "name": "Fierce Battle"},
        {"id": 6, "name": "Legendary Power"},
    ]

    SAMPLE_CARDS_CATALOG: list[dict[str, Any]] = [
        {
            "id": 1001,
            "name": "LR Goku",
            "subname": "Pinnacle of Fury",
            "rarity": 5,
            "element": 13,  # Super STR
            "category_ids": [1, 18],
            "category_names": ["Pure Saiyans", "Movie Heroes"],
            "link_ids": [1, 2, 3, 5, 6],
            "leader_skill": "Super Class Ki +3, HP, ATK & DEF +130%",
            "passive_skill_description": "ATK & DEF +150%; Guards all attacks; reduces damage received by 30%",
            "special_descriptions": ["Causes colossal damage to enemy and raises DEF"],
        },
        {
            "id": 1002,
            "name": "UR Vegeta",
            "subname": "Proud Prince",
            "rarity": 4,
            "element": 10,  # Super AGL
            "category_ids": [1],
            "category_names": ["Pure Saiyans"],
            "link_ids": [1, 3, 5],
            "leader_skill": "Pure Saiyans Category Ki +3, Stats +170%",
            "passive_skill_description": "ATK & DEF +120%; high chance of evading enemy's attack",
            "special_descriptions": ["Causes immense damage and greatly raises ATK"],
        },
        {
            "id": 1003,
            "name": "SSR Raditz",
            "subname": "Invader",
            "rarity": 3,
            "element": 23,  # Extreme STR
            "category_ids": [1],
            "category_names": ["Pure Saiyans"],
            "link_ids": [1, 3],
            "leader_skill": "Extreme STR Type Ki +2, HP, ATK & DEF +50%",
            "passive_skill_description": "ATK & DEF +80%",
            "special_descriptions": ["Causes supreme damage"],
        },
        {
            "id": 1004,
            "name": "R Saibaman",
            "subname": "Underling",
            "rarity": 2,
            "element": 20,
            "category_ids": [],
            "category_names": [],
            "link_ids": [],
            "leader_skill": "None",
            "passive_skill_description": "None",
            "special_descriptions": [],
        },
        {
            "id": 1005,
            "name": "LR Gohan",
            "subname": "Awakened Power",
            "rarity": 5,
            "element": 12,  # Super INT
            "category_ids": [14, 18, 65],
            "category_names": ["Hybrid Saiyans", "Movie Heroes", "Super Heroes"],
            "link_ids": [1, 2, 5, 6],
            "leader_skill": '"Super Heroes" Category Ki +3 and HP, ATK & DEF +170%, plus an additional HP, ATK & DEF +30% for "Movie Heroes"',
            "passive_skill_description": "Guards all attacks; reduces damage received by 60%",
            "special_descriptions": ["Greatly raises DEF and causes mega-colossal damage"],
        },
        {
            "id": 1012901,
            "name": "Super Saiyan Goku & Super Saiyan Vegeta",
            "subname": "Fused Fighting Force",
            "rarity": 5,
            "element": 12,
            "category_ids": [1, 3],
            "category_names": ["Pure Saiyans", "Potara"],
            "link_ids": [1, 2, 3, 5, 6],
            "transformation_names": ["Super Vegito"],
            "transformation_ids": [4012901],
            "transformation_elements": [12],
            "leader_skill": '"Potara" Category Ki +3, HP & ATK +170% and DEF +130%; or INT Type Ki +3 and HP, ATK & DEF +90%',
            "passive_skill_description": "ATK & DEF +120%; performs Potara Fusion when HP is 50% or less",
            "special_descriptions": ["Causes colossal damage"],
        },
        {
            "id": 1003211,
            "name": "SS3 Goku",
            "subname": "Golden Fist",
            "rarity": 5,
            "element": 10,
            "category_ids": [1, 2],
            "category_names": ["Pure Saiyans", "Super Saiyan 3"],
            "link_ids": [1, 2, 4, 5, 6],
            "leader_skill": "AGL Type ATK +3000",
            "eza_leader_skill_pre": "AGL Type Ki +3, Stats +70%",
            "eza_leader_skill": "AGL Type Ki +3, Stats +90%",
            "passive_skill_description": "ATK 100% for 7 turns",
            "eza_passive_skill_description_pre": "DEF 70%; ATK 120% for 7 turns",
            "eza_passive_skill_description": "Guards all attacks; reduces damage received by 50%; chance of evading enemy attacks +50%",
            "special_descriptions": ["Causes colossal damage"],
            "special_descriptions_eza": ["Greatly raises DEF and causes colossal damage"],
        },
    ]

    def __init__(self, cache_dir: str | None = None, cache_ttl_seconds: int = 43200) -> None:
        self.cache_dir = cache_dir or "in_memory_fake_cache"
        self.cache_ttl_seconds = cache_ttl_seconds
        self.banners_dir = f"{self.cache_dir}/banners"

        self.zbattles = copy.deepcopy(self.SAMPLE_ZBATTLES)
        self.events = copy.deepcopy(self.SAMPLE_EVENTS)
        self.categories = copy.deepcopy(self.SAMPLE_CATEGORIES)
        self.links = copy.deepcopy(self.SAMPLE_LINKS)
        self.catalog = copy.deepcopy(self.SAMPLE_CARDS_CATALOG)

        # Call counts / tracking
        self.calls_log: list[str] = []

    def get_zbattles(
        self, region: str = "glb", active_only: bool = False, force_refresh: bool = False
    ) -> list[dict[str, Any]]:
        _ = (region, active_only, force_refresh)
        self.calls_log.append("get_zbattles")
        return [dict(z, is_currently_open=True) for z in self.zbattles]

    def get_events(
        self, category: int | None = None, region: str = "glb", force_refresh: bool = False
    ) -> list[dict[str, Any]]:
        _ = (region, force_refresh)
        self.calls_log.append("get_events")
        items = [dict(e, is_currently_open=True) for e in self.events]
        if category is not None:
            items = [e for e in items if e.get("category") == category]
        return items

    def download_banner(self, event: dict[str, Any], prefer_button: bool = True) -> str | None:
        _ = prefer_button
        self.calls_log.append("download_banner")
        event_id = event.get("id", "0")
        tmp_dir = os.path.join(tempfile.gettempdir(), "fake_dokkandb_banners")
        os.makedirs(tmp_dir, exist_ok=True)
        banner_path = os.path.join(tmp_dir, f"event_{event_id}_banner.png")
        if not os.path.exists(banner_path):
            img = np.zeros((40, 100, 3), dtype=np.uint8)
            cv2.imwrite(banner_path, img)
        return banner_path

    def get_link_level_events(
        self, region: str = "glb", active_only: bool = False
    ) -> list[dict[str, Any]]:
        _ = active_only
        self.calls_log.append("get_link_level_events")
        all_events = self.get_events(region=region)
        keywords = [
            "chamber of spirit and time",
            "turtle school's intensive training",
            "grand elder guru's guidance",
            "god-level intensive training",
        ]
        results = []
        for ev in all_events:
            name = (ev.get("name") or "").lower()
            if any(kw in name for kw in keywords):
                ev_copy = dict(ev, is_currently_open=True)
                ev_copy["banner_local_path"] = self.download_banner(ev_copy)
                results.append(ev_copy)
        return results

    def get_chamber_of_spirit_and_time(self, region: str = "glb") -> dict[str, Any] | None:
        self.calls_log.append("get_chamber_of_spirit_and_time")
        events = self.get_link_level_events(region=region)
        for ev in events:
            if "chamber of spirit and time" in (ev.get("name") or "").lower():
                return ev
        return events[0] if events else None

    def get_area_tabs(
        self, region: str = "glb", force_refresh: bool = False
    ) -> list[dict[str, Any]]:
        _ = (region, force_refresh)
        self.calls_log.append("get_area_tabs")
        return [
            {"id": 1, "name": "Story", "area_category_ids": [1]},
            {"id": 2, "name": "Growth", "area_category_ids": [2]},
            {"id": 5, "name": "Challenge", "area_category_ids": [20]},
            {"id": 6, "name": "Z-Battle", "area_category_ids": [30]},
        ]

    def get_challenge_events(
        self, region: str = "glb", active_only: bool = False, force_refresh: bool = False
    ) -> list[dict[str, Any]]:
        _ = (active_only, force_refresh)
        self.calls_log.append("get_challenge_events")
        return [e for e in self.get_events(region=region) if e.get("category") == 20]

    def get_event_details(
        self, event_id: int, region: str = "glb", force_refresh: bool = False
    ) -> dict[str, Any] | None:
        _ = (region, force_refresh)
        self.calls_log.append(f"get_event_details_{event_id}")
        return {
            "id": event_id,
            "name": f"Event {event_id}",
            "mission_categories": [],
            "stages": [{"stage_id": 1, "name": "Stage 1"}],
        }

    def get_cards_by_ids(
        self, card_ids: list[int], region: str = "glb", force_refresh: bool = False
    ) -> list[dict[str, Any]]:
        _ = (region, force_refresh)
        self.calls_log.append("get_cards_by_ids")
        id_set = set(card_ids)
        return [copy.deepcopy(c) for c in self.catalog if c.get("id") in id_set]

    def get_enemy_skills_by_ids(
        self, skill_ids: list[int], region: str = "glb", force_refresh: bool = False
    ) -> list[dict[str, Any]]:
        _ = (region, force_refresh)
        self.calls_log.append("get_enemy_skills_by_ids")
        return [{"id": sid, "name": f"Skill {sid}", "description": ""} for sid in skill_ids]

    def get_stage_boss_info(
        self, event_id: int, stage_id: int, region: str = "glb", force_refresh: bool = False
    ) -> dict[str, Any] | None:
        _ = (region, force_refresh)
        self.calls_log.append(f"get_stage_boss_info_{stage_id}")
        return {
            "event_id": event_id,
            "stage_id": stage_id,
            "event_name": f"Event {event_id}",
            "stage_name": f"Stage {stage_id}",
            "difficulty": 1,
            "total_battles": 1,
            "is_multi_battle": False,
            "phases": [
                {
                    "phase_index": 1,
                    "phase": 1,
                    "battle_index": 1,
                    "round_index": 1,
                    "is_new_battle": True,
                    "element": 23,
                    "element_name": "Extreme STR",
                    "hp": 10000000,
                    "atk": 250000,
                    "def_stat": 80000,
                    "actions_per_turn": 6,
                    "estimated_sa_damage": 625000,
                    "bosses": [
                        {
                            "name": "Broly",
                            "card_id": 9991,
                            "element": 23,
                            "type_name": "Extreme STR",
                            "hp": 10000000,
                            "atk": 250000,
                            "defence": 80000,
                            "mechanics": [],
                        }
                    ],
                }
            ],
        }

    def get_event_missions(
        self, event_id: int, region: str = "glb", force_refresh: bool = False
    ) -> list[dict[str, Any]]:
        _ = (event_id, region, force_refresh)
        self.calls_log.append("get_event_missions")
        return []

    def load_banner_template(self, banner_path: str) -> np.ndarray | None:
        _ = banner_path
        self.calls_log.append("load_banner_template")
        return np.zeros((50, 100, 3), dtype=np.uint8)

    def get_categories(
        self, region: str = "glb", force_refresh: bool = False
    ) -> list[dict[str, Any]]:
        _ = (region, force_refresh)
        self.calls_log.append("get_categories")
        return copy.deepcopy(self.categories)

    def get_category_leaders(
        self, category_id: int, region: str = "glb", force_refresh: bool = False
    ) -> list[dict[str, Any]]:
        _ = (region, force_refresh)
        self.calls_log.append(f"get_category_leaders_{category_id}")
        leaders: list[dict[str, Any]] = []
        for c in self.catalog:
            if category_id in c.get("category_ids", []):
                leaders.append(
                    {
                        "id": c.get("id"),
                        "name": c.get("name"),
                        "leader_skills": [
                            {
                                "efficacy_type": 5,
                                "efficacy_values": "[3,0,0]",
                                "sub_target_types": [{"target_value": category_id}],
                            },
                            {
                                "efficacy_type": 82,
                                "efficacy_values": "[31,170,0]",
                                "sub_target_types": [{"target_value": category_id}],
                            },
                        ],
                    }
                )
        return leaders

    def get_links(self, region: str = "glb", force_refresh: bool = False) -> list[dict[str, Any]]:
        _ = (region, force_refresh)
        self.calls_log.append("get_links")
        return copy.deepcopy(self.links)

    def get_leader_200_catalog(
        self, region: str = "glb", force_refresh: bool = False
    ) -> list[dict[str, Any]]:
        _ = (region, force_refresh)
        self.calls_log.append("get_leader_200_catalog")
        return [c for c in self.catalog if "200%" in c.get("leader_skill", "")]

    def get_cards_catalog(
        self, region: str = "glb", force_refresh: bool = False
    ) -> list[dict[str, Any]]:
        _ = (region, force_refresh)
        self.calls_log.append("get_cards_catalog")
        return copy.deepcopy(self.catalog)

    def get_card(
        self, card_id: int, region: str = "glb", force_refresh: bool = False
    ) -> dict[str, Any] | None:
        _ = (region, force_refresh)
        self.calls_log.append(f"get_card_{card_id}")
        card = next((c for c in self.catalog if c.get("id") == card_id), None)
        return copy.deepcopy(card) if card else None

    def search_cards(
        self, query: str, region: str = "glb", limit: int = 20
    ) -> list[dict[str, Any]]:
        _ = region
        self.calls_log.append("search_cards")
        q = query.strip().lower()
        results = [
            c
            for c in self.catalog
            if q in c.get("name", "").lower() or q in c.get("subname", "").lower()
        ]
        return results[:limit]

    def get_user_box_card_ids(self) -> list[int]:
        self.calls_log.append("get_user_box_card_ids")
        return [c["id"] for c in self.catalog if "id" in c]

    def get_challenge_missions(
        self,
        event_name: str | int,
        region: str = "glb",
        force_refresh: bool = False,
        stage_num: int | None = None,
        event_id: int | None = None,
    ) -> list[dict[str, Any]]:
        _ = (event_name, region, force_refresh, stage_num, event_id)
        self.calls_log.append("get_challenge_missions")
        return []

    def get_best_linking_partners(
        self,
        card_id: int,
        pool_card_ids: list[int] | None = None,
        top_n: int = 5,
        region: str = "glb",
    ) -> list[dict[str, Any]]:
        _ = (pool_card_ids, region)
        self.calls_log.append("get_best_linking_partners")
        card = self.get_card(card_id)
        if not card:
            return []
        card_links = set(card.get("link_ids") or [])
        partners = []
        for other in self.catalog:
            if other.get("id") == card_id:
                continue
            shared = card_links & set(other.get("link_ids") or [])
            if shared:
                partners.append(
                    {
                        "card_id": other.get("id"),
                        "name": other.get("name"),
                        "subname": other.get("subname"),
                        "shared_links_count": len(shared),
                        "shared_links": [f"Link_{i}" for i in shared],
                        "shared_categories_count": 1,
                    }
                )
        partners.sort(key=lambda x: x["shared_links_count"], reverse=True)
        return partners[:top_n]

    def enrich_card(
        self,
        card: dict[str, Any],
        region: str = "glb",
    ) -> dict[str, Any]:
        _ = region
        self.calls_log.append("enrich_card")
        cid = card.get("id")
        card_data = self.get_card(cid) if cid else None
        if not card_data:
            return card
        enriched = dict(card)
        for k in ("name", "subname", "rarity", "element", "leader_skill", "passive_skill"):
            if k in card_data and k not in enriched:
                enriched[k] = card_data[k]
        return enriched

    def enrich_box(
        self,
        cards: list[dict[str, Any]],
        region: str = "glb",
    ) -> list[dict[str, Any]]:
        self.calls_log.append("enrich_box")
        return [self.enrich_card(c, region=region) for c in cards]


class FakeHTTPResponse:
    """Simulated requests.Response object for in-memory HTTP mocking."""

    def __init__(self, data: Any, status_code: int = 200, content: bytes = b"") -> None:
        self._data = data
        self.status_code = status_code
        self.content = content or (b"\x89PNG\r\n\x1a\n" + b"\x00" * 200)

    def json(self) -> Any:
        return self._data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP Error {self.status_code}")


def fake_dokkandb_requests_get(url: str, *_args: Any, **_kwargs: Any) -> FakeHTTPResponse:
    """Direct drop-in side-effect for requests.get to simulate DokkanDB API endpoints in-memory.

    Intercepts calls to:
    - /cards-catalog-with-transformations?chunk=...
    - /card?code=...
    - /zbattle-all
    - /events-all
    - /categories
    - /links
    - /area-tabs
    - /assets/mirror/..., Supabase thumbnail storage URLs
    """
    clean_url = str(url)

    # 1. Catalog chunks
    if "cards-catalog-with-transformations" in clean_url or "chunk=" in clean_url:
        if "chunk=1" in clean_url:
            return FakeHTTPResponse(
                [
                    {"id": 1001, "name": "LR Goku", "rarity": 5},
                    {"id": 1002, "name": "UR Vegeta", "rarity": 4},
                    {"id": 1003, "name": "SSR Raditz", "rarity": 3},
                ]
            )
        elif "chunk=2" in clean_url:
            return FakeHTTPResponse(
                [
                    {"id": 1004, "name": "R Saibaman", "rarity": 2},
                    {"id": 1005, "name": "LR Gohan", "rarity": 5},
                ]
            )
        else:
            return FakeHTTPResponse([])

    # 1.5. Category leaders
    if "category-leaders" in clean_url:
        cat_id = 0
        match = re.search(r"code=(\d+)", clean_url)
        if match:
            cat_id = int(match.group(1))
        client = FakeDokkanDBClient()
        return FakeHTTPResponse(client.get_category_leaders(cat_id))

    # 2. Individual card deep details
    if "/card" in clean_url or ("code=" in clean_url and "category-leaders" not in clean_url):
        card_id = 0
        match = re.search(r"code=(\d+)", clean_url)
        if match:
            card_id = int(match.group(1))

        if card_id == 1001:
            data = [
                {
                    "id": 1001,
                    "name": "EZA Broly",
                    "rarity": 5,
                    "element": 23,
                    "leader_skill": "Extreme Class Ki +3, Stats +120%",
                    "eza_leader_skill": "Extreme Class Ki +4, Stats +150%",
                    "passive_skill_description": "Base Passive",
                    "eza_passive_skill_description": "Guards all attacks; reduces damage received by 60%",
                    "special_descriptions": ["Causes colossal damage"],
                    "special_descriptions_eza": [
                        "Greatly raises DEF and causes mega-colossal damage"
                    ],
                }
            ]
        elif card_id == 1002:
            data = [
                {
                    "id": 1002,
                    "name": "Base Goku",
                    "rarity": 4,
                    "element": 10,
                    "leader_skill": "Super Class Ki +3, Stats +120%",
                    "passive_skill_description": "ATK +120%",
                    "special_descriptions": ["Raises ATK & DEF for 1 turn"],
                }
            ]
        elif card_id == 1003211:
            data = [
                {
                    "id": 1003211,
                    "name": "SS3 Goku",
                    "rarity": 5,
                    "element": 10,
                    "leader_skill": "AGL Type ATK +3000",
                    "eza_leader_skill_pre": "AGL Type Ki +3, Stats +70%",
                    "eza_leader_skill": "AGL Type Ki +3, Stats +90%",
                    "passive_skill_description": "ATK 100% for 7 turns",
                    "eza_passive_skill_description_pre": "DEF 70%; ATK 120% for 7 turns",
                    "eza_passive_skill_description": "Guards all attacks; reduces damage received by 50%; chance of evading enemy attacks +50%",
                    "special_descriptions": ["Causes colossal damage"],
                    "special_descriptions_eza": ["Greatly raises DEF and causes colossal damage"],
                }
            ]
        else:
            data = [
                {
                    "id": card_id or 9999,
                    "name": f"Card {card_id}",
                    "rarity": 5,
                    "element": 10,
                    "leader_skill": "All Types Ki +3",
                    "passive_skill_description": "Guards all attacks",
                    "special_descriptions": ["Causes immense damage"],
                }
            ]
        return FakeHTTPResponse(data)

    # 3. Categories
    if "categories" in clean_url:
        return FakeHTTPResponse(FakeDokkanDBClient.SAMPLE_CATEGORIES)

    # 4. Links
    if "links" in clean_url:
        return FakeHTTPResponse(FakeDokkanDBClient.SAMPLE_LINKS)

    # 5. Z-Battles
    if "zbattle-all" in clean_url:
        return FakeHTTPResponse(FakeDokkanDBClient.SAMPLE_ZBATTLES)

    # 6. Events all
    if "events-all" in clean_url:
        return FakeHTTPResponse(FakeDokkanDBClient.SAMPLE_EVENTS)

    # 7. Area tabs
    if "area-tabs" in clean_url:
        return FakeHTTPResponse(
            [
                {"id": 1, "name": "Story", "area_category_ids": [1]},
                {"id": 2, "name": "Growth", "area_category_ids": [2]},
                {"id": 5, "name": "Challenge", "area_category_ids": [20]},
            ]
        )

    # 8. Images / Thumbnails / Assets mirror
    if any(k in clean_url for k in ("supabase.co", "assets/mirror", ".png", "thumb")):
        # Return valid PNG binary payload
        fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 250
        return FakeHTTPResponse([], status_code=200, content=fake_png)

    # Fallback
    return FakeHTTPResponse([])
