"""
Module alias providing seamless backward and forward compatibility
between teambuilder.py and team_builder.py.
"""

from dokkan_eza_link_farmer.ai.team_builder import (  # noqa: F401
    ELEMENT_ADVANTAGE,
    ELEMENT_DISADVANTAGE,
    KI_LINKS,
    TOP_TIER_STAT_LINKS,
    CandidateEvaluation,
    TeamBuilder,
)

__all__ = [
    "CandidateEvaluation",
    "TeamBuilder",
    "KI_LINKS",
    "TOP_TIER_STAT_LINKS",
    "ELEMENT_ADVANTAGE",
    "ELEMENT_DISADVANTAGE",
]
