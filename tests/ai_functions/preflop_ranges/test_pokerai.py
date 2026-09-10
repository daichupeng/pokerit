from __future__ import annotations

import asyncio
import json

import httpx
import pytest

import ai_functions.preflop_ranges.pokerai as pokerai_module
from ai_functions.preflop_ranges.pokerai import (
    PokerAIQueryResult,
    apply_pokerai_evidence,
    build_preflop_request,
    query_postgame_snapshots,
    query_preflop_strategy,
)


def _snapshot(
    *,
    decision_id: str = "1:preflop:2",
    round_count: int = 1,
    position: str = "HJ",
    history: list[dict] | None = None,
    game_format: str = "cash",
    cards: list[str] | None = None,
) -> dict:
    return {
        "decision_id": decision_id,
        "round_count": round_count,
        "street": "preflop",
        "known_facts": {
            "format": game_format,
            "players_dealt": 6,
            "blinds": {"small": 50, "big": 100},
            "ante": {"type": "none", "amount": 0},
            "hero_position": position,
            "hero_cards": cards or ["Ah", "Kh"],
            "action_history_before": history or [],
        },
        "derived_calculations": {"hero_stack_bb_at_decision": 100},
        "evidence_sources": [
            {"type": "heuristic_inference"},
            {"type": "range_knowledge_base", "pack_id": "cash_6max_100bb_v1"},
        ],
    }


def test_build_request_maps_six_max_hj_to_mp_and_uses_incremental_amounts(monkeypatch):
    monkeypatch.setenv("POKERAI_PREFLOP_VERSION", "6max")
    snapshot = _snapshot(history=[
        {
            "actor": "Bot", "position": "UTG", "action": "raise",
            "amount_paid": 250, "amount_to": 250, "all_in": False,
        },
    ])

    request = build_preflop_request(snapshot)

    assert request["positions"] == {"hero": "MP"}
    assert request["table_size"] == "6max"
    assert request["hole_cards"] == "AhKh"
    assert request["preflop_actions"] == [
        {"position": "SB", "action": "small blind", "amount": 0.5},
        {"position": "BB", "action": "big blind", "amount": 1.0},
        {"position": "UTG", "action": "raise", "amount": 2.5},
    ]
    assert request["_pokerit"]["observed_raise_sizes_bb"] == [2.5]


def test_build_request_fails_closed_for_mtt_and_routes_later_hero_redecision():
    assert build_preflop_request(_snapshot(game_format="tournament")) is None
    request = build_preflop_request(_snapshot(position="CO", history=[
        {
            "actor": "Hero", "position": "CO", "action": "raise",
            "amount_paid": 250, "amount_to": 250,
        },
        {
            "actor": "Bot", "position": "SB", "action": "raise",
            "amount_paid": 700, "amount_to": 750,
        },
    ]))

    assert request is not None
    assert request["preflop_actions"][-2:] == [
        {"position": "CO", "action": "raise", "amount": 2.5},
        {"position": "SB", "action": "raise", "amount": 7.0},
    ]
    assert request["_pokerit"]["hand_class"] == "AKs"
    assert request["_pokerit"]["use_range_endpoint"] is True


@pytest.mark.parametrize("actions,situation", [
    (["fold"], "RFI"),
    (["fold", "fold"], "RFI"),
    (["call", "fold"], "Limp"),
    (["fold", "call"], "Limp"),
    (["call", "raise"], "Raise"),
])
def test_query_accepts_matching_node_after_folds_and_calls(actions, situation):
    history = [
        {"actor": "Bot", "position": position, "action": action,
         "amount_paid": 300 if action == "raise" else 100,
         "amount_to": 300 if action == "raise" else 100}
        for position, action in zip(("UTG", "MP"), actions)
    ]

    async def run():
        async def handler(request):
            body = json.loads(request.content)
            assert [a["action"] for a in body["preflop_actions"][2:]] == actions
            return httpx.Response(200, json={
                "hole_cards": "AhKh", "situation": situation,
                "strategy": [{"action": "raise", "frequency": 1}],
            })
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await query_preflop_strategy(
                _snapshot(position="CO", history=history),
                api_key="test-key", client=client,
            )

    result = asyncio.run(run())
    assert result.failure is None
    assert result.evidence["node"] == situation


