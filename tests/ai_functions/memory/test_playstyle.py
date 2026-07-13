"""Tests for playstyle.py (src/ai_functions/memory/playstyle.py). Monkeypatches
chat_model_with_usage so no network access is needed.
"""

from __future__ import annotations

import asyncio

from shared_services.llm import StreamResult, TokenUsage

from ai_functions.memory.playstyle import MAX_SUMMARY_CHARS, generate_playstyle_summary


def test_zero_evaluations_short_circuits_without_llm_call(monkeypatch):
    called = {"n": 0}

    async def _fake(**kwargs):
        called["n"] += 1
        return StreamResult(text="should not happen", usage=TokenUsage())

    monkeypatch.setattr("ai_functions.memory.playstyle.chat_model_with_usage", _fake)

    summary = asyncio.run(generate_playstyle_summary({"evaluations_folded": 0, "leaks": []}, {}))

    assert summary == ""
    assert called["n"] == 0


def test_summary_is_capped_to_max_length(monkeypatch):
    async def _fake(**kwargs):
        return StreamResult(text="x" * (MAX_SUMMARY_CHARS + 500), usage=TokenUsage())

    monkeypatch.setattr("ai_functions.memory.playstyle.chat_model_with_usage", _fake)

    summary = asyncio.run(generate_playstyle_summary(
        {"evaluations_folded": 3, "leaks": [{"tag": "low_vpip", "status": "confirmed"}]}, {},
    ))

    assert len(summary) == MAX_SUMMARY_CHARS


def test_summary_strips_whitespace(monkeypatch):
    async def _fake(**kwargs):
        return StreamResult(text="  a clean summary  \n", usage=TokenUsage())

    monkeypatch.setattr("ai_functions.memory.playstyle.chat_model_with_usage", _fake)

    summary = asyncio.run(generate_playstyle_summary({"evaluations_folded": 1, "leaks": []}, {}))

    assert summary == "a clean summary"
