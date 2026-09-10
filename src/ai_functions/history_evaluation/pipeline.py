"""Background pipeline for deterministic rolling history evaluations."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ai_functions.game_review import config
from ai_functions.game_review.leak_taxonomy import get_threshold_profile
from ai_functions.game_review.stat_leaks import detect_stat_leaks
from ai_functions.history_evaluation.analytics import compare_latest_to_baseline, history_sample_status
from ai_functions.history_evaluation.synthesis import synthesize
from poker_engine.db.base import SessionLocal
from poker_engine.db.models import EvaluationStatus, Game, Hand, HistoryEvaluation
from poker_engine.scenarios import profile_scope_for_game
from poker_engine.stats import RawStatCounts, compute_hand_stats, to_display


def _now():
    return datetime.now(timezone.utc)


def _game_time(game: Game) -> datetime:
    return game.ended_at or game.started_at or game.created_at or datetime.min.replace(tzinfo=timezone.utc)


def _hand_key(hand: Hand, games: dict) -> tuple:
    game = games[hand.game_id]
    fallback = datetime.min.replace(tzinfo=timezone.utc)
    return (
        _game_time(game),
        hand.created_at or fallback,
        hand.round_count,
        str(hand.id),
    )


def _hero_id(game: Game, user_id):
    hero = next((p for p in game.players if not p.is_bot and p.user_id == user_id), None)
    return hero.id if hero else None


def _counts(pairs: list[tuple[Hand, object]]) -> RawStatCounts:
    total = RawStatCounts()
    for hand, hero_id in pairs:
        total = total + compute_hand_stats(hand, hero_id)
    return total


def _load_scope_pairs(db, user_id, scope_key: str) -> tuple[dict, list[tuple[Hand, object]]]:
    all_games = db.execute(
        select(Game)
        .where(Game.hero_user_id == user_id)
        .options(selectinload(Game.players))
    ).scalars().all()
    games = {game.id: game for game in all_games if profile_scope_for_game(game) == scope_key}
    if not games:
        return {}, []
    hands = db.execute(
        select(Hand)
        .where(Hand.game_id.in_(games))
        .options(selectinload(Hand.actions), selectinload(Hand.players))
    ).scalars().all()
    hero_ids = {game_id: _hero_id(game, user_id) for game_id, game in games.items()}
    pairs = [(hand, hero_ids[hand.game_id]) for hand in hands if hero_ids.get(hand.game_id) is not None]
    pairs.sort(key=lambda pair: _hand_key(pair[0], games))
    return games, pairs


def build_history_snapshot(db, evaluation: HistoryEvaluation) -> dict:
    """Build all numeric output directly from saved hands/actions, with no LLM."""
    profile = get_threshold_profile(evaluation.scope_key)
    games, all_pairs = _load_scope_pairs(db, evaluation.user_id, evaluation.scope_key)

    games_with_hands = {hand.game_id for hand, _ in all_pairs}
    if evaluation.latest_game_id is not None:
        if evaluation.latest_game_id not in games_with_hands:
            raise ValueError("latest_game_id must belong to this user and scope and contain a saved hand")
        latest_game_id = evaluation.latest_game_id
    elif all_pairs:
        latest_game_id = max(
            games_with_hands,
            key=lambda game_id: (_game_time(games[game_id]), str(game_id)),
        )
    else:
        latest_game_id = None

    if latest_game_id is not None:
        latest_pairs = [pair for pair in all_pairs if pair[0].game_id == latest_game_id]
        anchor_time = _game_time(games[latest_game_id])
        # Game timestamps are transaction-level on Postgres, so two games
        # inserted in one transaction can tie. Treat tied non-selected games
        # as prior and force the selected latest game's hands to the end;
        # otherwise round_count ordering can silently discard valid history.
        prior_eligible = [
            pair for pair in all_pairs
            if pair[0].game_id != latest_game_id
            and _game_time(games[pair[0].game_id]) <= anchor_time
        ]
        eligible = [*prior_eligible, *latest_pairs]
    else:
        latest_pairs = []
        eligible = []

    rolling_pairs = eligible[-evaluation.window_hands:]
    prior_pairs = [pair for pair in eligible if pair[0].game_id != latest_game_id][-evaluation.window_hands:]

    rolling = to_display(_counts(rolling_pairs))
    latest = to_display(_counts(latest_pairs))
    baseline = to_display(_counts(prior_pairs))
    readiness = history_sample_status(rolling, profile)
    leaks = detect_stat_leaks(rolling, profile.key)
    trends = compare_latest_to_baseline(latest, baseline, profile)
    cutoff = rolling_pairs[0][0].created_at if rolling_pairs else None

    return {
        "latest_game_id": latest_game_id,
        "cutoff_at": cutoff,
        "games_included": len({hand.game_id for hand, _ in rolling_pairs}),
        "stats_snapshot": {
            "rolling_500": rolling,
            "latest_game": latest,
            "prior_500_baseline": baseline,
            "window": {
                "definition": "most recent saved hands in the same profile scope, anchored at latest_game",
                "requested_hands": evaluation.window_hands,
                "hands_used": len(rolling_pairs),
                "latest_game_hands": len(latest_pairs),
                "prior_baseline_hands": len(prior_pairs),
            },
        },
        "sample_status": readiness,
        "trend_comparison": {"latest_game_vs_prior_500": trends},
        "deterministic_stat_leaks": leaks,
        "threshold_profile": profile,
    }


async def run_history_evaluation(ctx, evaluation_id: str) -> None:
    db = SessionLocal()
    try:
        evaluation = db.get(HistoryEvaluation, evaluation_id)
        if evaluation is None:
            return
        evaluation.status = EvaluationStatus.RUNNING
        db.commit()

        result = build_history_snapshot(db, evaluation)
        profile = result["threshold_profile"]
        evaluation.latest_game_id = result["latest_game_id"]
        evaluation.cutoff_at = result["cutoff_at"]
        evaluation.games_included = result["games_included"]
        evaluation.stats_snapshot = result["stats_snapshot"]
        evaluation.sample_status = result["sample_status"]
        evaluation.trend_comparison = result["trend_comparison"]
        evaluation.deterministic_stat_leaks = result["deterministic_stat_leaks"]
        db.commit()

        deterministic_payload = {
            "scope": evaluation.scope_key,
            "window": evaluation.stats_snapshot["window"],
            "rolling_500": evaluation.stats_snapshot["rolling_500"],
            "latest_game": evaluation.stats_snapshot["latest_game"],
            "prior_500_baseline": evaluation.stats_snapshot["prior_500_baseline"],
            "sample_status": evaluation.sample_status,
            "trend_comparison": evaluation.trend_comparison,
            "deterministic_stat_leaks": evaluation.deterministic_stat_leaks,
            "threshold_profile": {"key": profile.key, "version": profile.version},
        }
        synthesis_error = None
        try:
            narrative, usage = await synthesize(deterministic_payload)
        except Exception as exc:  # deterministic report must survive LLM failure
            synthesis_error = str(exc)
            narrative = {
                "summary": "Deterministic rolling statistics are available below; narrative synthesis was unavailable.",
                "sections": [],
            }
            usage = {}

        evaluation.report = {
            **narrative,
            "report_kind": "rolling_history",
            "scope": evaluation.scope_key,
            "history_window": evaluation.stats_snapshot["window"],
            "games_included": evaluation.games_included,
            "latest_game_id": str(evaluation.latest_game_id) if evaluation.latest_game_id else None,
            "threshold_profile": {"key": profile.key, "version": profile.version},
            "sample_status": evaluation.sample_status,
            "trend_comparison": evaluation.trend_comparison,
            "synthesis_error": synthesis_error,
        }
        evaluation.model_versions = {
            "synthesis": config.MODEL,
            "usage": usage,
            "stat_threshold_profile": profile.key,
            "stat_threshold_version": profile.version,
            "statistics": "deterministic_raw_hands_v2",
        }
        evaluation.status = EvaluationStatus.COMPLETED
        evaluation.completed_at = _now()
        db.commit()
    except Exception as exc:  # noqa: BLE001
        evaluation = db.get(HistoryEvaluation, evaluation_id)
        if evaluation is not None:
            evaluation.status = EvaluationStatus.FAILED
            evaluation.error = str(exc)
            evaluation.completed_at = _now()
            db.commit()
    finally:
        db.close()


def find_stuck_history_evaluations(db) -> list[str]:
    rows = db.execute(
        select(HistoryEvaluation.id).where(HistoryEvaluation.status == EvaluationStatus.RUNNING)
    ).scalars().all()
    return [str(row) for row in rows]
