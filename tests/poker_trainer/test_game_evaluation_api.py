"""API tests for the game-evaluation endpoints (src/poker_trainer/api/game_evaluation.py).

Monkeypatches get_redis_pool so no real Redis is needed — POST /evaluate only
needs to prove it enqueued the right job, not that a worker picked it up.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from poker_engine.db.models import EvaluationStatus, Game, GameEvaluation, GamePlayer, User
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


class _FakeRedisPool:
    def __init__(self):
        self.enqueued = []

    async def enqueue_job(self, name, *args):
        self.enqueued.append((name, args))


def test_evaluate_enqueues_job_and_returns_pending_evaluation(db_session, monkeypatch):
    db = db_session
    owner = _make_user(db, "owner@test.local")
    game = _make_game(db, owner)

    fake_pool = _FakeRedisPool()
    monkeypatch.setattr(
        "poker_trainer.api.game_evaluation.get_redis_pool",
        lambda: _async_return(fake_pool),
    )

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_user] = lambda: owner
    try:
        client = TestClient(app)
        resp = client.post(f"/api/games/{game.id}/evaluate")
        assert resp.status_code == 200
        evaluation_id = resp.json()["evaluation_id"]
        assert evaluation_id

        evaluation = db.get(GameEvaluation, evaluation_id)
        assert evaluation is not None
        assert evaluation.status == EvaluationStatus.PENDING
        assert evaluation.game_id == game.id

        assert fake_pool.enqueued == [("run_evaluation", (evaluation_id,))]
    finally:
        app.dependency_overrides.clear()


def test_evaluate_404_for_non_owner(db_session, monkeypatch):
    db = db_session
    owner = _make_user(db, "owner2@test.local")
    intruder = _make_user(db, "intruder@test.local")
    game = _make_game(db, owner)

    fake_pool = _FakeRedisPool()
    monkeypatch.setattr(
        "poker_trainer.api.game_evaluation.get_redis_pool",
        lambda: _async_return(fake_pool),
    )

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_user] = lambda: intruder
    try:
        client = TestClient(app)
        resp = client.post(f"/api/games/{game.id}/evaluate")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_list_and_get_and_status_endpoints(db_session):
    db = db_session
    owner = _make_user(db, "owner3@test.local")
    game = _make_game(db, owner)
    evaluation = GameEvaluation(
        game_id=game.id, user_id=owner.id, status=EvaluationStatus.RUNNING,
        progress_current=2, progress_total=5, current_stage="review",
    )
    db.add(evaluation)
    db.commit()
    db.refresh(evaluation)

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_user] = lambda: owner
    try:
        client = TestClient(app)

        resp = client.get(f"/api/games/{game.id}/evaluations")
        assert resp.status_code == 200
        listed = resp.json()
        assert len(listed) == 1
        assert listed[0]["evaluation_id"] == str(evaluation.id)
        assert listed[0]["status"] == "RUNNING"

        resp = client.get(f"/api/games/{game.id}/evaluations/{evaluation.id}")
        assert resp.status_code == 200
        full = resp.json()
        assert full["current_stage"] == "review"
        assert full["progress_current"] == 2
        assert full["progress_total"] == 5

        resp = client.get(f"/api/games/{game.id}/evaluations/{evaluation.id}/status")
        assert resp.status_code == 200
        status_body = resp.json()
        assert status_body == {
            "status": "RUNNING", "progress_current": 2, "progress_total": 5,
            "current_stage": "review", "error": None,
        }
    finally:
        app.dependency_overrides.clear()


def test_get_evaluation_404_for_wrong_game(db_session):
    db = db_session
    owner = _make_user(db, "owner4@test.local")
    game = _make_game(db, owner)
    other_game = _make_game(db, owner)
    evaluation = GameEvaluation(game_id=other_game.id, user_id=owner.id, status=EvaluationStatus.PENDING)
    db.add(evaluation)
    db.commit()
    db.refresh(evaluation)

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_user] = lambda: owner
    try:
        client = TestClient(app)
        resp = client.get(f"/api/games/{game.id}/evaluations/{evaluation.id}")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


async def _async_return(value):
    return value
