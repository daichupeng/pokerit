"""WebSocket play loop: streams engine events and receives the hero's actions."""

from __future__ import annotations

import asyncio
import functools
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from poker_engine.db.base import SessionLocal
from poker_trainer.game.manager import manager

router = APIRouter()
log = logging.getLogger(__name__)

# Delay between streamed events so bot actions animate sequentially in the UI.
EVENT_DELAY_S = 0.45


def _ended_a_hand(events: list[dict]) -> bool:
    """True if a streamed batch contained a finished hand (a round_finish)."""
    return any(e.get("type") == "round_finish" for e in events)


def _save_soft(session) -> None:
    """Incrementally persist the game so far, swallowing/logging any error.

    Per design, a failed mid-game save must never interrupt play: the next
    completed hand's save re-writes everything still missing (the recorder
    dedups by round, so nothing is double-written).
    """
    try:
        with SessionLocal() as db:
            session.persist_incremental(db)
    except Exception:
        log.exception("incremental save failed for game %s", getattr(session, "game_id", "?"))


@router.websocket("/ws/games/{game_id}")
async def play(websocket: WebSocket, game_id: str) -> None:
    await websocket.accept()
    session = manager.get(game_id)
    if session is None:
        await websocket.send_json({"type": "error", "message": "Game not found."})
        await websocket.close()
        return

    lock = manager.lock(game_id)

    try:
        # On (re)connect: send current state, then either the pending hero ask or,
        # if the game hasn't been advanced yet, start it.
        async with lock:
            first_connect = session._last_view is None and not session.finished
            if first_connect:
                events = await asyncio.to_thread(session.start)
            else:
                events = []
            await websocket.send_json({
                "type": "init",
                "config": session.table_config(),
                "view": session.current_view(),
                "pending_ask": session.pending_ask(),
            })
            await _stream(websocket, events)
            if _ended_a_hand(events):
                _save_soft(session)
            if session.finished:
                await _finish(websocket, session, game_id)
                return

        while True:
            msg = await websocket.receive_json()
            if msg.get("type") != "action":
                continue
            action = msg.get("action", "call")
            amount = int(msg.get("amount", 0) or 0)

            async with lock:
                if session.finished:
                    break
                events = await asyncio.to_thread(
                    functools.partial(session.apply_hero_action, action, amount)
                )
                await _stream(websocket, events)
                # Persist after any batch that finished one or more hands.
                if _ended_a_hand(events):
                    _save_soft(session)
                if session.finished:
                    await _finish(websocket, session, game_id)
                    break
    except WebSocketDisconnect:
        # Leave the session in memory so the client can reconnect and resume.
        # Completed hands are already saved by the per-hand hook above.
        return


async def _stream(websocket: WebSocket, events: list[dict]) -> None:
    """Send events to the browser, pacing non-terminal ones for animation."""
    for event in events:
        await websocket.send_json({"type": "event", "event": event})
        if event["type"] == "round_finish":
            # Hold so the per-pot award animation can play out in series before
            # the next hand starts: ~1.35s per pot (travel + gap) + 2s winner
            # blink. Multiple pots (side pots) extend the hold.
            n_pots = max(1, len([p for p in event.get("pot_winners", [])
                                 if p.get("winners") and p.get("amount", 0) > 0]))
            await asyncio.sleep(n_pots * 1.35 + 2.0)
        elif event["type"] == "new_street":
            # Give the client time to slide the street's bets into the pot
            # before the next card/action arrives.
            await asyncio.sleep(0.8)
        elif event["type"] == "to_act":
            await asyncio.sleep(EVENT_DELAY_S)


async def _finish(websocket: WebSocket, session, game_id: str) -> None:
    """Persist the finished game and tell the client, then clean up."""
    game_id_db = None
    try:
        with SessionLocal() as db:
            game = session.persist(db)
            game_id_db = str(game.id) if game is not None else None
    except Exception as exc:  # persistence must not crash the socket
        await websocket.send_json({"type": "persist_error", "message": str(exc)})
    await websocket.send_json({"type": "saved", "db_game_id": game_id_db})
    manager.remove(game_id)
