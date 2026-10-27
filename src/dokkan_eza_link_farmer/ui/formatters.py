"""Terminal formatting helpers for Dokkan cards and elements."""

from __future__ import annotations

from typing import Any

from rich.text import Text


def element_color(element: int, element_name: str = "") -> str:
    """Returns terminal Rich style color string for element and class."""
    elem_name = (element_name or "").upper()
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
    return type_colors.get(element % 10, "bold white")


def dokkan_colored_name(card: Any) -> str:
    """Returns BBCode/markup-styled colored name for terminal printing."""
    elem_name = getattr(card, "element_name", "") or ""
    type_prefix = f"[{elem_name}] " if elem_name else ""
    full_name = getattr(card, "full_name", getattr(card, "name", ""))
    clean_name = str(full_name).replace("[", "(").replace("]", ")")
    color = getattr(card, "element_color", None)
    if color is None:
        color = element_color(getattr(card, "element", 0), elem_name)
    return f"[{color}]{type_prefix}{clean_name}[/{color}]"


def rich_formatted_name(card: Any, include_type: bool = True) -> Text:
    """Returns a rich Text instance styled with the card element color."""
    elem_name = getattr(card, "element_name", "") or ""
    full_name = getattr(card, "full_name", getattr(card, "name", ""))
    prefix = f"[{elem_name}] " if (include_type and elem_name) else ""
    color = getattr(card, "element_color", None)
    if color is None:
        color = element_color(getattr(card, "element", 0), elem_name)
    return Text(f"{prefix}{full_name}", style=color)
