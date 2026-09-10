"""DB I/O for the player profile: loading/saving ``player_profiles`` rows and
querying which evaluations are currently eligible to be folded (decision 2's
inclusion rule). Kept separate from ``fold.py`` so the fold's state-machine
logic stays pure and DB-free.
"""

from __future__ import annotations

import asyncio
import hashlib

from datetime import datetime, timezone

from sqlalchemy import select, text

from poker_engine.db.models import EvaluationStatus, GameEvaluation, PlayerProfile
from poker_engine.scenarios import DEFAULT_PROFILE_SCOPE, is_custom_profile_scope, profile_scope_for_game


def _now():
    return datetime.now(timezone.utc)


def load_profile_row(db, user_id, scope_key: str = DEFAULT_PROFILE_SCOPE) -> PlayerProfile | None:
    return db.get(PlayerProfile, (user_id, scope_key))


def query_folded_evaluations(
    db, user_id, reset_at=None, scope_key: str = DEFAULT_PROFILE_SCOPE
) -> list[GameEvaluation]:
    """Evaluations currently eligible for the fold, per decision 2:
    ``status == COMPLETED``, ``discarded_at IS NULL``, ``completed_at`` after
    ``reset_at`` (if given), and only the latest such evaluation per game
    (re-runs supersede older evaluations of the same game). Ordered by
    ``completed_at`` ascending — the order the fold must replay them in.
    """
    query = select(GameEvaluation).where(
        GameEvaluation.user_id == user_id,
        GameEvaluation.status == EvaluationStatus.COMPLETED,
        GameEvaluation.discarded_at.is_(None),
    )
    if reset_at is not None:
        query = query.where(GameEvaluation.completed_at > reset_at)
    candidates = [
        evaluation
        for evaluation in db.execute(query).scalars().all()
        if profile_scope_for_game(evaluation.game) == scope_key
        and (not is_custom_profile_scope(scope_key) or
             ((evaluation.stats_snapshot or {}).get("threshold_profile") or {}).get("key") == scope_key)
    ]

    latest_by_game: dict = {}
    for evaluation in candidates:
        current = latest_by_game.get(evaluation.game_id)
        if current is None or (evaluation.completed_at, str(evaluation.id)) > (current.completed_at, str(current.id)):
            latest_by_game[evaluation.game_id] = evaluation

    return sorted(latest_by_game.values(), key=lambda e: (e.completed_at, str(e.id)))


def evaluation_to_fold_input(evaluation: GameEvaluation) -> dict:
    """Adapt a ``GameEvaluation`` row into the dict shape ``fold_evaluation``
    expects."""
    stats_snapshot = evaluation.stats_snapshot or {}
    return {
        "eval_id": str(evaluation.id),
        "date": evaluation.completed_at.isoformat() if evaluation.completed_at else None,
        "leak_tags": evaluation.leak_tags or [],
        "disputed_tags": evaluation.disputed_tags or [],
        "stats_snapshot": stats_snapshot.get("game_level") or {},
        "threshold_profile": (stats_snapshot.get("threshold_profile") or {}).get("key"),
    }


def save_profile_row(
    db,
    user_id,
    state: dict,
    playstyle_summary: str | None,
    model_versions: dict | None = None,
    reset_at=None,
    scope_key: str = DEFAULT_PROFILE_SCOPE,
) -> PlayerProfile:
    """Upsert ``player_profiles`` for ``user_id`` with the given fold state.

    ``reset_at`` is passed through unchanged from the existing row unless
    explicitly overridden (the reset route is the only caller that overrides
    it) — folding/rebuilding never touches it themselves.
    """
    row = load_profile_row(db, user_id, scope_key)
    if row is None:
        row = PlayerProfile(user_id=user_id, scope_key=scope_key)
        db.add(row)
    row.evaluations_folded = state["evaluations_folded"]
    row.leaks = state["leaks"]
    row.playstyle_summary = playstyle_summary
    row.updated_at = _now()
    if model_versions is not None:
        row.model_versions = model_versions
    if reset_at is not None:
        row.reset_at = reset_at
    db.commit()
    db.refresh(row)
    return row


