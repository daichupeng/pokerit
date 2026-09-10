from poker_engine.config import GameConfig, SeatKind, SeatSpec
from types import SimpleNamespace

from poker_engine.scenarios import (
    SCENARIO_PRESETS,
    get_scenario_preset,
    profile_scope_for_game,
    profile_scope_for_settings,
)


def _seats():
    return [
        SeatSpec(name="Hero", kind=SeatKind.HUMAN),
        SeatSpec(name="Bot", kind=SeatKind.TAG),
    ]


def test_requested_presets_have_expected_stack_depth_and_bb_ante():
    assert SCENARIO_PRESETS["cash_6max_100bb"].buy_in / SCENARIO_PRESETS["cash_6max_100bb"].big_blind == 100
    assert SCENARIO_PRESETS["cash_8max_100bb"].buy_in / SCENARIO_PRESETS["cash_8max_100bb"].big_blind == 100
    assert SCENARIO_PRESETS["mtt_8max_40bb"].buy_in / SCENARIO_PRESETS["mtt_8max_40bb"].big_blind == 40
    assert SCENARIO_PRESETS["mtt_8max_25bb"].buy_in / SCENARIO_PRESETS["mtt_8max_25bb"].big_blind == 25
    assert SCENARIO_PRESETS["mtt_8max_15bb"].buy_in / SCENARIO_PRESETS["mtt_8max_15bb"].big_blind == 15
    assert all(
        preset.ante_type == "big_blind" and preset.ante == preset.big_blind
        for key, preset in SCENARIO_PRESETS.items()
        if key.startswith("mtt_")
    )
    assert SCENARIO_PRESETS["cash_6max_100bb"].num_bots == 5
    assert all(
        preset.num_bots == 7
        for key, preset in SCENARIO_PRESETS.items()
        if key != "cash_6max_100bb"
    )


def test_legacy_scenario_keys_resolve_to_new_presets():
    assert get_scenario_preset("cash_100bb").key == "cash_6max_100bb"
    assert get_scenario_preset("mtt_40bb").key == "mtt_8max_40bb"


def test_historical_mtt_game_keeps_its_legacy_profile_scope():
    game = SimpleNamespace(
        scenario="mtt_40bb", profile_scope="mtt_25_40bb", rule={},
        game_format="tournament", buy_in=4000, big_blind=100,
    )
    assert profile_scope_for_game(game) == "mtt_25_40bb"


def test_big_blind_ante_is_assigned_only_to_bb_in_sb_first_order():
    config = GameConfig(
        small_blind=50,
        buy_in=2500,
        seats=_seats(),
        ante=100,
        ante_type="big_blind",
        game_format="tournament",
    )
    assert config.raw_antes(6) == (0, 100, 0, 0, 0, 0)
    assert config.ante_trimming_status is False


def test_custom_settings_use_custom_profile_scope():
    assert profile_scope_for_settings(
        game_format="tournament", buy_in=1500, big_blind=100
    ) == "custom"
    assert profile_scope_for_settings(
        game_format="tournament", buy_in=2500, big_blind=100
    ) == "custom"
