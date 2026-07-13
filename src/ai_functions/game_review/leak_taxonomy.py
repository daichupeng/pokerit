"""Leak taxonomy and severity rules for the game-evaluation pipeline.

Every threshold used anywhere in the ``game_review`` pipeline lives in this
one module. ``stat_leaks.py`` (and, later, ``merge.py``) call into the
functions here rather than hardcoding any number of their own.

Two independent tag families:

- **Stat-derived tags** — computed purely from Phase 1's ``stats.to_display()``
  output. Severity is a severe/moderate band lookup, except for two tags
  (``limps_too_wide``, ``positional_looseness``) that compare two stats
  instead of thresholding one.
- **Judgment tags** — identified by the (future) street-review LLM agents;
  severity here is purely a function of how many times a tag was cited
  across the whole game.

Defaults below are for 6-max cash and are expected to be tuned later — the
*structure* (one file, one lookup path per tag, an explicit minimum-
opportunity floor) is the part that must not move.
"""

from __future__ import annotations

from dataclasses import dataclass

JUDGMENT_TAGS = frozenset({
    "missed_value_bet",
    "bad_bluff_spot",
    "inconsistent_sizing",
    "slowplay_risk",
    "missed_fold",
})

# Below this many opportunities (the stat's own denominator), a stat-derived
# tag is not evaluated/reported for this game. Applies only to leak-severity
# scoring — never to Phase 1's display layer, which always shows every stat
# with its raw counts regardless of sample size.
MIN_OPPORTUNITY_FLOOR = 5

# Position-group membership used only by the ``positional_looseness`` tag.
# Not a general position taxonomy — just the two buckets this one comparison
# needs, matching the labels produced by ``shared_services.hand_formatter``.
EP_POSITIONS = frozenset({"UTG", "UTG+1", "UTG+2"})
LP_POSITIONS = frozenset({"BTN", "CO"})

_POSTFLOP_STREETS = ("flop", "turn", "river")


@dataclass(frozen=True)
class StatThreshold:
    """One single-stat severity rule.

    ``path`` navigates a ``to_display()`` dict down to the sub-dict holding
    the stat (e.g. ``("vpip",)`` or ``("cbet", "flop")``); ``value_key`` picks
    the field to threshold (``"pct"`` or ``"ratio"``); the sub-dict's ``"d"``
    key is used for the minimum-opportunity floor.

    ``direction="low"``: severe when value < ``severe_bound``; moderate when
    ``severe_bound <= value <= moderate_bound`` (``severe_bound < moderate_bound``).
    ``direction="high"``: severe when value > ``severe_bound``; moderate when
    ``moderate_bound <= value <= severe_bound`` (``moderate_bound < severe_bound``).
    """

    path: tuple[str, ...]
    value_key: str
    direction: str
    severe_bound: float
    moderate_bound: float


STAT_THRESHOLDS: dict[str, StatThreshold] = {
    "low_vpip": StatThreshold(("vpip",), "pct", "low", severe_bound=16, moderate_bound=20),
    "high_vpip": StatThreshold(("vpip",), "pct", "high", severe_bound=38, moderate_bound=30),
    "under_3bet": StatThreshold(("three_bet",), "pct", "low", severe_bound=3, moderate_bound=5),
    "over_3bet": StatThreshold(("three_bet",), "pct", "high", severe_bound=13, moderate_bound=9),
    "overfolds_to_3bet": StatThreshold(("fold_to_3bet",), "pct", "high", severe_bound=75, moderate_bound=65),
    "too_passive_postflop": StatThreshold(("aggression_factor",), "ratio", "low", severe_bound=1.0, moderate_bound=1.5),
    "too_aggressive_postflop": StatThreshold(("aggression_factor",), "ratio", "high", severe_bound=4.5, moderate_bound=3.0),
    "overplays_to_showdown": StatThreshold(("wtsd",), "pct", "high", severe_bound=36, moderate_bound=30),
    "underplays_to_showdown": StatThreshold(("wtsd",), "pct", "low", severe_bound=18, moderate_bound=24),
    "weak_at_showdown": StatThreshold(("wsd",), "pct", "low", severe_bound=40, moderate_bound=48),
}

