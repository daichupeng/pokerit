"""Fixture-based tests for session_dynamics.py (in-memory Hand objects, no DB)."""

from __future__ import annotations

from poker_engine.db.models import Action, Hand, HandPlayer, Street
from poker_engine.stats import _sum_hands, to_display

from ai_functions.game_review.session_dynamics import compute_session_dynamics

HERO = "hero-gp"
VILLAIN = "villain-gp"


def _hand(round_count: int, is_winner: bool, pot_total: int = 100) -> Hand:
    h = Hand(round_count=round_count, street_reached=Street.PREFLOP, had_showdown=False, pot_total=pot_total)
    h.players = [
        HandPlayer(game_player_id=HERO, position="BTN", is_winner=is_winner),
        HandPlayer(game_player_id=VILLAIN, position="BB", is_winner=not is_winner),
    ]
    h.actions = [
        Action(game_player_id=HERO, street=Street.PREFLOP, action="raise", amount=300, seq=0),
        Action(game_player_id=VILLAIN, street=Street.PREFLOP, action="fold", amount=0, seq=1),
    ]
    return h


def test_thirds_split_covers_all_hands_and_boundaries():
    hands = [_hand(i, is_winner=True) for i in range(1, 13)]  # 12 hands -> thirds of 4
    result = compute_session_dynamics(hands, HERO)
    thirds = result["thirds"]
    assert [t["label"] for t in thirds] == ["first_third", "second_third", "third_third"]
    assert thirds[0]["round_range"] == [1, 4]
    assert thirds[1]["round_range"] == [5, 8]
    assert thirds[2]["round_range"] == [9, 12]


def test_thirds_sum_reconciles_with_full_game_stats():
    hands = [_hand(i, is_winner=(i % 2 == 0)) for i in range(1, 13)]
    result = compute_session_dynamics(hands, HERO)

    total_n = sum(t["display"]["vpip"]["n"] for t in result["thirds"])
    total_d = sum(t["display"]["vpip"]["d"] for t in result["thirds"])

    full_display = to_display(_sum_hands(hands, HERO))
    assert total_n == full_display["vpip"]["n"]
    assert total_d == full_display["vpip"]["d"]


def test_biggest_lost_pot_split_none_when_hero_never_loses():
    hands = [_hand(i, is_winner=True) for i in range(1, 6)]
    result = compute_session_dynamics(hands, HERO)
    assert result["biggest_lost_pot_split"] is None


def test_biggest_lost_pot_split_picks_largest_lost_pot():
    hands = [
        _hand(1, is_winner=True, pot_total=100),
        _hand(2, is_winner=False, pot_total=500),
        _hand(3, is_winner=True, pot_total=100),
        _hand(4, is_winner=False, pot_total=2000),  # biggest lost pot
        _hand(5, is_winner=True, pot_total=100),
    ]
    result = compute_session_dynamics(hands, HERO)
    split = result["biggest_lost_pot_split"]
    assert split is not None
    assert split["hand_round_count"] == 4
    assert split["pre"]["round_range"] == [1, 3]
    assert split["post"]["round_range"] == [4, 5]


def test_biggest_lost_pot_split_none_when_it_is_first_or_last_hand():
    # Biggest lost pot is the very first hand -> no "pre" segment possible.
    hands = [
        _hand(1, is_winner=False, pot_total=2000),
        _hand(2, is_winner=True, pot_total=100),
        _hand(3, is_winner=True, pot_total=100),
    ]
    result = compute_session_dynamics(hands, HERO)
    assert result["biggest_lost_pot_split"] is None
