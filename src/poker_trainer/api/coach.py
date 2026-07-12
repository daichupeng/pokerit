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
    chat,
    get_or_create_conversation,
)
from poker_engine.db.models import Conversation
from poker_trainer.auth.deps import get_db, require_user
from poker_engine.db.models import User
from poker_trainer.game.manager import manager
from shared_services.table_formatter import format_table

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


@router.post("/conversations")
def create_conversation(
    body: NewConversationRequest,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
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

    conv = get_or_create_conversation(
        db,
        user_id=user.id,
        game_id=body.game_id,
        conversation_id=body.conversation_id,
    )

    live_context: str | None = None
    if body.game_id is not None:
        session = manager.get(str(body.game_id))
        if session is not None:
            round_state = session.current_round_state()
            if round_state is not None:
                table_text = format_table(round_state, session.hero_uuid)
                live_context = f"Current table state:\n\n{table_text}"

    async def event_stream() -> AsyncIterator[str]:
        try:
            if conv.entry_point == "hand_history":
                coach_scenario = "hand_review"
            elif body.game_id:
                coach_scenario = "in_game"
            else:
                coach_scenario = "generic"
            generator = await chat(db, conv.id, body.message, live_context, conv_pair=3, coach_scenario=coach_scenario)
            async for chunk in generator:
                payload = json.dumps({"type": "chunk", "text": chunk})
                yield f"data: {payload}\n\n"
            done = json.dumps({"type": "done", "conversation_id": str(conv.id)})
            yield f"data: {done}\n\n"
        except Exception as exc:
            err = json.dumps({"type": "error", "message": str(exc)})
            yield f"data: {err}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
