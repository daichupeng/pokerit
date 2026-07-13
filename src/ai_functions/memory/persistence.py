"""DB I/O for the player profile: loading/saving ``player_profiles`` rows and
querying which evaluations are currently eligible to be folded (decision 2's
inclusion rule). Kept separate from ``fold.py`` so the fold's state-machine
logic stays pure and DB-free.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from poker_engine.db.models import EvaluationStatus, GameEvaluation, PlayerProfile


def _now():
    return datetime.now(timezone.utc)


def load_profile_row(db, user_id) -> PlayerProfile | None:
    return db.get(PlayerProfile, user_id)


def query_folded_evaluations(db, user_id, reset_at=None) -> list[GameEvaluation]:
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
    candidates = db.execute(query).scalars().all()

    latest_by_game: dict = {}
    for evaluation in candidates:
        current = latest_by_game.get(evaluation.game_id)
        if current is None or evaluation.completed_at > current.completed_at:
            latest_by_game[evaluation.game_id] = evaluation

    return sorted(latest_by_game.values(), key=lambda e: e.completed_at)


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
    }


def save_profile_row(
    db,
    user_id,
    state: dict,
    playstyle_summary: str | None,
    model_versions: dict | None = None,
    reset_at=None,
) -> PlayerProfile:
    """Upsert ``player_profiles`` for ``user_id`` with the given fold state.

    ``reset_at`` is passed through unchanged from the existing row unless
    explicitly overridden (the reset route is the only caller that overrides
    it) — folding/rebuilding never touches it themselves.
    """
    row = db.get(PlayerProfile, user_id)
    if row is None:
        row = PlayerProfile(user_id=user_id)
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


def build_profile_context(db, user_id) -> dict | None:
    """The ``player_profile`` pinned-context dict for synthesis: this user's
    current leak states, stat trends, and playstyle summary — or ``None`` if
    they have no profile yet (a first-ever evaluation), so synthesis can omit
    the key entirely (decision 4: read BEFORE this evaluation's own fold).
    """
    from ai_functions.memory.trends import compute_trends

    row = load_profile_row(db, user_id)
    if row is None or not row.evaluations_folded:
        return None

    folded = query_folded_evaluations(db, user_id, row.reset_at)
    snapshots = [(e.stats_snapshot or {}).get("game_level") or {} for e in folded]
    return {
        "evaluations_folded": row.evaluations_folded,
        "leaks": row.leaks,
        "trends": compute_trends(snapshots),
        "playstyle_summary": row.playstyle_summary,
    }


async def _regenerate_and_save(db, user_id, state: dict, reset_at=None) -> PlayerProfile:
    """Shared tail of fold_and_persist/rebuild_and_persist: recompute trends
    over the freshly-folded evaluation history, regenerate the playstyle
    summary from scratch (never appended, per decision 1), and persist.
    """
    from ai_functions.memory.playstyle import generate_playstyle_summary
    from ai_functions.memory.trends import compute_trends

    folded = query_folded_evaluations(db, user_id, reset_at)
    snapshots = [
        (e.stats_snapshot or {}).get("game_level") or {} for e in folded
    ]
    trends = compute_trends(snapshots)
    summary = await generate_playstyle_summary(state, trends)
    return save_profile_row(db, user_id, state, summary, reset_at=reset_at)


async def fold_and_persist(db, evaluation: GameEvaluation) -> PlayerProfile:
    """Fold one just-completed evaluation into its user's profile
    incrementally, regenerate the summary, and persist. The cheap day-to-day
    path (decision 3) — corrections always use ``rebuild_and_persist``
    instead so every correction trivially equals a from-scratch rebuild.
    """
    from ai_functions.memory.fold import EMPTY_PROFILE_STATE, fold_evaluation

    existing_row = load_profile_row(db, evaluation.user_id)
    state = (
        {"evaluations_folded": existing_row.evaluations_folded, "leaks": existing_row.leaks}
        if existing_row is not None
        else dict(EMPTY_PROFILE_STATE)
    )
    reset_at = existing_row.reset_at if existing_row is not None else None
    next_state = fold_evaluation(state, evaluation_to_fold_input(evaluation))
    return await _regenerate_and_save(db, evaluation.user_id, next_state, reset_at=reset_at)


async def rebuild_and_persist(db, user_id, reset_at=None) -> PlayerProfile:
    """Full from-scratch rebuild, regenerate the summary, and persist. Every
    correction route (discard/restore/dispute/reset) uses this so the
    resulting profile always equals a from-scratch rebuild by construction.

    ``reset_at``, when given, overrides the persisted row's own ``reset_at``
    (the reset route's job) — otherwise it's read from the existing row.
    """
    from ai_functions.memory.fold import rebuild_profile

    if reset_at is None:
        existing = load_profile_row(db, user_id)
        reset_at = existing.reset_at if existing else None
    state = rebuild_profile(db, user_id, reset_at=reset_at)
    return await _regenerate_and_save(db, user_id, state, reset_at=reset_at)
