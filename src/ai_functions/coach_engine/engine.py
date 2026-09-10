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

import re
import uuid
from collections.abc import AsyncIterator

from sqlalchemy.orm import Session

from ai_functions.tools.executors import make_range_equity_calculator_tool
from ai_functions.tools.loop import ToolCallRecord, run_tool_loop
from ai_functions.tools.schemas import IN_GAME_COACH_TOOL_SCHEMAS
from poker_engine.db.models import Conversation, Message
from shared_services.decision_facts import hand_description_conflicts
from shared_services.llm import TokenUsage, stream_chat_with_usage

MAX_CONTEXT_TOKENS = 10_000
SHORT_TERM_PAIRS = 5          # keep at most 5 user/assistant pairs
MODEL = "gpt-5.4-mini"
MAX_REPLY_TOKENS = 2048
TEMPERATURE = 1

_HAN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_EVIDENCE_LINE_RE = re.compile(r"(?im)^\s*Evidence:\s*.*(?:\r?\n|$)")
_EQUITY_NUMBER_RE = re.compile(
    r"(?is)(?:equity|win\s*rate|胜率|权益|赢率).{0,80}\d+(?:\.\d+)?\s*%"
    r"|\d+(?:\.\d+)?\s*%.{0,80}(?:equity|win\s*rate|胜率|权益|赢率)"
)
_EQUITY_TOPIC_RE = re.compile(r"(?is)(?:equity|win\s*rate|胜率|权益|赢率)")
_NUMERIC_EQUITY_REQUEST_RE = re.compile(
    r"(?is)(?:equity|win\s*rate|胜率|权益|赢率).{0,30}"
    r"(?:多少|区间|数值|百分比|算|计算|calculate|compute|range|number|%)"
    r"|(?:算|计算|calculate|compute|give|show).{0,30}"
    r"(?:equity|win\s*rate|胜率|权益|赢率)"
)
_PERCENT_RE = re.compile(r"\d+(?:\.\d+)?\s*%")
_PERCENT_VALUE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_DEFERRED_WORK_RE = re.compile(
    r"(?is)(?:下一(?:条|轮|次回复)|下条|next\s+(?:message|reply|turn)).{0,80}"
    r"(?:可以|会|帮|算|分析|分组|can|will|calculate|analy[sz]e|group)"
)
_FLOP_REQUEST_RE = re.compile(r"(?is)\bflop\b|翻牌|前三张.{0,4}牌")
_TURN_REQUEST_RE = re.compile(
    r"(?is)\bturn\b|转牌|第四张.{0,4}牌|不看.{0,8}第五张|河牌.{0,4}(?:前|之前)"
    r"|before.{0,12}river|without.{0,12}river"
)

