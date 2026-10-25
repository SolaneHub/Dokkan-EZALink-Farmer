from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import cv2
import numpy as np
import requests

logger = logging.getLogger(__name__)


DEFAULT_USER_BOX_PATH = os.path.join(
    os.path.expanduser("~"), ".dokkan-farmer", "cache", "user_box.json"
)


class DokkanDBClient:
    """Client for fetching Dokkan Battle event data and banner assets from dokkandb.com."""

    API_BASE_URL = "https://api.dokkandb.com/api"
    API_JP_BASE_URL = "https://api.dokkandb.com/jp/api"
    ASSETS_MIRROR_URL = "https://api.dokkandb.com/assets/mirror"
    ASSETS_FALLBACK_URL = (
        "https://enaskhebnjtktdfszdcb.supabase.co/storage/v1/object/public/assets/mirror"
    )

    DEFAULT_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://dokkandb.com/",
        "Origin": "https://dokkandb.com",
        "Accept": "application/json, image/*, */*",
    }

    def __init__(self, cache_dir: str | None = None, cache_ttl_seconds: int = 43200):
        if cache_dir is None:
            # Default to user home directory to keep application/distribution directory completely clean
            cache_dir = os.path.join(os.path.expanduser("~"), ".dokkan-farmer", "cache")
        self.cache_dir = os.path.abspath(cache_dir)
        self.banners_dir = os.path.join(self.cache_dir, "banners")
        self.cache_ttl_seconds = cache_ttl_seconds

    def _ensure_dirs(self) -> None:
        """Creates cache directories lazily when actually writing files."""
        os.makedirs(self.cache_dir, exist_ok=True)
        os.makedirs(self.banners_dir, exist_ok=True)

    def _get_api_url(self, endpoint: str, region: str = "glb") -> str:
        base = self.API_JP_BASE_URL if region.lower() == "jp" else self.API_BASE_URL
        endpoint = endpoint.lstrip("/")
        return f"{base}/{endpoint}"

    def get_zbattles(
        self, region: str = "glb", active_only: bool = False, force_refresh: bool = False
    ) -> list[dict[str, Any]]:
        """
        Retrieves all Extreme Z-Battles from DokkanDB.
        Uses local cache if available and not expired.
        """
        cache_file = os.path.join(self.cache_dir, f"dokkandb_zbattles_{region.lower()}.json")

        data: list[dict[str, Any]] | None = None
        if not force_refresh and os.path.exists(cache_file):
            try:
                mtime = os.path.getmtime(cache_file)
                if (time.time() - mtime) < self.cache_ttl_seconds:
                    with open(cache_file, encoding="utf-8") as f:
                        data = json.load(f)
            except Exception as e:
                logger.warning(f"Failed reading DokkanDB cache: {e}")

        if data is None:
            url = self._get_api_url("zbattle-all", region=region)
            try:
                resp = requests.get(url, headers=self.DEFAULT_HEADERS, timeout=12)
                resp.raise_for_status()
                data = resp.json()
                self._ensure_dirs()
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"Error fetching Z-Battles from DokkanDB ({url}): {e}")
                if os.path.exists(cache_file):
                    try:
                        with open(cache_file, encoding="utf-8") as f:
                            data = json.load(f)
                    except Exception:
                        pass
        if not data:
            return []

        now = datetime.now(timezone.utc)
        results: list[dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict):
                continue

            active_status = item.get("active")
            is_open = False
            if active_status == "normal":
                is_open = True
            else:
                st_str = item.get("start_at")
                et_str = item.get("end_at")
                if st_str and et_str:
                    try:
                        st = datetime.fromisoformat(st_str.replace("Z", "+00:00"))
                        et = datetime.fromisoformat(et_str.replace("Z", "+00:00"))
                        if st.tzinfo is None:
                            st = st.replace(tzinfo=timezone.utc)
                        if et.tzinfo is None:
                            et = et.replace(tzinfo=timezone.utc)
                        if st <= now <= et:
                            is_open = True
                    except Exception:
                        pass

            item_copy = dict(item)
            item_copy["is_currently_open"] = is_open

            if active_only and not is_open:
                continue

            results.append(item_copy)

        return results

    def get_events(
        self, category: int | None = None, region: str = "glb", force_refresh: bool = False
    ) -> list[dict[str, Any]]:
        """Retrieves general events (Story, Growth, Challenge, etc.) from DokkanDB."""
        cache_file = os.path.join(self.cache_dir, f"dokkandb_events_{region.lower()}.json")

        data: list[dict[str, Any]] | None = None
        if not force_refresh and os.path.exists(cache_file):
            try:
                mtime = os.path.getmtime(cache_file)
                if (time.time() - mtime) < self.cache_ttl_seconds:
                    with open(cache_file, encoding="utf-8") as f:
                        data = json.load(f)
            except Exception:
                pass

        if data is None:
            url = self._get_api_url("events-all", region=region)
            try:
                resp = requests.get(url, headers=self.DEFAULT_HEADERS, timeout=15)
                resp.raise_for_status()
                data = resp.json()
                self._ensure_dirs()
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"Error fetching events from DokkanDB: {e}")
                if os.path.exists(cache_file):
                    try:
                        with open(cache_file, encoding="utf-8") as f:
                            data = json.load(f)
                    except Exception:
                        pass
        if not data:
            return []

        if category is not None:
            return [e for e in data if e.get("category") == category]
        return data

    def download_banner(self, event: dict[str, Any], prefer_button: bool = True) -> str | None:
        """
        Downloads and caches the banner image for an event.
        Returns the absolute local path to the saved PNG image.
        """
        event_id = event.get("id")
        primary_rel = (
            event.get("listbutton_image_path") if prefer_button else event.get("banner_image_path")
        )
        secondary_rel = (
            event.get("banner_image_path") if prefer_button else event.get("listbutton_image_path")
        )

        rel_paths_to_try = [p for p in [primary_rel, secondary_rel] if p]
        if not rel_paths_to_try:
            return None

        for rel_path in rel_paths_to_try:
            clean_rel = rel_path.replace("\\", "/").lstrip("/")
            base_name = os.path.basename(clean_rel)
            # Check for existing legacy cache or modern name
            legacy_filename = f"eza_{event_id}_{base_name}"
            local_filename = f"event_{event_id}_{base_name}"
            legacy_path = os.path.join(self.banners_dir, legacy_filename)
            local_path = os.path.join(self.banners_dir, local_filename)

            if os.path.exists(legacy_path) and os.path.getsize(legacy_path) > 1000:
                return legacy_path
            if os.path.exists(local_path) and os.path.getsize(local_path) > 1000:
                return local_path

            urls_to_try = [
                f"{self.ASSETS_MIRROR_URL}/{clean_rel}",
                f"{self.ASSETS_FALLBACK_URL}/{clean_rel}",
            ]

            for u in urls_to_try:
                try:
                    r = requests.get(u, headers=self.DEFAULT_HEADERS, timeout=10)
                    if r.status_code == 200 and len(r.content) > 1000:
                        self._ensure_dirs()
                        with open(local_path, "wb") as f:
                            f.write(r.content)
                        return local_path
                except Exception as e:
                    logger.debug(f"Failed downloading banner from {u}: {e}")

        return None

    def get_link_level_events(
        self, region: str = "glb", active_only: bool = False
    ) -> list[dict[str, Any]]:
        """
        Retrieves known Link Level farming events from DokkanDB:
        - Ultimate Leveling Up! Chamber of Spirit and Time (Stanza dello Spirito e del Tempo)
        - Study Hard, Play Hard! Turtle School's Intensive Training (Roshi)
        - Astonishing Power-Up! Grand Elder Guru's Guidance (Guru)
        - In Search of Greater Power! God-Level Intensive Training (Whis)
        """
        all_events = self.get_events(region=region)
        now = datetime.now(timezone.utc)

        target_keywords = [
            "chamber of spirit and time",
            "turtle school's intensive training",
            "grand elder guru's guidance",
            "god-level intensive training",
        ]

        results: list[dict[str, Any]] = []
        for ev in all_events:
            name = (ev.get("name") or "").lower()
            if not any(kw in name for kw in target_keywords):
                continue

            active_status = ev.get("active")
            is_open = False
            if active_status == "normal":
                is_open = True
            else:
                st_str = ev.get("start_at")
                et_str = ev.get("end_at")
                if st_str and et_str:
                    try:
                        st = datetime.fromisoformat(st_str.replace("Z", "+00:00"))
                        et = datetime.fromisoformat(et_str.replace("Z", "+00:00"))
                        if st.tzinfo is None:
                            st = st.replace(tzinfo=timezone.utc)
                        if et.tzinfo is None:
                            et = et.replace(tzinfo=timezone.utc)
                        if st <= now <= et:
                            is_open = True
                    except Exception:
                        pass

            item = dict(ev)
            item["is_currently_open"] = is_open

            if active_only and not is_open:
                continue

            # Auto-download listbutton banner
            banner_path = self.download_banner(item, prefer_button=True)
            if banner_path:
                item["banner_local_path"] = banner_path

            results.append(item)

        # Sort: currently open first, then by event_priority or ID descending
        results.sort(key=lambda x: (not x.get("is_currently_open", False), -int(x.get("id", 0))))
        return results

    def get_chamber_of_spirit_and_time(self, region: str = "glb") -> dict[str, Any] | None:
        """
        Finds the 'Chamber of Spirit and Time' (Stanza dello Spirito e del Tempo) event.
        Prioritizes the currently active version.
        """
        events = self.get_link_level_events(region=region, active_only=False)
        spirit_events = [
            e for e in events if "chamber of spirit and time" in (e.get("name") or "").lower()
        ]

        if not spirit_events:
            return None

        # If any is open, return the open one
        for ev in spirit_events:
            if ev.get("is_currently_open"):
                return ev

        # Fallback to the latest event (highest ID)
        return spirit_events[0]

    ELEMENT_NAMES: dict[int, str] = {
        0: "AGL",
        1: "TEQ",
        2: "INT",
        3: "STR",
        4: "PHY",
        10: "Super AGL",
        11: "Super TEQ",
        12: "Super INT",
        13: "Super STR",
        14: "Super PHY",
        20: "Extreme AGL",
        21: "Extreme TEQ",
        22: "Extreme INT",
        23: "Extreme STR",
        24: "Extreme PHY",
    }

    def get_area_tabs(
        self, region: str = "glb", force_refresh: bool = False
    ) -> list[dict[str, Any]]:
        """
        Retrieves the event tabs (Quests, Story, Growth, Bonus, Challenge, Limited, etc.) from DokkanDB.
        """
        cache_file = os.path.join(self.cache_dir, f"dokkandb_area_tabs_{region.lower()}.json")
        data: list[dict[str, Any]] | None = None
        if not force_refresh and os.path.exists(cache_file):
            try:
                mtime = os.path.getmtime(cache_file)
                if (time.time() - mtime) < self.cache_ttl_seconds:
                    with open(cache_file, encoding="utf-8") as f:
                        data = json.load(f)
            except Exception:
                pass

        if data is None:
            url = self._get_api_url("area-tabs", region=region)
            try:
                resp = requests.get(url, headers=self.DEFAULT_HEADERS, timeout=12)
                resp.raise_for_status()
                data = resp.json()
                self._ensure_dirs()
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.warning(f"Error fetching area-tabs from DokkanDB ({url}): {e}")
                if os.path.exists(cache_file):
                    try:
                        with open(cache_file, encoding="utf-8") as f:
                            data = json.load(f)
                    except Exception:
                        pass
        return data or []

    def get_challenge_events(
        self, region: str = "glb", active_only: bool = False, force_refresh: bool = False
    ) -> list[dict[str, Any]]:
        """
        Retrieves challenge category events from DokkanDB (Supreme Magnificent Battle, Red Zone, etc.).
        Challenge events correspond to Tab 5 ("Challenge") on dokkandb.com, mapping to area category ID 20.
        Matches https://www.dokkandb.com/events?category=5&only=true ordering and filtering.
        """
        # Determine challenge category IDs from area-tabs (default to {20} for Tab 5 "Challenge")
        challenge_cats: set[int] = {20}
        try:
            tabs = self.get_area_tabs(region=region, force_refresh=force_refresh)
            for t in tabs:
                if t.get("id") == 5 or (t.get("name") or "").strip().lower() in (
                    "challenge",
                    "挑戦",
                ):
                    raw_cat_ids = t.get("area_category_ids")
                    if isinstance(raw_cat_ids, str):
                        try:
                            parsed = json.loads(raw_cat_ids)
                            if isinstance(parsed, dict) and "area_category_ids" in parsed:
                                challenge_cats.update(parsed["area_category_ids"])
                            elif isinstance(parsed, list):
                                challenge_cats.update(parsed)
                        except Exception:
                            pass
                    elif isinstance(raw_cat_ids, list):
                        challenge_cats.update(raw_cat_ids)
                    elif isinstance(raw_cat_ids, dict) and "area_category_ids" in raw_cat_ids:
                        challenge_cats.update(raw_cat_ids["area_category_ids"])
        except Exception as e:
            logger.debug(f"Could not resolve area-tabs for challenge: {e}")

        all_events = self.get_events(region=region, force_refresh=force_refresh)
        now = datetime.now(timezone.utc)
        results: list[dict[str, Any]] = []

        for ev in all_events:
            cat = ev.get("category")
            if cat not in challenge_cats:
                continue

            banner_path = (ev.get("banner_image_path") or "").replace("\\", "/")
            if "dummy_image.png" in banner_path:
                continue

            active_status = ev.get("active")
            is_portal = active_status == "portal"
            is_open = False
            if active_status == "normal" or is_portal:
                is_open = True

            st_str = ev.get("start_at")
            et_str = ev.get("end_at")
            if st_str and et_str:
                try:
                    st = datetime.fromisoformat(st_str.replace("Z", "+00:00"))
                    et = datetime.fromisoformat(et_str.replace("Z", "+00:00"))
                    if st.tzinfo is None:
                        st = st.replace(tzinfo=timezone.utc)
                    if et.tzinfo is None:
                        et = et.replace(tzinfo=timezone.utc)
                    if st <= now <= et:
                        is_open = True
                    elif et < now and active_status not in ("normal", "portal"):
                        is_open = False
                except Exception:
                    pass

            item = dict(ev)
            item["is_currently_open"] = is_open

            if active_only and not is_open:
                continue

            results.append(item)

        # Sort identical to dokkandb.com tab 5:
        # 1. Closed events last (if active_only=False)
        # 2. Portal events after normal active events
        # 3. event_priority descending (matches in-game banner order)
        # 4. announcement_id descending
        # 5. id descending
        results.sort(
            key=lambda x: (
                not x.get("is_currently_open", False),
                1 if x.get("active") == "portal" else 0,
                -int(x.get("event_priority") or 0),
                -int(x.get("announcement_id") or 0),
                -int(x.get("id") or 0),
            )
        )
        return results

    def get_event_details(
        self, event_id: int, region: str = "glb", force_refresh: bool = False
    ) -> dict[str, Any] | None:
        """
        Retrieves full event details from DokkanDB, including all quests, stages, and mission categories.
        Endpoint: /api/event-details?code={event_id}&search_term=
        """
        cache_file = os.path.join(
            self.cache_dir, f"dokkandb_event_details_{event_id}_{region.lower()}.json"
        )
        if not force_refresh and os.path.exists(cache_file):
            try:
                mtime = os.path.getmtime(cache_file)
                if (time.time() - mtime) < self.cache_ttl_seconds:
                    with open(cache_file, encoding="utf-8") as f:
                        return json.load(f)
            except Exception as e:
                logger.warning(f"Failed reading event-details cache: {e}")

        url = f"{self._get_api_url('event-details', region=region)}?code={event_id}"
        try:
            resp = requests.get(url, headers=self.DEFAULT_HEADERS, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list) and data:
                detail = data[0]
                self._ensure_dirs()
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(detail, f, ensure_ascii=False, indent=2)
                return detail
        except Exception as e:
            logger.error(f"Error fetching event details for {event_id} from DokkanDB ({url}): {e}")
            if os.path.exists(cache_file):
                try:
                    with open(cache_file, encoding="utf-8") as f:
                        return json.load(f)
                except Exception:
                    pass
        return None

    def get_cards_by_ids(
        self, card_ids: list[int], region: str = "glb", force_refresh: bool = False
    ) -> list[dict[str, Any]]:
        """
        Batch retrieves card summary metadata by IDs.
        Endpoint: /api/cards-by-ids?ids={id1,id2,...}
        """
        if not card_ids:
            return []
        ids_str = ",".join(str(cid) for cid in card_ids if cid)
        cache_file = os.path.join(
            self.cache_dir, f"dokkandb_cards_by_ids_{abs(hash(ids_str))}_{region.lower()}.json"
        )
        if not force_refresh and os.path.exists(cache_file):
            try:
                mtime = os.path.getmtime(cache_file)
                if (time.time() - mtime) < self.cache_ttl_seconds:
                    with open(cache_file, encoding="utf-8") as f:
                        return json.load(f)
            except Exception:
                pass

        url = f"{self._get_api_url('cards-by-ids', region=region)}?ids={ids_str}"
        try:
            resp = requests.get(url, headers=self.DEFAULT_HEADERS, timeout=12)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                self._ensure_dirs()
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                return data
        except Exception as e:
            logger.error(f"Error fetching cards-by-ids from DokkanDB ({url}): {e}")
        return []

    def get_enemy_skills_by_ids(
        self, skill_ids: list[int], region: str = "glb", force_refresh: bool = False
    ) -> list[dict[str, Any]]:
        """
        Batch retrieves enemy skills, immunities, and damage reduction mechanics.
        Endpoint: /api/enemy-skills-by-ids?ids={id1,id2,...}
        """
        if not skill_ids:
            return []
        ids_str = ",".join(str(sid) for sid in skill_ids if sid)
        cache_file = os.path.join(
            self.cache_dir, f"dokkandb_enemy_skills_{abs(hash(ids_str))}_{region.lower()}.json"
        )
        if not force_refresh and os.path.exists(cache_file):
            try:
                mtime = os.path.getmtime(cache_file)
                if (time.time() - mtime) < self.cache_ttl_seconds:
                    with open(cache_file, encoding="utf-8") as f:
                        return json.load(f)
            except Exception:
                pass

        url = f"{self._get_api_url('enemy-skills-by-ids', region=region)}?ids={ids_str}"
        try:
            resp = requests.get(url, headers=self.DEFAULT_HEADERS, timeout=12)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                self._ensure_dirs()
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                return data
        except Exception as e:
            logger.error(f"Error fetching enemy-skills-by-ids from DokkanDB ({url}): {e}")
        return []

    def get_stage_boss_info(
        self, event_id: int, stage_id: int, region: str = "glb", force_refresh: bool = False
    ) -> dict[str, Any] | None:
        """
        Retrieves and parses complete stage boss statistics, phases, typing, and special mechanics.
        Endpoint: /api/event-stats?code={event_id}&code2={stage_id}
        """
        cache_file = os.path.join(
            self.cache_dir, f"dokkandb_stage_stats_{stage_id}_{region.lower()}.json"
        )
        data: list[dict[str, Any]] | None = None
        if not force_refresh and os.path.exists(cache_file):
            try:
                mtime = os.path.getmtime(cache_file)
                if (time.time() - mtime) < self.cache_ttl_seconds:
                    with open(cache_file, encoding="utf-8") as f:
                        data = json.load(f)
            except Exception:
                pass

        if data is None:
            url = f"{self._get_api_url('event-stats', region=region)}?code={event_id}&code2={stage_id}"
            try:
                resp = requests.get(url, headers=self.DEFAULT_HEADERS, timeout=15)
                resp.raise_for_status()
                data = resp.json()
                self._ensure_dirs()
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"Error fetching stage stats ({url}): {e}")
                if os.path.exists(cache_file):
                    try:
                        with open(cache_file, encoding="utf-8") as f:
                            data = json.load(f)
                    except Exception:
                        pass

        if not data or not isinstance(data, list) or not data[0]:
            return None

        stage_data = data[0]
        enemy_info_raw = stage_data.get("enemy_info")
        if not enemy_info_raw:
            return None

        if isinstance(enemy_info_raw, str):
            try:
                enemy_info = json.loads(enemy_info_raw)
            except Exception:
                return None
        else:
            enemy_info = enemy_info_raw

        # 1. Parse battles and rounds from sugoroku events (type 301) or fallback to enemy_info
        payload = stage_data.get("payload", {})
        sug = payload.get("sugoroku", {}) if isinstance(payload, dict) else {}
        events = sug.get("events", {}) if isinstance(sug, dict) else {}

        battle_events = []
        if isinstance(events, dict):
            for k in sorted(events.keys(), key=lambda x: int(x) if x.isdigit() else 0):
                ev = events[k]
                if isinstance(ev, dict) and ev.get("type") == 301:
                    battle_events.append(ev)

        parsed_battles: list[dict[str, Any]] = []
        if battle_events:
            for b_idx, b_ev in enumerate(battle_events, start=1):
                rounds_list = b_ev.get("content", {}).get("enemies", [])
                rounds_data_b = []
                for r_idx, r_enemies in enumerate(rounds_list, start=1):
                    rounds_data_b.append(
                        {
                            "round_no": r_idx,
                            "enemies": r_enemies if isinstance(r_enemies, list) else [r_enemies],
                        }
                    )
                parsed_battles.append({"battle_no": b_idx, "rounds": rounds_data_b})
        else:
            enemy_info_raw = stage_data.get("enemy_info")
            enemy_info = {}
            if isinstance(enemy_info_raw, str):
                try:
                    enemy_info = json.loads(enemy_info_raw)
                except Exception:
                    enemy_info = {}
            elif isinstance(enemy_info_raw, dict):
                enemy_info = enemy_info_raw

            for b_idx, b in enumerate(enemy_info.get("battles", []), start=1):
                parsed_battles.append(
                    {
                        "battle_no": b_idx,
                        "rounds": [
                            {
                                "round_no": int(r.get("round_no", idx)),
                                "enemies": r.get("enemies", []),
                            }
                            for idx, r in enumerate(b.get("rounds", []), start=1)
                        ],
                    }
                )

        if not parsed_battles:
            return None

        all_card_ids: set[int] = set()
        all_skill_ids: set[int] = set()
        for b in parsed_battles:
            for r in b.get("rounds", []):
                for en in r.get("enemies", []):
                    cid = int(en.get("card_id") or 0)
                    sids = [int(s) for s in en.get("enemy_skill_ids", []) if s is not None]
                    if cid:
                        all_card_ids.add(cid)
                    for sid in sids:
                        all_skill_ids.add(sid)

        # Batch resolve cards and skills
        cards_list = self.get_cards_by_ids(list(all_card_ids), region=region)
        cards_map = {c.get("id"): c for c in cards_list if isinstance(c, dict) and "id" in c}

        # Enrich boss cards with categories if not present
        from dokkan_eza_link_farmer.ai.models import infer_boss_categories_from_name

        for cid in all_card_ids:
            card = cards_map.get(cid)
            if card and not card.get("category_names") and not card.get("categories"):
                try:
                    full_card = self.get_card(cid, region=region)
                    if full_card and isinstance(full_card, dict):
                        card["category_names"] = full_card.get("category_names") or []
                        card["category_ids"] = full_card.get("category_ids") or []
                        card["categories"] = full_card.get("category_names") or []
                except Exception:
                    pass

        skills_list = self.get_enemy_skills_by_ids(list(all_skill_ids), region=region)
        skills_map = {s.get("id"): s for s in skills_list if isinstance(s, dict) and "id" in s}

        summary: dict[str, Any] = {
            "event_id": event_id,
            "stage_id": stage_id,
            "event_name": stage_data.get("name", "Unknown Event"),
            "stage_name": stage_data.get("quest_name", "Unknown Stage"),
            "difficulty": stage_data.get("difficulty", 1),
            "total_battles": len(parsed_battles) if parsed_battles else 1,
            "is_multi_battle": len(parsed_battles) > 1,
            "phases": [],
        }

        total_phase_index = 0
        for b in parsed_battles:
            b_no = b["battle_no"]
            for r in b["rounds"]:
                total_phase_index += 1
                r_no = r["round_no"]
                is_new_battle = r_no == 1
                phase_hp = 0
                phase_atk = 0
                phase_def = 0
                phase_actions = 0
                bosses = []

                for en in r["enemies"]:
                    cid = int(en.get("card_id") or 0)
                    card = cards_map.get(cid, {})
                    skills = [skills_map.get(sid, {}) for sid in en.get("enemy_skill_ids", [])]
                    elem = int(card.get("element") or 0)

                    e_hp = int(en.get("hp") or 0)
                    e_atk = int(en.get("attack") or 0)
                    e_def = int(en.get("defence") or 0)
                    e_actions = int(en.get("multi_atk_num") or 0)

                    phase_hp += e_hp
                    phase_atk = max(phase_atk, e_atk)
                    phase_def = max(phase_def, e_def)
                    phase_actions += max(1, e_actions)

                    b_cats = card.get("category_names") or card.get("categories") or []
                    if not b_cats:
                        b_cats = infer_boss_categories_from_name(card.get("name", ""))
                    b_class = "Extreme" if elem >= 20 else ("Super" if elem >= 10 else "")

                    bosses.append(
                        {
                            "name": card.get("name", "Unknown Boss"),
                            "subname": card.get("subname", ""),
                            "card_id": cid,
                            "element": elem,
                            "type_name": self.ELEMENT_NAMES.get(elem, f"Type {elem}"),
                            "hp": e_hp,
                            "atk": e_atk,
                            "defence": e_def,
                            "def_stat": e_def,
                            "multi_atk_num": e_actions,
                            "actions_per_turn": max(1, e_actions),
                            "categories": b_cats,
                            "category_ids": card.get("category_ids") or [],
                            "card_class": b_class,
                            "mechanics": [
                                {
                                    "id": s.get("id"),
                                    "name": s.get("name"),
                                    "description": s.get("description") or s.get("effect", ""),
                                }
                                for s in skills
                                if s.get("name")
                            ],
                        }
                    )

                if len(bosses) > 1:
                    is_rainbow_phase = {b["element"] % 10 for b in bosses} >= {0, 1, 2, 3, 4}
                    if is_rainbow_phase:
                        phase_element_name = f"Rainbow ({len(bosses)} Enemies: All 5 Types)"
                    else:
                        phase_element_name = f"Multi-Type ({len(bosses)} Enemies)"
                elif bosses:
                    phase_element_name = bosses[0]["type_name"]
                else:
                    phase_element_name = ""

                phase_entry: dict[str, Any] = {
                    "phase_index": total_phase_index,
                    "phase": total_phase_index,
                    "battle_index": b_no,
                    "round_index": r_no,
                    "is_new_battle": is_new_battle,
                    "element": bosses[0]["element"] if bosses else 0,
                    "element_name": phase_element_name,
                    "hp": phase_hp,
                    "atk": phase_atk,
                    "def_stat": phase_def,
                    "actions_per_turn": phase_actions,
                    "estimated_sa_damage": int(phase_atk * 2.5) if phase_atk > 0 else 0,
                    "bosses": bosses,
                }
                summary["phases"].append(phase_entry)

        return summary

    def get_event_missions(
        self, event_id: int, region: str = "glb", force_refresh: bool = False
    ) -> list[dict[str, Any]]:
        """
        Retrieves all missions and reward conditions associated with an event.
        """
        detail = self.get_event_details(event_id, region=region, force_refresh=force_refresh)
        if not detail:
            return []

        missions: list[dict[str, Any]] = []
        for cat in detail.get("mission_categories", []):
            if not isinstance(cat, dict):
                continue
            for m in cat.get("missions", []):
                if isinstance(m, dict):
                    missions.append(m)

        return missions

    def load_banner_template(self, banner_path: str) -> np.ndarray | None:
        """Loads a banner image from disk as a BGR numpy array."""
        if not os.path.exists(banner_path):
            return None
        img = cv2.imread(banner_path, cv2.IMREAD_UNCHANGED)
        if img is None:
            return None
        if len(img.shape) == 3 and img.shape[2] == 4:
            return img[:, :, :3]
        return img

    def get_categories(
        self, region: str = "glb", force_refresh: bool = False
    ) -> list[dict[str, Any]]:
        """Retrieves all card categories from DokkanDB."""
        cache_file = os.path.join(self.cache_dir, f"dokkandb_categories_{region.lower()}.json")
        if not force_refresh and os.path.exists(cache_file):
            try:
                mtime = os.path.getmtime(cache_file)
                if (time.time() - mtime) < self.cache_ttl_seconds:
                    with open(cache_file, encoding="utf-8") as f:
                        return json.load(f)
            except Exception as e:
                logger.warning(f"Failed reading DokkanDB categories cache: {e}")

        url = self._get_api_url("categories", region=region)
        try:
            resp = requests.get(url, headers=self.DEFAULT_HEADERS, timeout=12)
            resp.raise_for_status()
            data = resp.json()
            self._ensure_dirs()
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return data
        except Exception as e:
            logger.error(f"Error fetching categories from DokkanDB ({url}): {e}")
            if os.path.exists(cache_file):
                with open(cache_file, encoding="utf-8") as f:
                    return json.load(f)
            return []

    def get_links(self, region: str = "glb", force_refresh: bool = False) -> list[dict[str, Any]]:
        """Retrieves all link skills from DokkanDB."""
        cache_file = os.path.join(self.cache_dir, f"dokkandb_links_{region.lower()}.json")
        if not force_refresh and os.path.exists(cache_file):
            try:
                mtime = os.path.getmtime(cache_file)
                if (time.time() - mtime) < self.cache_ttl_seconds:
                    with open(cache_file, encoding="utf-8") as f:
                        return json.load(f)
            except Exception as e:
                logger.warning(f"Failed reading DokkanDB links cache: {e}")

        url = self._get_api_url("links", region=region)
        try:
            resp = requests.get(url, headers=self.DEFAULT_HEADERS, timeout=12)
            resp.raise_for_status()
            data = resp.json()
            self._ensure_dirs()
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return data
        except Exception as e:
            logger.error(f"Error fetching links from DokkanDB ({url}): {e}")
            if os.path.exists(cache_file):
                with open(cache_file, encoding="utf-8") as f:
                    return json.load(f)
            return []

    def get_category_leaders(
        self, category_id: int, region: str = "glb", force_refresh: bool = False
    ) -> list[dict[str, Any]]:
        """Retrieves leaders for a specific category from DokkanDB."""
        cache_file = os.path.join(
            self.cache_dir, f"dokkandb_category_leaders_{category_id}_{region.lower()}.json"
        )
        if not force_refresh and os.path.exists(cache_file):
            try:
                mtime = os.path.getmtime(cache_file)
                if (time.time() - mtime) < self.cache_ttl_seconds:
                    with open(cache_file, encoding="utf-8") as f:
                        return json.load(f)
            except Exception as e:
                logger.warning(f"Failed reading DokkanDB category leaders cache: {e}")

        url = self._get_api_url(f"category-leaders?code={category_id}", region=region)
        try:
            resp = requests.get(url, headers=self.DEFAULT_HEADERS, timeout=12)
            resp.raise_for_status()
            data = resp.json()
            self._ensure_dirs()
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return data
        except Exception as e:
            logger.error(f"Error fetching category leaders from DokkanDB ({url}): {e}")
            if os.path.exists(cache_file):
                with open(cache_file, encoding="utf-8") as f:
                    return json.load(f)
            return []

    def parse_category_leader(self, item: dict[str, Any], category_id: int) -> dict[str, Any]:
        """Parses leader skill efficacy and stat boosts for a specific category from a category leader item."""
        card_id = int(item.get("id", 0))
        name = str(item.get("name", ""))

        base_boost = 0.0
        extra_boost = 0.0
        hp_stat = 0.0
        ki = 0
        is_main = False
        is_extra = False

        leader_skills = item.get("leader_skills", []) or []
        for ls in leader_skills:
            if not isinstance(ls, dict):
                continue
            sub_targets = ls.get("sub_target_types", []) or []
            cat_match = any(
                isinstance(st, dict) and int(st.get("target_value", -1)) == int(category_id)
                for st in sub_targets
            )
            if not cat_match:
                continue

            eff_type = ls.get("efficacy_type")
            eff_vals_raw = ls.get("efficacy_values")
            parsed: list[Any] = []
            if isinstance(eff_vals_raw, str):
                try:
                    parsed = json.loads(eff_vals_raw)
                    if isinstance(parsed, str):
                        parsed = json.loads(parsed)
                except Exception:
                    parsed = []
            elif isinstance(eff_vals_raw, list):
                parsed = eff_vals_raw

            if not isinstance(parsed, list) or not parsed:
                continue

            try:
                if eff_type == 82:
                    if len(parsed) >= 2:
                        flag = int(parsed[0])
                        val = float(parsed[1])
                        if flag == 31:
                            base_boost = max(base_boost, val)
                            hp_stat = max(hp_stat, val)
                            is_main = True
                        elif flag == 64:
                            extra_boost = max(extra_boost, val)
                            is_extra = True
                elif eff_type == 104:
                    if len(parsed) >= 2:
                        hp_val = float(parsed[0])
                        atk_def_val = float(parsed[1])
                        base_boost = max(base_boost, atk_def_val)
                        hp_stat = max(hp_stat, hp_val)
                        is_main = True
                elif eff_type in (5, 83):
                    if eff_type == 5 and len(parsed) >= 1:
                        ki = max(ki, int(parsed[0]))
                    elif eff_type == 83 and len(parsed) >= 2:
                        ki = max(ki, int(parsed[1]))
            except (ValueError, TypeError):
                continue

        return {
            "card_id": card_id,
            "name": name,
            "base_boost_pct": float(base_boost),
            "extra_boost_pct": float(extra_boost),
            "total_boost_pct": float(base_boost + extra_boost),
            "hp_stat_pct": float(hp_stat),
            "ki": int(ki),
            "is_main_leader": bool(is_main),
            "is_extra_leader": bool(is_extra),
        }

    def get_category_leaders_map(
        self, category_id: int, region: str = "glb"
    ) -> dict[int, dict[str, Any]]:
        """Retrieves leaders for a category as a card_id-indexed dictionary with parsed leader stats."""
        raw_leaders = self.get_category_leaders(category_id, region=region)
        result: dict[int, dict[str, Any]] = {}
        for item in raw_leaders:
            if isinstance(item, dict) and "id" in item:
                parsed = self.parse_category_leader(item, category_id)
                cid = parsed["card_id"]
                if cid > 0:
                    result[cid] = parsed
        return result

    def get_leader_200_catalog(
        self, region: str = "glb", force_refresh: bool = False
    ) -> list[dict[str, Any]]:
        """Retrieves the 200% leader skill catalog from DokkanDB."""
        cache_file = os.path.join(self.cache_dir, f"dokkandb_leader_200_{region.lower()}.json")
        if not force_refresh and os.path.exists(cache_file):
            try:
                mtime = os.path.getmtime(cache_file)
                if (time.time() - mtime) < self.cache_ttl_seconds:
                    with open(cache_file, encoding="utf-8") as f:
                        return json.load(f)
            except Exception as e:
                logger.warning(f"Failed reading DokkanDB leader 200 catalog cache: {e}")

        url = self._get_api_url("leader-200-catalog", region=region)
        try:
            resp = requests.get(url, headers=self.DEFAULT_HEADERS, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            self._ensure_dirs()
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return data
        except Exception as e:
            logger.error(f"Error fetching leader 200 catalog from DokkanDB: {e}")
            if os.path.exists(cache_file):
                with open(cache_file, encoding="utf-8") as f:
                    return json.load(f)
            return []

    def get_cards_catalog(
        self, region: str = "glb", force_refresh: bool = False
    ) -> list[dict[str, Any]]:
        """Retrieves the full card catalog with transformations from DokkanDB (chunks 1 & 2)."""
        unified_catalog = os.path.join(self.cache_dir, "dokkandb_catalog.json")
        if not force_refresh and os.path.exists(unified_catalog):
            try:
                with open(unified_catalog, encoding="utf-8") as f:
                    u_data = json.load(f)
                    if isinstance(u_data, list) and len(u_data) >= 800:
                        return u_data
            except Exception as e:
                logger.debug(f"Reading unified catalog failed: {e}")

        cache_file = os.path.join(self.cache_dir, f"dokkandb_cards_catalog_{region.lower()}.json")
        if not force_refresh and os.path.exists(cache_file):
            try:
                mtime = os.path.getmtime(cache_file)
                if (time.time() - mtime) < self.cache_ttl_seconds:
                    with open(cache_file, encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, list) and len(data) >= 800:
                            return data
            except Exception as e:
                logger.warning(f"Failed reading DokkanDB cards catalog cache: {e}")

        base_url = self._get_api_url("cards-catalog-with-transformations", region=region)
        combined: list[dict[str, Any]] = []
        for chunk in [1, 2]:
            url = f"{base_url}?chunk={chunk}"
            try:
                resp = requests.get(url, headers=self.DEFAULT_HEADERS, timeout=25)
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, list):
                    combined.extend(data)
            except Exception as e:
                logger.warning(f"Error fetching catalog chunk {chunk} from {url}: {e}")

        if combined:
            self._ensure_dirs()
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(combined, f, ensure_ascii=False, indent=2)
            return combined

        if os.path.exists(cache_file):
            try:
                with open(cache_file, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    def get_card(
        self, card_id: int, region: str = "glb", force_refresh: bool = False
    ) -> dict[str, Any] | None:
        """Retrieves detailed card data (passives, supers, links, categories) by ID/code."""
        cards_dir = os.path.join(self.cache_dir, "cards")
        os.makedirs(cards_dir, exist_ok=True)
        cache_file = os.path.join(cards_dir, f"card_{card_id}_{region.lower()}.json")

        if not force_refresh and os.path.exists(cache_file):
            try:
                mtime = os.path.getmtime(cache_file)
                if (time.time() - mtime) < self.cache_ttl_seconds:
                    with open(cache_file, encoding="utf-8") as f:
                        return json.load(f)
            except Exception as e:
                logger.warning(f"Failed reading cached card {card_id}: {e}")

        url = f"{self._get_api_url('card', region=region)}?code={card_id}"
        for attempt in range(4):
            try:
                resp = requests.get(url, headers=self.DEFAULT_HEADERS, timeout=10)
                if resp.status_code == 429:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                resp.raise_for_status()
                data = resp.json()
                card_info = (
                    data[0]
                    if isinstance(data, list) and data
                    else (data if isinstance(data, dict) else None)
                )
                if card_info:
                    with open(cache_file, "w", encoding="utf-8") as f:
                        json.dump(card_info, f, ensure_ascii=False, indent=2)
                return card_info
            except Exception as e:
                if attempt == 3:
                    logger.error(f"Error fetching card {card_id} from DokkanDB: {e}")
                time.sleep(0.5)

        if os.path.exists(cache_file):
            with open(cache_file, encoding="utf-8") as f:
                return json.load(f)
        return None

    def search_cards(
        self, query: str, region: str = "glb", limit: int = 20
    ) -> list[dict[str, Any]]:
        """Searches cards by name, subname, or ID from the catalog."""
        catalog = self.get_cards_catalog(region=region)
        q = query.strip().lower()
        results: list[dict[str, Any]] = []
        for card in catalog:
            name = (card.get("name") or "").lower()
            subname = (card.get("subname") or "").lower()
            card_id_str = str(card.get("id") or "")
            if q in name or q in subname or q == card_id_str:
                results.append(card)
                if len(results) >= limit:
                    break
        return results

    def get_user_box_card_ids(self) -> list[int]:
        """
        Loads player-owned card IDs from config/box.json or box.json if available.
        Format can be [1025551, 1028731] or [{"id": 1025551}, ...].
        """
        candidate_paths = [
            DEFAULT_USER_BOX_PATH,
            os.path.join(self.cache_dir, "user_box.json"),
            "config/box.json",
            "config/my_box.json",
            "box.json",
            os.path.join(self.cache_dir, "box.json"),
        ]
        for p in candidate_paths:
            if os.path.exists(p):
                try:
                    with open(p, encoding="utf-8") as f:
                        data = json.load(f)
                    ids: list[int] = []
                    if isinstance(data, list):
                        for item in data:
                            if isinstance(item, int):
                                ids.append(item)
                            elif isinstance(item, str) and item.isdigit():
                                ids.append(int(item))
                            elif isinstance(item, dict) and "id" in item:
                                ids.append(int(item["id"]))
                    elif (
                        isinstance(data, dict)
                        and "cards" in data
                        and isinstance(data["cards"], list)
                    ):
                        for item in data["cards"]:
                            if isinstance(item, int):
                                ids.append(item)
                            elif isinstance(item, str) and item.isdigit():
                                ids.append(int(item))
                            elif isinstance(item, dict) and "id" in item:
                                ids.append(int(item["id"]))
                    if ids:
                        return ids
                except Exception as e:
                    logger.warning(f"Error reading user box file {p}: {e}")
        return []

    def get_challenge_missions(
        self,
        event_name: str | int,
        region: str = "glb",
        force_refresh: bool = False,
        stage_num: int | None = None,
        event_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieves and filters missions associated with a challenge event from DokkanDB."""
        import re

        if isinstance(event_name, int) and not event_id:
            event_id = event_name
            event_name = str(event_name)
        elif not isinstance(event_name, str):
            event_name = str(event_name or "")

        # Try to resolve event_id by name if not provided
        if not event_id and event_name:
            ev_clean = event_name.strip().lower()
            try:
                for ev in self.get_events(region=region):
                    title = (ev.get("name") or "").strip().lower()
                    if ev_clean == title or ev_clean in title or title in ev_clean:
                        event_id = ev.get("id")
                        break
            except Exception:
                pass

        # 1. Direct event missions if event_id is available
        if event_id:
            direct = self.get_event_missions(event_id, region=region, force_refresh=force_refresh)
            if direct:
                if stage_num is not None and stage_num > 0:
                    stage_matched = []
                    for m in direct:
                        desc = (m.get("description") or "") + " " + (m.get("name") or "")
                        st_found = [
                            int(s) for s in re.findall(r"\bstage\s*(\d+)\b", desc, re.IGNORECASE)
                        ]
                        if not st_found or stage_num in st_found:
                            stage_matched.append(m)
                    return stage_matched
                return direct

        cache_file = os.path.join(
            self.cache_dir, f"dokkandb_missions_challenge_{region.lower()}.json"
        )
        data: list[dict[str, Any]] | None = None
        if not force_refresh and os.path.exists(cache_file):
            try:
                mtime = os.path.getmtime(cache_file)
                if (time.time() - mtime) < self.cache_ttl_seconds:
                    with open(cache_file, encoding="utf-8") as f:
                        data = json.load(f)
            except Exception as e:
                logger.warning(f"Failed reading DokkanDB missions cache: {e}")

        if data is None:
            url = f"{self._get_api_url('missions-catalog-filtered', region=region)}?p_category=3"
            try:
                resp = requests.get(url, headers=self.DEFAULT_HEADERS, timeout=20)
                if resp.status_code == 200:
                    data = resp.json()
                    self._ensure_dirs()
                    with open(cache_file, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                else:
                    logger.warning(f"DokkanDB missions-catalog returned status {resp.status_code}")
            except Exception as e:
                logger.warning(f"Error fetching challenge missions from DokkanDB: {e}")
                if os.path.exists(cache_file):
                    try:
                        with open(cache_file, encoding="utf-8") as f:
                            data = json.load(f)
                    except Exception:
                        pass
                else:
                    return []

        if not data:
            return []

        # Extract base name and optional edition (e.g. "Universe Survival Saga" from "[Universe Survival Saga]")
        bracket_match = re.search(r"\[(.*?)\]", event_name)
        edition_keyword = bracket_match.group(1).strip().lower() if bracket_match else ""
        clean_name = event_name.split("[")[0].replace("RE", "").strip().lower()

        # Collect all missions
        all_missions: list[dict[str, Any]] = []
        seen_all_ids: set[int] = set()
        for group in data:
            if not isinstance(group, dict):
                continue
            for m in group.get("missions", []):
                m_id = m.get("id")
                if m_id and m_id not in seen_all_ids:
                    seen_all_ids.add(m_id)
                    all_missions.append(m)

        matched: list[dict[str, Any]] = []
        if edition_keyword:
            for m in all_missions:
                desc = (m.get("description") or "").lower()
                name = (m.get("name") or "").lower()
                if edition_keyword in desc or edition_keyword in name:
                    matched.append(m)

        # Fallback to matching base name if no edition or if edition query yielded 0
        if not matched:
            for m in all_missions:
                desc = (m.get("description") or "").lower()
                name = (m.get("name") or "").lower()
                if clean_name and (clean_name in desc or clean_name in name):
                    matched.append(m)

        if stage_num is not None and stage_num > 0:
            stage_matched = []
            for m in matched:
                desc = (m.get("description") or "") + " " + (m.get("name") or "")
                st_found = [int(s) for s in re.findall(r"\bstage\s*(\d+)\b", desc, re.IGNORECASE)]
                if not st_found or stage_num in st_found:
                    stage_matched.append(m)
            return stage_matched

        return matched

    def get_best_linking_partners(
        self,
        card_id: int,
        pool_card_ids: list[int] | None = None,
        top_n: int = 5,
        region: str = "glb",
    ) -> list[dict[str, Any]]:
        """
        Finds the best linking partners for a given card ID.
        If pool_card_ids is provided, restricts partners to cards owned in that pool (e.g. player's box).
        Returns partners sorted by shared links count descending, then shared categories count descending.
        """
        catalog = self.get_cards_catalog(region=region)
        card = next((c for c in catalog if c.get("id") == card_id), None)
        if not card:
            full_card = self.get_card(card_id, region=region)
            if not full_card:
                return []
            card = full_card

        card_links = set(card.get("link_ids") or []) - {None}
        if not card_links:
            return []
        card_cats = set(card.get("category_ids") or [])

        links_meta = self.get_links(region=region)
        link_name_map = {
            link_item["id"]: link_item["name"]
            for link_item in links_meta
            if isinstance(link_item, dict) and "id" in link_item and "name" in link_item
        }

        candidates = catalog
        if pool_card_ids:
            pool_set = set(pool_card_ids)
            candidates = [c for c in catalog if c.get("id") in pool_set]

        partners: list[dict[str, Any]] = []
        for other in candidates:
            o_id = other.get("id")
            if not o_id or o_id == card_id:
                continue
            o_links = set(other.get("link_ids") or []) - {None}
            shared_links = card_links & o_links
            if not shared_links:
                continue
            o_cats = set(other.get("category_ids") or [])
            shared_cats = card_cats & o_cats

            shared_link_names = [link_name_map.get(lid, f"Link_{lid}") for lid in shared_links]
            partners.append(
                {
                    "card_id": o_id,
                    "name": other.get("name"),
                    "subname": other.get("subname"),
                    "shared_links_count": len(shared_links),
                    "shared_links": shared_link_names,
                    "shared_categories_count": len(shared_cats),
                }
            )

        partners.sort(
            key=lambda x: (x["shared_links_count"], x["shared_categories_count"]), reverse=True
        )
        return partners[:top_n]

    def enrich_card(
        self,
        card: dict[str, Any],
        region: str = "glb",
    ) -> dict[str, Any]:
        """
        Enriches a card dictionary with full DokkanDB data:
        link skill names, category names, passive skill, and leader skill.
        """
        cid = int(card.get("id") or 0)
        if not cid:
            return card

        card_data = self.get_card(cid, region=region)
        if not card_data:
            return card

        enriched = dict(card)
        if "name" not in enriched or not enriched["name"] or enriched["name"] == "Unknown":
            enriched["name"] = card_data.get("name")
        if "subname" not in enriched or not enriched["subname"]:
            enriched["subname"] = card_data.get("subname")
        if "rarity" not in enriched:
            enriched["rarity"] = card_data.get("rarity")
        if "element" not in enriched:
            enriched["element"] = card_data.get("element")

        # Links
        links_meta = self.get_links(region=region)
        link_name_map = {
            link_item["id"]: link_item["name"]
            for link_item in links_meta
            if isinstance(link_item, dict) and "id" in link_item and "name" in link_item
        }
        raw_link_ids = card_data.get("link_ids") or []
        enriched["link_ids"] = [lid for lid in raw_link_ids if lid is not None]
        enriched["links"] = [link_name_map.get(lid, f"Link_{lid}") for lid in enriched["link_ids"]]

        # Categories
        cat_names = card_data.get("category_names") or []
        enriched["categories"] = [c for c in cat_names if c]
        raw_cat_ids = card_data.get("category_ids") or []
        enriched["category_ids"] = [c for c in raw_cat_ids if c is not None]

        # Leader skill (EZA version preferred if available)
        leader = card_data.get("eza_leader_skill") or card_data.get("leader_skill")
        if leader:
            enriched["leader_skill"] = leader

        # Passive skill (EZA version preferred if available)
        passive = card_data.get("eza_passive_skill_description") or card_data.get(
            "passive_skill_description"
        )
        if passive:
            enriched["passive_skill"] = passive

        # Transformations & forms (standby, active skill, transforms)
        if "transformations" not in enriched:
            trans_list: list[dict[str, Any]] = []
            trans_data = card_data.get("transformation_data")
            if isinstance(trans_data, list) and trans_data:
                for idx, trans in enumerate(trans_data, start=1):
                    if isinstance(trans, dict):
                        trans_list.append(
                            {
                                "form_id": int(trans.get("id") or 0),
                                "form_index": idx,
                                "form_name": str(trans.get("name") or f"Transform_{idx}"),
                                "element": int(trans.get("element") or card_data.get("element", 0)),
                                "links": [
                                    str(trans.get(f"link_skill_name_{i}"))
                                    for i in range(1, 8)
                                    if trans.get(f"link_skill_name_{i}")
                                ],
                                "link_ids": [
                                    int(lid)
                                    for lid in (trans.get("link_ids") or [])
                                    if lid is not None
                                ],
                                "passive_skill_text": trans.get("passive_skill_description") or "",
                                "super_attack_text": " | ".join(
                                    str(s) for s in (trans.get("special_descriptions") or []) if s
                                ),
                                "min_turn": int(trans.get("min_turn", idx + 2)),
                            }
                        )
            elif card_data.get("transformation_names") or card_data.get("transformation_ids"):
                t_names = card_data.get("transformation_names") or []
                t_ids = card_data.get("transformation_ids") or []
                t_elems = card_data.get("transformation_elements") or []
                count = max(len(t_names), len(t_ids))
                for idx in range(count):
                    tid = int(t_ids[idx]) if idx < len(t_ids) else 0
                    tname = str(t_names[idx]) if idx < len(t_names) else f"Transform_{idx + 1}"
                    telem = (
                        int(t_elems[idx])
                        if idx < len(t_elems)
                        else int(card_data.get("element", 0))
                    )
                    trans_list.append(
                        {
                            "form_id": tid,
                            "form_index": idx + 1,
                            "form_name": tname,
                            "element": telem,
                            "min_turn": idx + 3,
                        }
                    )
            elif isinstance(card_data.get("transformations"), list):
                trans_list = [
                    t if isinstance(t, dict) else t.to_dict() for t in card_data["transformations"]
                ]

            if trans_list:
                enriched["transformations"] = trans_list

        return enriched

    def enrich_box(
        self,
        cards: list[dict[str, Any]],
        region: str = "glb",
    ) -> list[dict[str, Any]]:
        """
        Enriches a list of player box cards with DokkanDB details and computes
        the best linking partners within the player's box for each card.
        """
        pool_ids = [int(c["id"]) for c in cards if "id" in c and c["id"]]
        enriched_list: list[dict[str, Any]] = []

        for c in cards:
            cid = int(c.get("id") or 0)
            ec = self.enrich_card(c, region=region)
            if cid:
                ec["best_in_box_partners"] = self.get_best_linking_partners(
                    cid, pool_card_ids=pool_ids, top_n=3, region=region
                )
            enriched_list.append(ec)
            time.sleep(0.02)

        return enriched_list
