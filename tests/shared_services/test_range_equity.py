from __future__ import annotations

from itertools import combinations

from shared_services.range_equity import calculate_range_equity


def test_exact_river_equity_records_assumptions_and_provenance():
    result = calculate_range_equity(
        ["As", "Ks"],
        ["Qs", "Js", "Ts", "2d", "3c"],
        [
            {"label": "sets", "hands": [{"hand": "QQ"}, {"hand": "JJ"}]},
            {"label": "two pair", "hands": [{"hand": "QJo"}]},
        ],
    )

    assert result["status"] == "ok"
    assert result["calculator"]["method"] == "exact_enumeration"
    assert result["calculator"]["enumerated_outcomes"] > 0
    assert [scenario["equity_pct"] for scenario in result["scenarios"]] == [100.0, 100.0]
    assert result["scenario_equity_interval_pct"] == {
        "low": 100.0,
        "high": 100.0,
        "basis": "minimum_and_maximum_across_supplied_range_scenarios",
    }
    assert result["range_definition_source"] == "explicit_tool_input_assumption"
    assert result["provenance"]["range_assumptions_are_recorded_facts"] is False
    assert result["provenance"]["calculator_consumed_preflop_strategy_api"] is False


def test_range_expansion_removes_known_blockers():
    result = calculate_range_equity(
        ["9c", "6c"],
        ["9h", "Th", "7c", "Qc"],
        [{"label": "set", "hands": [{"hand": "99"}]}],
    )

    scenario = result["scenarios"][0]
    assert result["status"] == "ok"
    assert scenario["combo_count"] == 1
    assert scenario["blocked_combo_count"] == 5
    assert scenario["outcomes_evaluated"] == 44


def test_turn_scenario_interval_is_derived_from_exact_scenario_results():
    result = calculate_range_equity(
        ["9c", "6c"],
        ["9h", "Th", "7c", "Qc"],
        [
            {
                "label": "value-heavy",
                "hands": [
                    {"hand": "QQ"}, {"hand": "TT"}, {"hand": "77"},
                    {"hand": "AQo"},
                ],
            },
            {
                "label": "draw-heavy",
                "hands": [
                    {"hand": "AhKh"}, {"hand": "KhJh"}, {"hand": "J8s"},
                ],
            },
        ],
    )

    equities = [scenario["equity_pct"] for scenario in result["scenarios"]]
    assert result["status"] == "ok"
    assert result["scenario_equity_interval_pct"]["low"] == min(equities)
    assert result["scenario_equity_interval_pct"]["high"] == max(equities)
    assert result["calculator"]["enumerated_outcomes"] == sum(
        scenario["outcomes_evaluated"] for scenario in result["scenarios"]
    )


def test_unsupported_range_syntax_fails_closed():
    result = calculate_range_equity(
        ["As", "Kd"],
        ["Qs", "Jh", "2c"],
        [{"label": "unsupported", "hands": [{"hand": "TT+"}]}],
    )

    assert result["status"] == "error"
    assert result["error"] == "unsupported_range_token:TT+"


def test_malformed_scenario_fails_closed():
    result = calculate_range_equity(
        ["As", "Kd"], ["Qs", "Jh", "2c"], ["not-a-scenario"],
    )

    assert result["status"] == "error"
    assert result["error"] == "invalid_scenario"


def test_scenario_label_cannot_imply_solver_or_provider_provenance():
    for label in ("solver range", "GTO baseline", "PokerAI postflop"):
        result = calculate_range_equity(
            ["As", "Kd"],
            ["Qs", "Jh", "2c"],
            [{"label": label, "hands": [{"hand": "QQ"}]}],
        )

        assert result["status"] == "error"
        assert result["error"] == "invalid_or_duplicate_scenario_label"


def test_overly_broad_flop_calculation_fails_closed():
    rank_pairs = list(combinations("23456789TJQKA", 2))[:50]
    hands = [{"hand": f"{first}{second}o"} for first, second in rank_pairs]

    result = calculate_range_equity(
        ["As", "Kd"],
        ["Qs", "Jh", "2c"],
        [{"label": "too broad", "hands": hands}],
    )

    assert result["status"] == "error"
    assert result["error"].startswith("calculation_too_large:")
