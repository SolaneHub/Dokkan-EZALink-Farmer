"""Catalog indexing and card matching module for Dokkan Battle."""

from __future__ import annotations

import difflib
import logging
import re
from collections import defaultdict
from datetime import datetime
from typing import Any

from dokkan_eza_link_farmer.ai.art_variants import (
    discover_art_variants_from_catalog,
    is_art_variant,
)

logger = logging.getLogger(__name__)


def get_card_release_timestamp(card: dict[str, Any]) -> float:
    """Extracts numeric unix timestamp of card release date for Dokkan in-game release sorting.

    Dokkan Battle character box sorted by Release Date orders newest cards first (descending).
    """
    ts_str = str(
        card.get("open_at") or card.get("open_at_card") or card.get("open_at_eza") or ""
    ).strip()
    if not ts_str:
        return 0.0
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", ""))
        return dt.timestamp()
    except Exception:
        return 0.0


def normalize_title(text: str | None) -> str:
    """Removes non-alphanumeric characters and lowercases text for robust matching."""
    if not text:
        return ""
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


class CatalogMatcher:
    """Indexes Dokkan card database and matches OCR card metadata against known cards."""

    def __init__(self, catalog: list[dict[str, Any]] | None = None) -> None:
        self._catalog: list[dict[str, Any]] = []
        self._subname_index: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._id_index: dict[int, dict[str, Any]] = {}
        if catalog:
            self.load_catalog(catalog)

    def load_catalog(self, catalog: list[dict[str, Any]]) -> None:
        """Loads and indexes DokkanDB cards catalog by subname and ID."""
        self._catalog.clear()
        self._catalog.extend(catalog)
        self._subname_index.clear()
        self._id_index.clear()
        discover_art_variants_from_catalog(self._catalog)

        for card in self._catalog:
            self.index_single_card(card)
            awakening_list = card.get("awakening_data") or []
            for awk in awakening_list:
                self.index_single_card(awk, parent_card=card)

    def index_single_card(
        self, card: dict[str, Any], parent_card: dict[str, Any] | None = None
    ) -> None:
        """Indexes a single card or awakened form into _id_index and _subname_index."""
        cid = card.get("id")
        if not cid:
            return
        cid_int = int(cid)

        has_eza = bool(
            card.get("has_eza")
            or card.get("eza_leader_skill_set_id")
            or card.get("eza_leader_skill")
            or card.get("passive_skills_rows_eza")
            or (parent_card and parent_card.get("has_eza"))
        )
        has_seza = bool(
            card.get("has_seza")
            or card.get("eza_leader_skill_set_id_pre")
            or card.get("eza_passive_skill_description_pre")
            or (parent_card and parent_card.get("has_seza"))
        )

        card_entry = dict(card)
        card_entry["has_eza"] = has_eza
        card_entry["has_seza"] = has_seza
        if (
            card_entry.get("element") is None
            and parent_card
            and parent_card.get("element") is not None
        ):
            card_entry["element"] = parent_card["element"]

        self._id_index[cid_int] = card_entry

        sub = card.get("subname")
        if sub:
            norm = normalize_title(sub)
            if not any(int(c.get("id", 0)) == cid_int for c in self._subname_index[norm]):
                self._subname_index[norm].append(card_entry)
                self._subname_index[norm].sort(
                    key=lambda c: (
                        1 if is_art_variant(int(c.get("id", 0))) else 0,
                        -get_card_release_timestamp(c),
                        -int(c.get("id", 0)),
                    )
                )

    def match_card_candidate(
        self,
        recognized_text: str,
        detected_class: str | None = None,
        detected_elem: str | None = None,
        detected_rarity: int | None = None,
        session_seen_ids: set[int] | None = None,
        last_registered_card_id: int | None = None,
    ) -> tuple[dict[str, Any] | None, float]:
        """
        Scores indexed catalog cards against OCR extracted text, element, class, and rarity.
        Resolves multi-ID card variants chronologically against session_seen_ids and adjacency.
        Returns: (best_card_dict, confidence_score)
        """
        if not recognized_text:
            return None, 0.0

        norm_query = normalize_title(recognized_text)
        if len(norm_query) < 2:
            return None, 0.0

        elem_names_base = {0: "AGL", 1: "TEQ", 2: "INT", 3: "STR", 4: "PHY"}
        scored_candidates: list[tuple[dict[str, Any], float]] = []

        for card in self._id_index.values():
            if detected_rarity is not None and card.get("rarity") != detected_rarity:
                continue

            card_elem = card.get("element")
            if detected_elem is not None and card_elem is not None:
                base_e = elem_names_base.get(int(card_elem) % 5)
                if base_e != detected_elem:
                    continue

            if detected_class is not None and card_elem is not None:
                card_class = "EXTREME" if int(card_elem) >= 20 else "SUPER"
                if card_class != detected_class:
                    continue

            sub = card.get("subname") or ""
            name = card.get("name") or ""
            norm_sub = normalize_title(sub)
            norm_name = normalize_title(name)
            combined_norm = norm_sub + norm_name

            if (norm_sub and norm_query == norm_sub) or (
                combined_norm and norm_query == combined_norm
            ):
                score = 0.99
            elif norm_sub and norm_sub in norm_query:
                score = 0.98 if norm_name and norm_name in norm_query else 0.95
            elif combined_norm and combined_norm in norm_query:
                score = 0.95
            else:
                score_sub = (
                    difflib.SequenceMatcher(None, norm_query, norm_sub).ratio() if norm_sub else 0.0
                )
                score_comb = (
                    difflib.SequenceMatcher(None, norm_query, combined_norm).ratio()
                    if combined_norm
                    else 0.0
                )
                score = max(score_sub, score_comb)

                if norm_sub and len(norm_sub) >= 6 and len(norm_query) >= 6:
                    sm = difflib.SequenceMatcher(None, norm_query, norm_sub)
                    l_match = sm.find_longest_match(0, len(norm_query), 0, len(norm_sub))
                    if l_match.size >= max(8, int(len(norm_sub) * 0.65)):
                        sub_cov = l_match.size / len(norm_sub)
                        query_cov = l_match.size / len(norm_query)
                        if sub_cov >= 0.70 and query_cov >= 0.40:
                            score = max(score, min(0.88, 0.75 + 0.15 * sub_cov))

            if score >= 0.50:
                scored_candidates.append((card, score))

        if not scored_candidates:
            return None, 0.0

        max_score = max(s for _, s in scored_candidates)
        # Only group true ties (e.g. variants sharing identical titles/names or within 0.005)
        threshold = max_score - 0.005
        top_cands = [(c, s) for c, s in scored_candidates if s >= threshold]

        if not top_cands:
            best_c, best_s = max(scored_candidates, key=lambda it: it[1])
            return best_c, best_s

        if len(top_cands) == 1:
            return top_cands[0][0], max_score

        # Multi-ID Variant Resolution
        seen_set = session_seen_ids or set()
        unseen_cands = [cs for cs in top_cands if int(cs[0].get("id", 0)) not in seen_set]

        if unseen_cands:
            # Prefer higher confidence score, then canonical base card over art variant,
            # then release date descending (newest card first, matching Dokkan in-game Released sort),
            # then higher card ID descending
            unseen_cands.sort(
                key=lambda cs: (
                    -cs[1],
                    1 if is_art_variant(int(cs[0].get("id", 0))) else 0,
                    -get_card_release_timestamp(cs[0]),
                    -int(cs[0].get("id", 0)),
                )
            )
            return unseen_cands[0][0], max_score

        # If all candidate variants have already been seen in this session,
        # check if this is an adjacent duplicate copy of last_registered_card_id
        if last_registered_card_id is not None and last_registered_card_id in [
            int(cs[0].get("id", 0)) for cs in top_cands
        ]:
            adj = next(
                cs[0] for cs in top_cands if int(cs[0].get("id", 0)) == last_registered_card_id
            )
            return adj, max_score

        top_cands.sort(
            key=lambda cs: (
                -cs[1],
                1 if is_art_variant(int(cs[0].get("id", 0))) else 0,
                -get_card_release_timestamp(cs[0]),
                -int(cs[0].get("id", 0)),
            )
        )
        return top_cands[0][0], max_score

    def match_card_by_text(self, recognized_text: str) -> dict[str, Any] | None:
        """Matches card by subname or title text with growth button stripping and fuzzy matching."""
        if not recognized_text:
            return None

        clean_text = re.sub(
            r"^(?:growth|owth|wth|vth|uth|nth|rth|th)\b[\s\-\.$$\|]*",
            "",
            recognized_text,
            flags=re.IGNORECASE,
        ).strip()

        norm_query = normalize_title(clean_text)
        if len(norm_query) < 3:
            return None

        for norm_sub, cands in self._subname_index.items():
            card = cands[0] if isinstance(cands, list) and cands else cands  # type: ignore[index]
            if norm_query in norm_sub or norm_sub in norm_query:
                return card  # type: ignore[return-value]

        best_card = None
        best_score = 0.0
        for norm_sub, cands in self._subname_index.items():
            card = cands[0] if isinstance(cands, list) and cands else cands  # type: ignore[index]
            score = difflib.SequenceMatcher(None, norm_query, norm_sub).ratio()
            if score > best_score and score >= 0.68:
                best_score = score
                best_card = card

        return best_card  # type: ignore[return-value]

    _normalize_title = staticmethod(normalize_title)
    _index_single_card = index_single_card
    _match_card_candidate = match_card_candidate


