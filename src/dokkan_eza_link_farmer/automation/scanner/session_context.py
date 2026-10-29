"""Scan session context dataclass for the Character Box scanner."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ScanSessionContext:
    """Explicit typed state container for an active card scanning session.

    Replaces implicit god-object inspection (hasattr/task mutation) with
    a transparent, typed session context.
    """

    seen_ids: set[int] = field(default_factory=set)
    recently_scanned_positions: dict[int, tuple[float, float]] = field(default_factory=dict)
    scanned_cards: dict[int, dict[str, Any]] = field(default_factory=dict)
    catalog_index: dict[int, dict[str, Any]] = field(default_factory=dict)
    last_registered_card_id: int | None = None

    def is_card_seen(self, card_id: int | None) -> bool:
        """Returns True if the card_id has been seen in this session."""
        if not card_id:
            return False
        return card_id in self.seen_ids


__all__ = ["ScanSessionContext"]
