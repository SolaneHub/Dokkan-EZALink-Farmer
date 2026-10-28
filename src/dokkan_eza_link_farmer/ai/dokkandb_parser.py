"""DokkanDB character payload parser and factory."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

from dokkan_eza_link_farmer.ai.card_models import CardForm, PassiveTags, SATags
from dokkan_eza_link_farmer.core.system_tools import AppPaths

if TYPE_CHECKING:
    from dokkan_eza_link_farmer.ai.card_models import DokkanCard


def parse_card_from_dokkandb(
    cls: Any,
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
            data.get("eza_passive_skill_description") or data.get("passive_skill_description") or ""
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
        passive_text = " / ".join(p for p in p_parts if p) or (data.get("passive_skill_name") or "")

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

    # Active Skill
    active_name = str(data.get("active_skill_name") or "")
    active_cond = str(data.get("active_skill_condition") or "")
    active_eff = str(data.get("active_skill_effect") or "")

    # Standby Skill
    standby_name = str(data.get("standby_skill_name") or "")
    standby_cond = str(data.get("standby_skill_condition") or "")
    standby_eff = str(data.get("standby_skill_effect") or "")

    # In-battle transformations & alternate forms
    transformations: list[CardForm] = []
    try:
        from dokkan_eza_link_farmer.ai.syncer import parse_passive_tags, parse_sa_tags
    except ImportError:
        parse_passive_tags = None
        parse_sa_tags = None

    trans_data = data.get("transformation_data")
    if isinstance(trans_data, list) and trans_data:
        for idx, trans in enumerate(trans_data, start=1):
            if isinstance(trans, dict):
                t_sa_text = " | ".join(
                    str(s) for s in (trans.get("special_descriptions") or []) if s
                )
                t_sa_tags = parse_sa_tags(t_sa_text) if parse_sa_tags else SATags()
                t_pass_text = trans.get("passive_skill_description") or ""
                t_pass_tags = (
                    parse_passive_tags(t_pass_text, sa_tags=t_sa_tags)
                    if parse_passive_tags
                    else PassiveTags()
                )
                transformations.append(
                    CardForm(
                        form_id=int(trans.get("id") or 0),
                        form_index=idx,
                        form_name=str(trans.get("name") or f"Transform_{idx}"),
                        element=int(trans.get("element") or element),
                        links=[
                            str(trans.get(f"link_skill_name_{i}"))
                            for i in range(1, 8)
                            if trans.get(f"link_skill_name_{i}")
                        ],
                        link_ids=[
                            int(lid) for lid in (trans.get("link_ids") or []) if lid is not None
                        ],
                        passive_skill_text=t_pass_text,
                        super_attack_text=t_sa_text,
                        passive_tags=t_pass_tags,
                        sa_tags=t_sa_tags,
                        min_turn=int(trans.get("min_turn", idx + 3)),
                    )
                )
    elif data.get("transformation_names") or data.get("transformation_ids"):
        t_names = data.get("transformation_names") or []
        t_ids = data.get("transformation_ids") or []
        t_elems = data.get("transformation_elements") or []
        count = max(len(t_names), len(t_ids))
        cache_dir = os.path.join(AppPaths.get_cache_dir(), "cards")
        for idx in range(count):
            tid = int(t_ids[idx]) if idx < len(t_ids) else 0
            tname = str(t_names[idx]) if idx < len(t_names) else f"Transform_{idx + 1}"
            telem = int(t_elems[idx]) if idx < len(t_elems) else element

            tdetail = None
            if tid:
                for reg in ("glb", "jp"):
                    cp = os.path.join(cache_dir, f"card_{tid}_{reg}.json")
                    if os.path.exists(cp):
                        try:
                            with open(cp, encoding="utf-8") as fh:
                                tdetail = json.load(fh)
                                break
                        except Exception:
                            pass

            t_pass = ""
            t_sa_text = ""
            t_links = []
            t_link_ids = []
            if tdetail:
                t_pass = (
                    tdetail.get("eza_passive_skill_description")
                    if card_is_eza and tdetail.get("eza_passive_skill_description")
                    else (tdetail.get("passive_skill_description") or "")
                )
                sa_list = (
                    tdetail.get("special_descriptions_eza")
                    if card_is_eza
                    else tdetail.get("special_descriptions")
                ) or []
                t_sa_text = " | ".join(str(s) for s in sa_list if s)
                t_links = [
                    str(tdetail.get(f"link_skill_name_{i}"))
                    for i in range(1, 8)
                    if tdetail.get(f"link_skill_name_{i}")
                ]
                t_link_ids = [
                    int(lid) for lid in (tdetail.get("link_ids") or []) if lid is not None
                ]

            t_sa_tags = parse_sa_tags(t_sa_text) if parse_sa_tags else SATags()
            t_pass_tags = (
                parse_passive_tags(str(t_pass or ""), sa_tags=t_sa_tags)
                if parse_passive_tags
                else PassiveTags()
            )

            min_t = idx + 4
            if "exchange" in tname.lower() or "reversible" in active_eff.lower():
                min_t = 4
            elif (
                "potara" in active_eff.lower()
                or "fusion" in active_eff.lower()
                or "5" in active_cond
            ):
                min_t = 5

            transformations.append(
                CardForm(
                    form_id=tid,
                    form_index=idx + 1,
                    form_name=tname,
                    element=telem,
                    links=t_links or links,
                    link_ids=t_link_ids or parsed_link_ids,
                    passive_skill_text=str(t_pass or ""),
                    super_attack_text=t_sa_text,
                    passive_tags=t_pass_tags,
                    sa_tags=t_sa_tags,
                    min_turn=min_t,
                )
            )

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
        active_skill_name=active_name,
        active_skill_condition=active_cond,
        active_skill_effect=active_eff,
        standby_skill_name=standby_name,
        standby_skill_condition=standby_cond,
        standby_skill_effect=standby_eff,
        transformations=transformations,
    )


__all__ = ["parse_card_from_dokkandb"]
