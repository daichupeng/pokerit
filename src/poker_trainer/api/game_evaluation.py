"""REST endpoints for the game-evaluation background pipeline (coach agent
Stage 5) and the correction loop (discard/restore/dispute/viewed — Phase
5+6's Stage 4). Enqueues an arq job and exposes polling/read endpoints — no
WebSocket, per the feature's Fork L decision.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from poker_engine.db.models import EvaluationStatus, GameEvaluation, User
from poker_trainer.api.games import _load_owned_game
from poker_trainer.auth.deps import get_db, require_user
from poker_trainer.jobs import get_redis_pool

from ai_functions.memory.persistence import rebuild_and_persist

router = APIRouter(prefix="/api", tags=["game-evaluation"])


def _now():
    return datetime.now(timezone.utc)


def _load_owned_evaluation(db: Session, game_id: str, eval_id: str, user: User) -> GameEvaluation:
    game = _load_owned_game(db, game_id, user)
    try:
        evaluation = db.get(GameEvaluation, eval_id)
    except Exception:  # malformed UUID etc.
        evaluation = None
    if evaluation is None or evaluation.game_id != game.id:
        raise HTTPException(404, "Evaluation not found.")
    return evaluation


def _summary(evaluation: GameEvaluation) -> dict:
    return {
        "evaluation_id": str(evaluation.id),
        "status": evaluation.status.value,
        "created_at": evaluation.created_at.isoformat() if evaluation.created_at else None,
        "completed_at": evaluation.completed_at.isoformat() if evaluation.completed_at else None,
    }


@router.post("/games/{game_id}/evaluate")
async def evaluate_game(
    game_id: str,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    game = _load_owned_game(db, game_id, user)

    evaluation = GameEvaluation(
        game_id=game.id, user_id=user.id, status=EvaluationStatus.PENDING,
        progress_current=0, progress_total=0,
    )
    db.add(evaluation)
    db.commit()
    db.refresh(evaluation)

    pool = await get_redis_pool()
    await pool.enqueue_job("run_evaluation", str(evaluation.id))

    return {"evaluation_id": str(evaluation.id)}


@router.get("/games/{game_id}/evaluations")
def list_evaluations(
    game_id: str,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    game = _load_owned_game(db, game_id, user)
    evaluations = db.execute(
        select(GameEvaluation)
        .where(GameEvaluation.game_id == game.id)
        .order_by(GameEvaluation.created_at.desc())
    ).scalars().all()
    return [_summary(e) for e in evaluations]


@router.get("/games/{game_id}/evaluations/{eval_id}")
def get_evaluation(
    game_id: str,
    eval_id: str,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    evaluation = _load_owned_evaluation(db, game_id, eval_id, user)
    return {
        **_summary(evaluation),
        "current_stage": evaluation.current_stage,
        "progress_current": evaluation.progress_current,
        "progress_total": evaluation.progress_total,
        "error": evaluation.error,
        "stats_snapshot": evaluation.stats_snapshot,
        "leak_tags": evaluation.leak_tags,
        "report": evaluation.report,
        "model_versions": evaluation.model_versions,
        "discarded_at": evaluation.discarded_at.isoformat() if evaluation.discarded_at else None,
        "disputed_tags": evaluation.disputed_tags or [],
        "viewed_at": evaluation.viewed_at.isoformat() if evaluation.viewed_at else None,
    }


@router.get("/games/{game_id}/evaluations/{eval_id}/status")
def get_evaluation_status(
    game_id: str,
    eval_id: str,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    evaluation = _load_owned_evaluation(db, game_id, eval_id, user)
    return {
        "status": evaluation.status.value,
        "progress_current": evaluation.progress_current,
        "progress_total": evaluation.progress_total,
        "current_stage": evaluation.current_stage,
        "error": evaluation.error,
    }


@router.post("/games/{game_id}/evaluations/{eval_id}/discard")
async def discard_evaluation(
    game_id: str,
    eval_id: str,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    evaluation = _load_owned_evaluation(db, game_id, eval_id, user)
    evaluation.discarded_at = _now()
    db.commit()
    await rebuild_and_persist(db, user.id)
    return {"discarded_at": evaluation.discarded_at.isoformat()}


@router.post("/games/{game_id}/evaluations/{eval_id}/restore")
async def restore_evaluation(
    game_id: str,
    eval_id: str,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    evaluation = _load_owned_evaluation(db, game_id, eval_id, user)
    evaluation.discarded_at = None
    db.commit()
    await rebuild_and_persist(db, user.id)
    return {"discarded_at": None}


class DisputeRequest(BaseModel):
    tags: list[str]
    disputed: bool


@router.post("/games/{game_id}/evaluations/{eval_id}/dispute")
async def dispute_evaluation_tags(
    game_id: str,
    eval_id: str,
    body: DisputeRequest,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    evaluation = _load_owned_evaluation(db, game_id, eval_id, user)
    disputed = set(evaluation.disputed_tags or [])
    if body.disputed:
        disputed |= set(body.tags)
    else:
        disputed -= set(body.tags)
    evaluation.disputed_tags = sorted(disputed)
    db.commit()
    await rebuild_and_persist(db, user.id)
    return {"disputed_tags": evaluation.disputed_tags}


@router.post("/games/{game_id}/evaluations/{eval_id}/viewed")
def mark_evaluation_viewed(
    game_id: str,
    eval_id: str,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    evaluation = _load_owned_evaluation(db, game_id, eval_id, user)
    if evaluation.viewed_at is None:
        evaluation.viewed_at = _now()
        db.commit()
    return {"viewed_at": evaluation.viewed_at.isoformat()}


@router.get("/evaluations/unviewed")
def list_unviewed_evaluations(
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    """Completed, non-discarded evaluations this user hasn't opened yet —
    for the history-page new-report popup."""
    evaluations = db.execute(
        select(GameEvaluation).where(
            GameEvaluation.user_id == user.id,
            GameEvaluation.status == EvaluationStatus.COMPLETED,
            GameEvaluation.discarded_at.is_(None),
            GameEvaluation.viewed_at.is_(None),
        ).order_by(GameEvaluation.completed_at.desc())
    ).scalars().all()
    return [
        {**_summary(e), "game_id": str(e.game_id)}
        for e in evaluations
    ]
