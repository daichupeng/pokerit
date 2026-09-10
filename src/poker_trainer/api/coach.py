"""AI coach API — streaming chat endpoint.

POST /api/coach/chat
  Body: { "message": str, "conversation_id"?: uuid, "game_id"?: uuid }
  Returns: text/event-stream (SSE)

  Each SSE event carries a JSON payload:
    { "type": "chunk", "text": "..." }   — streamed text fragment
    { "type": "done", "conversation_id": "..." }  — stream finished

POST /api/coach/conversations
  Creates a new conversation and returns { "conversation_id": "..." }.

GET /api/coach/conversations/{conversation_id}
  Returns the full message history for the conversation.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_functions.coach_engine.engine import (
    build_scenario_context,
    chat,
    get_or_create_conversation,
)
from ai_functions.decision_snapshot import build_live_preflop_snapshot
from ai_functions.preflop_ranges import (
    PREFLOP_LOOKUP_LIMIT_PER_HAND,
    PokerAIQueryResult,
    apply_pokerai_evidence,
    query_preflop_strategy,
)
from poker_engine.db.models import Conversation, Game, Hand
from poker_trainer.auth.deps import get_db, require_user
from poker_engine.db.models import User
from poker_trainer.game.manager import manager
from shared_services.table_formatter import format_table
from shared_services.decision_facts import build_hand_facts

router = APIRouter(prefix="/api/coach", tags=["coach"])


class ChatRequest(BaseModel):
    message: str
    conversation_id: uuid.UUID | None = None
    game_id: uuid.UUID | None = None


class NewConversationRequest(BaseModel):
    game_id: uuid.UUID | None = None
    pinned_context: str | None = None  # always-present context block (hand, game summary, etc.)
    entry_point: str = "generic"
    hand_id: uuid.UUID | None = None


def _require_owned_context(db: Session, user: User, game_id=None, hand_id=None, conversation_id=None) -> None:
    """Authorize before creating a conversation or reading live/private context."""
    if conversation_id is not None:
        conv = db.get(Conversation, conversation_id)
        if conv is None or conv.user_id != user.id:
            raise HTTPException(404, "Conversation not found.")
    if game_id is not None:
        live = manager.get(str(game_id))
        if live is not None:
            if manager.get_owned(str(game_id), user.id) is None:
                raise HTTPException(404, "Game not found.")
        else:
            game = db.get(Game, game_id)
            if game is None or game.hero_user_id != user.id:
                raise HTTPException(404, "Game not found.")
    if hand_id is not None:
        hand = db.get(Hand, hand_id)
        if hand is None or hand.game.hero_user_id != user.id:
            raise HTTPException(404, "Hand not found.")
        if game_id is not None and str(hand.game_id) != str(game_id):
            raise HTTPException(404, "Hand not found.")


async def _cached_live_preflop_result(
    session, snapshot: dict,
) -> PokerAIQueryResult:
    """Resolve one live decision once, capped across distinct nodes per hand."""
    decision_id = str(snapshot.get("decision_id") or "")
    cached = session.preflop_strategy_cache.get(decision_id)
    if isinstance(cached, PokerAIQueryResult):
        return cached

    round_prefix = f"{snapshot.get('round_count')}:preflop:"
    attempted = sum(
        isinstance(result, PokerAIQueryResult) and result.attempted
        for key, result in session.preflop_strategy_cache.items()
        if str(key).startswith(round_prefix)
    )
    if attempted >= PREFLOP_LOOKUP_LIMIT_PER_HAND:
        result = PokerAIQueryResult(None, "per_hand_limit_reached")
    else:
        result = await query_preflop_strategy(snapshot)
    session.preflop_strategy_cache[decision_id] = result
    return result


def _build_live_equity_context(
    round_state: dict, hero_uuid: str,
) -> dict | None:
    """Bind only public board cards and Hero's cards for heads-up calculation."""
    live_players = [
        seat for seat in round_state.get("seats") or []
        if seat.get("state") in {"participating", "allin"}
    ]
    hero_hole = (round_state.get("hole_cards_by_uuid") or {}).get(hero_uuid) or []
    board = round_state.get("community_card") or []
    if (
        len(live_players) != 2
        or not any(seat.get("uuid") == hero_uuid for seat in live_players)
        or len(hero_hole) != 2
        or len(board) not in (3, 4, 5)
    ):
        return None
    return {
        "hole": list(hero_hole),
        "board": list(board),
        "active_players": 2,
    }


