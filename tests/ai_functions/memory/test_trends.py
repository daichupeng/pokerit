"""Tests for trends.py (src/ai_functions/memory/trends.py). Pure function
over already-stored to_display() snapshots — hand-computed expected values."""

from __future__ import annotations

from ai_functions.memory.trends import K, compute_trends


def _snapshot(vpip_pct, n=20, d=100):
    return {"vpip": {"pct": vpip_pct, "n": n, "d": d}}


def test_series_and_direction_up():
    snapshots = [_snapshot(20), _snapshot(25), _snapshot(30)]
    trends = compute_trends(snapshots)
    assert trends["vpip"]["series"] == [
        {"value": 20, "n": 20, "d": 100},
        {"value": 25, "n": 20, "d": 100},
        {"value": 30, "n": 20, "d": 100},
    ]
    assert trends["vpip"]["direction"] == "up"


def test_direction_down():
    trends = compute_trends([_snapshot(30), _snapshot(20)])
    assert trends["vpip"]["direction"] == "down"


def test_direction_flat_when_unchanged():
    trends = compute_trends([_snapshot(25), _snapshot(25)])
    assert trends["vpip"]["direction"] == "flat"


def test_direction_flat_with_single_point():
    trends = compute_trends([_snapshot(25)])
    assert trends["vpip"]["direction"] == "flat"


def test_only_last_k_snapshots_used():
    snapshots = [_snapshot(v) for v in range(K + 5)]
    trends = compute_trends(snapshots)
    assert len(trends["vpip"]["series"]) == K
    assert trends["vpip"]["series"][0]["value"] == 5
    assert trends["vpip"]["series"][-1]["value"] == K + 4


def test_stat_missing_from_snapshot_is_skipped():
    trends = compute_trends([{"pfr": {"pct": 20, "n": 20, "d": 100}}])
    assert "vpip" not in trends
    assert "pfr" in trends


def test_empty_snapshots_yields_empty_trends():
    assert compute_trends([]) == {}
