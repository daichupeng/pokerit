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

from ai_functions.game_review.synthesis import normalize_report_evidence, run_synthesis


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
     "citations": [{
         "hand_id": "h1", "round_count": 0, "street": "preflop",
         "hero_action": "called a 3-bet", "issue": "the continue range is too weak",
         "better_line": "fold", "why": "folding avoids a dominated low-equity pot",
         "confidence": "high",
     }]},
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
    assert sections[1]["examples"][0]["hero_action"] == "called a 3-bet"
    assert sections[1]["examples"][0]["better_line"] == "fold"
    assert sections[1]["examples"][0]["why"]

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


def test_run_synthesis_includes_player_profile_and_attaches_profile_status(db_session, monkeypatch):
    db = db_session
    user = _make_user(db)
    game, hero_gp, villain_gp = _make_game(db, user)

    captured_messages = {}

    async def _fake_chat_model_with_usage(**kwargs):
        captured_messages["messages"] = kwargs["messages"]
        report = {
            "summary": "x",
            "sections": [{"tag": "missed_fold", "narrative": "returning leak narrative"}],
        }
        return StreamResult(text=json.dumps(report), usage=TokenUsage())

    monkeypatch.setattr(
        "ai_functions.tools.loop.chat_model_with_usage",
        _fake_chat_model_with_usage,
    )

    player_profile = {
        "evaluations_folded": 2,
        "leaks": [{"tag": "missed_fold", "status": "confirmed"}],
        "trends": {},
        "playstyle_summary": "Plays tight.",
    }

    result = asyncio.run(run_synthesis(
        stats_snapshot={}, session_dynamics={}, leak_tags=_LEAK_TAGS,
        db=db, game_id=str(game.id), user=user,
        player_profile=player_profile,
        profile_status_by_tag={"missed_fold": "returning"},
    ))

    pinned_context = json.loads(captured_messages["messages"][-1]["content"])
    assert pinned_context["player_profile"] == player_profile
    assert pinned_context["leak_tags"][0]["profile_status"] == "returning"

    sections = result["report"]["sections"]
    assert sections[0]["tag"] == "missed_fold"
    assert sections[0]["profile_status"] == "returning"


def test_run_synthesis_omits_player_profile_key_when_none(db_session, monkeypatch):
    db = db_session
    user = _make_user(db)
    game, hero_gp, villain_gp = _make_game(db, user)

    captured_messages = {}

    async def _fake_chat_model_with_usage(**kwargs):
        captured_messages["messages"] = kwargs["messages"]
        report = {"summary": "x", "sections": [{"tag": "missed_fold", "narrative": "n"}]}
        return StreamResult(text=json.dumps(report), usage=TokenUsage())

    monkeypatch.setattr(
        "ai_functions.tools.loop.chat_model_with_usage",
        _fake_chat_model_with_usage,
    )

    result = asyncio.run(run_synthesis(
        stats_snapshot={}, session_dynamics={}, leak_tags=_LEAK_TAGS,
        db=db, game_id=str(game.id), user=user,
    ))

    pinned_context = json.loads(captured_messages["messages"][-1]["content"])
    assert "player_profile" not in pinned_context
    assert result["report"]["sections"][0]["profile_status"] is None


def test_run_synthesis_pins_sample_status_for_small_sample_wording(db_session, monkeypatch):
    db = db_session
    user = _make_user(db)
    game, _, _ = _make_game(db, user)
    captured_messages = {}

    async def _fake_chat_model_with_usage(**kwargs):
        captured_messages["messages"] = kwargs["messages"]
        return StreamResult(
            text=json.dumps({"summary": "Early signal only.", "sections": []}),
            usage=TokenUsage(),
        )

    monkeypatch.setattr(
        "ai_functions.tools.loop.chat_model_with_usage",
        _fake_chat_model_with_usage,
    )
    sample_status = {
        "version": "2026-07-23.v3",
        "metrics": [{
            "metric": "W$SD", "observed": 0, "required": 5,
            "status": "insufficient_sample",
        }],
    }

    asyncio.run(run_synthesis(
        stats_snapshot={"wsd": {"pct": None, "n": 0, "d": 0}},
        session_dynamics={}, leak_tags=[], sample_status=sample_status,
        db=db, game_id=str(game.id), user=user,
    ))

    pinned_context = json.loads(captured_messages["messages"][-1]["content"])
    assert pinned_context["sample_status"] == sample_status


def test_run_synthesis_guards_aggression_factor_operands(db_session, monkeypatch):
    db = db_session
    user = _make_user(db)
    game, _, _ = _make_game(db, user)
    captured_messages = {}
    aggression_leak = {
        "tag": "too_aggressive_postflop",
        "kind": "stat",
        "severity": 3,
        "evidence": {
            "stat": "too_aggressive_postflop", "ratio": 10.0,
            "n": 10, "d": 1,
        },
    }

    async def _fake_chat_model_with_usage(**kwargs):
        captured_messages["messages"] = kwargs["messages"]
        report = {
            "summary": "AF is 10.0 from 1 aggressive action over 10 passive actions. Focus on control.",
            "sections": [{
                "tag": "too_aggressive_postflop",
                "narrative": (
                    "The postflop aggression factor is 10.0 based on 1 aggressive action "
                    "over 10 passive actions. Slow down in marginal spots."
                ),
            }],
        }
        return StreamResult(text=json.dumps(report), usage=TokenUsage())

    monkeypatch.setattr(
        "ai_functions.tools.loop.chat_model_with_usage",
        _fake_chat_model_with_usage,
    )

    result = asyncio.run(run_synthesis(
        stats_snapshot={"aggression_factor": {"ratio": 10.0, "n": 10, "d": 1}},
        session_dynamics={}, leak_tags=[aggression_leak],
        db=db, game_id=str(game.id), user=user,
    ))

    pinned_context = json.loads(captured_messages["messages"][-1]["content"])
    evidence = pinned_context["leak_tags"][0]["evidence"]
    assert evidence["formula"] == "postflop bets+raises / postflop calls"
    assert evidence["bets_raises"] == 10
    assert evidence["calls"] == 1

    report = result["report"]
    assert "1 aggressive action over 10 passive actions" not in report["summary"]
    narrative = report["sections"][0]["narrative"]
    assert narrative.startswith(
        "Postflop aggression factor is 10.0, calculated from 10 bets/raises and 1 call; "
        "checks and folds are excluded from AF."
    )
    assert "Slow down in marginal spots." in narrative


def test_normalize_report_evidence_repairs_saved_aggression_report():
    saved = {
        "summary": "AF is 10.0 from 1 aggressive action over 10 passive actions. Other note.",
        "sections": [{
            "tag": "too_aggressive_postflop",
            "kind": "stat",
            "severity": 3,
            "evidence": {"ratio": 10.0, "n": 10, "d": 1},
            "narrative": (
                "The aggression factor is 10.0 based on 1 aggressive action over "
                "10 passive actions. Keep marginal lines controlled."
            ),
        }],
        "report_kind": "current_game_observation",
    }

    normalized = normalize_report_evidence(saved)

    assert normalized["summary"] == "Other note."
    assert normalized["report_kind"] == "current_game_observation"
    assert normalized["sections"][0]["narrative"] == (
        "Postflop aggression factor is 10.0, calculated from 10 bets/raises and 1 call; "
        "checks and folds are excluded from AF. "
        "Keep marginal lines controlled."
    )
    assert saved["sections"][0]["narrative"].startswith("The aggression factor")