for _street in _POSTFLOP_STREETS:
    STAT_THRESHOLDS[f"under_cbet_{_street}"] = StatThreshold(
        ("cbet", _street), "pct", "low", severe_bound=40, moderate_bound=55
    )
    STAT_THRESHOLDS[f"over_cbet_{_street}"] = StatThreshold(
        ("cbet", _street), "pct", "high", severe_bound=80, moderate_bound=70
    )
    STAT_THRESHOLDS[f"overfolds_to_cbet_{_street}"] = StatThreshold(
        ("fold_to_cbet", _street), "pct", "high", severe_bound=65, moderate_bound=55
    )

# Two-stat comparison tags, handled outside the generic single-threshold path.
GAP_TAG = "limps_too_wide"
POSITIONAL_TAG = "positional_looseness"

ALL_STAT_TAGS = frozenset(STAT_THRESHOLDS) | {GAP_TAG, POSITIONAL_TAG}


def _get_path(display: dict, path: tuple[str, ...]) -> dict | None:
    node = display
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


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


def _severity_single_stat(tag: str, display: dict) -> dict | None:
    threshold = STAT_THRESHOLDS[tag]
    node = _get_path(display, threshold.path)
    if node is None or node.get("d", 0) < MIN_OPPORTUNITY_FLOOR:
        return None
    value = node.get(threshold.value_key)
    if value is None:
        return None
    severity = _severity_from_bounds(value, threshold.direction, threshold.severe_bound, threshold.moderate_bound)
    if severity is None:
        return None
    return {
        "tag": tag,
        "kind": "stat",
        "severity": severity,
        "evidence": {"stat": tag, threshold.value_key: value, "n": node.get("n"), "d": node["d"]},
    }


def _severity_limps_too_wide(display: dict) -> dict | None:
    vpip = display.get("vpip")
    pfr = display.get("pfr")
    if not vpip or not pfr or vpip.get("d", 0) < MIN_OPPORTUNITY_FLOOR:
        return None
    gap = vpip["pct"] - pfr["pct"]
    severity = None
    if gap > 10:
        severity = 3
    elif 6 <= gap <= 10:
        severity = 2
    if severity is None:
        return None
    return {
        "tag": GAP_TAG,
        "kind": "stat",
        "severity": severity,
        "evidence": {"stat": GAP_TAG, "pct": round(gap, 1), "n": vpip["n"] - pfr["n"], "d": vpip["d"]},
    }


def _combined_position_vpip(display: dict, positions: frozenset[str]) -> tuple[int, int] | None:
    by_position = display.get("by_position") or {}
    n = d = 0
    found = False
    for pos, pos_display in by_position.items():
        if pos not in positions:
            continue
        vpip = pos_display.get("vpip")
        if not vpip:
            continue
        n += vpip["n"]
        d += vpip["d"]
        found = True
    if not found:
        return None
    return n, d


def _severity_positional_looseness(display: dict) -> dict | None:
    ep = _combined_position_vpip(display, EP_POSITIONS)
    lp = _combined_position_vpip(display, LP_POSITIONS)
    if ep is None or lp is None:
        return None
    ep_n, ep_d = ep
    lp_n, lp_d = lp
    if ep_d < MIN_OPPORTUNITY_FLOOR or lp_d < MIN_OPPORTUNITY_FLOOR:
        return None
    ep_pct = round(100 * ep_n / ep_d, 1)
    lp_pct = round(100 * lp_n / lp_d, 1)
    diff = lp_pct - ep_pct  # positive = EP tighter than LP, as expected
    severity = None
    if diff <= 0:
        severity = 3
    elif diff <= 5:
        severity = 2
    if severity is None:
        return None
    return {
        "tag": POSITIONAL_TAG,
        "kind": "stat",
        "severity": severity,
        "evidence": {"stat": POSITIONAL_TAG, "ep_pct": ep_pct, "lp_pct": lp_pct, "n": ep_n + lp_n, "d": ep_d + lp_d},
    }


def severity_for_stat_tag(tag: str, display: dict) -> dict | None:
    """Return the merged leak-tag dict for ``tag`` given a ``to_display()`` dict, or ``None``."""
    if tag == GAP_TAG:
        return _severity_limps_too_wide(display)
    if tag == POSITIONAL_TAG:
        return _severity_positional_looseness(display)
    if tag in STAT_THRESHOLDS:
        return _severity_single_stat(tag, display)
    raise ValueError(f"Unknown stat tag: {tag}")


def severity_for_judgment_count(n: int) -> int:
    """Judgment-tag severity from occurrence count across the whole game."""
    if n <= 1:
        return 1
    if n <= 3:
        return 2
    return 3
