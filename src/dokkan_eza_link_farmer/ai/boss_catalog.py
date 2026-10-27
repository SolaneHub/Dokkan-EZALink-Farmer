"""Endgame Boss Catalog for Red Zone and Blue Zone challenge events.

Loads and exposes structured BossStage and BossPhase models from
src/dokkan_eza_link_farmer/assets/config/boss_stages.json.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from dokkan_eza_link_farmer.ai.models import BossStage
from dokkan_eza_link_farmer.core.system_tools import get_resource_path

logger = logging.getLogger(__name__)

DEFAULT_BOSS_CATALOG_PATH = get_resource_path("config/boss_stages.json")


def get_boss_catalog_path(override_path: str | Path | None = None) -> Path:
    """Returns resolved path to the boss stages JSON catalog."""
    if override_path is not None:
        p = Path(override_path)
        if p.exists():
            return p
    default_p = Path(DEFAULT_BOSS_CATALOG_PATH)
    if default_p.exists():
        return default_p

    # Fallback to local relative assets
    local_p = Path(__file__).resolve().parent.parent / "assets" / "config" / "boss_stages.json"
    if local_p.exists():
        return local_p

    return default_p


def load_boss_catalog(
    file_path: str | Path | None = None,
) -> dict[str, BossStage]:
    """Loads all boss stages from JSON catalog into BossStage domain models.

    The returned dictionary is indexed by both string stage_id (e.g. '10101')
    and slug (e.g. 'rz_broly').
    """
    path = get_boss_catalog_path(file_path)
    if not os.path.exists(path):
        logger.warning("Boss stages catalog not found at %s", path)
        return {}

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    stage_list: list[dict[str, Any]] = []
    if isinstance(data, list):
        stage_list = data
    elif isinstance(data, dict):
        stage_list = data.get("stages", [])

    catalog: dict[str, BossStage] = {}
    for item in stage_list:
        if not isinstance(item, dict):
            continue
        stage = BossStage.from_dict(item)
        slug = str(item.get("slug") or f"stage_{stage.stage_id}").strip().lower()

        catalog[slug] = stage
        catalog[str(stage.stage_id)] = stage

    return catalog


def list_boss_stages(file_path: str | Path | None = None) -> list[BossStage]:
    """Returns the list of unique BossStage instances from catalog."""
    cat = load_boss_catalog(file_path)
    seen_ids: set[int] = set()
    stages: list[BossStage] = []
    for stage in cat.values():
        if stage.stage_id not in seen_ids:
            seen_ids.add(stage.stage_id)
            stages.append(stage)
    stages.sort(key=lambda s: s.stage_id)
    return stages


def get_boss_stage(
    stage_identifier: int | str | BossStage,
    file_path: str | Path | None = None,
    dokkandb: Any = None,
    difficulty: int | str | None = None,
) -> BossStage:
    """Retrieves a BossStage by BossStage instance, stage_id integer or string slug/id.

    Raises KeyError if stage is not found in the catalog or DokkanDB.
    """
    if isinstance(stage_identifier, BossStage):
        return stage_identifier

    from dokkan_eza_link_farmer.ai.boss_models import parse_difficulty_code

    catalog = load_boss_catalog(file_path)
    key = str(stage_identifier).strip().lower()

    if key in catalog:
        return catalog[key]

    # Partial match fallback (e.g. 'broly' -> 'rz_broly')
    for k, stage in catalog.items():
        if key in k or key in stage.stage_name.lower():
            return stage

    # DokkanDB live query fallback if numeric
    if str(stage_identifier).isdigit():
        st_num = int(stage_identifier)
        if dokkandb is None:
            try:
                from dokkan_eza_link_farmer.integrations.dokkandb_client import DokkanDBClient

                dokkandb = DokkanDBClient()
            except Exception:
                dokkandb = None
        if dokkandb is not None:
            try:
                # 1. If st_num is a stage_id (7-8 digits: event_id + quest(3) + difficulty(1))
                if len(str(st_num)) >= 6:
                    ev_id = int(str(st_num)[:-4])
                    boss_info = dokkandb.get_stage_boss_info(ev_id, st_num)
                    if boss_info and boss_info.get("phases"):
                        return BossStage.from_dokkandb(boss_info)
                    det = dokkandb.get_event_details(ev_id)
                    st_name = f"Stage {st_num}"
                    ev_name = det.get("name") if det else f"Event {ev_id}"
                    if det and det.get("quests"):
                        for q in det["quests"]:
                            for s in q.get("stages", []):
                                if s.get("stage_id") == st_num:
                                    st_name = q.get("quest_name") or st_name
                                    break
                    return BossStage(
                        stage_id=st_num,
                        event_id=ev_id,
                        stage_name=st_name,
                        event_name=ev_name,
                        difficulty=4,
                        phases=[],
                    )

                # 2. If st_num matches an event id directly (typically 3-4 digits)
                det = dokkandb.get_event_details(st_num)
                if det and det.get("quests"):
                    first_q = det["quests"][0]
                    stages_arr = first_q.get("stages", [])
                    if stages_arr:
                        diff_code = (
                            parse_difficulty_code(difficulty) if difficulty is not None else None
                        )
                        chosen_s = None
                        if diff_code is not None:
                            chosen_s = next(
                                (
                                    s
                                    for s in stages_arr
                                    if int(s.get("difficulty") or 0) == diff_code
                                ),
                                None,
                            )
                        if not chosen_s:
                            sorted_stages = sorted(
                                stages_arr,
                                key=lambda s: int(s.get("difficulty") or 0),
                                reverse=True,
                            )
                            chosen_s = sorted_stages[0]
                        st_id = chosen_s.get("stage_id")
                        if st_id:
                            boss_info = dokkandb.get_stage_boss_info(st_num, st_id)
                            if boss_info and boss_info.get("phases"):
                                return BossStage.from_dokkandb(boss_info)
                            return BossStage(
                                stage_id=st_id,
                                event_id=st_num,
                                stage_name=first_q.get("quest_name") or "Stage 1",
                                event_name=det.get("name") or f"Event {st_num}",
                                difficulty=chosen_s.get("difficulty", 4),
                                phases=[],
                            )
            except Exception as e:
                logger.debug(f"Error checking DokkanDB event {st_num}: {e}")

    # Fallback: search Challenge events by query name in DokkanDB
    if dokkandb is None:
        try:
            from dokkan_eza_link_farmer.integrations.dokkandb_client import DokkanDBClient

            dokkandb = DokkanDBClient()
        except Exception:
            dokkandb = None
    if dokkandb is not None:
        try:
            events = dokkandb.get_challenge_events(active_only=False)
            for ev in events:
                ev_name = (ev.get("name") or "").lower()
                ev_id = ev.get("id")
                if key in ev_name or key == str(ev_id):
                    det = dokkandb.get_event_details(ev_id)
                    if det and det.get("quests"):
                        first_q = det["quests"][0]
                        stages_arr = first_q.get("stages", [])
                        if stages_arr:
                            diff_code = (
                                parse_difficulty_code(difficulty)
                                if difficulty is not None
                                else None
                            )
                            chosen_s = None
                            if diff_code is not None:
                                chosen_s = next(
                                    (
                                        s
                                        for s in stages_arr
                                        if int(s.get("difficulty") or 0) == diff_code
                                    ),
                                    None,
                                )
                            if not chosen_s:
                                sorted_stages = sorted(
                                    stages_arr,
                                    key=lambda s: int(s.get("difficulty") or 0),
                                    reverse=True,
                                )
                                chosen_s = sorted_stages[0]
                            st_id = chosen_s.get("stage_id")
                            if st_id:
                                boss_info = dokkandb.get_stage_boss_info(ev_id, st_id)
                                if boss_info and boss_info.get("phases"):
                                    return BossStage.from_dokkandb(boss_info)
                                return BossStage(
                                    stage_id=st_id,
                                    event_id=ev_id,
                                    stage_name=first_q.get("quest_name") or "Stage 1",
                                    event_name=ev.get("name") or f"Event {ev_id}",
                                    difficulty=chosen_s.get("difficulty", 4),
                                    phases=[],
                                )
        except Exception as e:
            logger.debug(f"Error searching DokkanDB events for '{key}': {e}")

    available = sorted({f"{s.stage_id} ({k})" for k, s in catalog.items()})
    raise KeyError(f"Boss stage '{stage_identifier}' not found in catalog. Available: {available}")


__all__ = [
    "DEFAULT_BOSS_CATALOG_PATH",
    "get_boss_catalog_path",
    "get_boss_stage",
    "list_boss_stages",
    "load_boss_catalog",
]
