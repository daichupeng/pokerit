"""WebSocket play loop: streams engine events and receives the hero's actions."""

from __future__ import annotations

import asyncio
import functools
import logging
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from poker_engine import stats as stats_engine
from poker_engine.db.base import SessionLocal
from poker_engine.db.models import User
from poker_trainer.auth.config import APP_BASE_URL
from poker_trainer.auth.deps import websocket_user
from poker_trainer.game.manager import manager

router = APIRouter()
log = logging.getLogger(__name__)

# Delay between streamed events so bot actions animate sequentially in the UI.
EVENT_DELAY_S = 0.45
SHOWDOWN_REVEAL_DELAY_S = 1.5


def _ended_a_hand(events: list[dict]) -> bool:
    """True if a streamed batch contained a finished hand (a round_finish)."""
    return any(e.get("type") == "round_finish" for e in events)


def _save_soft(session) -> dict | None:
    """Incrementally persist the game so far, swallowing/logging any error.

    Per design, a failed mid-game save must never interrupt play: the next
    completed hand's save re-writes everything still missing (the recorder
    dedups by round, so nothing is double-written).

    Returns the hero's freshly recomputed per-game stats (display shape) on
    success, so the caller can push a ``stats_update`` event, or ``None`` if
    the save failed or there's no hero seat to compute stats for.
    """
    try:
        with SessionLocal() as db:
            game = session.persist_incremental(db)
            session.save_failed = False
            hero = next(
                (gp for gp in game.players if not gp.is_bot and gp.user_id is not None),
                None,
            )
            if hero is None:
                return None
            counts = stats_engine.compute_game_stats(db, game.id, hero.id)
            return stats_engine.to_display(counts)
    except Exception:
        session.save_failed = True
        log.exception("incremental save failed for game %s", getattr(session, "game_id", "?"))
        return None


@router.websocket("/ws/games/{game_id}")
async def play(websocket: WebSocket, game_id: str, user: User | None = Depends(websocket_user)) -> None:
    origin = websocket.headers.get("origin")
    expected = urlsplit(APP_BASE_URL)
    if origin is not None and origin.rstrip("/") != f"{expected.scheme}://{expected.netloc}":
        await websocket.close(code=1008)
        return
    session = manager.get_owned(game_id, user.id) if user is not None else None
    if session is None:
        await websocket.close(code=1008)
        return
    await websocket.accept()

    lock = manager.lock(game_id)

    try:
        # On (re)connect: send current state, then either the pending hero ask or,
        # if the game hasn't been advanced yet, start it.
        async with lock:
            first_connect = session._last_view is None and not session.finished
            if first_connect:
                gen = session.start_gen()
                # Consume the first batch in a thread: this is where the deck is
                # shuffled, cards dealt, and _last_view populated.
                first_batch = await asyncio.to_thread(lambda: next(gen, None))
                await websocket.send_json({
                    "type": "init",
                    "config": session.table_config(),
                    "view": session.current_view(),
                    "pending_ask": session.pending_ask(),
                })
                if first_batch:
                    for event in first_batch:
                        await websocket.send_json({"type": "event", "event": event})
                    await asyncio.sleep(0.8)  # let the dealt-cards view settle
                hand_ended = await _stream_gen(websocket, gen)
            else:
                await websocket.send_json({
                    "type": "init",
                    "config": session.table_config(),
                    "view": session.current_view(),
                    "pending_ask": session.pending_ask(),
                })
                hand_ended = False
            if hand_ended:
                await _save_and_notify(websocket, session)
            if session.finished:
                if await _finish(websocket, session, game_id):
                    return

        while True:
            msg = await websocket.receive_json()
            message_type = msg.get("type")
            if message_type == "retry_save":
                async with lock:
                    if session.finished:
                        if await _finish(websocket, session, game_id):
                            break
                    else:
                        await _save_and_notify(websocket, session)
                continue
            if message_type == "end_game":
                async with lock:
                    if session.finished:
                        break
                    final_players = session.finish_early()
                    await websocket.send_json({
                        "type": "event",
                        "event": {
                            "type": "game_finish",
                            "players": final_players,
                            "reason": "ended_by_player",
                        },
                    })
                    saved = await _finish(websocket, session, game_id)
                if saved:
                    break
                continue
            if message_type != "action":
                continue
            action = msg.get("action", "call")
            amount = int(msg.get("amount", 0) or 0)

            async with lock:
                if session.finished:
                    break
                gen = await asyncio.to_thread(
                    functools.partial(session.apply_hero_action_gen, action, amount)
                )
                hand_ended = await _stream_gen(websocket, gen)
                if hand_ended:
                    await _save_and_notify(websocket, session)
                if session.finished:
                    if await _finish(websocket, session, game_id):
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
        elif event["type"] == "showdown_reveal":
            # Let all-in cards settle face-up before running the remaining board.
            await asyncio.sleep(SHOWDOWN_REVEAL_DELAY_S)
        elif event["type"] == "new_street":
            # Give the client time to slide the street's bets into the pot
            # before the next card/action arrives.
            await asyncio.sleep(0.8)
        elif event["type"] == "to_act":
            await asyncio.sleep(EVENT_DELAY_S)


