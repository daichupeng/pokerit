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
        "limp": _stat(pct=5, n=5, d=100),
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


def test_vpip_leak_uses_per_hand_table_size_profile_instead_of_mixed_average():
    display = _healthy_display()
    display["vpip"] = _stat(pct=19, n=19, d=100)
    display["by_table_size"] = {
        "8": {**_healthy_display(), "vpip": _stat(pct=19, n=9, d=50)},
        "6": {**_healthy_display(), "vpip": _stat(pct=18, n=9, d=50)},
    }

    leaks = detect_stat_leaks(display, "cash_8max_100bb")
    low_vpip = next(leak for leak in leaks if leak["tag"] == "low_vpip")

    # 19% is healthy for the 8-max profile; 18% is moderate-low for 6-max.
    assert low_vpip["severity"] == 2
    assert low_vpip["evidence"]["table_size"] == 6
    assert low_vpip["evidence"]["profile"] == "cash_6max_100bb"


def test_short_handed_mtt_vpip_is_descriptive_until_profile_exists():
    display = _healthy_display()
    display["by_table_size"] = {
        "6": {**_healthy_display(), "vpip": _stat(pct=5, n=1, d=20)},
    }

    tags = {leak["tag"] for leak in detect_stat_leaks(display, "mtt_8max_25bb")}
    assert "low_vpip" not in tags
