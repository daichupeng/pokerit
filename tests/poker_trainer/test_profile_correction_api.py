"""API tests for the correction loop and coaching-profile endpoints:
discard/restore/dispute/viewed (src/poker_trainer/api/game_evaluation.py),
unviewed listing, and coaching profile read/reset
(src/poker_trainer/api/profile.py).

Each mutation route rebuilds the profile from scratch via
rebuild_and_persist — these tests assert the resulting profile always equals
whatever rebuild_profile() would independently produce, per Stage 4's "Done
when". Monkeypatches the playstyle LLM call so no network access is needed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from poker_engine.db.models import (
    EvaluationStatus,
    Game,
    GameEvaluation,
    GamePlayer,
    PlayerProfile,
    User,
)
from poker_trainer.auth.deps import get_db, require_user
from poker_trainer.main import app
from shared_services.llm import StreamResult, TokenUsage

from ai_functions.memory.fold import rebuild_profile


async def _fake_playstyle_llm(**kwargs):
    return StreamResult(text="Plays a balanced game.", usage=TokenUsage())


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


def _make_completed_evaluation(db, user, game, completed_at, leak_tags):
    evaluation = GameEvaluation(
        game_id=game.id, user_id=user.id, status=EvaluationStatus.COMPLETED,
        stats_snapshot={"game_level": {}, "session_dynamics": {}},
        leak_tags=leak_tags, completed_at=completed_at,
    )
    db.add(evaluation)
    db.flush()
    return evaluation


def _client(db, user):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_user] = lambda: user
    return TestClient(app)


def test_discard_and_restore_round_trip_rebuild_matches_from_scratch(db_session, monkeypatch):
    db = db_session
    monkeypatch.setattr("ai_functions.memory.playstyle.chat_model_with_usage", _fake_playstyle_llm)
    user = _make_user(db, "owner1@test.local")
    game = _make_game(db, user)
    evaluation = _make_completed_evaluation(
        db, user, game, datetime.now(timezone.utc),
        [{"tag": "missed_fold", "kind": "judgment", "severity": 1, "citations": []}],
    )
    db.commit()

    client = _client(db, user)
    try:
        resp = client.post(f"/api/games/{game.id}/evaluations/{evaluation.id}/discard")
        assert resp.status_code == 200

        db.refresh(evaluation)
        assert evaluation.discarded_at is not None

        profile = db.get(PlayerProfile, user.id)
        assert profile.evaluations_folded == 0
        assert profile.leaks == []
        # equals a from-scratch rebuild
        assert rebuild_profile(db, user.id) == {"evaluations_folded": 0, "leaks": []}

        resp = client.post(f"/api/games/{game.id}/evaluations/{evaluation.id}/restore")
        assert resp.status_code == 200

        db.refresh(evaluation)
        assert evaluation.discarded_at is None

        db.refresh(profile)
        assert profile.evaluations_folded == 1
        assert rebuild_profile(db, user.id) == {
            "evaluations_folded": profile.evaluations_folded, "leaks": profile.leaks,
        }
    finally:
        app.dependency_overrides.clear()


def test_dispute_excludes_tag_and_rebuild_matches(db_session, monkeypatch):
    db = db_session
    monkeypatch.setattr("ai_functions.memory.playstyle.chat_model_with_usage", _fake_playstyle_llm)
    user = _make_user(db, "owner2@test.local")
    game = _make_game(db, user)
    evaluation = _make_completed_evaluation(
        db, user, game, datetime.now(timezone.utc),
        [{"tag": "missed_fold", "kind": "judgment", "severity": 1, "citations": []}],
    )
    db.commit()

    client = _client(db, user)
    try:
        resp = client.post(
            f"/api/games/{game.id}/evaluations/{evaluation.id}/dispute",
            json={"tags": ["missed_fold"], "disputed": True},
        )
        assert resp.status_code == 200
        assert resp.json()["disputed_tags"] == ["missed_fold"]

        db.refresh(evaluation)
        assert evaluation.disputed_tags == ["missed_fold"]

        profile = db.get(PlayerProfile, user.id)
        # Disputed tag contributes nothing -> no record for it at all.
        assert not any(r["tag"] == "missed_fold" for r in profile.leaks)
        assert rebuild_profile(db, user.id) == {
            "evaluations_folded": profile.evaluations_folded, "leaks": profile.leaks,
        }

        # Un-dispute: rebuild should bring the tag back.
        resp = client.post(
            f"/api/games/{game.id}/evaluations/{evaluation.id}/dispute",
            json={"tags": ["missed_fold"], "disputed": False},
        )
        assert resp.status_code == 200
        assert resp.json()["disputed_tags"] == []

        db.refresh(profile)
        assert any(r["tag"] == "missed_fold" for r in profile.leaks)
    finally:
        app.dependency_overrides.clear()


def test_viewed_is_idempotent_and_first_open_only(db_session):
    db = db_session
    user = _make_user(db, "owner3@test.local")
    game = _make_game(db, user)
    evaluation = _make_completed_evaluation(db, user, game, datetime.now(timezone.utc), [])
    db.commit()

    client = _client(db, user)
    try:
        resp = client.post(f"/api/games/{game.id}/evaluations/{evaluation.id}/viewed")
        assert resp.status_code == 200
        first_viewed_at = resp.json()["viewed_at"]
        assert first_viewed_at is not None

        resp = client.post(f"/api/games/{game.id}/evaluations/{evaluation.id}/viewed")
        assert resp.status_code == 200
        assert resp.json()["viewed_at"] == first_viewed_at
    finally:
        app.dependency_overrides.clear()


def test_unviewed_lists_only_completed_undiscarded_unviewed(db_session):
    db = db_session
    user = _make_user(db, "owner4@test.local")
    game = _make_game(db, user)

    unviewed = _make_completed_evaluation(db, user, game, datetime.now(timezone.utc), [])
    viewed = _make_completed_evaluation(db, user, game, datetime.now(timezone.utc), [])
    viewed.viewed_at = datetime.now(timezone.utc)
    discarded = _make_completed_evaluation(db, user, game, datetime.now(timezone.utc), [])
    discarded.discarded_at = datetime.now(timezone.utc)
    pending = GameEvaluation(game_id=game.id, user_id=user.id, status=EvaluationStatus.PENDING)
    db.add(pending)
    db.commit()

    client = _client(db, user)
    try:
        resp = client.get("/api/evaluations/unviewed")
        assert resp.status_code == 200
        ids = {row["evaluation_id"] for row in resp.json()}
        assert ids == {str(unviewed.id)}
    finally:
        app.dependency_overrides.clear()


def test_cross_user_access_404s_on_all_correction_routes(db_session):
    db = db_session
    owner = _make_user(db, "owner5@test.local")
    intruder = _make_user(db, "intruder5@test.local")
    game = _make_game(db, owner)
    evaluation = _make_completed_evaluation(db, owner, game, datetime.now(timezone.utc), [])
    db.commit()

    client = _client(db, intruder)
    try:
        for path, method in [
            (f"/api/games/{game.id}/evaluations/{evaluation.id}/discard", "post"),
            (f"/api/games/{game.id}/evaluations/{evaluation.id}/restore", "post"),
            (f"/api/games/{game.id}/evaluations/{evaluation.id}/viewed", "post"),
        ]:
            resp = getattr(client, method)(path)
            assert resp.status_code == 404, path

        resp = client.post(
            f"/api/games/{game.id}/evaluations/{evaluation.id}/dispute",
            json={"tags": ["missed_fold"], "disputed": True},
        )
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_coaching_profile_empty_when_no_profile_yet(db_session):
    db = db_session
    user = _make_user(db, "owner6@test.local")
    db.commit()

    client = _client(db, user)
    try:
        resp = client.get("/api/profile/coaching")
        assert resp.status_code == 200
        body = resp.json()
        assert body["evaluations_folded"] == 0
        assert body["leaks_by_status"] == {"flagged": [], "confirmed": [], "resolved": []}
        assert body["playstyle_summary"] == ""
    finally:
        app.dependency_overrides.clear()


def test_coaching_profile_groups_leaks_by_status(db_session, monkeypatch):
    db = db_session
    monkeypatch.setattr("ai_functions.memory.playstyle.chat_model_with_usage", _fake_playstyle_llm)
    user = _make_user(db, "owner7@test.local")
    game = _make_game(db, user)
    _make_completed_evaluation(
        db, user, game, datetime.now(timezone.utc),
        [{"tag": "missed_fold", "kind": "judgment", "severity": 1, "citations": []}],
    )
    db.commit()

    client = _client(db, user)
    try:
        # Trigger a fold via discard+restore round trip (exercises rebuild_and_persist).
        evaluation = db.execute(
            select(GameEvaluation).where(GameEvaluation.game_id == game.id)
        ).scalars().first()
        client.post(f"/api/games/{game.id}/evaluations/{evaluation.id}/discard")
        client.post(f"/api/games/{game.id}/evaluations/{evaluation.id}/restore")

        resp = client.get("/api/profile/coaching")
        assert resp.status_code == 200
        body = resp.json()
        assert body["evaluations_folded"] == 1
        flagged_tags = [leak["tag"] for leak in body["leaks_by_status"]["flagged"]]
        assert flagged_tags == ["missed_fold"]
    finally:
        app.dependency_overrides.clear()


def test_reset_sets_reset_at_and_never_touches_evaluation_rows(db_session, monkeypatch):
    db = db_session
    monkeypatch.setattr("ai_functions.memory.playstyle.chat_model_with_usage", _fake_playstyle_llm)
    user = _make_user(db, "owner8@test.local")
    game = _make_game(db, user)
    evaluation = _make_completed_evaluation(
        db, user, game, datetime.now(timezone.utc) - timedelta(days=1),
        [{"tag": "missed_fold", "kind": "judgment", "severity": 1, "citations": []}],
    )
    original_completed_at = evaluation.completed_at
    original_discarded_at = evaluation.discarded_at
    original_leak_tags = evaluation.leak_tags
    db.commit()

    client = _client(db, user)
    try:
        resp = client.post("/api/profile/reset")
        assert resp.status_code == 200
        body = resp.json()
        assert body["evaluations_folded"] == 0
        assert body["reset_at"] is not None

        profile = db.get(PlayerProfile, user.id)
        assert profile.evaluations_folded == 0
        assert profile.leaks == []
        assert profile.reset_at is not None

        # Evaluation row is completely untouched.
        db.refresh(evaluation)
        assert evaluation.completed_at == original_completed_at
        assert evaluation.discarded_at == original_discarded_at
        assert evaluation.leak_tags == original_leak_tags
        assert evaluation.status == EvaluationStatus.COMPLETED
    finally:
        app.dependency_overrides.clear()