_SENTINEL = object()


async def _stream_gen(websocket: WebSocket, gen) -> bool:
    """Drive an _advance_gen() generator, streaming each batch with per-step pacing.

    Each generator step runs in a thread (bot compute is CPU-bound). After a
    [to_act] batch the WS layer sleeps before advancing, so the frontend has
    time to highlight the seat before the bot's action arrives.
    Returns True if a round_finish was sent (caller should save).
    """
    hand_ended = False
    while True:
        batch = await asyncio.to_thread(lambda: next(gen, _SENTINEL))
        if batch is _SENTINEL:
            break
        for event in batch:
            await websocket.send_json({"type": "event", "event": event})
        types = {e["type"] for e in batch}
        if "round_finish" in types:
            hand_ended = True
            finish_ev = next(e for e in batch if e["type"] == "round_finish")
            n_pots = max(1, len([p for p in finish_ev.get("pot_winners", [])
                                 if p.get("winners") and p.get("amount", 0) > 0]))
            await asyncio.sleep(n_pots * 1.35 + 2.0)
        elif "showdown_reveal" in types:
            await asyncio.sleep(SHOWDOWN_REVEAL_DELAY_S)
        elif "new_street" in types:
            await asyncio.sleep(0.8)
        elif "to_act" in types:
            # Highlight the seat — sleep before the next step computes the bot action.
            await asyncio.sleep(EVENT_DELAY_S)
    return hand_ended


async def _save_and_notify(websocket: WebSocket, session) -> None:
    hero_stats = _save_soft(session)
    if getattr(session, "save_failed", False):
        await websocket.send_json({
            "type": "persist_error", "finished": session.finished,
            "message": "Saving failed. Completed hands are buffered; retry saving before closing the game.",
        })
    else:
        await websocket.send_json({"type": "save_status", "saved": True})
        if hero_stats is not None:
            await websocket.send_json({"type": "stats_update", "stats": hero_stats})


async def _finish(websocket: WebSocket, session, game_id: str) -> bool:
    """Persist the finished game and tell the client, then clean up."""
    game_id_db = None
    try:
        with SessionLocal() as db:
            game = session.persist(db)
            if game is None:
                raise RuntimeError("No persisted game returned")
            game_id_db = str(game.id)
    except Exception:  # Keep the finished session available for retry/reconnect.
        log.exception("final save failed for game %s", game_id)
        await websocket.send_json({
            "type": "persist_error", "finished": True,
            "message": "Game ended, but saving failed. Retry saving before closing the game.",
        })
        return False
    await websocket.send_json({"type": "saved", "db_game_id": game_id_db})
    manager.remove(game_id)
    return True
