from __future__ import annotations

import asyncio
from types import SimpleNamespace

import poker_trainer.api.coach as coach_module
from ai_functions.preflop_ranges import PokerAIQueryResult


def _snapshot(round_count: int, action_index: int) -> dict:
    return {
        "round_count": round_count,
        "decision_id": f"{round_count}:preflop:{action_index}",
    }


def test_live_preflop_lookup_caches_each_node_and_caps_two_per_hand(monkeypatch):
    calls: list[str] = []

    async def fake_query(snapshot):
        decision_id = snapshot["decision_id"]
        calls.append(decision_id)
        return PokerAIQueryResult(
            {"type": "preflop_strategy_api", "decision_id": decision_id},
            attempted=True,
        )

    monkeypatch.setattr(coach_module, "query_preflop_strategy", fake_query)
    session = SimpleNamespace(preflop_strategy_cache={})

    async def run():
        first = await coach_module._cached_live_preflop_result(
            session, _snapshot(7, 1),
        )
        repeated = await coach_module._cached_live_preflop_result(
            session, _snapshot(7, 1),
        )
        second = await coach_module._cached_live_preflop_result(
            session, _snapshot(7, 3),
        )
        capped = await coach_module._cached_live_preflop_result(
            session, _snapshot(7, 5),
        )
        next_hand = await coach_module._cached_live_preflop_result(
            session, _snapshot(8, 1),
        )
        return first, repeated, second, capped, next_hand

    first, repeated, second, capped, next_hand = asyncio.run(run())

    assert repeated is first
    assert second.evidence is not None
    assert capped.evidence is None
    assert capped.failure == "per_hand_limit_reached"
    assert capped.attempted is False
    assert next_hand.evidence is not None
    assert calls == ["7:preflop:1", "7:preflop:3", "8:preflop:1"]
