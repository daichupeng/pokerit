"""Detect stat-derived leak tags from Phase 1's stats display output.

Pure function, no LLM, no DB access. All thresholds live in ``leak_taxonomy``;
this module only orchestrates the lookup.
"""

from __future__ import annotations

from ai_functions.game_review import leak_taxonomy

_TABLE_SIZE_VPIP_TAGS = frozenset({"low_vpip", "high_vpip"})


def _profile_for_table_size(base_profile, table_size: int):
    """Choose a supported VPIP benchmark for the players dealt this hand.

    Cash profiles have explicit 6-max and 8-max benchmarks. Tournament
    profiles currently have authoritative 8-max benchmarks only, so their
    short-handed buckets remain descriptive instead of being judged against an
    inappropriate full-ring threshold.
    """
    if table_size >= 7:
        if base_profile.key.startswith("cash_"):
            return leak_taxonomy.get_threshold_profile("cash_8max_100bb")
        return base_profile
    if 5 <= table_size <= 6 and base_profile.key.startswith("cash_"):
        return leak_taxonomy.get_threshold_profile("cash_6max_100bb")
    return None


def _segmented_vpip_leak(tag: str, stats_display: dict, base_profile) -> dict | None:
    segments = []
    for raw_size, segment_display in (stats_display.get("by_table_size") or {}).items():
        try:
            table_size = int(raw_size)
        except (TypeError, ValueError):
            continue
        profile = _profile_for_table_size(base_profile, table_size)
        if profile is None:
            continue
        leak = leak_taxonomy.severity_for_stat_tag(tag, segment_display, profile.key)
        if leak is None:
            continue
        segments.append({
            "table_size": table_size,
            "profile": profile.key,
            "severity": leak["severity"],
            **leak["evidence"],
        })
    if not segments:
        return None
    segments.sort(key=lambda item: (item["severity"], item.get("d", 0)), reverse=True)
    strongest = segments[0]
    return {
        "tag": tag,
        "kind": "stat",
        "severity": strongest["severity"],
        "evidence": {
            "stat": tag,
            "table_size": strongest["table_size"],
            "profile": strongest["profile"],
            "pct": strongest.get("pct"),
            "n": strongest.get("n"),
            "d": strongest.get("d"),
            "segments": segments,
        },
    }


def detect_stat_leaks(stats_display: dict, profile_key: str | None = None) -> list[dict]:
    """Evaluate every stat-derived tag in the taxonomy against ``stats_display``.

    ``stats_display`` is game-level ``stats.to_display()`` output (including
    its ``by_position`` sub-dict, needed for ``positional_looseness``).
    Returns the merged leak-tag shape for every tag that clears its severity
    band, skipping tags below the minimum-opportunity floor.
    """
    leaks = []
    profile = leak_taxonomy.get_threshold_profile(profile_key)
    for tag in profile.enabled_stat_tags:
        if tag in _TABLE_SIZE_VPIP_TAGS and stats_display.get("by_table_size"):
            leak = _segmented_vpip_leak(tag, stats_display, profile)
        else:
            leak = leak_taxonomy.severity_for_stat_tag(tag, stats_display, profile.key)
        if leak is not None:
            leaks.append(leak)
    return leaks
