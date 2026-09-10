"""API for scope-isolated rolling history evaluations."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_functions.game_review.leak_taxonomy import get_threshold_profile
from poker_engine.db.models import EvaluationStatus, Game, Hand, HistoryEvaluation, User
from poker_engine.scenarios import (
    DEFAULT_PROFILE_SCOPE,
    profile_scope_for_game,
    is_profile_scope,
    profile_scope_label,
)
from poker_trainer.auth.deps import get_db, require_user
from poker_trainer.jobs import get_redis_pool

router = APIRouter(prefix="/api/profile/history-evaluations", tags=["history-evaluation"])


class HistoryEvaluationRequest(BaseModel):
    scope: str = DEFAULT_PROFILE_SCOPE
    window_hands: int = Field(default=500, ge=1, le=500)
    latest_game_id: UUID | None = None


def _validate_scope(scope: str) -> None:
    if not is_profile_scope(scope):
        raise HTTPException(422, f"Unknown training profile scope: {scope}")


def _load_owned(db: Session, evaluation_id: str, user: User) -> HistoryEvaluation:
    try:
        evaluation = db.get(HistoryEvaluation, evaluation_id)
    except Exception:
        evaluation = None
    if evaluation is None or evaluation.user_id != user.id:
        raise HTTPException(404, "History evaluation not found.")
    return evaluation


def _summary(evaluation: HistoryEvaluation) -> dict:
    return {
        "evaluation_id": str(evaluation.id),
        "scope": evaluation.scope_key,
        "scope_label": (evaluation.report or {}).get("scope_label") or profile_scope_label(evaluation.scope_key),
        "status": evaluation.status.value,
        "window_hands": evaluation.window_hands,
        "latest_game_id": str(evaluation.latest_game_id) if evaluation.latest_game_id else None,
        "created_at": evaluation.created_at.isoformat() if evaluation.created_at else None,
        "completed_at": evaluation.completed_at.isoformat() if evaluation.completed_at else None,
    }


@router.post("")
async def create_history_evaluation(
    body: HistoryEvaluationRequest,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    _validate_scope(body.scope)
    if body.scope == "custom":
        raise HTTPException(422, "Choose a specific custom training scope; mixed custom history cannot be evaluated.")
    if body.latest_game_id is not None:
        latest_game = db.get(Game, body.latest_game_id)
        if latest_game is None or latest_game.hero_user_id != user.id:
            raise HTTPException(404, "Latest game not found.")
        if profile_scope_for_game(latest_game) != body.scope:
            raise HTTPException(422, "Latest game does not belong to the requested profile scope.")
        has_saved_hand = db.execute(
            select(Hand.id).where(Hand.game_id == latest_game.id).limit(1)
        ).scalar_one_or_none()
        if has_saved_hand is None:
            raise HTTPException(422, "Latest game does not contain a saved hand.")
    profile = get_threshold_profile(body.scope)
    evaluation = HistoryEvaluation(
        user_id=user.id,
        scope_key=body.scope,
        window_hands=body.window_hands,
        latest_game_id=body.latest_game_id,
        threshold_profile=profile.key,
        threshold_version=profile.version,
        status=EvaluationStatus.PENDING,
    )
    db.add(evaluation)
    db.commit()
    db.refresh(evaluation)
    pool = await get_redis_pool()
    await pool.enqueue_job("run_history_evaluation", str(evaluation.id))
    return {"evaluation_id": str(evaluation.id)}


@router.get("")
def list_history_evaluations(
    scope: str = Query(default=DEFAULT_PROFILE_SCOPE),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    _validate_scope(scope)
    rows = db.execute(
        select(HistoryEvaluation)
        .where(HistoryEvaluation.user_id == user.id, HistoryEvaluation.scope_key == scope)
        .order_by(HistoryEvaluation.created_at.desc())
    ).scalars().all()
    return [_summary(row) for row in rows]


@router.get("/{evaluation_id}")
def get_history_evaluation(
    evaluation_id: str,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    evaluation = _load_owned(db, evaluation_id, user)
    return {
        **_summary(evaluation),
        "cutoff_at": evaluation.cutoff_at.isoformat() if evaluation.cutoff_at else None,
        "games_included": evaluation.games_included,
        "stats_snapshot": evaluation.stats_snapshot,
        "sample_status": evaluation.sample_status,
        "trend_comparison": evaluation.trend_comparison,
        "deterministic_stat_leaks": evaluation.deterministic_stat_leaks or [],
        "report": evaluation.report,
        "model_versions": evaluation.model_versions,
        "threshold_profile": evaluation.threshold_profile,
        "threshold_version": evaluation.threshold_version,
        "error": evaluation.error,
    }


@router.get("/{evaluation_id}/status")
def get_history_evaluation_status(
    evaluation_id: str,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    evaluation = _load_owned(db, evaluation_id, user)
    return {"status": evaluation.status.value, "error": evaluation.error}
