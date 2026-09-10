"""Detect stat-derived leak tags from Phase 1's stats display output.

Pure function, no LLM, no DB access. All thresholds live in ``leak_taxonomy``;
this module only orchestrates the lookup.
"""

from __future__ import annotations

from ai_functions.game_review import leak_taxonomy

_TABLE_SIZE_VPIP_TAGS = frozenset({"low_vpip", "high_vpip"})
_THREE_BET_TAGS = frozenset({"under_3bet", "over_3bet"})


def _attach_preflop_evidence(leak: dict, stats_display: dict) -> dict:
    """Attach the exact hands and related split counters to preflop stat tags."""
    tag = leak.get("tag")
    if tag == leak_taxonomy.GAP_TAG:
        event_key = "open_limp"
    elif tag in _THREE_BET_TAGS:
        event_key = "three_bet_opportunity"
    else:
        return leak

    events = list((stats_display.get("preflop_events") or {}).get(event_key) or [])
    evidence = dict(leak.get("evidence") or {})
    evidence["events"] = events
    if tag in _THREE_BET_TAGS:
        evidence.update({
            "definition": "first voluntary hero decision facing exactly one raise",
            "squeeze": stats_display.get("squeeze"),
            "limp_reraise": stats_display.get("limp_reraise"),
            "limp_reraise_events": list(
                (stats_display.get("preflop_events") or {}).get(
                    "limp_reraise_opportunity"
                ) or []
            ),
        })
    leak["evidence"] = evidence
    leak["citations"] = [
        {
            "hand_id": event.get("hand_id"),
            "round_count": event.get("round_count"),
            "street": "preflop",
            "action": event.get("action"),
        }
        for event in events
        if event.get("round_count") is not None
    ]
    return leak


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
    """Judge mixed-table-size VPIP as one weighted session observation.

    Segment-specific profiles still supply the appropriate reference bounds,
    but one short/noisy segment can no longer represent the whole game. Hands
    from unsupported table sizes remain descriptive and are excluded from the
    leak decision.
    """
    segments = []
    total_n = 0
    total_d = 0
    weighted_severe = 0.0
    weighted_moderate = 0.0
    required = 0
    direction: str | None = None
    for raw_size, segment_display in (stats_display.get("by_table_size") or {}).items():
        try:
            table_size = int(raw_size)
        except (TypeError, ValueError):
            continue
        profile = _profile_for_table_size(base_profile, table_size)
        if profile is None:
            continue
        vpip = segment_display.get("vpip") or {}
        n = int(vpip.get("n", 0) or 0)
        d = int(vpip.get("d", 0) or 0)
        if d <= 0:
            continue
        threshold = profile.thresholds[tag]
        direction = threshold.direction
        total_n += n
        total_d += d
        weighted_severe += threshold.severe_bound * d
        weighted_moderate += threshold.moderate_bound * d
        required = max(required, profile.minimum_opportunities[tag])
        segments.append({
            "table_size": table_size,
            "profile": profile.key,
            "pct": vpip.get("pct"),
            "n": n,
            "d": d,
        })
    if not segments or total_d < required or direction is None:
        return None

    pct = round(100 * total_n / total_d, 1)
    severe_bound = weighted_severe / total_d
    moderate_bound = weighted_moderate / total_d
    severity = leak_taxonomy.severity_from_bounds(
        pct,
        direction,
        severe_bound,
        moderate_bound,
    )
    if severity is None:
        return None

    segments.sort(key=lambda item: item["table_size"], reverse=True)
    evidence = {
        "stat": tag,
        "pct": pct,
        "n": total_n,
        "d": total_d,
        "session_vpip": stats_display.get("vpip"),
        "reference": {
            "direction": direction,
            "moderate_bound": round(moderate_bound, 1),
            "severe_bound": round(severe_bound, 1),
            "method": "hands-weighted supported table-size profiles",
        },
        "segments": segments,
    }
    if len(segments) == 1:
        evidence.update({
            "table_size": segments[0]["table_size"],
            "profile": segments[0]["profile"],
        })
    else:
        evidence["profiles"] = sorted({segment["profile"] for segment in segments})
    return {
        "tag": tag,
        "kind": "stat",
        "severity": severity,
        "evidence": evidence,
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
            leaks.append(_attach_preflop_evidence(leak, stats_display))
    return leaks