def test_query_returns_sanitized_presolved_reference_and_replaces_local_fallback(monkeypatch):
    monkeypatch.setenv("POKERAI_PREFLOP_VERSION", "6max")

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-key"
        assert request.url.path == "/v1/gto/preflop"
        assert json.loads(request.content)["hole_cards"] == "AhKh"
        return httpx.Response(200, json={
            "hole_cards": "AhKh",
            "situation": "Raise",
            "strategy": [
                {"action": "call", "frequency": 0.25},
                {"action": "raise", "frequency": 0.75, "amount_bb": 9},
            ],
            "quota": {"used": 1, "limit": 1000},
        })

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await query_preflop_strategy(
                _snapshot(history=[{
                    "actor": "Bot", "position": "UTG", "action": "raise",
                    "amount_paid": 300, "amount_to": 300,
                }]),
                api_key="test-key",
                client=client,
            )

    result = asyncio.run(run())

    assert result.failure is None
    assert result.attempted is True
    assert result.evidence["type"] == "preflop_strategy_api"
    assert result.evidence["match_status"] == "presolved_reference"
    assert result.evidence["strategy"] == [
        {"action": "call", "frequency": 0.25},
        {"action": "raise", "frequency": 0.75, "amount_bb": 9.0},
    ]
    assert result.evidence["quota_after_query"] == {"used": 1, "limit": 1000}
    snapshot = apply_pokerai_evidence(_snapshot(), result.evidence)
    assert {source["type"] for source in snapshot["evidence_sources"]} == {
        "heuristic_inference", "preflop_strategy_api",
    }


@pytest.mark.parametrize("depth", [5, 40, 94.85, 200, 1000])
def test_any_depth_queries_api_and_retains_per_opponent_comparisons(depth):
    snapshot = _snapshot(position="UTG")
    snapshot["derived_calculations"]["hero_stack_bb_at_decision"] = depth
    snapshot["known_facts"]["opponent_stacks"] = [
        {"position": "BB", "starting_stack_bb": 100},
        {"position": "SB", "starting_stack_bb": 250},
    ]
    async def run():
        async def handler(request):
            body = json.loads(request.content)
            assert "_pokerit" not in body and "opponent_stacks" not in body
            return httpx.Response(200, json={
                "hole_cards": "AhKh", "situation": "RFI",
                "strategy": [{"action": "raise", "frequency": 1}],
            })
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await query_preflop_strategy(snapshot, client=client, api_key="test-key")
    result = asyncio.run(run())
    assert result.attempted and result.failure is None
    comparison = result.evidence["stack_comparison"]
    assert comparison["effective_stack_known"]
    assert comparison["hero_starting_stack_bb"] == depth
    for row, opponent in zip(comparison["opponents"], [100, 250]):
        assert row["effective_stack_bb"] == min(depth, opponent)
        assert row["difference_bb"] == round(min(depth, opponent) - 100, 2)
        assert row["difference_pct"] == round(min(depth, opponent) - 100, 2)
    assert result.evidence["strategy"] == [{"action": "raise", "frequency": 1.0}]


