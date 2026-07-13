"""Severity boundary tests for leak_taxonomy.py."""

from __future__ import annotations

from ai_functions.game_review import leak_taxonomy


def _stat(pct=None, ratio=None, n=0, d=10):
    out = {"n": n, "d": d}
    if pct is not None:
        out["pct"] = pct
    if ratio is not None:
        out["ratio"] = ratio
    return out


def _base_display(**overrides):
    display = {
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
    display.update(overrides)
    return display


def test_low_vpip_severe():
    display = _base_display(vpip=_stat(pct=10, n=10, d=100))
    leak = leak_taxonomy.severity_for_stat_tag("low_vpip", display)
    assert leak == {
        "tag": "low_vpip", "kind": "stat", "severity": 3,
        "evidence": {"stat": "low_vpip", "pct": 10, "n": 10, "d": 100},
    }


def test_low_vpip_moderate():
    display = _base_display(vpip=_stat(pct=18, n=18, d=100))
    leak = leak_taxonomy.severity_for_stat_tag("low_vpip", display)
    assert leak["severity"] == 2


def test_vpip_in_healthy_band_is_none():
    display = _base_display(vpip=_stat(pct=25, n=25, d=100))
    assert leak_taxonomy.severity_for_stat_tag("low_vpip", display) is None
    assert leak_taxonomy.severity_for_stat_tag("high_vpip", display) is None


def test_high_vpip_severe():
    display = _base_display(vpip=_stat(pct=40, n=40, d=100))
    leak = leak_taxonomy.severity_for_stat_tag("high_vpip", display)
    assert leak["severity"] == 3


def test_under_cbet_flop_moderate():
    display = _base_display(cbet={
        "flop": _stat(pct=45, n=9, d=20),
        "turn": _stat(pct=60, n=6, d=10),
        "river": _stat(pct=60, n=6, d=10),
    })
    leak = leak_taxonomy.severity_for_stat_tag("under_cbet_flop", display)
    assert leak["severity"] == 2
    assert leak["evidence"]["stat"] == "under_cbet_flop"


def test_min_opportunity_floor_suppresses_tag():
    display = _base_display(vpip=_stat(pct=10, n=2, d=4))
    assert leak_taxonomy.severity_for_stat_tag("low_vpip", display) is None


def test_too_passive_postflop_uses_ratio_not_pct():
    display = _base_display(aggression_factor=_stat(ratio=0.5, n=5, d=10))
    leak = leak_taxonomy.severity_for_stat_tag("too_passive_postflop", display)
    assert leak["severity"] == 3
    assert leak["evidence"]["ratio"] == 0.5


def test_limps_too_wide_severe():
    display = _base_display(
        vpip=_stat(pct=30, n=30, d=100),
        pfr=_stat(pct=15, n=15, d=100),
    )
    leak = leak_taxonomy.severity_for_stat_tag("limps_too_wide", display)
    assert leak["severity"] == 3
    assert leak["evidence"]["pct"] == 15.0


def test_limps_too_wide_none_when_gap_small():
    display = _base_display(
        vpip=_stat(pct=25, n=25, d=100),
        pfr=_stat(pct=22, n=22, d=100),
    )
    assert leak_taxonomy.severity_for_stat_tag("limps_too_wide", display) is None


def test_positional_looseness_severe_when_ep_not_tighter():
    display = _base_display(by_position={
        "UTG": {"vpip": _stat(pct=30, n=30, d=100)},
        "BTN": {"vpip": _stat(pct=25, n=25, d=100)},
    })
    leak = leak_taxonomy.severity_for_stat_tag("positional_looseness", display)
    assert leak["severity"] == 3


def test_positional_looseness_none_when_ep_much_tighter():
    display = _base_display(by_position={
        "UTG": {"vpip": _stat(pct=12, n=12, d=100)},
        "BTN": {"vpip": _stat(pct=40, n=40, d=100)},
    })
    assert leak_taxonomy.severity_for_stat_tag("positional_looseness", display) is None


def test_positional_looseness_none_without_position_data():
    display = _base_display(by_position={})
    assert leak_taxonomy.severity_for_stat_tag("positional_looseness", display) is None


def test_severity_for_judgment_count():
    assert leak_taxonomy.severity_for_judgment_count(1) == 1
    assert leak_taxonomy.severity_for_judgment_count(2) == 2
    assert leak_taxonomy.severity_for_judgment_count(3) == 2
    assert leak_taxonomy.severity_for_judgment_count(4) == 3
    assert leak_taxonomy.severity_for_judgment_count(10) == 3


def test_unknown_tag_raises():
    import pytest

    with pytest.raises(ValueError):
        leak_taxonomy.severity_for_stat_tag("not_a_real_tag", _base_display())


def test_stat_tag_opportunity_single_stat():
    display = _base_display(vpip=_stat(pct=25, n=25, d=42))
    assert leak_taxonomy.stat_tag_opportunity("low_vpip", display) == 42
    assert leak_taxonomy.stat_tag_opportunity("high_vpip", display) == 42


def test_stat_tag_opportunity_none_when_stat_missing():
    display = _base_display()
    del display["vpip"]
    assert leak_taxonomy.stat_tag_opportunity("low_vpip", display) is None


def test_stat_tag_opportunity_gap_tag_uses_vpip_denominator():
    display = _base_display(vpip=_stat(pct=25, n=25, d=77))
    assert leak_taxonomy.stat_tag_opportunity("limps_too_wide", display) == 77


def test_stat_tag_opportunity_positional_tag_uses_min_of_ep_lp():
    display = _base_display(by_position={
        "UTG": {"vpip": _stat(pct=15, n=3, d=20)},
        "BTN": {"vpip": _stat(pct=40, n=8, d=50)},
    })
    assert leak_taxonomy.stat_tag_opportunity("positional_looseness", display) == 20


def test_stat_tag_opportunity_positional_tag_none_without_position_data():
    display = _base_display(by_position={})
    assert leak_taxonomy.stat_tag_opportunity("positional_looseness", display) is None


def test_stat_tag_opportunity_unknown_tag_raises():
    import pytest

    with pytest.raises(ValueError):
        leak_taxonomy.stat_tag_opportunity("not_a_real_tag", _base_display())
