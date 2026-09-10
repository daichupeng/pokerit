from ai_functions.game_review.leak_taxonomy import get_threshold_profile
from ai_functions.history_evaluation.analytics import (
    compare_latest_to_baseline,
    enabled_metric_specs,
)


def _display(vpip_pct: float, hands: int = 100) -> dict:
    stat = lambda pct=0, n=0, d=0: {"pct": pct, "n": n, "d": d}
    return {
        "vpip": stat(vpip_pct, round(vpip_pct * hands / 100), hands),
        "pfr": stat(20, 20, hands),
        "limp": stat(5, 5, hands),
        "open_limp": stat(3, 3, hands),
        "three_bet": stat(7, 7, 100),
        "fold_to_3bet": stat(50, 10, 20),
        "aggression_factor": {"ratio": 2.0, "infinite": False, "n": 20, "d": 10},
        "wtsd": stat(27, 27, 100),
        "wsd": stat(50, 10, 20),
        "cbet": {street: stat(60, 20, 30) for street in ("flop", "turn", "river")},
        "fold_to_cbet": {street: stat(50, 15, 30) for street in ("flop", "turn", "river")},
        "open_shove": stat(20, 4, 20),
        "reshove": stat(20, 4, 20),
        "call_off": stat(50, 10, 20),
        "by_position": {
            "UTG": {"vpip": stat(20, 4, 20)},
            "BTN": {"vpip": stat(30, 6, 20)},
        },
    }


def _trend(comparisons: list[dict], metric: str) -> dict:
    return next(item for item in comparisons if item["metric"] == metric)


def test_high_vpip_moving_toward_healthy_range_is_improving():
    profile = get_threshold_profile("cash_6max_100bb")
    result = compare_latest_to_baseline(_display(35), _display(45), profile)
    assert _trend(result, "vpip")["trend_status"] == "improving"
    assert _trend(result, "vpip")["delta"] == -10


def test_low_vpip_moving_further_down_is_worsening():
    profile = get_threshold_profile("cash_6max_100bb")
    result = compare_latest_to_baseline(_display(10), _display(15), profile)
    assert _trend(result, "vpip")["trend_status"] == "worsening"


def test_trend_requires_both_samples():
    profile = get_threshold_profile("cash_6max_100bb")
    result = compare_latest_to_baseline(_display(35, hands=4), _display(45), profile)
    assert _trend(result, "vpip")["trend_status"] == "insufficient_sample"


def test_push_fold_profile_excludes_postflop_and_adds_frequency_only_metrics():
    profile = get_threshold_profile("mtt_8max_15bb")
    names = {spec.metric for spec in enabled_metric_specs(profile)}
    assert {"open_shove", "reshove", "call_off"} <= names
    assert "aggression_factor" not in names
    assert "cbet_flop" not in names


def test_positional_gap_requires_ep_and_lp_samples_and_is_direction_aware():
    profile = get_threshold_profile("cash_6max_100bb")
    current = _display(25)
    baseline = _display(25)
    current["by_position"]["BTN"]["vpip"] = {"pct": 35, "n": 7, "d": 20}
    baseline["by_position"]["BTN"]["vpip"] = {"pct": 20, "n": 4, "d": 20}

    trend = _trend(compare_latest_to_baseline(current, baseline, profile), "positional_gap")
    assert trend["current"]["value"] == 15.0
    assert trend["baseline"]["value"] == 0.0
    assert trend["trend_status"] == "improving"


def test_infinite_af_with_enough_actions_is_not_mislabeled_insufficient():
    profile = get_threshold_profile("cash_6max_100bb")
    current = _display(25)
    baseline = _display(25)
    current["aggression_factor"] = {"ratio": None, "infinite": True, "n": 25, "d": 0}
    baseline["aggression_factor"] = {"ratio": 2.0, "infinite": False, "n": 25, "d": 10}

    trend = _trend(compare_latest_to_baseline(current, baseline, profile), "aggression_factor")
    assert trend["trend_status"] == "worsening"
    assert trend["delta"] is None
