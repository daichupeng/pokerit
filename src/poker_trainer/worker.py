"""arq worker entry point for the game-evaluation background pipeline.

Run with: uv run arq poker_trainer.worker.WorkerSettings
"""

from __future__ import annotations

import logging
import os

from arq.connections import RedisSettings

from poker_engine.db.base import SessionLocal
from shared_services.logging_config import configure_logging

from ai_functions.game_review.pipeline import find_stuck_evaluations, run_evaluation

_log = logging.getLogger("prompts")

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379")


async def startup(ctx) -> None:
    configure_logging()

    # Resumability for an ungracefully-killed worker: any evaluation still
    # marked RUNNING has no active job behind it (arq's own job-level retries
    # only cover exceptions raised *during* a job, not a killed process), so
    # re-enqueue it. run_evaluation() itself skips already-completed batches.
    db = SessionLocal()
    try:
        stuck_ids = find_stuck_evaluations(db)
    finally:
        db.close()

    pool = ctx["redis"]
    for evaluation_id in stuck_ids:
        _log.info("game_review.worker.resuming_evaluation", extra={"evaluation_id": evaluation_id})
        await pool.enqueue_job("run_evaluation", evaluation_id)


async def shutdown(ctx) -> None:
    pass


class WorkerSettings:
    functions = [run_evaluation]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(REDIS_URL)
    max_tries = 2
    job_timeout = 1800  # 30 min ceiling for a full evaluation (up to 500 hands)
