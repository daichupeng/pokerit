"""Detect stat-derived leak tags from Phase 1's stats display output.

Pure function, no LLM, no DB access. All thresholds live in ``leak_taxonomy``;
this module only orchestrates the lookup.
"""

from __future__ import annotations

from ai_functions.game_review import leak_taxonomy


def detect_stat_leaks(stats_display: dict) -> list[dict]:
    """Evaluate every stat-derived tag in the taxonomy against ``stats_display``.

    ``stats_display`` is game-level ``stats.to_display()`` output (including
    its ``by_position`` sub-dict, needed for ``positional_looseness``).
    Returns the merged leak-tag shape for every tag that clears its severity
    band, skipping tags below the minimum-opportunity floor.
    """
    leaks = []
    for tag in leak_taxonomy.ALL_STAT_TAGS:
        leak = leak_taxonomy.severity_for_stat_tag(tag, stats_display)
        if leak is not None:
            leaks.append(leak)
    return leaks
