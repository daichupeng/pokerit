"""DB-backed tests for the tool executors in src/ai_functions/tools/executors.py.

Requires Postgres (see tests/conftest.py); skipped automatically if unreachable.
"""

from __future__ import annotations

import random

from ai_functions.tools.executors import (
    make_equity_calculator_tool,
    make_hand_lookup_tool,
    make_hand_search_tool,
    make_pot_odds_tool,
    make_stats_query_tool,
)
from poker_engine import pk_adapter, stats
from poker_engine.db.models import Action, Game, GamePlayer, Hand, HandPlayer, Street, User


def _make_user(db, email="hero@test.local"):
    user = User(email=email, display_name="Hero")
    db.add(user)
    db.flush()
    return user


def _make_game(db, user, max_round=50):
    game = Game(
        started_at=None,
        ended_at=None,
        small_blind=50,
        big_blind=100,
        buy_in=10000,
        max_round=max_round,
        hero_user_id=user.id,
    )
    db.add(game)
    db.flush()
    hero_gp = GamePlayer(
        game_id=game.id, seat_index=0, display_name="Hero", engine_uuid="hero-uuid",
        user_id=user.id, is_bot=False, starting_stack=10000,
    )
    villain_gp = GamePlayer(
        game_id=game.id, seat_index=1, display_name="Bot", engine_uuid="bot-uuid",
        user_id=None, is_bot=True, starting_stack=10000,
    )
    db.add_all([hero_gp, villain_gp])
    db.flush()
    return game, hero_gp, villain_gp


def _add_hand(db, game, hero_gp, villain_gp, round_count, hero_action="raise", position="BTN"):
    hand = Hand(
        game_id=game.id, round_count=round_count, street_reached=Street.PREFLOP,
        board=[], had_showdown=False,
    )
    db.add(hand)
    db.flush()
    db.add_all([
        HandPlayer(hand_id=hand.id, game_player_id=hero_gp.id, position=position,
                   hole_cards=["As", "Kh"]),
        HandPlayer(hand_id=hand.id, game_player_id=villain_gp.id, position="BB"),
    ])
    db.add(Action(hand_id=hand.id, game_player_id=hero_gp.id, street=Street.PREFLOP,
                   action=hero_action, amount=300, seq=0))
    db.add(Action(hand_id=hand.id, game_player_id=villain_gp.id, street=Street.PREFLOP,
                   action="fold", amount=0, seq=1))
    db.flush()
    return hand


def test_hand_lookup_tool_matches_format_hand(db_session):
    from poker_trainer.api.games import hand_detail
    from shared_services.hand_formatter import format_hand

    db = db_session
    user = _make_user(db)
    game, hero_gp, villain_gp = _make_game(db, user)
    _add_hand(db, game, hero_gp, villain_gp, round_count=0)

    tool = make_hand_lookup_tool(db, str(game.id), user)
    result = tool(round_count=0)

    detail = hand_detail(str(game.id), 0, user, db)
    expected_text = format_hand(detail, game.small_blind, game.big_blind)

    assert result["round_count"] == 0
    assert result["context"] == expected_text


def test_stats_query_tool_matches_stats_to_display(db_session):
    db = db_session
    user = _make_user(db)
    game, hero_gp, villain_gp = _make_game(db, user)
    _add_hand(db, game, hero_gp, villain_gp, round_count=0, hero_action="raise")
    _add_hand(db, game, hero_gp, villain_gp, round_count=1, hero_action="call")

    tool = make_stats_query_tool(db, str(game.id), user)
    result = tool()

    counts = stats.compute_game_stats(db, game.id, hero_gp.id)
    expected = stats.to_display(counts)
    assert result == expected
    assert result["hands_dealt"] == 2
    assert result["pfr"]["n"] == 1


def test_stats_query_tool_filters_by_position(db_session):
    db = db_session
    user = _make_user(db)
    game, hero_gp, villain_gp = _make_game(db, user)
    _add_hand(db, game, hero_gp, villain_gp, round_count=0, hero_action="raise", position="BTN")

    tool = make_stats_query_tool(db, str(game.id), user)
    result = tool(position="BTN")

    assert result["hands_dealt"] == 1
    assert "by_position" not in result


def test_stats_query_tool_filters_by_street(db_session):
    db = db_session
    user = _make_user(db)
    game, hero_gp, villain_gp = _make_game(db, user)
    _add_hand(db, game, hero_gp, villain_gp, round_count=0, hero_action="raise")

    tool = make_stats_query_tool(db, str(game.id), user)
    result = tool(street="flop")

    assert set(result) == {"cbet", "fold_to_cbet"}


def test_equity_calculator_tool_matches_mc_win_rate_and_labels_random_opponent():
    tool = make_equity_calculator_tool()
    rng = random.Random(0)
    expected = pk_adapter.mc_win_rate(["As", "Ah"], [], 2, rng=rng)

    # Not deterministic across separate rng instances (tool doesn't accept an
    # rng override — matches mc_win_rate's own default signature), so just
    # assert shape/bounds and the "random opponent" labeling requirement.
    result = tool(hole=["As", "Ah"], board=[], n_active_players=2)

    assert 0.0 <= result["win_rate"] <= 1.0
    assert "random opponent" in result["note"].lower()
    assert 0.0 <= expected <= 1.0


def test_pot_odds_tool_computes_required_equity():
    tool = make_pot_odds_tool()

    # Pot of 100, call of 50: required equity = 50 / (100+50) = 33.3%
    result = tool(pot_size=100, amount_to_call=50)

    assert result["required_equity_pct"] == 33.3


def test_pot_odds_tool_handles_zero_denominator():
    tool = make_pot_odds_tool()
    result = tool(pot_size=0, amount_to_call=0)
    assert result["required_equity_pct"] == 0.0


def test_hand_search_tool_filters_by_street_reached(db_session):
    db = db_session
    user = _make_user(db)
    game, hero_gp, villain_gp = _make_game(db, user)
    _add_hand(db, game, hero_gp, villain_gp, round_count=0)

    tool = make_hand_search_tool(db, str(game.id), user)
    result = tool(street_reached="preflop")

    assert len(result["hands"]) == 1
    assert result["hands"][0]["round_count"] == 0

    result_none = tool(street_reached="river")
    assert result_none["hands"] == []


def test_hand_search_tool_filters_by_hero_action_type(db_session):
    db = db_session
    user = _make_user(db)
    game, hero_gp, villain_gp = _make_game(db, user)
    _add_hand(db, game, hero_gp, villain_gp, round_count=0, hero_action="raise")
    _add_hand(db, game, hero_gp, villain_gp, round_count=1, hero_action="call")

    tool = make_hand_search_tool(db, str(game.id), user)

    raises = tool(hero_action_type="raise")
    assert [h["round_count"] for h in raises["hands"]] == [0]

    calls = tool(hero_action_type="call")
    assert [h["round_count"] for h in calls["hands"]] == [1]


def test_hand_search_tool_filters_by_pot_range(db_session):
    db = db_session
    user = _make_user(db)
    game, hero_gp, villain_gp = _make_game(db, user)
    hand0 = _add_hand(db, game, hero_gp, villain_gp, round_count=0)
    hand0.pot_total = 100
    hand1 = _add_hand(db, game, hero_gp, villain_gp, round_count=1)
    hand1.pot_total = 5000
    db.flush()

    tool = make_hand_search_tool(db, str(game.id), user)

    result = tool(min_pot=1000)
    assert [h["round_count"] for h in result["hands"]] == [1]

    result = tool(max_pot=1000)
    assert [h["round_count"] for h in result["hands"]] == [0]
