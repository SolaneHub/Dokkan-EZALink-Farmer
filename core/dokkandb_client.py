import os
import time
import json
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
import requests
import cv2
import numpy as np

logger = logging.getLogger(__name__)


class DokkanDBClient:
    """Client for fetching Dokkan Battle event data and banner assets from dokkandb.com."""

    API_BASE_URL = "https://api.dokkandb.com/api"
    API_JP_BASE_URL = "https://api.dokkandb.com/jp/api"
    ASSETS_MIRROR_URL = "https://api.dokkandb.com/assets/mirror"
    ASSETS_FALLBACK_URL = "https://enaskhebnjtktdfszdcb.supabase.co/storage/v1/object/public/assets/mirror"

    DEFAULT_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://dokkandb.com/",
        "Origin": "https://dokkandb.com",
        "Accept": "application/json, image/*, */*"
    }

    def __init__(self, cache_dir: str = "cache", cache_ttl_seconds: int = 43200):
        self.cache_dir = os.path.abspath(cache_dir)
        self.banners_dir = os.path.join(self.cache_dir, "banners")
        self.cache_ttl_seconds = cache_ttl_seconds
        os.makedirs(self.cache_dir, exist_ok=True)
        os.makedirs(self.banners_dir, exist_ok=True)

    def _get_api_url(self, endpoint: str, region: str = "glb") -> str:
        base = self.API_JP_BASE_URL if region.lower() == "jp" else self.API_BASE_URL
        endpoint = endpoint.lstrip("/")
        return f"{base}/{endpoint}"

    def get_zbattles(
        self,
        region: str = "glb",
        active_only: bool = False,
        force_refresh: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Retrieves all Extreme Z-Battles from DokkanDB.
        Uses local cache if available and not expired.
        """
        cache_file = os.path.join(self.cache_dir, f"dokkandb_zbattles_{region.lower()}.json")

        data: Optional[List[Dict[str, Any]]] = None
        if not force_refresh and os.path.exists(cache_file):
            try:
                mtime = os.path.getmtime(cache_file)
                if (time.time() - mtime) < self.cache_ttl_seconds:
                    with open(cache_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
            except Exception as e:
                logger.warning(f"Failed reading DokkanDB cache: {e}")

        if data is None:
            url = self._get_api_url("zbattle-all", region=region)
            try:
                resp = requests.get(url, headers=self.DEFAULT_HEADERS, timeout=12)
                resp.raise_for_status()
                data = resp.json()
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"Error fetching Z-Battles from DokkanDB ({url}): {e}")
                if os.path.exists(cache_file):
                    try:
                        with open(cache_file, "r", encoding="utf-8") as f:
                            data = json.load(f)
                    except Exception:
                        pass
                if data is None:
                    return []

        now = datetime.now(timezone.utc)
        results = []
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
        self,
        category: Optional[int] = None,
        region: str = "glb",
        force_refresh: bool = False
    ) -> List[Dict[str, Any]]:
        """Retrieves general events (Story, Growth, Challenge, etc.) from DokkanDB."""
        cache_file = os.path.join(self.cache_dir, f"dokkandb_events_{region.lower()}.json")

        data: Optional[List[Dict[str, Any]]] = None
        if not force_refresh and os.path.exists(cache_file):
            try:
                mtime = os.path.getmtime(cache_file)
                if (time.time() - mtime) < self.cache_ttl_seconds:
                    with open(cache_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
            except Exception:
                pass

        if data is None:
            url = self._get_api_url("events-all", region=region)
            try:
                resp = requests.get(url, headers=self.DEFAULT_HEADERS, timeout=15)
                resp.raise_for_status()
                data = resp.json()
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"Error fetching events from DokkanDB: {e}")
                if os.path.exists(cache_file):
                    try:
                        with open(cache_file, "r", encoding="utf-8") as f:
                            data = json.load(f)
                    except Exception:
                        pass
                if data is None:
                    return []

        if category is not None:
            return [e for e in data if e.get("category") == category]
        return data

    def download_banner(self, event: Dict[str, Any], prefer_button: bool = True) -> Optional[str]:
        """
        Downloads and caches the banner image for an event.
        Returns the absolute local path to the saved PNG image.
        """
        event_id = event.get("id")
        primary_rel = event.get("listbutton_image_path") if prefer_button else event.get("banner_image_path")
        secondary_rel = event.get("banner_image_path") if prefer_button else event.get("listbutton_image_path")

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
                f"{self.ASSETS_FALLBACK_URL}/{clean_rel}"
            ]

            for u in urls_to_try:
                try:
                    r = requests.get(u, headers=self.DEFAULT_HEADERS, timeout=10)
                    if r.status_code == 200 and len(r.content) > 1000:
                        with open(local_path, "wb") as f:
                            f.write(r.content)
                        return local_path
                except Exception as e:
                    logger.debug(f"Failed downloading banner from {u}: {e}")

        return None

    def get_link_level_events(
        self,
        region: str = "glb",
        active_only: bool = False
    ) -> List[Dict[str, Any]]:
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
            "god-level intensive training"
        ]

        results = []
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

    def get_chamber_of_spirit_and_time(self, region: str = "glb") -> Optional[Dict[str, Any]]:
        """
        Finds the 'Chamber of Spirit and Time' (Stanza dello Spirito e del Tempo) event.
        Prioritizes the currently active version.
        """
        events = self.get_link_level_events(region=region, active_only=False)
        spirit_events = [e for e in events if "chamber of spirit and time" in (e.get("name") or "").lower()]

        if not spirit_events:
            return None

        # If any is open, return the open one
        for ev in spirit_events:
            if ev.get("is_currently_open"):
                return ev

        # Fallback to the latest event (highest ID)
        return spirit_events[0]

    def load_banner_template(self, banner_path: str) -> Optional[np.ndarray]:
        """Loads a banner image from disk as a BGR numpy array."""
        if not os.path.exists(banner_path):
            return None
        img = cv2.imread(banner_path, cv2.IMREAD_UNCHANGED)
        if img is None:
            return None
        if len(img.shape) == 3 and img.shape[2] == 4:
            return img[:, :, :3]
        return img
