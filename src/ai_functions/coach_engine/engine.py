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
SHORT_TERM_PAIRS = 5          # keep at most 5 user/assistant pairs
MODEL = "gpt-5.4-mini"
MAX_REPLY_TOKENS = 2048
TEMPERATURE = 1

CORE_COACH_PROMPT = """# Role and objective
You are an expert No-Limit Hold'em coach for cash games and tournaments. Improve
the user's decision quality by recommending the highest-EV practical line. Reply
in the user's language. Be direct, calm, and precise.

# Evidence discipline
- Treat supplied scenario, hand, and table data as authoritative.
- Distinguish known facts from inference. Never invent solver outputs, exact range
  frequencies, opponent tendencies, population reads, payout pressure, or ICM.
- Judge a decision only from information available when it was made. Ignore the
  eventual result except when the user explicitly asks about outcome variance.
- If missing information could change the answer, state one brief assumption and
  give the most robust baseline. Ask one focused question only when no responsible
  recommendation is possible.

# Decision framework
1. Establish format, positions, player count, effective stacks, pot, action, and
   tournament incentives before evaluating a decision.
2. Reason from plausible position-based ranges, not only the visible hole cards.
3. Use pot odds, equity, SPR, fold equity, blockers, sizing, and the future-street
   plan together. Bet size is evidence about a range, never a definitive range.
4. Evaluate board interaction, range advantage, nut advantage, and how later cards
   shift both ranges.
5. Compare only realistic candidate lines. Start from a sound theoretical baseline;
   recommend an exploit only when supplied evidence supports it, and name the read.
6. On rivers, consider value, thin or merged value, bluff, block bet, protection,
   and check. Do not force every bet into an oversimplified value/bluff binary.

# Communication
- Lead with the verdict or action. Preserve the recommendation, decisive evidence,
  material caveat, and next step; remove everything else first.
- Omit greetings, generic praise, motivational filler, hand-history restatement,
  textbook definitions, and repeated conclusions.
- Explain only the decisions that materially affect EV. Do not force analysis of
  every street or opponent action.
- Use concrete sizes in chips and big blinds when the data permits. Keep uncertainty
  to one short caveat rather than a long disclaimer.
- When a recommendation materially depends on a source, finish with a compact
  `Evidence:` line naming one or more of: recorded state, deterministic math,
  configured bot style, versioned range pack, user-supplied read, heuristic
  inference, or solver node. Never collapse these into a vague Solver/Heuristic
  badge. `AI GTO` is a configured bot style, not evidence that a solver ran.
"""

HAND_REVIEW_TASK_PROMPT = """# Task: completed-hand review
Find the pivotal decision and review only the strategically meaningful actions.
For each material mistake, give the better line or size and the reason it wins EV.
Mention one relevant alternative only when the decision is genuinely close.

Output:
- First line: `Verdict — Good`, `Verdict — Close`, or `Verdict — Mistake`, followed
  by the pivotal decision in one sentence.
- Then use short chronological bullets only for material decisions; skip standard
  actions and empty streets.
- Finish with exactly one `Next-session rule:` that is specific and executable.
- If no clear mistake can be established, say so without manufacturing a leak.

Default length: 80–150 words for a simple hand and at most 350 words for a complex
hand. If the user asks about one spot, answer only that spot.
"""

IN_GAME_TASK_PROMPT = """# Task: current in-game decision
Recommend the best next action from the current table state. Give an exact size in
chips and BB for bets or raises. Discuss prior action only if it changes this choice.

Output only the useful fields:
- `Action:` the recommended action and size.
- `Why:` the one or two decisive reasons.
- `Plan:` one short future-street contingency, only when it is strategically useful.

Default maximum: 100 words. Do not recap the hand and do not add a general lesson.
"""

GENERAL_COACH_TASK_PROMPT = """# Task: general coaching
Answer the user's exact poker question directly. Use a short example only when it
materially clarifies the answer. Default maximum: 200 words. Do not turn a narrow
question into a full hand review or a general poker lecture.
"""


def _coach_prompt(task_prompt: str) -> str:
    return f"{CORE_COACH_PROMPT.strip()}\n\n{task_prompt.strip()}"


