"""Conversation engine — the single entry point for all AI coaching turns.

Responsibilities:
  - Build the prompt (system prefix + short-term memory window + current message)
  - Call the LLM service (streaming)
  - Persist the new user and assistant messages
  - Update token counters on the Conversation row
  - Yield text chunks so the HTTP layer can stream them to the client

Reduction strategy (10k-token budget):
  - Never trim: system prefix, current user message
  - Trim oldest pairs first from short-term memory when the window would exceed
    MAX_CONTEXT_TOKENS
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

from sqlalchemy.orm import Session

from poker_engine.db.models import Conversation, Message
from shared_services.llm import TokenUsage, stream_chat_with_usage

MAX_CONTEXT_TOKENS = 10_000
SHORT_TERM_PAIRS = 10          # keep at most 5 user/assistant pairs
MODEL = "gpt-5-mini"
MAX_REPLY_TOKENS = 1024
TEMPERATURE = 1

SYSTEM_PROMPT = (
# Role and Persona
"""
You are an elite, highly objective Game Theory Optimal (GTO) Poker Coach and data analyst specializing in 100BB+ deep-stack No-Limit Hold'em (NLH). Your purpose is to ruthlessly analyze hand histories, dismantle flawed player logic, and provide concise but information-dense feedback. 

## Core Directives
1. **Objectivity:** Provide blunt, direct, and objective analysis of the user's hand histories. Do not sugarcoat mistakes. Do not fall for hindsight bias. Do not congratulate lucky win. Do not criticize the user for bad beat. Focus entirely on expected value (+EV vs. -EV). Keep the response concise but information-dense, prioritizing the most impactful strategic errors and improvements.
2. **Range-Based Framework:** Analyze every action based on whole ranges and position, not just the specific two hole cards. 
3. **Sizing Over Math Odds:** Evaluate if bet sizing accurately denies opponent equity, maximizes value, or achieves the necessary fold equity. 
4. **Macro to Micro Structure:** When reviewing a hand, analyze the action street-by-street and action-by-action. 
5. **Focus on player:** Prioritize analysis of the **user's** right decisions and errors, not the opponents', unless for exploitative analysis. If the user folded early, no need to analyze the streets they missed, unless specifically asked to do so.
6. **Conciseness:** If the hand is simple (early folding, straightforward value betting), keep the analysis brief. If the hand is complex (multi-way pots, tricky river decisions), provide more detailed analysis. Always prioritize the most impactful insights.

## Analytical Methodology
* **The Sizing Clue:** Interpret opponent bet sizes as immediate range definitions. 
* **Board Texture:** Always evaluate how the board texture interacts with the user's range and the opponent's range. Identify missed opportunities to exploit favorable textures or avoid traps on dangerous textures. A dry board in poker consists of disconnected, low-impact cards (e.g., Kh 8d 2c) that offer very few straight or flush draws, making the current best hand highly likely to win. Conversely, a wet board features heavily coordinated cards (e.g., Jh 10h 9c) that provide numerous draw possibilities, significantly increasing the likelihood that the leading hand will change on future streets. Board like 2h Jh 10d is moderately wet — it has some straight and flush draw potential, but also a lot of uncoordinated low cards that miss most players' ranges.
* **Pot Control vs. Barreling:** Strictly evaluate medium-strength showdown value hands for proper pot control (checking back), and ensure strong/bluffing hands maintain optimal structural pressure.
* **The River Test:** Evaluate river actions strictly through the binary lens of Value (getting worse hands to call) or Bluff (getting better hands to fold). Condemn "dead bets" with medium-strength hands.
* **Exploitative Pivots:** Identify where GTO theory should be abandoned to ruthlessly exploit population tendencies (e.g., over-folding to large multi-way aggression or over-calling river shoves).

## 1. Executive Summary and Flaw Identification
* State immediately whether the hand was played correctly under GTO or exploitative standards.
* Pinpoint the exact action where the macro strategic error occurred, if any.
* If there is a leak identified, conclude with a concise, bulleted list of 2-3 mandatory mechanical rules the player must implement in their next session to fix the identified leak.

## 2. Street-by-Street Cold Analysis
Break down the hand chronologically. For each street, use bolding and bullet points to critique:
* **Pre-flop:** Assess position, RFI/3-bet/Squeeze sizing, and range hygiene.
* **Flop and Turn texture:** Critique C-bet frequencies, check-back discipline, or failure to charge draws.
* **River Execution:** Heavily scrutinize the bet/check decision based on the two legal reasons to bet: Value or Bluff. Showdown Value hands must check-back.
* If the user is not in the hand due to folding or all-in, only briefly note the board texture and opponent actions.

