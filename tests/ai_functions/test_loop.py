"""Tests for run_tool_loop() (src/ai_functions/tools/loop.py).

The backend-guard test needs no network access. The live-OpenAI test is
skipped unless OPENAI_API_KEY is set, mirroring the Postgres-unreachable skip
convention in tests/conftest.py.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from ai_functions.tools.executors import make_equity_calculator_tool
from ai_functions.tools.loop import run_tool_loop
from ai_functions.tools.schemas import EQUITY_CALCULATOR_SCHEMA


def test_run_tool_loop_rejects_non_openai_model():
    async def _run(model: str):
        await run_tool_loop(
            messages=[{"role": "user", "content": "hi"}],
            model=model,
            tools=[EQUITY_CALCULATOR_SCHEMA],
            executors={},
        )

    with pytest.raises(ValueError):
        asyncio.run(_run("minimax-m2"))

    with pytest.raises(ValueError):
        asyncio.run(_run("llama3"))


@pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set")
def test_run_tool_loop_executes_tool_and_returns_history():
    asyncio.run(_run_tool_loop_executes_tool_and_returns_history())


async def _run_tool_loop_executes_tool_and_returns_history():
    executors = {"equity_calculator": make_equity_calculator_tool()}
    messages = [
        {
            "role": "user",
            "content": (
                "Use the equity_calculator tool to compute hero's equity "
                "with hole cards As Ah, no board cards, against 2 active "
                "players. Then state the number in your final answer."
            ),
        }
    ]

    result = await run_tool_loop(
        messages=messages,
        model="gpt-5-mini",
        tools=[EQUITY_CALCULATOR_SCHEMA],
        executors=executors,
        temperature=1,  # gpt-5-mini only supports the default temperature
    )

    assert result.final_text
    assert len(result.tool_calls) >= 1
    assert result.tool_calls[0].name == "equity_calculator"
    assert "win_rate" in result.tool_calls[0].result
