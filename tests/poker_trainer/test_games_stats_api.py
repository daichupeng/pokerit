"""API test: GET /api/games/{game_id}/stats enforces the same ownership check
as other game routes (404 for a game not owned by the requesting user).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from poker_engine.db.models import Game, GamePlayer, User
from poker_trainer.auth.deps import get_db, require_user
from poker_trainer.main import app


def _make_user(db, email):
    user = User(email=email, display_name="Someone")
    db.add(user)
    db.flush()
    return user


def _make_game(db, hero_user):
    game = Game(small_blind=50, big_blind=100, buy_in=10000, max_round=50, hero_user_id=hero_user.id)
    db.add(game)
    db.flush()
    db.add(GamePlayer(
        game_id=game.id, seat_index=0, display_name="Hero", engine_uuid="hero-uuid",
        user_id=hero_user.id, is_bot=False, starting_stack=10000,
    ))
    db.flush()
    return game


def test_game_stats_404_for_non_owner(db_session):
    db = db_session
    owner = _make_user(db, "owner@test.local")
    intruder = _make_user(db, "intruder@test.local")
    game = _make_game(db, owner)

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_user] = lambda: intruder
    try:
        client = TestClient(app)
        resp = client.get(f"/api/games/{game.id}/stats")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_game_stats_200_for_owner(db_session):
    db = db_session
    owner = _make_user(db, "owner2@test.local")
    game = _make_game(db, owner)

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_user] = lambda: owner
    try:
        client = TestClient(app)
        resp = client.get(f"/api/games/{game.id}/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert body["hands_dealt"] == 0
        assert body["vpip"] == {"pct": 0.0, "n": 0, "d": 0}
    finally:
        app.dependency_overrides.clear()
