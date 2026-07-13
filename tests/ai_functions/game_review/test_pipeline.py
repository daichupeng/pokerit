"""Tests for pipeline.py (src/ai_functions/game_review/pipeline.py).

Calls run_evaluation() directly — no real Redis/arq needed, since the job
function itself has no queue dependency. Monkeypatches the two LLM call
sites (street_agent's chat_model_with_usage and the tool-loop's, used by
synthesis) so the whole run completes without network access.
"""

from __future__ import annotations

import asyncio
import json

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from poker_engine.db.models import (
    Action,
    BatchStatus,
    EvaluationStatus,
    Game,
    GameEvaluation,
    GameEvaluationBatch,
    GamePlayer,
    Hand,
    HandPlayer,
    Street,
    User,
)
from shared_services.llm import StreamResult, TokenUsage

from ai_functions.game_review.pipeline import run_evaluation


def _patch_session_local(db_session, monkeypatch):
    """pipeline.py opens its own SessionLocal() per task; point it at this
    test's connection/transaction so writes are visible to db_session and
    rolled back by conftest's teardown, same pattern as
    test_ws_stats_update.py's SessionLocal monkeypatch.
    """
    TestSessionLocal = sessionmaker(bind=db_session.get_bind(), future=True, expire_on_commit=False)
    monkeypatch.setattr("ai_functions.game_review.pipeline.SessionLocal", TestSessionLocal)


def _make_user(db, email="hero@test.local"):
    user = User(email=email, display_name="Hero")
    db.add(user)
    db.flush()
    return user


def _make_game(db, user):
    game = Game(small_blind=50, big_blind=100, buy_in=10000, max_round=50, hero_user_id=user.id)
    db.add(game)
    db.flush()
    hero_gp = GamePlayer(
        game_id=game.id, seat_index=0, display_name="Hero", engine_uuid="hero-uuid",
        user_id=user.id, is_bot=False, starting_stack=10000,
    )
    villain_gp = GamePlayer(
        game_id=game.id, seat_index=1, display_name="Bot", engine_uuid="bot-uuid",
        user_id=None, is_bot=True, starting_stack=10000,
    )
    db.add_all([hero_gp, villain_gp])
    db.flush()
    return game, hero_gp, villain_gp


def _make_hands(db, game, hero_gp, villain_gp):
    # Hand 0: preflop-only. Hero raises, villain folds. Qualifies the preflop pool.
    hand0 = Hand(game_id=game.id, round_count=0, street_reached=Street.PREFLOP,
                 board=[], had_showdown=False, pot_total=300)
    db.add(hand0)
    db.flush()
    db.add_all([
        HandPlayer(hand_id=hand0.id, game_player_id=hero_gp.id, position="BTN", hole_cards=["As", "Kh"]),
        HandPlayer(hand_id=hand0.id, game_player_id=villain_gp.id, position="BB"),
    ])
    db.add(Action(hand_id=hand0.id, game_player_id=hero_gp.id, street=Street.PREFLOP,
                   action="raise", amount=300, seq=0))
    db.add(Action(hand_id=hand0.id, game_player_id=villain_gp.id, street=Street.PREFLOP,
                   action="fold", amount=0, seq=1))

    # Hand 1: reaches flop. Hero calls preflop, checks flop (nonfold action),
    # faces a bet, folds. Qualifies both preflop and flop pools.
    hand1 = Hand(game_id=game.id, round_count=1, street_reached=Street.FLOP,
                 board=["2c", "7d", "Jh"], had_showdown=False, pot_total=700)
    db.add(hand1)
    db.flush()
    db.add_all([
        HandPlayer(hand_id=hand1.id, game_player_id=hero_gp.id, position="BB", hole_cards=["Qs", "Qd"]),
        HandPlayer(hand_id=hand1.id, game_player_id=villain_gp.id, position="BTN"),
    ])
    db.add(Action(hand_id=hand1.id, game_player_id=villain_gp.id, street=Street.PREFLOP,
                   action="raise", amount=300, seq=0))
    db.add(Action(hand_id=hand1.id, game_player_id=hero_gp.id, street=Street.PREFLOP,
                   action="call", amount=300, seq=1))
    db.add(Action(hand_id=hand1.id, game_player_id=hero_gp.id, street=Street.FLOP,
                   action="check", amount=0, seq=2))
    db.add(Action(hand_id=hand1.id, game_player_id=villain_gp.id, street=Street.FLOP,
                   action="raise", amount=200, seq=3))
    db.add(Action(hand_id=hand1.id, game_player_id=hero_gp.id, street=Street.FLOP,
                   action="fold", amount=0, seq=4))
    db.flush()

    return hand0, hand1


def _fake_street_llm(call_log):
    async def _fake(**kwargs):
        call_log.append(kwargs["messages"][1]["content"])
        return StreamResult(text="[]", usage=TokenUsage(prompt_tokens=5, completion_tokens=2))

    return _fake