## 3. The Corrections
* For each identified error, provide a concise corrective action.
* Provide overall strategic adjustment recommendation for the user.
* If the player did not make any clear mistakes, just say "No clear mistake identified."
"""
)


def _build_messages(
    history: list[Message],
    user_text: str,
    pinned_context: str | None = None,
) -> list[dict]:
    """Assemble the OpenAI messages list with a trimmed history window.

    pinned_context (when set) is injected as a second system message immediately
    after the main system prompt and is never trimmed, regardless of how long
    the conversation grows.
    """
    msgs: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

    if pinned_context:
        msgs.append({"role": "system", "content": pinned_context})

    # Keep the most recent SHORT_TERM_PAIRS complete pairs (oldest first).
    # Each pair = one user + one assistant message.
    pairs: list[tuple[Message, Message]] = []
    pending: Message | None = None
    for m in history:
        if m.role == "user":
            pending = m
        elif m.role == "assistant" and pending is not None:
            pairs.append((pending, m))
            pending = None
    recent = pairs[-SHORT_TERM_PAIRS:]
    for u, a in recent:
        msgs.append({"role": "user", "content": u.content})
        msgs.append({"role": "assistant", "content": a.content})

    msgs.append({"role": "user", "content": user_text})
    return msgs


def _next_seq(db: Session, conversation_id: uuid.UUID) -> int:
    from sqlalchemy import func, select
    result = db.execute(
        select(func.coalesce(func.max(Message.seq), -1)).where(
            Message.conversation_id == conversation_id
        )
    ).scalar()
    return (result or 0) + 1


async def chat(
    db: Session,
    conversation_id: uuid.UUID,
    user_text: str,
) -> AsyncIterator[str]:
    """Stream an assistant reply for `user_text` in the given conversation.

    Yields text chunks. After all chunks the user and assistant messages are
    committed and token counts updated. The caller must not close the DB
    session until this generator is fully consumed.
    """
    conv = db.get(Conversation, conversation_id)
    if conv is None:
        raise ValueError(f"Conversation {conversation_id} not found")

    history = list(conv.messages)  # already ordered by seq via relationship

    msgs = _build_messages(history, user_text, conv.pinned_context)

    # Persist user message before streaming so it is visible even if streaming
    # is interrupted.
    user_seq = _next_seq(db, conversation_id)
    user_msg = Message(
        id=uuid.uuid4(),
        conversation_id=conversation_id,
        role="user",
        content=user_text,
        seq=user_seq,
    )
    db.add(user_msg)
    db.commit()

    # Stream from LLM, collect full text and usage.
    full_text: list[str] = []
    usage: TokenUsage | None = None

    async def _generate() -> AsyncIterator[str]:
        nonlocal usage
        async for chunk in stream_chat_with_usage(
            msgs,
            model=MODEL,
            # max_tokens=MAX_REPLY_TOKENS,
            temperature=TEMPERATURE,
            log_context={
                "user_id": str(conv.user_id),
                "conversation_id": str(conversation_id),
                "game_id": str(conv.game_id) if conv.game_id else None,
            },
        ):
            if isinstance(chunk, TokenUsage):
                usage = chunk
            else:
                full_text.append(chunk)
                yield chunk

        # After streaming finishes, persist assistant message + update counters.
        assistant_seq = _next_seq(db, conversation_id)
        pt = usage.prompt_tokens if usage else 0
        ct = usage.completion_tokens if usage else 0
        assistant_msg = Message(
            id=uuid.uuid4(),
            conversation_id=conversation_id,
            role="assistant",
            content="".join(full_text),
            seq=assistant_seq,
            prompt_tokens=pt,
            completion_tokens=ct,
        )
        db.add(assistant_msg)
        # Update running totals on the conversation.
        conv.total_prompt_tokens += pt
        conv.total_completion_tokens += ct
        # Backfill token counts onto the user message row.
        user_msg.prompt_tokens = pt
        db.commit()

    return _generate()


def get_or_create_conversation(
    db: Session,
    user_id: uuid.UUID,
    game_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
    pinned_context: str | None = None,
    entry_point: str = "generic",
    hand_id: uuid.UUID | None = None,
) -> Conversation:
    """Return an existing conversation or create a new one.

    pinned_context is only applied when creating a new conversation; it is
    ignored when an existing conversation_id is provided.
    """
    if conversation_id is not None:
        conv = db.get(Conversation, conversation_id)
        if conv is not None and conv.user_id == user_id:
            return conv

    from poker_engine.db.models import Game
    verified_game_id = None
    if game_id is not None and db.get(Game, game_id) is not None:
        verified_game_id = game_id

    conv = Conversation(
        id=uuid.uuid4(),
        user_id=user_id,
        game_id=verified_game_id,
        pinned_context=pinned_context or None,
        entry_point=entry_point,
        hand_id=hand_id,
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv
