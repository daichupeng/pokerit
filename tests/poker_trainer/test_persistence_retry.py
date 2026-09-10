"""Commit failure must not discard buffered hands or acknowledge an unsaved game."""
import asyncio
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from poker_engine.config import GameConfig, SeatKind, SeatSpec
from poker_engine.db.models import Game, Hand
from poker_trainer.game.session import GameSession
from poker_trainer import ws


def _game_session():
    return GameSession(GameConfig(
        small_blind=50, buy_in=1000, max_round=1,
        seats=[SeatSpec(name="Hero", kind=SeatKind.HUMAN, email="retry@test.local"),
               SeatSpec(name="Bot", kind=SeatKind.ROCK)],
    ), seed=7)


@pytest.mark.parametrize("existing_game", [False, True])
@pytest.mark.parametrize("commit_ack_lost", [False, True])
def test_commit_failure_retry_saves_each_hand_once(db_session, existing_game, commit_ack_lost):
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False,
                           join_transaction_mode="create_savepoint")
    session = _game_session()
    if existing_game:
        with factory() as db:
            session.persist_start(db)
    original_id = session.recorder._game_id
    session.start()
    while not session.finished:
        session.apply_hero_action("call", 0)

    with factory() as db:
        commit = db.commit
        def fail_commit():
            db.flush()
            if commit_ack_lost:
                commit()
            raise RuntimeError("simulated commit failure")
        db.commit = fail_commit
        with pytest.raises(RuntimeError):
            session.persist(db)
    assert session.recorder._game_id == original_id
    assert session.recorder._persisted_rounds == set()

    with factory() as db:
        game = session.persist(db)
        assert len(game.hands) == 1
        assert game.ended_at is not None
        assert db.scalar(select(func.count()).select_from(Game)) == 1
        assert db.scalar(select(func.count()).select_from(Hand)) == 1
        game_id = game.id
    with factory() as db:
        assert session.persist(db).id == game_id
        assert db.scalar(select(func.count()).select_from(Hand)) == 1


def test_final_save_failure_retains_session_until_retry(monkeypatch):
    messages = []
    class Socket:
        async def send_json(self, message): messages.append(message)
    attempts = []
    def persist(db):
        attempts.append(True)
        if len(attempts) == 1:
            raise RuntimeError("private database diagnostic")
        return SimpleNamespace(id="saved-id")
    session = SimpleNamespace(game_id="retry-game", persist=persist)
    ws.manager.add(session)
    monkeypatch.setattr(ws, "SessionLocal", lambda: nullcontext(object()))
    try:
        assert asyncio.run(ws._finish(Socket(), session, session.game_id)) is False
        assert ws.manager.get(session.game_id) is session
        assert [m["type"] for m in messages] == ["persist_error"]
        assert "private" not in str(messages)
        assert asyncio.run(ws._finish(Socket(), session, session.game_id)) is True
        assert ws.manager.get(session.game_id) is None
        assert messages[-1] == {"type": "saved", "db_game_id": "saved-id"}
    finally:
        ws.manager.remove(session.game_id)
