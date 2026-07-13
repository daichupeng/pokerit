"""Stat trends — compute-on-read over the last K folded evaluations' stored
``stats_snapshot``s. Pure function, no storage: trends are never persisted,
just recomputed whenever the coaching profile is read (see the feature
spec's "Stat trends are NOT stored" decision).
"""

from __future__ import annotations

K = 10

# The stats a hero-facing trend view cares about — the same top-level keys
# leak_taxonomy.py already thresholds, read directly off to_display() output.
_TREND_STATS = (
    ("vpip", "pct"),
    ("pfr", "pct"),
    ("three_bet", "pct"),
    ("fold_to_3bet", "pct"),
    ("aggression_factor", "ratio"),
    ("wtsd", "pct"),
    ("wsd", "pct"),
)

_FLAT_EPSILON = 1e-9


def _direction(series: list[float]) -> str:
    if len(series) < 2:
        return "flat"
    delta = series[-1] - series[0]
    if abs(delta) < _FLAT_EPSILON:
        return "flat"
    return "up" if delta > 0 else "down"


def compute_trends(snapshots: list[dict]) -> dict[str, dict]:
    """``snapshots`` is a chronologically-ordered list of game-level
    ``to_display()`` dicts (oldest first) — callers pass the last ``K``
    folded evaluations' snapshots. Returns, per stat name, ``{"series":
    [{"value", "n", "d"}, ...], "direction": "up"|"down"|"flat"}``, skipping
    a stat entirely for evaluations where it wasn't recorded.
    """
    windowed = snapshots[-K:]
    trends = {}
    for stat_name, value_key in _TREND_STATS:
        series = []
        for snapshot in windowed:
            node = snapshot.get(stat_name)
            if not node or value_key not in node:
                continue
            series.append({"value": node[value_key], "n": node.get("n"), "d": node.get("d")})
        if not series:
            continue
        trends[stat_name] = {
            "series": series,
            "direction": _direction([point["value"] for point in series]),
        }
    return trends