def test_later_hero_redecision_uses_range_endpoint_and_extracts_current_hand(monkeypatch):
    monkeypatch.setenv("POKERAI_PREFLOP_VERSION", "6max")
    snapshot = _snapshot(position="UTG", cards=["Ah", "5h"], history=[
        {
            "actor": "Hero", "position": "UTG", "action": "raise",
            "amount_paid": 300, "amount_to": 300,
        },
        {
            "actor": "Bot", "position": "SB", "action": "raise",
            "amount_paid": 850, "amount_to": 900,
        },
    ])

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/gto/preflop/range"
        body = json.loads(request.content)
        assert body["table_size"] == "6max"
        assert "hole_cards" not in body
        return httpx.Response(200, json={
            "range": {
                "A5s": {"fold": 0, "call": 0.74, "raise": 0.26},
            },
            "quota": {"used": 3, "limit": 1000},
        })

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await query_preflop_strategy(
                snapshot, api_key="test-key", client=client,
            )

    result = asyncio.run(run())

    assert result.failure is None
    assert result.attempted is True
    assert result.evidence["endpoint"] == "/v1/gto/preflop/range"
    assert result.evidence["node"] == "3-Bet"
    assert result.evidence["hero_cards"] == "Ah5h"
    assert result.evidence["strategy"] == [
        {"action": "fold", "frequency": 0.0},
        {"action": "call", "frequency": 0.74},
        {"action": "raise", "frequency": 0.26},
    ]
    assert result.evidence["quota_after_query"] == {"used": 3, "limit": 1000}


def test_query_rejects_response_for_a_different_node_or_hand():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "hole_cards": "QsQh",
            "situation": "RFI",
            "strategy": [{"action": "raise", "frequency": 1}],
        })

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await query_preflop_strategy(
                _snapshot(history=[{
                    "actor": "Bot", "position": "UTG", "action": "raise",
                    "amount_paid": 300, "amount_to": 300,
                }]),
                api_key="test-key",
                client=client,
            )

    result = asyncio.run(run())

    assert result.evidence is None
    assert result.failure == "invalid_response"
    assert result.attempted is True


def test_postgame_query_cap_is_fifteen_and_selects_two_decisions_per_hand(monkeypatch):
    monkeypatch.setenv("POKERAI_API_KEY", "configured")
    snapshots = []
    for round_count in range(20):
        snapshots.append(_snapshot(
            decision_id=f"{round_count}:preflop:0",
            round_count=round_count,
            position="BTN",
        ))
        snapshots.append(_snapshot(
            decision_id=f"{round_count}:preflop:2",
            round_count=round_count,
            position="BTN",
        ))
        snapshots.append(_snapshot(
            decision_id=f"{round_count}:preflop:4",
            round_count=round_count,
            position="BTN",
        ))
    calls: list[str] = []

    async def fake_query(snapshot):
        calls.append(snapshot["decision_id"])
        return PokerAIQueryResult({
            "type": "preflop_strategy_api",
            "decision_id": snapshot["decision_id"],
        })

    metadata = asyncio.run(query_postgame_snapshots(
        snapshots, limit=15, query=fake_query,
    ))

    assert metadata["attempted"] == 15
    assert metadata["resolved"] == 15
    assert len(calls) == 15
    round_counts = {
        round_id: sum(call.startswith(f"{round_id}:") for call in calls)
        for round_id in {call.split(":", 1)[0] for call in calls}
    }
    assert max(round_counts.values()) == 2
    assert round_counts["0"] == 2


def test_postgame_default_path_disables_retries_and_keeps_strict_request_cap(monkeypatch):
    monkeypatch.setenv("POKERAI_API_KEY", "configured")
    calls: list[bool] = []

    async def fake_provider(snapshot, *, retry_transient=True):
        calls.append(retry_transient)
        return PokerAIQueryResult(None, "network_error")

    monkeypatch.setattr(pokerai_module, "query_preflop_strategy", fake_provider)
    snapshots = [
        _snapshot(decision_id=f"{index}:preflop:0", round_count=index, position="BTN")
        for index in range(20)
    ]

    metadata = asyncio.run(query_postgame_snapshots(snapshots, limit=15))

    assert metadata["attempted"] == 15
    assert len(calls) == 15
    assert calls == [False] * 15