HAND_REVIEW_PROMPT = _coach_prompt(HAND_REVIEW_TASK_PROMPT)
IN_GAME_COACH_PROMPT = _coach_prompt(IN_GAME_TASK_PROMPT)
GENERAL_COACH_PROMPT = _coach_prompt(GENERAL_COACH_TASK_PROMPT)


def build_scenario_context(source) -> str:
    """Build a stable system block from a live GameConfig or persisted Game."""
    game_format = getattr(source, "game_format", "cash") or "cash"
    scenario = getattr(source, "scenario", "custom") or "custom"
    small_blind = getattr(source, "small_blind", 0) or 0
    big_blind = getattr(source, "big_blind", 0) or small_blind * 2
    buy_in = getattr(source, "buy_in", 0) or 0
    ante = getattr(source, "ante", 0) or 0
    ante_type = getattr(source, "ante_type", "none") or "none"
    stage = getattr(source, "tournament_stage", None)
    stack_bb = round(buy_in / big_blind, 1) if big_blind else 0

    lines = [
        "Training scenario (authoritative):",
        f"- Format: {game_format}",
        f"- Scenario: {scenario}",
        f"- Configured starting stack: {stack_bb} BB ({buy_in} chips)",
        f"- Blinds: {small_blind}/{big_blind}",
        f"- Ante: {ante_type} {ante}" if ante else "- Ante: none",
    ]
    if stage:
        lines.append(f"- Tournament stage label: {stage}")

    if game_format == "cash":
        lines.append(
            "Analyze decisions in chip-EV cash-game terms; do not introduce ICM."
        )
    elif stack_bb <= 15:
        lines.append(
            "Prioritize short-stack preflop thresholds, fold equity, open-shoves, "
            "reshoves, and commitment. Do not import deep-stack heuristics."
        )
    elif stack_bb <= 40:
        lines.append(
            "Account for shallower SPR, ante pressure, tighter postflop maneuvering, "
            "and reshove ranges. Do not import 100BB cash heuristics automatically."
        )
    else:
        lines.append(
            "Use tournament chip-EV strategy with ante pressure and stack preservation."
        )
    if game_format == "tournament":
        lines.append(
            "No payout, field, or bubble data is available: assume chip EV and do not "
            "invent ICM pressure unless the user explicitly supplies that context."
        )
    lines.append(
        "For a live hand, use current stacks from the table state for effective-stack "
        "decisions; the configured starting stack is only the scenario anchor."
    )
    return "\n".join(lines)


def _build_messages(
    history: list[Message],
    user_text: str,
    pinned_context: str | None = None,
    live_context: str | None = None,
    conv_pair: int = SHORT_TERM_PAIRS,
    system_prompt: str = HAND_REVIEW_PROMPT,
    scenario_context: str | None = None,
) -> list[dict]:
    """Assemble the OpenAI messages list with a trimmed history window.

    pinned_context (when set) is injected as a second system message immediately
    after the main system prompt and is never trimmed, regardless of how long
    the conversation grows.

    live_context (when set) is injected after pinned_context and is refreshed on
    every turn — use it for mutable state like the current table snapshot.
    """
    msgs: list[dict] = [{"role": "system", "content": system_prompt}]

    if scenario_context:
        msgs.append({"role": "system", "content": scenario_context})

    if pinned_context:
        msgs.append({"role": "system", "content": pinned_context})

    if live_context:
        msgs.append({"role": "system", "content": live_context})

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
    recent = pairs[-conv_pair:]
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
    live_context: str | None = None,
    conv_pair: int = SHORT_TERM_PAIRS,
    coach_scenario: str = "hand_review",
    scenario_context: str | None = None,
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

    if coach_scenario == "hand_review":
        system_prompt = HAND_REVIEW_PROMPT
    elif coach_scenario == "in_game":
        system_prompt = IN_GAME_COACH_PROMPT
    else:
        system_prompt = GENERAL_COACH_PROMPT

    msgs = _build_messages(
        history,
        user_text,
        conv.pinned_context,
        live_context,
        conv_pair,
        system_prompt,
        scenario_context,
    )

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
            max_tokens=MAX_REPLY_TOKENS,
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
