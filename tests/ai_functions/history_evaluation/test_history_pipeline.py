from __future__ import annotations

import asyncio

from sqlalchemy.orm import sessionmaker

from ai_functions.history_evaluation.pipeline import build_history_snapshot, run_history_evaluation
from poker_engine.db.models import (
    Action,
    EvaluationStatus,
    Game,
    GamePlayer,
    Hand,
    HandPlayer,
    HistoryEvaluation,
    PlayerProfile,
    Street,
    User,
)


def _game(db, user, suffix: str):
    game = Game(
        small_blind=50, big_blind=100, buy_in=10000, max_round=50,
        hero_user_id=user.id, scenario="cash_6max_100bb", profile_scope="cash_6max_100bb",
    )
    db.add(game)
    db.flush()
    hero = GamePlayer(
        game_id=game.id, seat_index=0, display_name="Hero", engine_uuid=f"hero-{suffix}",
        user_id=user.id, is_bot=False, starting_stack=10000,
    )
    villain = GamePlayer(
        game_id=game.id, seat_index=1, display_name="Bot", engine_uuid=f"bot-{suffix}",
        is_bot=True, starting_stack=10000,
    )
    db.add_all([hero, villain])
    db.flush()
    return game, hero, villain


def _hands(db, game, hero, villain, count: int, vpip: bool):
    for round_count in range(count):
        hand = Hand(
            game_id=game.id, round_count=round_count,
            street_reached=Street.PREFLOP, board=[], had_showdown=False,
        )
        db.add(hand)
        db.flush()
        db.add_all([
            HandPlayer(hand_id=hand.id, game_player_id=hero.id, position="BTN"),
            HandPlayer(hand_id=hand.id, game_player_id=villain.id, position="BB"),
        ])
        db.add(Action(
            hand_id=hand.id, game_player_id=hero.id, street=Street.PREFLOP,
            action="raise" if vpip else "fold", amount=300 if vpip else 0, seq=0,
        ))


def _fixture(db):
    user = User(email="history@test.local", display_name="Hero")
    db.add(user)
    db.flush()
    old_game, old_hero, old_villain = _game(db, user, "old")
    latest_game, latest_hero, latest_villain = _game(db, user, "latest")
    _hands(db, old_game, old_hero, old_villain, 20, vpip=False)
    _hands(db, latest_game, latest_hero, latest_villain, 10, vpip=True)
    evaluation = HistoryEvaluation(
        user_id=user.id, scope_key="cash_6max_100bb", window_hands=25,
        latest_game_id=latest_game.id, threshold_profile="cash_6max_100bb",
        threshold_version="2026-07-23.v2", status=EvaluationStatus.PENDING,
    )
    db.add(evaluation)
    db.commit()
    return user, latest_game, evaluation


def test_snapshot_uses_sum_counts_and_excludes_latest_game_from_baseline(db_session):
    _, latest_game, evaluation = _fixture(db_session)
    result = build_history_snapshot(db_session, evaluation)
    snapshot = result["stats_snapshot"]
    assert snapshot["rolling_500"]["vpip"] == {"pct": 40.0, "n": 10, "d": 25}
    assert snapshot["latest_game"]["vpip"] == {"pct": 100.0, "n": 10, "d": 10}
    assert snapshot["prior_500_baseline"]["vpip"] == {"pct": 0.0, "n": 0, "d": 20}
    assert result["latest_game_id"] == latest_game.id


def test_llm_failure_keeps_deterministic_history_report_completed(db_session, monkeypatch):
    user, _, evaluation = _fixture(db_session)
    TestSessionLocal = sessionmaker(bind=db_session.get_bind(), future=True, expire_on_commit=False)
    monkeypatch.setattr("ai_functions.history_evaluation.pipeline.SessionLocal", TestSessionLocal)

    async def fail_synthesis(*args, **kwargs):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr("ai_functions.history_evaluation.pipeline.synthesize", fail_synthesis)
    asyncio.run(run_history_evaluation({}, str(evaluation.id)))
    db_session.refresh(evaluation)
    assert evaluation.status == EvaluationStatus.COMPLETED
    assert evaluation.stats_snapshot["rolling_500"]["hands_dealt"] == 25
    assert evaluation.report["synthesis_error"] == "model unavailable"
    assert db_session.get(PlayerProfile, (user.id, "cash_6max_100bb")) is None
