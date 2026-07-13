"""Tests for street_agent.py (src/ai_functions/game_review/street_agent.py).

The parsing/validation tests need no network — they monkeypatch
chat_model_with_usage with a scripted async stand-in, same pattern as
tests/poker_trainer/test_ws_stats_update.py's SessionLocal monkeypatch. DB is
needed because run_street_agent renders real hands via build_hand_text, which
walks Game/Hand/HandPlayer/Action relationships.
"""

from __future__ import annotations

import asyncio
import json

from poker_engine.db.models import Action, Game, GamePlayer, Hand, HandPlayer, Street, User
from shared_services.llm import StreamResult, TokenUsage

from ai_functions.game_review.street_agent import parse_findings, run_street_agent


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


def _add_hand(db, game, hero_gp, villain_gp, round_count, hero_action="raise"):
    hand = Hand(game_id=game.id, round_count=round_count, street_reached=Street.PREFLOP,
                board=[], had_showdown=False, pot_total=300)
    db.add(hand)
    db.flush()
    db.add_all([
        HandPlayer(hand_id=hand.id, game_player_id=hero_gp.id, position="BTN", hole_cards=["As", "Kh"]),
        HandPlayer(hand_id=hand.id, game_player_id=villain_gp.id, position="BB"),
    ])
    db.add(Action(hand_id=hand.id, game_player_id=hero_gp.id, street=Street.PREFLOP,
                   action=hero_action, amount=300, seq=0))
    db.add(Action(hand_id=hand.id, game_player_id=villain_gp.id, street=Street.PREFLOP,
                   action="fold", amount=0, seq=1))
    db.flush()
    return hand


def test_parse_findings_keeps_valid_finding_and_attaches_hand_id():
    hand = Hand(round_count=5)
    hand.id = "hand-uuid-5"
    raw = json.dumps([{"tag": "missed_fold", "round_count": 5, "note": "should have folded"}])

    findings = parse_findings(raw, [hand], "preflop")

    assert findings == [{
        "tag": "missed_fold",
        "hand_id": "hand-uuid-5",
        "round_count": 5,
        "street": "preflop",
        "note": "should have folded",
    }]


def test_parse_findings_drops_unknown_tag():
    hand = Hand(round_count=1)
    hand.id = "hand-uuid-1"
    raw = json.dumps([{"tag": "not_a_real_tag", "round_count": 1, "note": "x"}])

    assert parse_findings(raw, [hand], "flop") == []


def test_parse_findings_drops_round_count_outside_batch():
    hand = Hand(round_count=1)
    hand.id = "hand-uuid-1"
    raw = json.dumps([{"tag": "missed_fold", "round_count": 999, "note": "x"}])

    assert parse_findings(raw, [hand], "flop") == []


def test_parse_findings_handles_malformed_json():
    hand = Hand(round_count=1)
    hand.id = "hand-uuid-1"

    assert parse_findings("not json at all", [hand], "turn") == []


def test_parse_findings_handles_fenced_json():
    hand = Hand(round_count=2)
    hand.id = "hand-uuid-2"
    raw = "```json\n" + json.dumps([{"tag": "slowplay_risk", "round_count": 2, "note": "x"}]) + "\n```"

    findings = parse_findings(raw, [hand], "river")

    assert findings[0]["tag"] == "slowplay_risk"


def test_parse_findings_handles_empty_list():
    hand = Hand(round_count=1)
    hand.id = "hand-uuid-1"

    assert parse_findings("[]", [hand], "preflop") == []


def test_run_street_agent_returns_empty_for_empty_pool(db_session):
    db = db_session
    user = _make_user(db)
    game, hero_gp, villain_gp = _make_game(db, user)

    result = asyncio.run(run_street_agent("preflop", [], game, hero_gp.id))

    assert result == []


def test_run_street_agent_citation_matches_scripted_finding(db_session, monkeypatch):
    db = db_session
    user = _make_user(db)
    game, hero_gp, villain_gp = _make_game(db, user)
    hand = _add_hand(db, game, hero_gp, villain_gp, round_count=7)

    async def _fake_chat_model_with_usage(**kwargs):
        finding = {"tag": "missed_fold", "round_count": 7, "note": "hero should have folded here"}
        return StreamResult(text=json.dumps([finding]), usage=TokenUsage(prompt_tokens=10, completion_tokens=5))

    monkeypatch.setattr(
        "ai_functions.game_review.street_agent.chat_model_with_usage",
        _fake_chat_model_with_usage,
    )

    findings = asyncio.run(run_street_agent("preflop", [hand], game, hero_gp.id))

    assert len(findings) == 1
    assert findings[0]["hand_id"] == str(hand.id)
    assert findings[0]["round_count"] == 7
    assert findings[0]["street"] == "preflop"
    assert findings[0]["tag"] == "missed_fold"
