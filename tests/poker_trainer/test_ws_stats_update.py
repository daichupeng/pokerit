"""WS test: after a hand finishes, ws.py's `_save_soft` returns stats matching
a direct `compute_game_stats` call, so the `stats_update` event it feeds into
`websocket.send_json` carries the right numbers.

Drives the real persistence path (`GameSession.persist_incremental` via a
fake session object) against a real DB rather than replaying full gameplay
through pokerkit — the WS layer's job (compute + shape the event) is what's
under test, not the poker engine itself.
"""

from __future__ import annotations

from poker_engine.db.models import Action, Game, GamePlayer, Hand, HandPlayer, Street, User
from poker_engine.stats import compute_game_stats, to_display
from poker_trainer.ws import _save_soft


class _FakeSession:
    """Stands in for GameSession: persist_incremental returns a Game with
    players/hands already committed, exactly like the real recorder would.
    """

    def __init__(self, game_id):
        self.game_id = str(game_id)
        self._db_game_id = game_id

    def persist_incremental(self, db):
        return db.get(Game, self._db_game_id)


def test_save_soft_returns_stats_matching_compute_game_stats(db_session, monkeypatch):
    db = db_session
    user = User(email="ws-hero@test.local", display_name="Hero")
    db.add(user)
    db.flush()

    game = Game(small_blind=50, big_blind=100, buy_in=10000, max_round=50, hero_user_id=user.id)
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

    hand = Hand(game_id=game.id, round_count=0, street_reached=Street.PREFLOP, board=[], had_showdown=False)
    db.add(hand)
    db.flush()
    db.add_all([
        HandPlayer(hand_id=hand.id, game_player_id=hero_gp.id, position="BTN"),
        HandPlayer(hand_id=hand.id, game_player_id=villain_gp.id, position="BB"),
    ])
    db.add(Action(hand_id=hand.id, game_player_id=hero_gp.id, street=Street.PREFLOP,
                   action="raise", amount=300, seq=0))
    db.add(Action(hand_id=hand.id, game_player_id=villain_gp.id, street=Street.PREFLOP,
                   action="fold", amount=0, seq=1))
    db.commit()

    # _save_soft opens its own SessionLocal(); point it at this test's engine/session
    # by monkeypatching SessionLocal to hand back a context-manager over db_session
    # (rollback in conftest's teardown still applies, so this test stays isolated).
    class _CtxSession:
        def __enter__(self_inner):
            return db

        def __exit__(self_inner, *exc):
            return False

    monkeypatch.setattr("poker_trainer.ws.SessionLocal", lambda: _CtxSession())

    fake_session = _FakeSession(game.id)
    result = _save_soft(fake_session)

    expected = to_display(compute_game_stats(db, game.id, hero_gp.id))
    assert result == expected
    assert result["vpip"] == {"pct": 100.0, "n": 1, "d": 1}