@router.post("/conversations")
def create_conversation(
    body: NewConversationRequest,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    _require_owned_context(db, user, body.game_id, body.hand_id)
    conv = get_or_create_conversation(
        db,
        user_id=user.id,
        game_id=body.game_id,
        pinned_context=body.pinned_context,
        entry_point=body.entry_point,
        hand_id=body.hand_id,
    )
    return {"conversation_id": str(conv.id)}


@router.get("/conversations/by-hand/{hand_id}")
def get_conversation_by_hand(
    hand_id: uuid.UUID,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return the most recent hand_history conversation for a specific hand, or 404."""
    conv = (
        db.execute(
            select(Conversation)
            .where(
                Conversation.user_id == user.id,
                Conversation.hand_id == hand_id,
                Conversation.entry_point == "hand_history",
            )
            .order_by(Conversation.created_at.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    if conv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No conversation found for this hand")
    return {
        "conversation_id": str(conv.id),
        "game_id": str(conv.game_id) if conv.game_id else None,
        "hand_id": str(conv.hand_id),
        "messages": [
            {
                "role": m.role,
                "content": m.content,
                "seq": m.seq,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in conv.messages
        ],
    }


@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: uuid.UUID,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return {
        "conversation_id": str(conv.id),
        "game_id": str(conv.game_id) if conv.game_id else None,
        "messages": [
            {
                "role": m.role,
                "content": m.content,
                "seq": m.seq,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in conv.messages
        ],
    }


@router.post("/chat")
async def coach_chat(
    body: ChatRequest,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    if not body.message.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Message cannot be empty")

    _require_owned_context(db, user, body.game_id, conversation_id=body.conversation_id)

    conv = get_or_create_conversation(
        db,
        user_id=user.id,
        game_id=body.game_id,
        conversation_id=body.conversation_id,
    )

    live_context: str | None = None
    scenario_context: str | None = None
    decision_facts: dict | None = None
    evidence_sources: list[dict] | None = None
    equity_context: dict | None = None
    if body.game_id is not None:
        session = manager.get_owned(str(body.game_id), user.id)
        if session is not None:
            scenario_context = build_scenario_context(session.config)
            round_state = session.current_round_state(for_coach=True)
            if round_state is not None:
                pending_ask = session.pending_ask()
                valid_actions = (
                    pending_ask.get("valid_actions") if pending_ask is not None else None
                )
                table_text = format_table(
                    round_state,
                    session.hero_uuid,
                    valid_actions=valid_actions,
                )
                decision_facts = build_hand_facts(
                    (round_state.get("hole_cards_by_uuid") or {}).get(session.hero_uuid),
                    round_state.get("community_card") or [],
                )
                equity_context = _build_live_equity_context(
                    round_state, session.hero_uuid,
                )
                preflop_snapshot = build_live_preflop_snapshot(
                    round_state, session.hero_uuid,
                ) if pending_ask is not None else None
                if preflop_snapshot is not None:
                    lookup = await _cached_live_preflop_result(
                        session, preflop_snapshot,
                    )
                    if lookup.evidence is not None:
                        apply_pokerai_evidence(preflop_snapshot, lookup.evidence)
                    evidence_sources = preflop_snapshot.get("evidence_sources") or []
                    strategy_sources = [
                        source for source in evidence_sources
                        if source.get("type") in {
                            "preflop_strategy_api", "range_knowledge_base",
                        }
                    ]
                    if strategy_sources:
                        table_text += (
                            "\n\nPreflop Strategy Evidence "
                            "(code-resolved; use only within its stated assumptions):\n"
                            + json.dumps(strategy_sources, ensure_ascii=False, indent=2)
                        )
                    elif lookup.failure:
                        table_text += (
                            "\n\nPreflop Strategy Lookup Status "
                            "(code-resolved; no strategy evidence is available):\n"
                            + json.dumps({
                                "status": "unavailable",
                                "reason": lookup.failure,
                                "per_hand_lookup_limit": PREFLOP_LOOKUP_LIMIT_PER_HAND,
                            }, ensure_ascii=False, indent=2)
                        )
                live_context = (
                    "Decision Snapshot (authoritative current hand; no future actions or run-out):\n"
                    "Use this hand for questions such as 'this hand', 'now', or 'what should I do'. "
                    "Do not import cards, board, actions, or pot sizes from earlier hands.\n\n"
                    f"{table_text}"
                )
        else:
            game = db.get(Game, body.game_id)
            if game is not None and game.hero_user_id == user.id:
                scenario_context = build_scenario_context(game)
    elif conv.game_id is not None:
        game = db.get(Game, conv.game_id)
        if game is not None and game.hero_user_id == user.id:
            scenario_context = build_scenario_context(game)

    async def event_stream() -> AsyncIterator[str]:
        try:
            if conv.entry_point == "hand_history":
                coach_scenario = "hand_review"
            elif body.game_id:
                coach_scenario = "in_game"
            else:
                coach_scenario = "generic"
            generator = await chat(
                db,
                conv.id,
                body.message,
                live_context,
                conv_pair=3,
                coach_scenario=coach_scenario,
                scenario_context=scenario_context,
                decision_facts=decision_facts,
                evidence_sources=evidence_sources,
                equity_context=equity_context,
            )
            async for chunk in generator:
                payload = json.dumps({"type": "chunk", "text": chunk})
                yield f"data: {payload}\n\n"
            done = json.dumps({"type": "done", "conversation_id": str(conv.id)})
            yield f"data: {done}\n\n"
        except Exception as exc:
            err = json.dumps({"type": "error", "message": str(exc)})
            yield f"data: {err}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
