from fastapi.testclient import TestClient

from poker_engine.db.models import EvaluationStatus, Game, HistoryEvaluation, User
from poker_trainer.auth.deps import get_db, require_user
from poker_trainer.main import app


class _FakePool:
    def __init__(self):
        self.enqueued = []

    async def enqueue_job(self, name, *args):
        self.enqueued.append((name, args))


async def _return(value):
    return value


def test_create_list_get_and_status_history_evaluation(db_session, monkeypatch):
    user = User(email="history-api@test.local", display_name="Hero")
    db_session.add(user)
    db_session.commit()
    pool = _FakePool()
    monkeypatch.setattr(
        "poker_trainer.api.history_evaluation.get_redis_pool",
        lambda: _return(pool),
    )
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[require_user] = lambda: user
    try:
        client = TestClient(app)
        response = client.post("/api/profile/history-evaluations", json={
            "scope": "cash_6max_100bb", "window_hands": 500, "latest_game_id": None,
        })
        assert response.status_code == 200
        evaluation_id = response.json()["evaluation_id"]
        assert pool.enqueued == [("run_history_evaluation", (evaluation_id,))]

        evaluation = db_session.get(HistoryEvaluation, evaluation_id)
        assert evaluation.status == EvaluationStatus.PENDING
        assert evaluation.threshold_version == "2026-07-23.v3"

        listed = client.get("/api/profile/history-evaluations?scope=cash_6max_100bb")
        assert listed.status_code == 200
        assert listed.json()[0]["evaluation_id"] == evaluation_id

        detail = client.get(f"/api/profile/history-evaluations/{evaluation_id}")
        assert detail.status_code == 200
        assert detail.json()["scope"] == "cash_6max_100bb"

        status = client.get(f"/api/profile/history-evaluations/{evaluation_id}/status")
        assert status.json() == {"status": "PENDING", "error": None}
    finally:
        app.dependency_overrides.clear()


def test_history_evaluation_rejects_unknown_scope(db_session):
    user = User(email="history-api-scope@test.local", display_name="Hero")
    db_session.add(user)
    db_session.commit()
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[require_user] = lambda: user
    try:
        response = TestClient(app).post(
            "/api/profile/history-evaluations",
            json={"scope": "mixed_everything", "window_hands": 500},
        )
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_history_evaluation_rejects_latest_game_without_saved_hands(db_session):
    user = User(email="history-api-empty@test.local", display_name="Hero")
    db_session.add(user)
    db_session.flush()
    game = Game(
        small_blind=50, big_blind=100, buy_in=10000, max_round=50,
        hero_user_id=user.id, scenario="cash_6max_100bb",
        profile_scope="cash_6max_100bb",
    )
    db_session.add(game)
    db_session.commit()
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[require_user] = lambda: user
    try:
        response = TestClient(app).post(
            "/api/profile/history-evaluations",
            json={
                "scope": "cash_6max_100bb",
                "window_hands": 500,
                "latest_game_id": str(game.id),
            },
        )
        assert response.status_code == 422
        assert "saved hand" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()