def match_card_candidate(
    matcher: CatalogMatcher,
    recognized_text: str,
    detected_class: str | None = None,
    detected_elem: str | None = None,
    detected_rarity: int | None = None,
    session_seen_ids: set[int] | None = None,
    last_registered_card_id: int | None = None,
) -> tuple[dict[str, Any] | None, float]:
    """Module-level helper to match card candidate using a CatalogMatcher instance."""
    return matcher.match_card_candidate(
        recognized_text,
        detected_class=detected_class,
        detected_elem=detected_elem,
        detected_rarity=detected_rarity,
        session_seen_ids=session_seen_ids,
        last_registered_card_id=last_registered_card_id,
    )


def match_card_by_text(matcher: CatalogMatcher, recognized_text: str) -> dict[str, Any] | None:
    """Module-level helper to match card by text using a CatalogMatcher instance."""
    return matcher.match_card_by_text(recognized_text)


def index_single_card(
    matcher: CatalogMatcher, card: dict[str, Any], parent_card: dict[str, Any] | None = None
) -> None:
    """Module-level helper to index a single card using a CatalogMatcher instance."""
    matcher.index_single_card(card, parent_card=parent_card)


_index_single_card = index_single_card
_match_card_candidate = match_card_candidate
_match_card_by_text = match_card_by_text
_normalize_title = normalize_title

__all__ = [
    "CatalogMatcher",
    "_index_single_card",
    "_match_card_candidate",
    "_match_card_by_text",
    "_normalize_title",
    "get_card_release_timestamp",
    "index_single_card",
    "match_card_by_text",
    "match_card_candidate",
    "normalize_title",
]