CORE_COACH_PROMPT = """# Role and objective
You are an expert No-Limit Hold'em coach for cash games and tournaments. Improve
the user's decision quality by recommending the highest-EV practical line. Reply
in the user's language. Be direct, calm, and precise.

# Evidence discipline
- Treat supplied scenario, hand, and table data as authoritative.
- Treat supplied deterministic hand facts and canonical actions as code-owned.
  Never downgrade or reinterpret them from the raw cards or engine action names.
- Distinguish known facts from inference. Never invent solver outputs, exact range
  frequencies, opponent tendencies, population reads, payout pressure, or ICM.
- Never give numeric equity, equity intervals, or clean-out counts unless the
  context includes an explicit calculator result and its provenance. Structural
  cards remaining by rank or suit are not clean outs and are not equity.
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
  `Evidence:` line using the same user-facing labels as the after-game coach:
  Recorded hand, Exact math, Bot preset style, Preflop range chart, Preflop
  strategy API, User-provided read, AI strategy judgment, or Solver result.
  Never replace these with internal provenance terms or a vague Solver/Heuristic
  badge. `AI GTO` is a configured bot style, not evidence that a solver ran.
- `preflop_strategy_api` supplies fixed-pack frequencies, not live solver results
  or frequencies adjusted for observed sizing or actual stacks.
- Explain supplied stack_comparison differences and uncertain directional effects
  as AI strategy judgment; never invent adjusted frequencies or EV loss.
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

For numeric postflop equity, call the range-equity tool with explicit ranges. Use
earlier `board_street` only when requested. Quote results exactly; never derive
postflop ranges from PokerAI.

Output only the useful fields:
- `Action:` the recommended action and size.
- `Why:` the one or two decisive reasons.
- `Plan:` one short future-street contingency, only when it is strategically useful.

`Plan:` is a contingency inside this hand, not an offer to do more work later.
Answer the current request now; never say you can calculate, group, or analyze it
in the next message, and never ask whether the user wants that promised follow-up.

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


def _explicit_user_language(text: str) -> str | None:
    """Return a clear language signal from one user message, if present.

    Chinese poker questions commonly mix English terms such as ``3-bet`` or
    ``opener`` into an otherwise Chinese sentence. Any Han character is
    therefore a stronger signal than the presence of Latin characters.
    """
    if _HAN_RE.search(text):
        return "Chinese"
    if _LATIN_RE.search(text):
        return "English"
    return None


def _resolve_response_language(user_text: str, history: list[Message]) -> str:
    """Resolve this turn's language from user messages only.

    An explicit current-message signal always wins. Punctuation/numeric-only
    follow-ups inherit the most recent clear user language; assistant replies
    are deliberately ignored so the model cannot lock itself into its previous
    output language.
    """
    current = _explicit_user_language(user_text)
    if current:
        return current
    for message in reversed(history):
        if message.role != "user":
            continue
        previous = _explicit_user_language(message.content)
        if previous:
            return previous
    return "English"


def _language_instruction(language: str) -> str:
    if language == "Chinese":
        return (
            "Response language for this turn: Chinese. Reply in Chinese and match "
            "the user's script; standard poker terms may remain in English. Do not "
            "copy the language of prior assistant replies."
        )
    return (
        "Response language for this turn: English. Reply in English even if prior "
        "assistant replies used another language."
    )


def _in_game_fact_conflict(text: str, hand_facts: dict | None) -> bool:
    return hand_description_conflicts(text, hand_facts)


def _requested_earlier_board_streets(user_text: str) -> set[str]:
    requested: set[str] = set()
    if _FLOP_REQUEST_RE.search(user_text):
        requested.add("flop")
    if _TURN_REQUEST_RE.search(user_text):
        requested.add("turn")
    return requested


def _latest_range_equity_result(
    tool_calls: list[ToolCallRecord] | None,
) -> dict | None:
    for call in reversed(tool_calls or []):
        if (
            call.name == "range_equity_calculator"
            and isinstance(call.result, dict)
            and call.result.get("status") == "ok"
        ):
            return call.result
    return None


def _format_number(value: object) -> str:
    number = float(value)
    return f"{number:.2f}".rstrip("0").rstrip(".")


def _range_equity_summary(result: dict) -> str:
    calculator = result.get("calculator") or {}
    lines = [
        "Calculation: "
        f"{calculator.get('name')} {calculator.get('version')}; "
        f"{calculator.get('method')}; board={result.get('analysis_street')} "
        f"{' '.join(result.get('board') or [])}; "
        f"{calculator.get('enumerated_outcomes')} outcomes."
    ]
    for scenario in result.get("scenarios") or []:
        range_text = ", ".join(
            (
                str(item.get("hand"))
                if float(item.get("weight", 1)) == 1
                else f"{item.get('hand')}@{_format_number(float(item.get('weight')) * 100)}%"
            )
            for item in scenario.get("requested_range") or []
        )
        lines.append(
            f"- {scenario.get('label')}: [{range_text}] -> "
            f"{_format_number(scenario.get('equity_pct'))}% equity "
            f"({scenario.get('combo_count')} legal combos; "
            f"{scenario.get('blocked_combo_count')} blocked; "
            f"{scenario.get('outcomes_evaluated')} outcomes)."
        )
    interval = result.get("scenario_equity_interval_pct") or {}
    lines.append(
        "- Scenario interval: "
        f"{_format_number(interval.get('low'))}%–{_format_number(interval.get('high'))}%; "
        "range definitions are assumptions, not recorded facts or solver output."
    )
    return "\n".join(lines)


def _equity_claims_match_result(text: str, user_text: str, result: dict) -> bool:
    mentions_equity_number = bool(
        _EQUITY_NUMBER_RE.search(text)
        or (_EQUITY_TOPIC_RE.search(user_text) and _PERCENT_RE.search(text))
    )
    if not mentions_equity_number:
        return True
    claimed = [float(match.group(1)) for match in _PERCENT_VALUE_RE.finditer(text)]
    interval = result.get("scenario_equity_interval_pct") or {}
    allowed = [
        float(scenario.get("equity_pct"))
        for scenario in result.get("scenarios") or []
    ]
    allowed.extend([float(interval.get("low")), float(interval.get("high"))])
    return all(
        any(abs(value - expected) <= 0.51 for expected in allowed)
        for value in claimed
    )


def _finalize_in_game_response(
    text: str,
    hand_facts: dict | None,
    language: str,
    user_text: str = "",
    evidence_sources: list[dict] | None = None,
    tool_calls: list[ToolCallRecord] | None = None,
    require_range_equity: bool = False,
) -> str:
    """Apply code-owned evidence and fail closed on unsupported live claims."""
    clean = _EVIDENCE_LINE_RE.sub("", text).strip()
    equity_result = _latest_range_equity_result(tool_calls)
    conflict = _in_game_fact_conflict(clean, hand_facts)
    unsupported_equity = bool(
        (
            _EQUITY_NUMBER_RE.search(clean)
            or (_EQUITY_TOPIC_RE.search(user_text) and _PERCENT_RE.search(clean))
        )
        and not equity_result
    )
    mismatched_equity = bool(
        equity_result
        and not _equity_claims_match_result(clean, user_text, equity_result)
    )
    missing_required_equity = bool(require_range_equity and not equity_result)
    deferred_work = bool(_DEFERRED_WORK_RE.search(clean))
    if (
        conflict
        or unsupported_equity
        or mismatched_equity
        or missing_required_equity
        or deferred_work
    ):
        label = (hand_facts or {}).get("made_hand_label") or "unknown"
        if language == "Chinese":
            if conflict:
                reason = f"模型描述与确定性牌力冲突；你的已知成牌是 {label}。"
            elif unsupported_equity:
                reason = (
                    "当前快照没有带计算来源的 equity 结果；模型给出的具体区间未被采用。"
                    f"你的确定性成牌是 {label}。"
                )
            elif mismatched_equity:
                reason = "模型给出的 equity 数字与本轮精确枚举结果不一致，因此没有采用。"
            elif missing_required_equity:
                reason = "用户要求了数值 equity，但本轮没有得到有效的范围枚举结果。"
            else:
                reason = "答复试图把当前工作推迟到下一条消息，因此没有把这个承诺展示为有效计划。"
            evidence = "Recorded hand" if hand_facts else "AI strategy judgment"
            return (
                "Action: **已拦截这条建议，请重试当前问题。**\n\n"
                f"Why: {reason}\n\n"
                f"Evidence: {evidence}"
            )
        if conflict:
            reason = f"The model description conflicts with the deterministic hand: {label}."
        elif unsupported_equity:
            reason = (
                "No calculator provenance was supplied for numeric equity. The stated range was discarded. "
                f"The deterministic made hand is {label}."
            )
        elif mismatched_equity:
            reason = "The stated equity values do not match this turn's exact enumeration and were discarded."
        elif missing_required_equity:
            reason = "Numeric equity was requested, but this turn produced no valid range enumeration."
        else:
            reason = (
                "The reply deferred the current work to a later message, so that "
                "promise was not accepted as a valid plan."
            )
        evidence = "Recorded hand" if hand_facts else "AI strategy judgment"
        return (
            "Action: **This recommendation was blocked; retry the current question.**\n\n"
            f"Why: {reason}\n\n"
            f"Evidence: {evidence}"
        )

    source_types = {
        str(source.get("type") or "") for source in (evidence_sources or [])
    }
    labels: list[str] = []
    if hand_facts or "engine_state" in source_types:
        labels.append("Recorded hand")
    if equity_result:
        labels.append("Exact math")
    if "preflop_strategy_api" in source_types:
        labels.append("Preflop strategy API")
    elif "range_knowledge_base" in source_types:
        labels.append("Preflop range chart")
    labels.append("AI strategy judgment")
    calculation = f"\n\n{_range_equity_summary(equity_result)}" if equity_result else ""
    return f"{clean}{calculation}\n\nEvidence: {', '.join(labels)}"


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
    language_context: str | None = None,
) -> list[dict]:
    """Assemble the OpenAI messages list with a trimmed history window.

    pinned_context (when set) is injected as a second system message immediately
    after the main system prompt and is never trimmed, regardless of how long
    the conversation grows.

    live_context (when set) is injected after pinned_context and is refreshed on
    every turn — use it for mutable state like the current table snapshot.
    """
    msgs: list[dict] = [{"role": "system", "content": system_prompt}]

    if language_context:
        msgs.append({"role": "system", "content": language_context})

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
    decision_facts: dict | None = None,
    evidence_sources: list[dict] | None = None,
    equity_context: dict | None = None,
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

    language_context = None
    response_language = "English"
    if coach_scenario == "in_game":
        response_language = _resolve_response_language(user_text, history)
        language_context = _language_instruction(response_language)

    msgs = _build_messages(
        history,
        user_text,
        conv.pinned_context,
        live_context,
        conv_pair,
        system_prompt,
        scenario_context,
        language_context,
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
        tool_calls: list[ToolCallRecord] = []
        log_context = {
            "user_id": str(conv.user_id),
            "conversation_id": str(conversation_id),
            "game_id": str(conv.game_id) if conv.game_id else None,
        }
        can_calculate_range_equity = bool(
            coach_scenario == "in_game"
            and equity_context
            and len(equity_context.get("hole") or []) == 2
            and len(equity_context.get("board") or []) in (3, 4, 5)
            and equity_context.get("active_players") == 2
        )
        if can_calculate_range_equity:
            loop_result = await run_tool_loop(
                messages=msgs,
                model=MODEL,
                tools=IN_GAME_COACH_TOOL_SCHEMAS,
                executors={
                    "range_equity_calculator": make_range_equity_calculator_tool(
                        equity_context["hole"],
                        equity_context["board"],
                        _requested_earlier_board_streets(user_text),
                    ),
                },
                max_tokens=MAX_REPLY_TOKENS,
                temperature=TEMPERATURE,
                log_context=log_context,
            )
            usage = loop_result.usage
            tool_calls = loop_result.tool_calls
            full_text.append(loop_result.final_text)
        else:
            async for chunk in stream_chat_with_usage(
                msgs,
                model=MODEL,
                max_tokens=MAX_REPLY_TOKENS,
                temperature=TEMPERATURE,
                log_context=log_context,
            ):
                if isinstance(chunk, TokenUsage):
                    usage = chunk
                else:
                    full_text.append(chunk)
                    if coach_scenario != "in_game":
                        yield chunk

        if coach_scenario == "in_game":
            finalized = _finalize_in_game_response(
                "".join(full_text), decision_facts, response_language, user_text,
                evidence_sources, tool_calls,
                require_range_equity=bool(
                    can_calculate_range_equity
                    and _NUMERIC_EQUITY_REQUEST_RE.search(user_text)
                ),
            )
            full_text[:] = [finalized]
            yield finalized

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
    game = db.get(Game, game_id) if game_id is not None else None
    if game is not None and game.hero_user_id == user_id:
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
