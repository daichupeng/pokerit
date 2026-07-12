"""DB-backed tests for stats.py's query layer (compute_game_stats / compute_player_stats).

Requires Postgres (see tests/conftest.py); skipped automatically if unreachable.
"""

from __future__ import annotations

import uuid

from poker_engine.db.models import Action, Game, GamePlayer, Hand, HandPlayer, Street, User
from poker_engine.stats import compute_game_stats, compute_player_stats


def _make_user(db, email="hero@test.local"):
    user = User(email=email, display_name="Hero")
    db.add(user)
    db.flush()
    return user


def _make_game(db, user, ended_at=None, max_round=50):
    game = Game(
        started_at=None,
        ended_at=ended_at,
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


def _add_hand(db, game, hero_gp, villain_gp, round_count, hero_action="raise", street_reached=Street.PREFLOP):
    hand = Hand(
        game_id=game.id, round_count=round_count, street_reached=street_reached,
        board=[], had_showdown=False,
    )
    db.add(hand)
    db.flush()
    db.add_all([
        HandPlayer(hand_id=hand.id, game_player_id=hero_gp.id, position="BTN"),
        HandPlayer(hand_id=hand.id, game_player_id=villain_gp.id, position="BB"),
    ])
    db.add(Action(hand_id=hand.id, game_player_id=hero_gp.id, street=Street.PREFLOP,
                   action=hero_action, amount=300, seq=0))
    db.add(Action(hand_id=hand.id, game_player_id=villain_gp.id, street=Street.PREFLOP,
                   action="fold", amount=0, seq=1))
    db.flush()
    return hand


def test_in_progress_game_reflects_only_recorded_hands(db_session):
    db = db_session
    user = _make_user(db)
    game, hero_gp, villain_gp = _make_game(db, user, ended_at=None)
    assert game.ended_at is None

    _add_hand(db, game, hero_gp, villain_gp, round_count=0, hero_action="raise")
    _add_hand(db, game, hero_gp, villain_gp, round_count=1, hero_action="call")

    counts = compute_game_stats(db, game.id, hero_gp.id)
    assert counts.hands_dealt == 2
    assert counts.vpip_hands == 2
    assert counts.pfr_hands == 1


def test_compute_game_stats_404_style_empty_for_unknown_hero(db_session):
    db = db_session
    user = _make_user(db, email="other@test.local")
    game, hero_gp, villain_gp = _make_game(db, user)
    _add_hand(db, game, hero_gp, villain_gp, round_count=0)

    counts = compute_game_stats(db, game.id, uuid.uuid4())
    assert counts.hands_dealt == 0


def test_compute_player_stats_rollup_across_games_exact_case(db_session):
    """The required rollup numeric case, this time through the real DB query layer.

    Game A: 3/10 VPIP hands. Game B: 1/20 VPIP hands. Rollup must be 4/30 (~13.3%),
    not 17.5% (the average of the two percentages).
    """
    db = db_session
    user = _make_user(db)

    game_a, hero_a, villain_a = _make_game(db, user)
    for i in range(10):
        action = "raise" if i < 3 else "fold"
        # Blind-only (non-VPIP) hands use smallblind/bigblind postings only.
        if action == "fold":
            hand = Hand(game_id=game_a.id, round_count=i, street_reached=Street.PREFLOP,
                        board=[], had_showdown=False)
            db.add(hand)
            db.flush()
            db.add_all([
                HandPlayer(hand_id=hand.id, game_player_id=hero_a.id, position="BB"),
                HandPlayer(hand_id=hand.id, game_player_id=villain_a.id, position="BTN"),
            ])
            db.add(Action(hand_id=hand.id, game_player_id=hero_a.id, street=Street.PREFLOP,
                           action="bigblind", amount=100, seq=0))
            db.add(Action(hand_id=hand.id, game_player_id=villain_a.id, street=Street.PREFLOP,
                           action="fold", amount=0, seq=1))
            db.flush()
        else:
            _add_hand(db, game_a, hero_a, villain_a, round_count=i, hero_action="raise")

    game_b, hero_b, villain_b = _make_game(db, user)
    for i in range(20):
        if i == 0:
            _add_hand(db, game_b, hero_b, villain_b, round_count=i, hero_action="call")
        else:
            hand = Hand(game_id=game_b.id, round_count=i, street_reached=Street.PREFLOP,
                        board=[], had_showdown=False)
            db.add(hand)
            db.flush()
            db.add_all([
                HandPlayer(hand_id=hand.id, game_player_id=hero_b.id, position="BB"),
                HandPlayer(hand_id=hand.id, game_player_id=villain_b.id, position="BTN"),
            ])
            db.add(Action(hand_id=hand.id, game_player_id=hero_b.id, street=Street.PREFLOP,
                           action="bigblind", amount=100, seq=0))
            db.add(Action(hand_id=hand.id, game_player_id=villain_b.id, street=Street.PREFLOP,
                           action="fold", amount=0, seq=1))
            db.flush()

    counts = compute_player_stats(db, user.id)
    assert counts.hands_dealt == 30
    assert counts.vpip_hands == 4
