"""Custom history uses exact settings, with legacy reports kept out of new profiles."""
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from ai_functions.history_evaluation.pipeline import build_history_snapshot
from ai_functions.memory.persistence import query_folded_evaluations
from poker_engine.db.models import (
    Action, EvaluationStatus, Game, GameEvaluation, GamePlayer, Hand,
    HandPlayer, HistoryEvaluation, Street, User,
)
from poker_engine.scenarios import profile_scope_for_game
from poker_trainer.auth.deps import get_db, require_user
from poker_trainer.main import app


def _saved_game(db, user, game_format, buy_in, vpip):
    game = Game(hero_user_id=user.id, small_blind=50, big_blind=100,
                buy_in=buy_in, max_round=50, scenario="custom", profile_scope="custom",
                game_format=game_format, ante=0, ante_type="none")
    db.add(game)
    db.flush()
    hero = GamePlayer(game=game, seat_index=0, display_name="Hero", engine_uuid="hero",
                      user_id=user.id, is_bot=False, starting_stack=buy_in)
    bot = GamePlayer(game=game, seat_index=1, display_name="Bot", engine_uuid="bot",
                     is_bot=True, starting_stack=buy_in)
    db.add_all([hero, bot])
    db.flush()
    hand = Hand(game=game, round_count=1, street_reached=Street.PREFLOP, board=[], had_showdown=False)
    db.add(hand)
    db.flush()
    db.add_all([HandPlayer(hand=hand, game_player_id=hero.id, position="BTN"),
                HandPlayer(hand=hand, game_player_id=bot.id, position="BB")])
    db.add(Action(hand=hand, game_player_id=hero.id, street=Street.PREFLOP,
                  action="raise" if vpip else "fold", amount=300 if vpip else 0, seq=0))
    db.flush()
    return game


def test_custom_history_and_scope_options_do_not_mix_cash_and_mtt(db_session, monkeypatch):
    db = db_session
    user = User(email="custom-scopes@test.local", display_name="Hero")
    db.add(user)
    db.flush()
    cash = _saved_game(db, user, "cash", 10000, True)
    mtt = _saved_game(db, user, "tournament", 1500, False)
    db.commit()
    cash_scope, mtt_scope = profile_scope_for_game(cash), profile_scope_for_game(mtt)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_user] = lambda: user
    class Pool:
        async def enqueue_job(self, *args): pass
    async def pool(): return Pool()
    monkeypatch.setattr("poker_trainer.api.history_evaluation.get_redis_pool", pool)
    try:
        client = TestClient(app)
        profile = client.get(f"/api/profile/coaching?scope={cash_scope}").json()
        labels = {s["key"]: s["label"] for s in profile["available_scopes"]}
        assert "现金桌" in labels[cash_scope]
        assert "MTT" in labels[mtt_scope]
        assert "custom" not in labels
        for game, scope, expected in [(cash, cash_scope, 100.0), (mtt, mtt_scope, 0.0)]:
            stats = client.get(f"/api/profile/stats?scope={scope}").json()["stats"]
            assert stats["hands_dealt"] == 1
            assert stats["vpip"]["pct"] == expected
            response = client.post("/api/profile/history-evaluations", json={
                "scope": scope, "latest_game_id": str(game.id),
            })
            assert response.status_code == 200
            evaluation = db.get(HistoryEvaluation, response.json()["evaluation_id"])
            snapshot = build_history_snapshot(db, evaluation)
            assert snapshot["stats_snapshot"]["rolling_500"]["hands_dealt"] == 1
            assert snapshot["stats_snapshot"]["rolling_500"]["vpip"]["pct"] == expected
            assert snapshot["deterministic_stat_leaks"] == []
            vpip_sample = next(m for m in snapshot["sample_status"]["metrics"] if m["metric"] == "vpip")
            assert vpip_sample["snapshot"]["pct"] == expected
            assert vpip_sample["status"] == "descriptive"
            assert vpip_sample["required"] is None
            assert all(m["trend_status"] == "descriptive" for m in snapshot["trend_comparison"]["latest_game_vs_prior_500"])
            assert snapshot["sample_status"]["benchmark_status"] == "unavailable_descriptive_statistics_only"
        assert client.post("/api/profile/history-evaluations", json={"scope": "custom"}).status_code == 422
        assert client.post("/api/profile/history-evaluations", json={
            "scope": cash_scope, "latest_game_id": str(mtt.id),
        }).status_code == 422
        # Existing reports retain their original scope and can still be read.
        assert db.scalar(select(Game.profile_scope).where(Game.id == cash.id)) == "custom"
    finally:
        app.dependency_overrides.clear()


def test_old_generic_custom_report_is_not_folded_into_new_scope(db_session):
    db = db_session
    user = User(email="custom-old-report@test.local", display_name="Hero")
    db.add(user)
    db.flush()
    game = _saved_game(db, user, "cash", 10000, True)
    scope = profile_scope_for_game(game)
    old = GameEvaluation(game=game, user_id=user.id, status=EvaluationStatus.COMPLETED,
                         completed_at=datetime.now(timezone.utc),
                         stats_snapshot={"threshold_profile": {"key": "custom"}})
    db.add(old)
    db.commit()
    assert query_folded_evaluations(db, user.id, scope_key=scope) == []
    new = GameEvaluation(game=game, user_id=user.id, status=EvaluationStatus.COMPLETED,
                         completed_at=datetime.now(timezone.utc),
                         stats_snapshot={"threshold_profile": {"key": scope}})
    db.add(new)
    db.commit()
    assert [row.id for row in query_folded_evaluations(db, user.id, scope_key=scope)] == [new.id]
