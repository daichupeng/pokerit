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


def test_custom_scope_isolates_format_seats_depth_and_ante_without_rounding():
    from poker_engine.scenarios import is_custom_profile_scope
    settings = dict(game_format="cash", buy_in=10000, big_blind=100,
                    num_players=6, ante=0, ante_type="none")
    baseline = profile_scope_for_settings(**settings)
    assert is_custom_profile_scope(baseline)
    assert len(baseline) <= 40
    for changes in [dict(game_format="tournament"), dict(num_players=8),
                    dict(buy_in=10001), dict(ante=100, ante_type="big_blind"),
                    dict(tournament_stage="standard")]:
        assert profile_scope_for_settings(**{**settings, **changes}) != baseline
    assert profile_scope_for_settings(**{**settings, "buy_in": 20000, "big_blind": 200}) == baseline
    assert baseline != "cash_6max_100bb"


def test_legacy_custom_games_derive_scopes_from_saved_settings():
    from uuid import uuid4
    base = dict(id=uuid4(), scenario="custom", profile_scope="custom", rule={},
                game_format="cash", buy_in=10000, big_blind=100,
                players=[object()] * 6, ante=0, ante_type="none")
    cash = profile_scope_for_game(SimpleNamespace(**base))
    mtt = profile_scope_for_game(SimpleNamespace(**{**base, "game_format": "tournament"}))
    assert cash != mtt
    assert cash == profile_scope_for_settings(game_format="cash", buy_in=10000,
                                             big_blind=100, num_players=6)


def test_custom_statistics_do_not_apply_uncalibrated_leak_thresholds():
    from ai_functions.game_review.leak_taxonomy import get_threshold_profile, threshold_profile_key_for_game
    from ai_functions.game_review.stat_leaks import detect_stat_leaks
    scope = profile_scope_for_settings(game_format="tournament", buy_in=1500,
                                       big_blind=100, num_players=8)
    game = SimpleNamespace(scenario="custom", profile_scope=scope)
    assert threshold_profile_key_for_game(game) == scope
    profile = get_threshold_profile(scope)
    assert not profile.enabled_stat_tags
    assert detect_stat_leaks({"vpip": {"pct": 100, "n": 100, "d": 100}}, scope) == []
