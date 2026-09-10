"""Deterministic orchestrator for a game evaluation — the arq job function.

Snapshots stats, runs Stage 1 triage, dispatches every street-agent batch
concurrently, merges, then synthesizes. Idempotent by design: batch rows are
created once and never recreated, and only PENDING/FAILED batches are ever
re-run, so calling ``run_evaluation`` again after a crash resumes instead of
recomputing completed work.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from poker_engine.db.base import SessionLocal
from poker_engine.db.models import (
    BatchStatus,
    EvaluationStatus,
    Game,
    GameEvaluation,
    GameEvaluationBatch,
    Hand,
    User,
)
from poker_engine.stats import _sum_hands, preflop_event_evidence, to_display

from ai_functions.game_review import config
from ai_functions.game_review.leak_taxonomy import (
    get_threshold_profile,
    sample_status,
    threshold_profile_key_for_game,
)
from ai_functions.game_review.merge import merge_findings
from ai_functions.game_review.preflop_findings import detect_rfi_limp_findings
from ai_functions.game_review.session_dynamics import compute_session_dynamics
from ai_functions.game_review.street_agent import BATCH_SIZE, STREETS, run_batch
from ai_functions.game_review.synthesis import run_synthesis
from ai_functions.game_review.triage import triage_hands
from ai_functions.decision_snapshot import build_decision_snapshots
from ai_functions.preflop_ranges import (
    configured_api_key,
    configured_preflop_version,
    query_postgame_snapshots,
)
from ai_functions.memory.persistence import build_profile_context, fold_and_persist
from poker_engine.scenarios import profile_scope_for_game
from ai_functions.memory.profile_status import compute_profile_status

_log = logging.getLogger("prompts")

BATCH_MAX_ATTEMPTS = 2
MAX_CONCURRENT_BATCHES = 8


def _now():
    return datetime.now(timezone.utc)


def _chunk(items: list, size: int) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _load_game(db, game_id) -> Game | None:
    return db.execute(
        select(Game).where(Game.id == game_id).options(selectinload(Game.players))
    ).scalar_one_or_none()


def _load_game_with_hands(db, game_id) -> tuple[Game | None, list[Hand]]:
    game = _load_game(db, game_id)
    if game is None:
        return None, []
    hands = db.execute(
        select(Hand)
        .where(Hand.game_id == game_id)
        .options(selectinload(Hand.actions), selectinload(Hand.players))
        .order_by(Hand.round_count)
    ).scalars().all()
    return game, list(hands)


def _hero_gp_id(game: Game):
    from poker_trainer.api.games import _hero_seat

    hero = _hero_seat(game)
    return hero.id if hero else None


def _ensure_batches_created(db, evaluation: GameEvaluation, game: Game, hands: list[Hand]) -> None:
    """First-run-only setup: stats snapshot + batch rows. No-op on resume."""
    existing = db.execute(
        select(GameEvaluationBatch.id).where(GameEvaluationBatch.evaluation_id == evaluation.id)
    ).first()
    if existing is not None:
        return

    hero_gp_id = _hero_gp_id(game)
    threshold_profile = get_threshold_profile(threshold_profile_key_for_game(game))
    game_level = to_display(_sum_hands(hands, hero_gp_id))
    game_level["preflop_events"] = preflop_event_evidence(hands, hero_gp_id)
    stats_snapshot = {
        "evaluation_kind": "current_game",
        "game_level": game_level,
        "session_dynamics": compute_session_dynamics(hands, hero_gp_id),
        "threshold_profile": {
            "key": threshold_profile.key,
            "version": threshold_profile.version,
            "table_size_policy": "per_hand_supported_profiles",
        },
        "sample_status": sample_status(game_level, threshold_profile.key),
    }
    pools = triage_hands(hands, hero_gp_id)

    total_batches = 0
    for street in STREETS:
        pool = pools.get(street) or []
        for batch_index, batch in enumerate(_chunk(pool, BATCH_SIZE)):
            db.add(GameEvaluationBatch(
                evaluation_id=evaluation.id,
                agent=street,
                batch_index=batch_index,
                status=BatchStatus.PENDING,
                hand_ids=[str(h.id) for h in batch],
            ))
            total_batches += 1

    evaluation.stats_snapshot = stats_snapshot
    evaluation.status = EvaluationStatus.RUNNING
    evaluation.current_stage = "review"
    evaluation.progress_total = total_batches + 1  # +1 for synthesis
    db.commit()


async def _prepare_pokerai_evidence(evaluation_id) -> None:
    """Resolve at most 15 selected preflop decisions once per evaluation."""
    db = SessionLocal()
    try:
        evaluation = db.get(GameEvaluation, evaluation_id)
        if evaluation is None:
            return
        existing = (evaluation.stats_snapshot or {}).get("preflop_strategy_api")
        if existing is not None:
            return
        if configured_api_key() is None:
            stats_snapshot = dict(evaluation.stats_snapshot or {})
            stats_snapshot["preflop_strategy_api"] = {
                "configured": False,
                "version": configured_preflop_version(),
                "call_limit": config.POSTGAME_POKERAI_CALL_LIMIT,
                "attempted": 0,
                "resolved": 0,
                "failures": [],
                "evidence_by_decision": {},
            }
            evaluation.stats_snapshot = stats_snapshot
            db.commit()
            return

        game, hands = _load_game_with_hands(db, evaluation.game_id)
        if game is None:
            return
        hero_gp_id = _hero_gp_id(game)
        preflop_batches = db.execute(
            select(GameEvaluationBatch).where(
                GameEvaluationBatch.evaluation_id == evaluation_id,
                GameEvaluationBatch.agent == "preflop",
            ).order_by(GameEvaluationBatch.batch_index)
        ).scalars().all()
        selected_hand_ids = {
            str(hand_id)
            for batch in preflop_batches
            for hand_id in (batch.hand_ids or [])
        }
        snapshots = [
            snapshot
            for hand in hands
            if str(hand.id) in selected_hand_ids
            for snapshot in build_decision_snapshots(game, hand, hero_gp_id, "preflop")
        ]
    finally:
        db.close()

    metadata = await query_postgame_snapshots(
        snapshots, limit=config.POSTGAME_POKERAI_CALL_LIMIT,
    )

    db = SessionLocal()
    try:
        evaluation = db.get(GameEvaluation, evaluation_id)
        if evaluation is None:
            return
        if (evaluation.stats_snapshot or {}).get("preflop_strategy_api") is None:
            stats_snapshot = dict(evaluation.stats_snapshot or {})
            stats_snapshot["preflop_strategy_api"] = metadata
            evaluation.stats_snapshot = stats_snapshot
            db.commit()
    finally:
        db.close()


async def _run_one_batch(evaluation_id, batch_id, street: str, semaphore: asyncio.Semaphore) -> None:
    async with semaphore:
        db = SessionLocal()
        try:
            batch = db.get(GameEvaluationBatch, batch_id)
            evaluation = db.get(GameEvaluation, evaluation_id)
            game = _load_game(db, evaluation.game_id)
            hand_ids = list(batch.hand_ids)
            hands = db.execute(
                select(Hand)
                .where(Hand.id.in_(hand_ids))
                .options(selectinload(Hand.actions), selectinload(Hand.players))
                .order_by(Hand.round_count)
            ).scalars().all()
            hero_gp_id = _hero_gp_id(game)
            pokerai_meta = (evaluation.stats_snapshot or {}).get("preflop_strategy_api") or {}
            pokerai_evidence = pokerai_meta.get("evidence_by_decision") or {}

            error: str | None = None
            findings: list[dict] | None = None
            for attempt in range(1, BATCH_MAX_ATTEMPTS + 1):
                try:
                    findings = await run_batch(
                        street,
                        list(hands),
                        game,
                        hero_gp_id,
                        pokerai_evidence_by_decision=pokerai_evidence,
                    )
                    error = None
                    break
                except Exception as exc:  # noqa: BLE001 - recorded per batch, never crashes the gather
                    error = str(exc)
                    _log.warning(
                        "game_review.pipeline.batch_attempt_failed",
                        extra={"evaluation_id": str(evaluation_id), "street": street,
                               "batch_id": str(batch_id), "attempt": attempt, "error": error},
                    )

            if error is not None:
                batch.status = BatchStatus.FAILED
                batch.error = error
            else:
                batch.status = BatchStatus.COMPLETED
                batch.output = findings
            batch.completed_at = _now()
            evaluation.progress_current += 1
            db.commit()
        finally:
            db.close()


async def _run_pending_batches(evaluation_id) -> None:
    db = SessionLocal()
    try:
        pending = db.execute(
            select(GameEvaluationBatch).where(
                GameEvaluationBatch.evaluation_id == evaluation_id,
                GameEvaluationBatch.status.in_((BatchStatus.PENDING, BatchStatus.FAILED)),
            )
        ).scalars().all()
        tasks = [(b.id, b.agent) for b in pending]
    finally:
        db.close()

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_BATCHES)
    await asyncio.gather(*[
        _run_one_batch(evaluation_id, batch_id, street, semaphore) for batch_id, street in tasks
    ])


def _collect_street_findings(db, evaluation_id) -> dict[str, list[dict]]:
    batches = db.execute(
        select(GameEvaluationBatch).where(GameEvaluationBatch.evaluation_id == evaluation_id)
    ).scalars().all()
    street_findings: dict[str, list[dict]] = defaultdict(list)
    for batch in batches:
        street_findings[batch.agent].extend(batch.output or [])
    return dict(street_findings)


async def run_evaluation(ctx, evaluation_id: str) -> None:
    """The arq job: run (or resume) one game evaluation end to end."""
    db = SessionLocal()
    try:
        evaluation = db.get(GameEvaluation, evaluation_id)
        if evaluation is None:
            return

        game, hands = _load_game_with_hands(db, evaluation.game_id)
        if game is None:
            evaluation.status = EvaluationStatus.FAILED
            evaluation.error = "Game not found."
            evaluation.completed_at = _now()
            db.commit()
            return

        _ensure_batches_created(db, evaluation, game, hands)
    except Exception as exc:  # noqa: BLE001
        evaluation = db.get(GameEvaluation, evaluation_id)
        if evaluation is not None:
            evaluation.status = EvaluationStatus.FAILED
            evaluation.error = str(exc)
            evaluation.completed_at = _now()
            db.commit()
        return
    finally:
        db.close()

    try:
        await _prepare_pokerai_evidence(evaluation_id)
    except Exception as exc:  # noqa: BLE001 - optional evidence must fail closed
        _log.warning(
            "game_review.pokerai.prepare_failed",
            extra={"evaluation_id": str(evaluation_id), "error": str(exc)},
        )

    try:
        await _run_pending_batches(evaluation_id)
    except Exception as exc:  # noqa: BLE001
        db = SessionLocal()
        try:
            evaluation = db.get(GameEvaluation, evaluation_id)
            evaluation.status = EvaluationStatus.FAILED
            evaluation.error = str(exc)
            evaluation.completed_at = _now()
            db.commit()
        finally:
            db.close()
        return

    db = SessionLocal()
    try:
        evaluation = db.get(GameEvaluation, evaluation_id)
        failed_batches = db.execute(
            select(GameEvaluationBatch).where(
                GameEvaluationBatch.evaluation_id == evaluation_id,
                GameEvaluationBatch.status == BatchStatus.FAILED,
            )
        ).scalars().all()
        if failed_batches:
            evaluation.status = EvaluationStatus.FAILED
            evaluation.error = "; ".join(
                f"{b.agent}[{b.batch_index}]: {b.error}" for b in failed_batches
            )
            evaluation.completed_at = _now()
            db.commit()
            return

        street_findings = _collect_street_findings(db, evaluation_id)
        game, hands = _load_game_with_hands(db, evaluation.game_id)
        hero_gp_id = _hero_gp_id(game)
        street_findings.setdefault("preflop", []).extend(
            detect_rfi_limp_findings(game, hands, hero_gp_id)
        )
        threshold_meta = evaluation.stats_snapshot.get("threshold_profile") or {}
        threshold_profile = get_threshold_profile(threshold_meta.get("key"))
        leak_tags = merge_findings(
            street_findings,
            evaluation.stats_snapshot["game_level"],
            threshold_profile.key,
        )
        evaluation.leak_tags = leak_tags
        evaluation.current_stage = "synthesis"
        db.commit()

        user = db.get(User, evaluation.user_id)

        # Read BEFORE this evaluation folds itself in, so its own result
        # can't contaminate its own report (decision 4).
        profile_scope = profile_scope_for_game(game)
        player_profile = build_profile_context(db, evaluation.user_id, profile_scope)
        profile_status_by_tag = compute_profile_status(player_profile, leak_tags)

        result = await run_synthesis(
            stats_snapshot=evaluation.stats_snapshot["game_level"],
            session_dynamics=evaluation.stats_snapshot["session_dynamics"],
            leak_tags=leak_tags,
            db=db,
            game_id=str(evaluation.game_id),
            user=user,
            player_profile=player_profile,
            profile_status_by_tag=profile_status_by_tag,
            sample_status=evaluation.stats_snapshot["sample_status"],
        )

        already_folded = evaluation.folded_at is not None

        evaluation.report = {
            **result["report"],
            "report_kind": "current_game_observation",
            "threshold_profile": {
                "key": threshold_profile.key,
                "version": threshold_profile.version,
            },
            "preflop_evidence": {
                key: value
                for key, value in (
                    (evaluation.stats_snapshot.get("preflop_strategy_api") or {}).items()
                )
                if key != "evidence_by_decision"
            },
        }
        preflop_meta = evaluation.stats_snapshot.get("preflop_strategy_api") or {}
        evaluation.model_versions = {
            "street_agent": config.MODEL,
            "synthesis": config.MODEL,
            "stat_threshold_profile": threshold_profile.key,
            "stat_threshold_version": threshold_profile.version,
            "preflop_strategy_api": (
                preflop_meta.get("version")
                if int(preflop_meta.get("resolved") or 0) > 0 else None
            ),
        }
        evaluation.status = EvaluationStatus.COMPLETED
        evaluation.progress_current = evaluation.progress_total
        evaluation.completed_at = _now()
        db.commit()

        # Guard against double-folding: a crash-resume can re-run synthesis
        # (and land here again) for an evaluation this exact row already
        # folded once — incrementally folding it a second time would double-
        # count its occurrences, unlike rebuild_profile which only ever sees
        # one row per game. If a fold is ever actually missed (a crash
        # between the two commits above), a rebuild recovers it, since
        # rebuild_profile doesn't depend on folded_at at all.
        if not already_folded:
            await fold_and_persist(db, evaluation)
            evaluation.folded_at = _now()
            db.commit()
    except Exception as exc:  # noqa: BLE001
        evaluation = db.get(GameEvaluation, evaluation_id)
        evaluation.status = EvaluationStatus.FAILED
        evaluation.error = str(exc)
        evaluation.completed_at = _now()
        db.commit()
    finally:
        db.close()


def find_stuck_evaluations(db) -> list[str]:
    """Evaluation ids whose status is RUNNING — candidates to re-enqueue on worker startup."""
    rows = db.execute(
        select(GameEvaluation.id).where(GameEvaluation.status == EvaluationStatus.RUNNING)
    ).scalars().all()
    return [str(r) for r in rows]
