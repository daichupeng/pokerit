"""REST endpoints for the game-evaluation background pipeline (coach agent
Stage 5). Enqueues an arq job and exposes polling/read endpoints — no
WebSocket, per the feature's Fork L decision.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from poker_engine.db.models import EvaluationStatus, GameEvaluation, User
from poker_trainer.api.games import _load_owned_game
from poker_trainer.auth.deps import get_db, require_user
from poker_trainer.jobs import get_redis_pool

router = APIRouter(prefix="/api", tags=["game-evaluation"])


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
