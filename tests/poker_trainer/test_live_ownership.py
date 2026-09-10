"""Authenticated browser and coach access must stay inside the owner's game."""
import base64
import json
from contextlib import nullcontext
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner
from starlette.websockets import WebSocketDisconnect

from poker_engine.db.models import AccountStatus, Conversation, User
from poker_trainer.auth import config
from poker_trainer.auth.deps import get_db, require_user
from poker_trainer.game.manager import manager
from poker_trainer.main import app


def _cookie(user_id):
    payload = base64.b64encode(json.dumps({"uid": str(user_id)}).encode())
    return TimestampSigner(config.SESSION_SECRET).sign(payload).decode()


@pytest.fixture
def live_game(db_session, monkeypatch):
    owner = User(email="live-owner@test.local", display_name="Owner")
    other = User(email="live-other@test.local", display_name="Other")
    deleted = User(email="live-deleted@test.local", display_name="Deleted", status=AccountStatus.DELETED)
    db_session.add_all([owner, other, deleted])
    db_session.commit()
    session = SimpleNamespace(
        game_id=str(uuid4()), owner_user_id=owner.id, finished=False,
        _last_view={"marker": "private-hero-view"},
        table_config=lambda: {}, current_view=lambda: {"marker": "private-hero-view"},
        pending_ask=lambda: None,
    )
    manager.add(session)
    app.dependency_overrides[get_db] = lambda: db_session
    monkeypatch.setattr("poker_trainer.auth.deps.SessionLocal", lambda: nullcontext(db_session))
    try:
        yield session, owner, other, deleted
    finally:
        manager.remove(session.game_id)
        app.dependency_overrides.clear()


def test_socket_rejects_anonymous_other_user_deleted_account_and_foreign_origin(live_game):
    session, owner, other, deleted = live_game
    for user, origin in [(None, None), (other, None), (deleted, None), (owner, "https://foreign.invalid")]:
        client = TestClient(app)
        if user:
            client.cookies.set(config.SESSION_COOKIE, _cookie(user.id))
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect(f"/ws/games/{session.game_id}", headers={"origin": origin} if origin else {}):
                pytest.fail("Unauthorized connection accepted")
        assert exc.value.code == 1008


def test_socket_owner_can_receive_current_state(live_game):
    session, owner, _, _ = live_game
    client = TestClient(app)
    client.cookies.set(config.SESSION_COOKIE, _cookie(owner.id))
    with client.websocket_connect(f"/ws/games/{session.game_id}", headers={"origin": config.APP_BASE_URL}) as socket:
        assert socket.receive_json()["view"] == {"marker": "private-hero-view"}


def test_coach_rejects_foreign_live_game_before_creating_conversation(live_game, db_session):
    from sqlalchemy import func, select
    session, _, other, _ = live_game
    app.dependency_overrides[require_user] = lambda: other
    client = TestClient(app)
    for endpoint, body in [("chat", {"message": "What are my cards?"}), ("conversations", {})]:
        response = client.post(f"/api/coach/{endpoint}", json={**body, "game_id": session.game_id})
        assert response.status_code == 404
    assert db_session.scalar(select(func.count()).select_from(Conversation)) == 0


def test_owner_can_create_conversation_for_unsaved_live_game(live_game):
    session, owner, _, _ = live_game
    app.dependency_overrides[require_user] = lambda: owner
    response = TestClient(app).post("/api/coach/conversations", json={"game_id": session.game_id})
    assert response.status_code == 200
    assert response.json()["conversation_id"]


def test_finished_socket_accepts_save_retry_without_losing_session(live_game, monkeypatch):
    session, owner, _, _ = live_game
    session.finished = True
    attempts = []
    def persist(db):
        attempts.append(True)
        if len(attempts) == 1:
            raise RuntimeError("database unavailable")
        return SimpleNamespace(id="saved-game")
    session.persist = persist
    monkeypatch.setattr("poker_trainer.ws.SessionLocal", lambda: nullcontext(object()))
    client = TestClient(app)
    client.cookies.set(config.SESSION_COOKIE, _cookie(owner.id))
    with client.websocket_connect(f"/ws/games/{session.game_id}") as socket:
        assert socket.receive_json()["type"] == "init"
        assert socket.receive_json()["type"] == "persist_error"
        assert manager.get(session.game_id) is session
        socket.send_json({"type": "retry_save"})
        assert socket.receive_json() == {"type": "saved", "db_game_id": "saved-game"}
    assert manager.get(session.game_id) is None


def test_created_game_binds_owner_and_exact_custom_scope(live_game):
    from poker_engine.scenarios import profile_scope_for_settings
    _, owner, _, _ = live_game
    app.dependency_overrides[require_user] = lambda: owner
    response = TestClient(app).post("/api/games", json={
        "num_bots": 1, "randomize_styles": False, "styles": ["rock"],
        "scenario": "custom", "game_format": "cash", "buy_in": 7500,
    })
    assert response.status_code == 200
    game_id = response.json()["game_id"]
    try:
        session = manager.get(game_id)
        assert session.owner_user_id == owner.id
        assert response.json()["profile_scope"] == profile_scope_for_settings(
            game_format="cash", buy_in=7500, big_blind=100, num_players=2,
        )
    finally:
        manager.remove(game_id)