def build_profile_context(
    db, user_id, scope_key: str = DEFAULT_PROFILE_SCOPE
) -> dict | None:
    """The ``player_profile`` pinned-context dict for synthesis: this user's
    current leak states, stat trends, and playstyle summary — or ``None`` if
    they have no profile yet (a first-ever evaluation), so synthesis can omit
    the key entirely (decision 4: read BEFORE this evaluation's own fold).
    """
    from ai_functions.memory.trends import compute_trends
    from ai_functions.memory.fold import EMPTY_PROFILE_STATE, fold_evaluation

    row = load_profile_row(db, user_id, scope_key)
    folded = query_folded_evaluations(db, user_id, row.reset_at if row else None, scope_key)
    if not folded:
        return None
    state = dict(EMPTY_PROFILE_STATE)
    for evaluation in folded:
        state = fold_evaluation(state, evaluation_to_fold_input(evaluation))
    summary_is_current = row is not None and (
        row.evaluations_folded == state["evaluations_folded"] and row.leaks == state["leaks"]
    )
    snapshots = [(e.stats_snapshot or {}).get("game_level") or {} for e in folded]
    return {
        "evaluations_folded": state["evaluations_folded"],
        "leaks": state["leaks"],
        "trends": compute_trends(snapshots),
        "playstyle_summary": row.playstyle_summary if summary_is_current else "",
        "profile_scope": scope_key,
    }


async def _regenerate_and_save(
    db, user_id, state: dict, reset_at=None, scope_key: str = DEFAULT_PROFILE_SCOPE
) -> PlayerProfile:
    """Shared tail of fold_and_persist/rebuild_and_persist: recompute trends
    over the freshly-folded evaluation history, regenerate the playstyle
    summary from scratch (never appended, per decision 1), and persist.
    """
    from ai_functions.memory.playstyle import generate_playstyle_summary
    from ai_functions.memory.trends import compute_trends

    folded = query_folded_evaluations(db, user_id, reset_at, scope_key)
    snapshots = [
        (e.stats_snapshot or {}).get("game_level") or {} for e in folded
    ]
    trends = compute_trends(snapshots)
    summary = await generate_playstyle_summary(state, trends)
    return save_profile_row(
        db, user_id, state, summary, reset_at=reset_at, scope_key=scope_key
    )


async def fold_and_persist(db, evaluation: GameEvaluation) -> PlayerProfile:
    """Refresh from the latest eligible evaluation per game, including re-runs."""
    return await rebuild_and_persist(
        db, evaluation.user_id, scope_key=profile_scope_for_game(evaluation.game)
    )


async def rebuild_and_persist(
    db, user_id, reset_at=None, scope_key: str = DEFAULT_PROFILE_SCOPE
) -> PlayerProfile:
    """Full from-scratch rebuild, regenerate the summary, and persist. Every
    correction route (discard/restore/dispute/reset) uses this so the
    resulting profile always equals a from-scratch rebuild by construction.

    ``reset_at``, when given, overrides the persisted row's own ``reset_at``
    (the reset route's job) — otherwise it's read from the existing row.
    """
    from ai_functions.memory.fold import rebuild_profile

    # Transaction-scoped across both the web app and workers, even before the
    # first profile row exists. Poll without blocking the event loop or moving
    # the session to a thread that could outlive cancellation and rollback.
    lock_key = int.from_bytes(
        hashlib.sha256(f"profile:{user_id}:{scope_key}".encode()).digest()[:8],
        byteorder="big", signed=True,
    )
    try:
        while not db.execute(
            text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": lock_key}
        ).scalar_one():
            await asyncio.sleep(0.05)
        db.expire_all()
        if reset_at is None:
            existing = load_profile_row(db, user_id, scope_key)
            reset_at = existing.reset_at if existing else None
        state = rebuild_profile(db, user_id, reset_at=reset_at, scope_key=scope_key)
        return await _regenerate_and_save(
            db, user_id, state, reset_at=reset_at, scope_key=scope_key
        )
    except BaseException:
        db.rollback()
        raise
