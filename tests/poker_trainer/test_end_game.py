from __future__ import annotations

from sqlalchemy import func, select

from poker_engine.config import GameConfig, SeatKind, SeatSpec
from poker_engine.db.models import Game, Hand
from poker_trainer.game.session import GameSession


def test_finish_early_saves_game_without_partial_hand(db_session):
    config = GameConfig(
        small_blind=50,
        buy_in=10000,
        max_round=100,
        seats=[
            SeatSpec(name="Hero", kind=SeatKind.HUMAN, email="end-game@test.local"),
            SeatSpec(name="Bot", kind=SeatKind.ROCK),
        ],
    )
    session = GameSession(config, hero_index=0, seed=7)
    session.start()

    assert session._state is not None
    assert session.recorder._current is not None

    final_players = session.finish_early()
    game = session.persist(db_session)

    assert session.finished is True
    assert session._state is None
    assert len(final_players) == 2
    assert sum(player["stack"] for player in final_players) == 20000
    assert db_session.scalar(
        select(func.count()).select_from(Hand).where(Hand.game_id == game.id)
    ) == 0
    saved_game = db_session.get(Game, game.id)
    assert saved_game.ended_at is not None