def _fake_synthesis_llm():
    async def _fake(**kwargs):
        report = {"summary": "Solid small sample.", "sections": []}
        return StreamResult(text=json.dumps(report), usage=TokenUsage(prompt_tokens=5, completion_tokens=2))

    return _fake


def test_run_evaluation_completes_end_to_end(db_session, monkeypatch):
    db = db_session
    _patch_session_local(db_session, monkeypatch)
    user = _make_user(db)
    game, hero_gp, villain_gp = _make_game(db, user)
    _make_hands(db, game, hero_gp, villain_gp)

    evaluation = GameEvaluation(game_id=game.id, user_id=user.id, status=EvaluationStatus.PENDING)
    db.add(evaluation)
    db.commit()
    db.refresh(evaluation)

    call_log: list[str] = []
    monkeypatch.setattr(
        "ai_functions.game_review.street_agent.chat_model_with_usage",
        _fake_street_llm(call_log),
    )
    monkeypatch.setattr(
        "ai_functions.tools.loop.chat_model_with_usage",
        _fake_synthesis_llm(),
    )

    asyncio.run(run_evaluation({}, str(evaluation.id)))

    db.refresh(evaluation)
    assert evaluation.status == EvaluationStatus.COMPLETED
    assert evaluation.progress_current == evaluation.progress_total
    assert evaluation.leak_tags is not None
    assert evaluation.report == {"summary": "Solid small sample.", "sections": []}
    assert evaluation.stats_snapshot["game_level"]["hands_dealt"] == 2

    batches = db.execute(
        select(GameEvaluationBatch)
        .where(GameEvaluationBatch.evaluation_id == evaluation.id)
    ).scalars().all()
    assert {b.agent for b in batches} == {"preflop", "flop"}
    assert all(b.status == BatchStatus.COMPLETED for b in batches)
    # 2 batches total (preflop pool of 2 hands, flop pool of 1 hand), each one LLM call.
    assert len(call_log) == 2


def test_run_evaluation_resume_skips_completed_batches(db_session, monkeypatch):
    db = db_session
    _patch_session_local(db_session, monkeypatch)
    user = _make_user(db)
    game, hero_gp, villain_gp = _make_game(db, user)
    _make_hands(db, game, hero_gp, villain_gp)

    evaluation = GameEvaluation(game_id=game.id, user_id=user.id, status=EvaluationStatus.PENDING)
    db.add(evaluation)
    db.commit()
    db.refresh(evaluation)

    call_log: list[str] = []
    monkeypatch.setattr(
        "ai_functions.game_review.street_agent.chat_model_with_usage",
        _fake_street_llm(call_log),
    )
    monkeypatch.setattr(
        "ai_functions.tools.loop.chat_model_with_usage",
        _fake_synthesis_llm(),
    )

    asyncio.run(run_evaluation({}, str(evaluation.id)))
    assert len(call_log) == 2

    # Simulate "crashed mid-run, restarted": reset to RUNNING, put the flop
    # batch back to PENDING (as if it never finished), leave preflop COMPLETED.
    db.refresh(evaluation)
    evaluation.status = EvaluationStatus.RUNNING
    evaluation.report = None
    evaluation.leak_tags = None
    batches = db.execute(
        select(GameEvaluationBatch)
        .where(GameEvaluationBatch.evaluation_id == evaluation.id)
    ).scalars().all()
    flop_batch = next(b for b in batches if b.agent == "flop")
    preflop_batch = next(b for b in batches if b.agent == "preflop")
    flop_batch.status = BatchStatus.PENDING
    flop_batch.output = None
    evaluation.progress_current -= 1
    db.commit()

    call_log.clear()
    asyncio.run(run_evaluation({}, str(evaluation.id)))

    # Only the still-pending flop batch should have triggered a new LLM call —
    # the already-completed preflop batch must never be recomputed.
    assert len(call_log) == 1

    db.refresh(evaluation)
    assert evaluation.status == EvaluationStatus.COMPLETED
    db.refresh(preflop_batch)
    db.refresh(flop_batch)
    assert preflop_batch.status == BatchStatus.COMPLETED
    assert flop_batch.status == BatchStatus.COMPLETED


def test_run_evaluation_marks_failed_when_batch_exhausts_retries(db_session, monkeypatch):
    db = db_session
    _patch_session_local(db_session, monkeypatch)
    user = _make_user(db)
    game, hero_gp, villain_gp = _make_game(db, user)
    _make_hands(db, game, hero_gp, villain_gp)

    evaluation = GameEvaluation(game_id=game.id, user_id=user.id, status=EvaluationStatus.PENDING)
    db.add(evaluation)
    db.commit()
    db.refresh(evaluation)

    async def _always_fails(**kwargs):
        raise RuntimeError("simulated LLM outage")

    monkeypatch.setattr(
        "ai_functions.game_review.street_agent.chat_model_with_usage",
        _always_fails,
    )

    asyncio.run(run_evaluation({}, str(evaluation.id)))

    db.refresh(evaluation)
    assert evaluation.status == EvaluationStatus.FAILED
    assert evaluation.error
    assert evaluation.report is None
