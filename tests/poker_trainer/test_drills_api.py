from fastapi.testclient import TestClient

from poker_engine.db.models import DrillSession, User
from poker_trainer.auth.deps import get_db, require_user
from poker_trainer.main import app


def _client(db, user):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_user] = lambda: user
    return TestClient(app)


def test_drill_session_hides_answer_and_advances_sequentially(db_session):
    user = User(email="drill@test.local", display_name="Driller")
    db_session.add(user)
    db_session.commit()
    client = _client(db_session, user)
    try:
        modes = client.get("/api/drills/modes").json()
        assert len(modes) == 4
        response = client.post(
            "/api/drills/sessions", json={"pack_id": "cash_6max_100bb_v1"}
        )
        assert response.status_code == 200
        session = response.json()
        assert session["question_count"] == 10
        assert "accepted_actions" not in session["current_question"]

        stored = db_session.get(DrillSession, session["session_id"])
        answer = stored.questions[0]["accepted_actions"][0]
        result = client.post(
            f"/api/drills/sessions/{session['session_id']}/answers",
            json={"question_index": 0, "action": answer},
        )
        assert result.status_code == 200
        assert result.json()["correct"] is True
        assert result.json()["session"]["next_index"] == 1

        out_of_order = client.post(
            f"/api/drills/sessions/{session['session_id']}/answers",
            json={"question_index": 3, "action": "fold"},
        )
        assert out_of_order.status_code == 409
    finally:
        app.dependency_overrides.clear()
