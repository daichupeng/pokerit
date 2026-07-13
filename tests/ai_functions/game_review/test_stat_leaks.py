"""Tests for detect_stat_leaks over a crafted to_display()-shaped dict."""

from __future__ import annotations

from ai_functions.game_review.stat_leaks import detect_stat_leaks


def _stat(pct=None, ratio=None, n=0, d=100):
    out = {"n": n, "d": d}
    if pct is not None:
        out["pct"] = pct
    if ratio is not None:
        out["ratio"] = ratio
    return out


def _healthy_display():
    return {
        "vpip": _stat(pct=25, n=25, d=100),
        "pfr": _stat(pct=20, n=20, d=100),
        "three_bet": _stat(pct=7, n=7, d=100),
        "fold_to_3bet": _stat(pct=50, n=5, d=10),
        "wtsd": _stat(pct=27, n=27, d=100),
        "wsd": _stat(pct=50, n=10, d=20),
        "aggression_factor": _stat(ratio=2.0, n=20, d=10),
        "cbet": {
            "flop": _stat(pct=60, n=6, d=10),
            "turn": _stat(pct=60, n=6, d=10),
            "river": _stat(pct=60, n=6, d=10),
        },
        "fold_to_cbet": {
            "flop": _stat(pct=50, n=5, d=10),
            "turn": _stat(pct=50, n=5, d=10),
            "river": _stat(pct=50, n=5, d=10),
        },
        "by_position": {},
    }


def test_healthy_display_yields_no_leaks():
    assert detect_stat_leaks(_healthy_display()) == []


def test_low_vpip_is_detected_exactly_once():
    display = _healthy_display()
    display["vpip"] = _stat(pct=10, n=10, d=100)
    leaks = detect_stat_leaks(display)
    tags = [leak["tag"] for leak in leaks]
    assert tags.count("low_vpip") == 1
    leak = next(leak for leak in leaks if leak["tag"] == "low_vpip")
    assert leak["kind"] == "stat"
    assert leak["severity"] == 3


def test_multiple_leaks_all_detected():
    display = _healthy_display()
    display["vpip"] = _stat(pct=45, n=45, d=100)
    display["three_bet"] = _stat(pct=15, n=15, d=100)
    leaks = detect_stat_leaks(display)
    tags = {leak["tag"] for leak in leaks}
    assert "high_vpip" in tags
    assert "over_3bet" in tags
