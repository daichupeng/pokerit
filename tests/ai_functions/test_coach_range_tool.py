from __future__ import annotations

import asyncio

from ai_functions.coach_engine import engine
from ai_functions.tools.loop import ToolCallRecord, ToolLoopResult
from poker_engine.db.models import Conversation, Message, User
from shared_services.decision_facts import build_hand_facts
from shared_services.llm import TokenUsage


def test_in_game_chat_offers_bound_range_tool_and_persists_provenance(
    db_session, monkeypatch,
):
    user = User(email="range-coach@test.local", display_name="Hero")
    db_session.add(user)
    db_session.flush()
    conversation = Conversation(user_id=user.id, entry_point="in_game")
    db_session.add(conversation)
    db_session.commit()
    captured = {}

    async def fake_tool_loop(**kwargs):
        captured["tools"] = kwargs["tools"]
        calculator = kwargs["executors"]["range_equity_calculator"]
        result = calculator(
            villain_ranges=[
                {"label": "set", "hands": [{"hand": "QQ"}]},
            ],
            board_street="turn",
        )
        equity = result["scenarios"][0]["equity_pct"]
        call = ToolCallRecord(
            name="range_equity_calculator",
            arguments={"board_street": "turn"},
            result=result,
            latency_ms=1,
        )
        return ToolLoopResult(
            final_text=f"Action: call\nWhy: 对 set 范围有 {equity}% equity。",
            tool_calls=[call],
            usage=TokenUsage(prompt_tokens=7, completion_tokens=3),
        )

    monkeypatch.setattr(engine, "run_tool_loop", fake_tool_loop)

    async def consume():
        generator = await engine.chat(
            db_session,
            conversation.id,
            "先不看第五张牌，算 turn equity",
            coach_scenario="in_game",
            decision_facts=build_hand_facts(
                ["9c", "6c"], ["9h", "Th", "7c", "Qc", "Ac"],
            ),
            equity_context={
                "hole": ["9c", "6c"],
                "board": ["9h", "Th", "7c", "Qc", "Ac"],
                "active_players": 2,
            },
        )
        return [chunk async for chunk in generator]

    chunks = asyncio.run(consume())
    assistant = (
        db_session.query(Message)
        .filter(Message.conversation_id == conversation.id, Message.role == "assistant")
        .one()
    )

    props = captured["tools"][0]["function"]["parameters"]["properties"]
    assert {"hole", "board"}.isdisjoint(props)
    assert len(chunks) == 1
    assert "board=turn 9h Th 7c Qc" in chunks[0]
    assert "Exact math" in chunks[0]
    assert assistant.content == chunks[0]
    assert assistant.prompt_tokens == 7
    assert assistant.completion_tokens == 3
