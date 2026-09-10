"""Versioned, scenario-specific leak thresholds for game evaluation.

Stat leaks are deliberately conservative: a metric is never classified until
its own opportunity floor is met.  The threshold profile and version are
stored with every evaluation so historical reports remain explainable after a
future tuning pass.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

THRESHOLD_VERSION = "2026-07-23.v3"
DEFAULT_THRESHOLD_PROFILE = "cash_6max_100bb"

JUDGMENT_TAGS = frozenset({
    "missed_value_bet",
    "bad_bluff_spot",
    "inconsistent_sizing",
    "slowplay_risk",
    "missed_fold",
})

PUSH_FOLD_JUDGMENT_TAGS = frozenset({
    "missed_open_shove",
    "bad_open_shove",
    "missed_reshove",
    "bad_reshove",
    "missed_call_off",
    "bad_call_off",
})

# One deliberately permissive floor shared by every deterministic metric.
# Even a small sample is useful as long as the report presents it as an early
# signal rather than a settled long-term conclusion.
MIN_OPPORTUNITY_FLOOR = 5

EP_POSITIONS = frozenset({"UTG", "UTG+1", "UTG+2"})
LP_POSITIONS = frozenset({"BTN", "CO"})
_POSTFLOP_STREETS = ("flop", "turn", "river")


@dataclass(frozen=True)
class StatThreshold:
    path: tuple[str, ...]
    value_key: str
    direction: str
    severe_bound: float
    moderate_bound: float


STAT_THRESHOLDS: dict[str, StatThreshold] = {
    "low_vpip": StatThreshold(("vpip",), "pct", "low", 16, 20),
    "high_vpip": StatThreshold(("vpip",), "pct", "high", 38, 30),
    "under_3bet": StatThreshold(("three_bet",), "pct", "low", 3, 5),
    "over_3bet": StatThreshold(("three_bet",), "pct", "high", 13, 9),
    "overfolds_to_3bet": StatThreshold(("fold_to_3bet",), "pct", "high", 75, 65),
    "too_passive_postflop": StatThreshold(("aggression_factor",), "ratio", "low", 1.0, 1.5),
    "too_aggressive_postflop": StatThreshold(("aggression_factor",), "ratio", "high", 4.5, 3.0),
    "overplays_to_showdown": StatThreshold(("wtsd",), "pct", "high", 36, 30),
    "underplays_to_showdown": StatThreshold(("wtsd",), "pct", "low", 18, 24),
    "weak_at_showdown": StatThreshold(("wsd",), "pct", "low", 40, 48),
}

for _street in _POSTFLOP_STREETS:
    STAT_THRESHOLDS[f"under_cbet_{_street}"] = StatThreshold(
        ("cbet", _street), "pct", "low", 40, 55
    )
    STAT_THRESHOLDS[f"over_cbet_{_street}"] = StatThreshold(
        ("cbet", _street), "pct", "high", 80, 70
    )
    STAT_THRESHOLDS[f"overfolds_to_cbet_{_street}"] = StatThreshold(
        ("fold_to_cbet", _street), "pct", "high", 65, 55
    )

GAP_TAG = "limps_too_wide"
POSITIONAL_TAG = "positional_looseness"
ALL_STAT_TAGS = frozenset(STAT_THRESHOLDS) | {GAP_TAG, POSITIONAL_TAG}
ALL_JUDGMENT_TAGS = JUDGMENT_TAGS | PUSH_FOLD_JUDGMENT_TAGS


def _base_minimums() -> dict[str, int]:
    minimums = {
        "low_vpip": MIN_OPPORTUNITY_FLOOR,
        "high_vpip": MIN_OPPORTUNITY_FLOOR,
        GAP_TAG: MIN_OPPORTUNITY_FLOOR,
        POSITIONAL_TAG: MIN_OPPORTUNITY_FLOOR,
        "under_3bet": MIN_OPPORTUNITY_FLOOR,
        "over_3bet": MIN_OPPORTUNITY_FLOOR,
        "overfolds_to_3bet": MIN_OPPORTUNITY_FLOOR,
        "too_passive_postflop": MIN_OPPORTUNITY_FLOOR,
        "too_aggressive_postflop": MIN_OPPORTUNITY_FLOOR,
        "overplays_to_showdown": MIN_OPPORTUNITY_FLOOR,
        "underplays_to_showdown": MIN_OPPORTUNITY_FLOOR,
        "weak_at_showdown": MIN_OPPORTUNITY_FLOOR,
    }
    for street in _POSTFLOP_STREETS:
        minimums[f"under_cbet_{street}"] = MIN_OPPORTUNITY_FLOOR
        minimums[f"over_cbet_{street}"] = MIN_OPPORTUNITY_FLOOR
        minimums[f"overfolds_to_cbet_{street}"] = MIN_OPPORTUNITY_FLOOR
    return minimums


@dataclass(frozen=True)
class ThresholdProfile:
    key: str
    version: str
    thresholds: dict[str, StatThreshold]
    minimum_opportunities: dict[str, int]
    enabled_stat_tags: frozenset[str]
    gap_moderate: float = 6
    gap_severe: float = 10
    positional_moderate: float = 5
    positional_severe: float = 0


def _thresholds(**overrides: tuple[float, float]) -> dict[str, StatThreshold]:
    result = dict(STAT_THRESHOLDS)
    for tag, (severe, moderate) in overrides.items():
        result[tag] = replace(result[tag], severe_bound=severe, moderate_bound=moderate)
    return result


_MINIMUMS = _base_minimums()
_PUSH_FOLD_STAT_TAGS = frozenset({"low_vpip", "high_vpip", GAP_TAG, POSITIONAL_TAG})

THRESHOLD_PROFILES: dict[str, ThresholdProfile] = {
    "cash_6max_100bb": ThresholdProfile(
        "cash_6max_100bb", THRESHOLD_VERSION, dict(STAT_THRESHOLDS), dict(_MINIMUMS), ALL_STAT_TAGS
    ),
    "cash_8max_100bb": ThresholdProfile(
        "cash_8max_100bb", THRESHOLD_VERSION,
        _thresholds(low_vpip=(14, 18), high_vpip=(34, 27), over_3bet=(12, 9)),
        dict(_MINIMUMS), ALL_STAT_TAGS,
    ),
    "mtt_8max_40bb": ThresholdProfile(
        "mtt_8max_40bb", THRESHOLD_VERSION,
        _thresholds(low_vpip=(15, 19), high_vpip=(40, 31), under_3bet=(2.5, 4.5), over_3bet=(15, 10)),
        dict(_MINIMUMS), ALL_STAT_TAGS,
    ),
    "mtt_8max_25bb": ThresholdProfile(
        "mtt_8max_25bb", THRESHOLD_VERSION,
        _thresholds(low_vpip=(14, 18), high_vpip=(42, 32), under_3bet=(2, 4), over_3bet=(18, 12)),
        dict(_MINIMUMS), ALL_STAT_TAGS,
    ),
    "mtt_8max_15bb": ThresholdProfile(
        "mtt_8max_15bb", THRESHOLD_VERSION,
        _thresholds(low_vpip=(12, 16), high_vpip=(50, 38)),
        dict(_MINIMUMS), _PUSH_FOLD_STAT_TAGS,
    ),
    "custom": ThresholdProfile(
        "custom", THRESHOLD_VERSION, dict(STAT_THRESHOLDS), dict(_MINIMUMS), ALL_STAT_TAGS
    ),
}

_PROFILE_ALIASES = {
    "cash_100bb": "cash_6max_100bb",
    "mtt_40bb": "mtt_8max_40bb",
    "mtt_25bb": "mtt_8max_25bb",
    "mtt_push_fold": "mtt_8max_15bb",
}


def get_threshold_profile(profile_key: str | None) -> ThresholdProfile:
    key = _PROFILE_ALIASES.get(profile_key or "", profile_key or DEFAULT_THRESHOLD_PROFILE)
    return THRESHOLD_PROFILES.get(key, THRESHOLD_PROFILES["custom"])


def threshold_profile_key_for_game(game) -> str:
    from poker_engine.scenarios import profile_scope_for_game

    scenario = getattr(game, "scenario", None)
    if scenario in THRESHOLD_PROFILES:
        return scenario
    scope = profile_scope_for_game(game)
    return get_threshold_profile(scope).key


def judgment_tags_for_profile(profile_key: str, street: str | None = None) -> frozenset[str]:
    if get_threshold_profile(profile_key).key == "mtt_8max_15bb":
        return PUSH_FOLD_JUDGMENT_TAGS if street == "preflop" else JUDGMENT_TAGS
    return JUDGMENT_TAGS


def _get_path(display: dict, path: tuple[str, ...]) -> dict | None:
    node = display
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def _opportunity_for_node(tag: str, node: dict) -> int:
    if tag in {"too_passive_postflop", "too_aggressive_postflop"}:
        return int(node.get("n", 0)) + int(node.get("d", 0))
    return int(node.get("d", 0))


def _severity_from_bounds(value: float, direction: str, severe_bound: float, moderate_bound: float) -> int | None:
    if direction == "low":
        if value < severe_bound:
            return 3
        if severe_bound <= value <= moderate_bound:
            return 2
        return None
    if value > severe_bound:
        return 3
    if moderate_bound <= value <= severe_bound:
        return 2
    return None


def stat_tag_opportunity(tag: str, display: dict) -> int | None:
    if tag == GAP_TAG:
        vpip = display.get("vpip")
        return int(vpip["d"]) if vpip else None
    if tag == POSITIONAL_TAG:
        ep = _combined_position_vpip(display, EP_POSITIONS)
        lp = _combined_position_vpip(display, LP_POSITIONS)
        return min(ep[1], lp[1]) if ep is not None and lp is not None else None
    if tag in STAT_THRESHOLDS:
        node = _get_path(display, STAT_THRESHOLDS[tag].path)
        return _opportunity_for_node(tag, node) if node else None
    raise ValueError(f"Unknown stat tag: {tag}")


def minimum_opportunities_for_tag(tag: str, profile_key: str | None = None) -> int:
    return get_threshold_profile(profile_key).minimum_opportunities.get(tag, MIN_OPPORTUNITY_FLOOR)


def _severity_single_stat(tag: str, display: dict, profile: ThresholdProfile) -> dict | None:
    threshold = profile.thresholds[tag]
    node = _get_path(display, threshold.path)
    opportunity = _opportunity_for_node(tag, node) if node else 0
    if node is None or opportunity < profile.minimum_opportunities[tag]:
        return None
    value = node.get(threshold.value_key)
    is_infinite = threshold.value_key == "ratio" and bool(node.get("infinite"))
    if is_infinite:
        value = float("inf")
    if value is None:
        return None
    severity = _severity_from_bounds(value, threshold.direction, threshold.severe_bound, threshold.moderate_bound)
    if severity is None:
        return None
    evidence_value = None if is_infinite else value
    evidence = {
        "stat": tag, threshold.value_key: evidence_value,
        "n": node.get("n"), "d": node.get("d"),
    }
    if is_infinite:
        evidence["infinite"] = True
    return {
        "tag": tag,
        "kind": "stat",
        "severity": severity,
        "evidence": evidence,
    }


def _severity_limps_too_wide(display: dict, profile: ThresholdProfile) -> dict | None:
    limp = display.get("limp")
    if not limp or limp.get("d", 0) < profile.minimum_opportunities[GAP_TAG]:
        return None
    limp_pct = limp["pct"]
    severity = 3 if limp_pct > profile.gap_severe else 2 if profile.gap_moderate <= limp_pct <= profile.gap_severe else None
    if severity is None:
        return None
    return {
        "tag": GAP_TAG, "kind": "stat", "severity": severity,
        "evidence": {"stat": GAP_TAG, "pct": limp_pct, "n": limp["n"], "d": limp["d"]},
    }


def _combined_position_vpip(display: dict, positions: frozenset[str]) -> tuple[int, int] | None:
    n = d = 0
    found = False
    for pos, pos_display in (display.get("by_position") or {}).items():
        if pos not in positions or not pos_display.get("vpip"):
            continue
        vpip = pos_display["vpip"]
        n += vpip["n"]
        d += vpip["d"]
        found = True
    return (n, d) if found else None


def _severity_positional_looseness(display: dict, profile: ThresholdProfile) -> dict | None:
    ep = _combined_position_vpip(display, EP_POSITIONS)
    lp = _combined_position_vpip(display, LP_POSITIONS)
    floor = profile.minimum_opportunities[POSITIONAL_TAG]
    if ep is None or lp is None or ep[1] < floor or lp[1] < floor:
        return None
    ep_pct, lp_pct = round(100 * ep[0] / ep[1], 1), round(100 * lp[0] / lp[1], 1)
    diff = lp_pct - ep_pct
    severity = 3 if diff <= profile.positional_severe else 2 if diff <= profile.positional_moderate else None
    if severity is None:
        return None
    return {
        "tag": POSITIONAL_TAG, "kind": "stat", "severity": severity,
        "evidence": {"stat": POSITIONAL_TAG, "ep_pct": ep_pct, "lp_pct": lp_pct, "n": ep[0] + lp[0], "d": ep[1] + lp[1]},
    }


def severity_for_stat_tag(tag: str, display: dict, profile_key: str | None = None) -> dict | None:
    profile = get_threshold_profile(profile_key)
    if tag not in ALL_STAT_TAGS:
        raise ValueError(f"Unknown stat tag: {tag}")
    if tag not in profile.enabled_stat_tags:
        return None
    if tag == GAP_TAG:
        return _severity_limps_too_wide(display, profile)
    if tag == POSITIONAL_TAG:
        return _severity_positional_looseness(display, profile)
    if tag in STAT_THRESHOLDS:
        return _severity_single_stat(tag, display, profile)
    raise ValueError(f"Unknown stat tag: {tag}")


def severity_for_judgment_count(n: int) -> int:
    if n <= 1:
        return 1
    if n <= 3:
        return 2
    return 3


def sample_status(display: dict, profile_key: str | None = None) -> dict:
    """Return deterministic sample-readiness metadata for report rendering."""
    profile = get_threshold_profile(profile_key)
    groups: list[tuple[str, tuple[str, ...]]] = [
        ("VPIP / PFR", ("low_vpip", "high_vpip", GAP_TAG)),
        ("3-bet", ("under_3bet", "over_3bet")),
        ("Fold to 3-bet", ("overfolds_to_3bet",)),
        ("Postflop aggression", ("too_passive_postflop", "too_aggressive_postflop")),
        ("WTSD", ("overplays_to_showdown", "underplays_to_showdown")),
        ("W$SD", ("weak_at_showdown",)),
        ("Positional VPIP", (POSITIONAL_TAG,)),
    ]
    for street in _POSTFLOP_STREETS:
        groups.extend([
            (f"{street.title()} C-bet", (f"under_cbet_{street}", f"over_cbet_{street}")),
            (f"Fold to {street.title()} C-bet", (f"overfolds_to_cbet_{street}",)),
        ])

    metrics = []
    for label, tags in groups:
        enabled = [tag for tag in tags if tag in profile.enabled_stat_tags]
        if not enabled:
            continue
        observed_values = [stat_tag_opportunity(tag, display) for tag in enabled]
        observed = min((value for value in observed_values if value is not None), default=0)
        required = max(profile.minimum_opportunities[tag] for tag in enabled)
        metric = {
            "metric": label,
            "observed": observed,
            "required": required,
            "status": "ready" if observed >= required else "insufficient_sample",
        }
        if label == "VPIP / PFR" and display.get("by_table_size"):
            segments = [
                {
                    "table_size": int(table_size),
                    "observed": int((segment.get("vpip") or {}).get("d", 0)),
                }
                for table_size, segment in display["by_table_size"].items()
            ]
            segments.sort(key=lambda item: item["table_size"], reverse=True)
            metric["segments"] = segments
            metric["observed"] = max((item["observed"] for item in segments), default=0)
            metric["status"] = "ready" if metric["observed"] >= required else "insufficient_sample"
        metrics.append(metric)
    return {"profile": profile.key, "version": profile.version, "metrics": metrics}
