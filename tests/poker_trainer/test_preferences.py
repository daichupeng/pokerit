import pytest

from poker_trainer.preferences import (
    DEFAULT_POSTFLOP_QUICK,
    DEFAULT_PREFLOP_QUICK,
    DEFAULT_SHOWDOWN_VISIBILITY,
    bet_shortcuts_from_preferences,
    merge_preferences,
    showdown_visibility_from_preferences,
)


def test_default_shortcuts_cover_common_open_and_three_bet_sizes():
    assert DEFAULT_PREFLOP_QUICK == [2.0, 2.5, 6.0, 7.5]
    assert bet_shortcuts_from_preferences({}) == (
        DEFAULT_PREFLOP_QUICK,
        DEFAULT_POSTFLOP_QUICK,
    )


def test_merge_preserves_unrelated_preferences():
    merged = merge_preferences(
        {"theme": "dark"},
        {"bet_shortcuts_v1": {"preflop": [2, 6], "postflop": [25, 75]}},
    )
    assert merged["theme"] == "dark"
    assert merged["bet_shortcuts_v1"] == {
        "preflop": [2.0, 6.0], "postflop": [25.0, 75.0],
    }


def test_empty_shortcut_row_is_rejected():
    with pytest.raises(ValueError):
        merge_preferences({}, {"bet_shortcuts_v1": {"preflop": [], "postflop": [50]}})


def test_showdown_visibility_defaults_to_realistic_and_round_trips_training():
    assert showdown_visibility_from_preferences({}) == DEFAULT_SHOWDOWN_VISIBILITY
    assert showdown_visibility_from_preferences({"showdown_visibility_v1": "unknown"}) == "realistic"

    merged = merge_preferences(
        {"theme": "dark"},
        {"showdown_visibility_v1": "training"},
    )

    assert merged == {"theme": "dark", "showdown_visibility_v1": "training"}


def test_invalid_showdown_visibility_is_rejected():
    with pytest.raises(ValueError):
        merge_preferences({}, {"showdown_visibility_v1": "reveal-folded"})
