"""Tests for synthesis.py (src/ai_functions/game_review/synthesis.py).

Monkeypatches chat_model_with_usage (the layer run_tool_loop calls into) so
no network access is needed, while still exercising the real run_tool_loop
round-trip logic and the real pot_odds/hand_lookup executors against a
DB-backed fixture game.
"""

from __future__ import annotations

import asyncio
import json

from poker_engine.db.models import Action, Game, GamePlayer, Hand, HandPlayer, Street, User
from shared_services.llm import StreamResult, TokenUsage

from ai_functions.game_review.synthesis import run_synthesis


def _make_user(db, email="hero@test.local"):
    user = User(email=email, display_name="Hero")
    db.add(user)
    db.flush()
    return user


def _make_game(db, user, max_round=50):
    game = Game(
        started_at=None, ended_at=None, small_blind=50, big_blind=100,
        buy_in=10000, max_round=max_round, hero_user_id=user.id,
    )
    db.add(game)
    db.flush()
    hero_gp = GamePlayer(
        game_id=game.id, seat_index=0, display_name="Hero", engine_uuid="hero-uuid",
        user_id=user.id, is_bot=False, starting_stack=10000,
    )
    villain_gp = GamePlayer(
        game_id=game.id, seat_index=1, display_name="Bot", engine_uuid="bot-uuid",
        user_id=None, is_bot=True, starting_stack=10000,
    )
    db.add_all([hero_gp, villain_gp])
    db.flush()
    return game, hero_gp, villain_gp


def _add_hand(db, game, hero_gp, villain_gp, round_count):
    hand = Hand(game_id=game.id, round_count=round_count, street_reached=Street.PREFLOP,
                board=[], had_showdown=False, pot_total=300)
    db.add(hand)
    db.flush()
    db.add_all([
        HandPlayer(hand_id=hand.id, game_player_id=hero_gp.id, position="BTN", hole_cards=["As", "Kh"]),
        HandPlayer(hand_id=hand.id, game_player_id=villain_gp.id, position="BB"),
    ])
    db.add(Action(hand_id=hand.id, game_player_id=hero_gp.id, street=Street.PREFLOP,
                   action="raise", amount=300, seq=0))
    db.add(Action(hand_id=hand.id, game_player_id=villain_gp.id, street=Street.PREFLOP,
                   action="fold", amount=0, seq=1))
    db.flush()
    return hand


_LEAK_TAGS = [
    {"tag": "missed_fold", "kind": "judgment", "severity": 1,
     "citations": [{"hand_id": "h1", "round_count": 0, "street": "preflop"}]},
    {"tag": "low_vpip", "kind": "stat", "severity": 3,
     "evidence": {"stat": "low_vpip", "pct": 10, "n": 10, "d": 100}},
]


def test_run_synthesis_sorts_sections_by_severity_and_uses_tool_call(db_session, monkeypatch):
    db = db_session
    user = _make_user(db)
    game, hero_gp, villain_gp = _make_game(db, user)
    _add_hand(db, game, hero_gp, villain_gp, round_count=0)

    call_count = {"n": 0}

    async def _fake_chat_model_with_usage(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # First round trip: model calls pot_odds to verify a claim.
            return StreamResult(
                text="",
                usage=TokenUsage(prompt_tokens=10, completion_tokens=5),
                tool_calls=[{"id": "call_1", "name": "pot_odds",
                             "arguments": json.dumps({"pot_size": 100, "amount_to_call": 50})}],
            )
        # Second round trip: final structured report, low-severity tag listed
        # first in raw output — code must resort it by severity.
        report = {
            "summary": "Hero is playing too tight overall.",
            "sections": [
                {"tag": "missed_fold", "narrative": "One clear missed fold at round 0."},
                {"tag": "low_vpip", "narrative": "VPIP is well below a healthy range."},
            ],
        }
        return StreamResult(text=json.dumps(report), usage=TokenUsage(prompt_tokens=20, completion_tokens=10))

    monkeypatch.setattr(
        "ai_functions.tools.loop.chat_model_with_usage",
        _fake_chat_model_with_usage,
    )

    result = asyncio.run(run_synthesis(
        stats_snapshot={"vpip": {"pct": 10, "n": 10, "d": 100}},
        session_dynamics={"thirds": []},
        leak_tags=_LEAK_TAGS,
        db=db,
        game_id=str(game.id),
        user=user,
    ))

    sections = result["report"]["sections"]
    assert [s["tag"] for s in sections] == ["low_vpip", "missed_fold"]
    assert sections[0]["severity"] == 3
    assert sections[0]["kind"] == "stat"
    assert sections[1]["citations"][0]["round_count"] == 0

    tool_names = [tc.name for tc in result["tool_calls"]]
    assert "pot_odds" in tool_names


def test_run_synthesis_drops_unknown_tag_and_survives_malformed_json(db_session, monkeypatch):
    db = db_session
    user = _make_user(db)
    game, hero_gp, villain_gp = _make_game(db, user)

    async def _fake_chat_model_with_usage(**kwargs):
        report = {
            "summary": "x",
            "sections": [{"tag": "not_a_pinned_tag", "narrative": "should be dropped"}],
        }
        return StreamResult(text=json.dumps(report), usage=TokenUsage())

    monkeypatch.setattr(
        "ai_functions.tools.loop.chat_model_with_usage",
        _fake_chat_model_with_usage,
    )

    result = asyncio.run(run_synthesis(
        stats_snapshot={}, session_dynamics={}, leak_tags=_LEAK_TAGS,
        db=db, game_id=str(game.id), user=user,
    ))

    assert result["report"]["sections"] == []
