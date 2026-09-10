"""Fixture-based tests for the deterministic stats engine (src/poker_engine/stats.py).

Hands are hand-built (no live engine run, no DB) using the real ORM classes as
plain in-memory objects — this is enough to exercise the pure counting
functions without a database.
"""

from __future__ import annotations

from poker_engine.db.models import Action, Hand, HandPlayer, Street
from poker_engine.stats import RawStatCounts, compute_hand_stats, to_display

HERO = "hero-gp"
VILLAIN = "villain-gp"
VILLAIN2 = "villain2-gp"


def _hand(
    street_reached: Street,
    had_showdown: bool,
    players: list[HandPlayer],
    actions: list[Action],
) -> Hand:
    h = Hand(street_reached=street_reached, had_showdown=had_showdown)
    h.players = players
    h.actions = actions
    return h


def _hp(gp_id: str, position: str | None = None, is_winner: bool = False, amount_won: int = 0) -> HandPlayer:
    return HandPlayer(game_player_id=gp_id, position=position, is_winner=is_winner, amount_won=amount_won)


def _act(gp_id: str, street: Street, action: str, amount: int, seq: int) -> Action:
    return Action(game_player_id=gp_id, street=street, action=action, amount=amount, seq=seq)


def test_vpip_hand_hero_calls_preflop():
    hand = _hand(
        Street.PREFLOP,
        had_showdown=False,
        players=[_hp(HERO, position="BTN"), _hp(VILLAIN, position="BB")],
        actions=[
            _act(VILLAIN, Street.PREFLOP, "bigblind", 100, 0),
            _act(HERO, Street.PREFLOP, "call", 100, 1),
            _act(VILLAIN, Street.PREFLOP, "raise", 300, 2),
            _act(HERO, Street.PREFLOP, "fold", 0, 3),
        ],
    )
    counts = compute_hand_stats(hand, HERO)
    assert counts.hands_dealt == 1
    assert counts.vpip_hands == 1
    assert counts.pfr_hands == 0


def test_blind_only_hand_is_not_vpip():
    hand = _hand(
        Street.PREFLOP,
        had_showdown=False,
        players=[_hp(HERO, position="BB"), _hp(VILLAIN, position="BTN")],
        actions=[
            _act(HERO, Street.PREFLOP, "bigblind", 100, 0),
            _act(VILLAIN, Street.PREFLOP, "raise", 300, 1),
            _act(HERO, Street.PREFLOP, "fold", 0, 2),
        ],
    )
    counts = compute_hand_stats(hand, HERO)
    assert counts.vpip_hands == 0
    assert counts.pfr_hands == 0


def test_big_blind_free_check_is_not_vpip():
    hand = _hand(
        Street.FLOP, False,
        [_hp(HERO, position="BB"), _hp(VILLAIN, position="SB")],
        [
            _act(VILLAIN, Street.PREFLOP, "call", 50, 0),
            _act(HERO, Street.PREFLOP, "call", 0, 1),
        ],
    )
    counts = compute_hand_stats(hand, HERO)
    assert counts.vpip_hands == 0
    assert counts.limp_hands == 0


def test_pfr_hand_hero_raises_preflop():
    hand = _hand(
        Street.PREFLOP,
        had_showdown=False,
        players=[_hp(HERO, position="BTN"), _hp(VILLAIN, position="BB")],
        actions=[
            _act(HERO, Street.PREFLOP, "raise", 300, 0),
            _act(VILLAIN, Street.PREFLOP, "fold", 0, 1),
        ],
    )
    counts = compute_hand_stats(hand, HERO)
    assert counts.vpip_hands == 1
    assert counts.pfr_hands == 1


def test_three_bet_opportunity_taken():
    hand = _hand(
        Street.PREFLOP,
        had_showdown=False,
        players=[_hp(HERO, position="BB"), _hp(VILLAIN, position="BTN")],
        actions=[
            _act(VILLAIN, Street.PREFLOP, "raise", 300, 0),
            _act(HERO, Street.PREFLOP, "raise", 900, 1),
            _act(VILLAIN, Street.PREFLOP, "fold", 0, 2),
        ],
    )
    counts = compute_hand_stats(hand, HERO)
    assert counts.three_bet_opportunities == 1
    assert counts.three_bet_hands == 1


def test_three_bet_opportunity_declined():
    hand = _hand(
        Street.PREFLOP,
        had_showdown=False,
        players=[_hp(HERO, position="BB"), _hp(VILLAIN, position="BTN")],
        actions=[
            _act(VILLAIN, Street.PREFLOP, "raise", 300, 0),
            _act(HERO, Street.PREFLOP, "call", 300, 1),
        ],
    )
    counts = compute_hand_stats(hand, HERO)
    assert counts.three_bet_opportunities == 1
    assert counts.three_bet_hands == 0


def test_raise_after_hero_fold_is_not_a_three_bet_opportunity():
    hand = _hand(
        Street.PREFLOP, False,
        [_hp(HERO), _hp(VILLAIN), _hp(VILLAIN2)],
        [
            _act(HERO, Street.PREFLOP, "fold", 0, 0),
            _act(VILLAIN, Street.PREFLOP, "raise", 300, 1),
        ],
    )
    assert compute_hand_stats(hand, HERO).three_bet_opportunities == 0


def test_cold_four_bet_is_not_counted_as_three_bet():
    hand = _hand(
        Street.PREFLOP, False,
        [_hp(HERO), _hp(VILLAIN), _hp(VILLAIN2)],
        [
            _act(VILLAIN, Street.PREFLOP, "raise", 300, 0),
            _act(VILLAIN2, Street.PREFLOP, "raise", 900, 1),
            _act(HERO, Street.PREFLOP, "raise", 2400, 2),
        ],
    )
    counts = compute_hand_stats(hand, HERO)
    assert counts.three_bet_opportunities == 0
    assert counts.three_bet_hands == 0


def test_fold_to_3bet():
    hand = _hand(
        Street.PREFLOP,
        had_showdown=False,
        players=[_hp(HERO, position="BTN"), _hp(VILLAIN, position="BB")],
        actions=[
            _act(HERO, Street.PREFLOP, "raise", 300, 0),
            _act(VILLAIN, Street.PREFLOP, "raise", 900, 1),
            _act(HERO, Street.PREFLOP, "fold", 0, 2),
        ],
    )
    counts = compute_hand_stats(hand, HERO)
    assert counts.faced_3bet_after_raise == 1
    assert counts.folded_to_3bet == 1


def test_three_bettor_folding_to_four_bet_is_not_fold_to_three_bet():
    hand = _hand(
        Street.PREFLOP, False,
        [_hp(HERO), _hp(VILLAIN)],
        [
            _act(VILLAIN, Street.PREFLOP, "raise", 300, 0),
            _act(HERO, Street.PREFLOP, "raise", 900, 1),
            _act(VILLAIN, Street.PREFLOP, "raise", 2400, 2),
            _act(HERO, Street.PREFLOP, "fold", 0, 3),
        ],
    )
    counts = compute_hand_stats(hand, HERO)
    assert counts.faced_3bet_after_raise == 0
    assert counts.folded_to_3bet == 0


def test_open_raiser_folding_after_cold_four_bet_is_not_fold_to_three_bet():
    hand = _hand(
        Street.PREFLOP, False,
        [_hp(HERO), _hp(VILLAIN), _hp(VILLAIN2)],
        [
            _act(HERO, Street.PREFLOP, "raise", 300, 0),
            _act(VILLAIN, Street.PREFLOP, "raise", 900, 1),
            _act(VILLAIN2, Street.PREFLOP, "raise", 2400, 2),
            _act(HERO, Street.PREFLOP, "fold", 0, 3),
        ],
    )
    counts = compute_hand_stats(hand, HERO)
    assert counts.faced_3bet_after_raise == 0
    assert counts.folded_to_3bet == 0


def test_cbet_on_each_street():
    hand = _hand(
        Street.RIVER,
        had_showdown=False,
        players=[_hp(HERO, position="BTN"), _hp(VILLAIN, position="BB")],
        actions=[
            _act(HERO, Street.PREFLOP, "raise", 300, 0),
            _act(VILLAIN, Street.PREFLOP, "call", 300, 1),
            _act(HERO, Street.FLOP, "raise", 200, 2),
            _act(VILLAIN, Street.FLOP, "call", 200, 3),
            _act(HERO, Street.TURN, "raise", 400, 4),
            _act(VILLAIN, Street.TURN, "call", 400, 5),
            _act(HERO, Street.RIVER, "raise", 800, 6),
            _act(VILLAIN, Street.RIVER, "fold", 0, 7),
        ],
    )
    counts = compute_hand_stats(hand, HERO)
    assert counts.cbet_opportunities_flop == 1 and counts.cbet_flop == 1
    assert counts.cbet_opportunities_turn == 1 and counts.cbet_turn == 1
    assert counts.cbet_opportunities_river == 1 and counts.cbet_river == 1


def test_in_position_cbet_after_opponent_check_is_counted():
    hand = _hand(
        Street.FLOP, False,
        [_hp(HERO), _hp(VILLAIN)],
        [
            _act(HERO, Street.PREFLOP, "raise", 300, 0),
            _act(VILLAIN, Street.PREFLOP, "call", 300, 1),
            _act(VILLAIN, Street.FLOP, "call", 0, 2),
            _act(HERO, Street.FLOP, "raise", 200, 3),
        ],
    )
    counts = compute_hand_stats(hand, HERO)
    assert counts.cbet_opportunities_flop == 1
    assert counts.cbet_flop == 1


def test_donk_bet_removes_cbet_opportunity():
    hand = _hand(
        Street.FLOP, False,
        [_hp(HERO), _hp(VILLAIN)],
        [
            _act(HERO, Street.PREFLOP, "raise", 300, 0),
            _act(VILLAIN, Street.PREFLOP, "call", 300, 1),
            _act(VILLAIN, Street.FLOP, "raise", 200, 2),
            _act(HERO, Street.FLOP, "call", 200, 3),
        ],
    )
    assert compute_hand_stats(hand, HERO).cbet_opportunities_flop == 0


def test_preflop_allin_runout_has_no_postflop_cbet_opportunities():
    hand = _hand(
        Street.RIVER, True,
        [_hp(HERO), _hp(VILLAIN)],
        [
            _act(HERO, Street.PREFLOP, "raise", 1000, 0),
            _act(VILLAIN, Street.PREFLOP, "call", 1000, 1),
        ],
    )
    counts = compute_hand_stats(hand, HERO)
    assert counts.cbet_opportunities_flop == 0
    assert counts.cbet_opportunities_turn == 0
    assert counts.cbet_opportunities_river == 0


def test_fold_to_cbet():
    hand = _hand(
        Street.FLOP,
        had_showdown=False,
        players=[_hp(HERO, position="BB"), _hp(VILLAIN, position="BTN")],
        actions=[
            _act(VILLAIN, Street.PREFLOP, "raise", 300, 0),
            _act(HERO, Street.PREFLOP, "call", 300, 1),
            _act(VILLAIN, Street.FLOP, "raise", 200, 2),
            _act(HERO, Street.FLOP, "fold", 0, 3),
        ],
    )
    counts = compute_hand_stats(hand, HERO)
    assert counts.faced_cbet_opportunities_flop == 1
    assert counts.faced_cbet_flop == 1
    assert counts.folded_to_cbet_flop == 1


def test_wtsd_hand():
    hand = _hand(
        Street.RIVER,
        had_showdown=True,
        players=[_hp(HERO, position="BTN", is_winner=False, amount_won=-100), _hp(VILLAIN, position="BB")],
        actions=[
            _act(HERO, Street.PREFLOP, "raise", 300, 0),
            _act(VILLAIN, Street.PREFLOP, "call", 300, 1),
            _act(HERO, Street.FLOP, "call", 0, 2),
            _act(VILLAIN, Street.FLOP, "call", 0, 3),
            _act(HERO, Street.RIVER, "call", 0, 4),
            _act(VILLAIN, Street.RIVER, "call", 0, 5),
        ],
    )
    counts = compute_hand_stats(hand, HERO)
    assert counts.saw_flop_hands == 1
    assert counts.showdown_hands == 1
    assert counts.wtsd_hands == 1
    assert counts.won_at_showdown_hands == 0


def test_table_reaching_flop_after_hero_folds_does_not_count_as_saw_flop():
    hand = _hand(
        Street.FLOP, False,
        [_hp(HERO), _hp(VILLAIN), _hp(VILLAIN2)],
        [
            _act(HERO, Street.PREFLOP, "fold", 0, 0),
            _act(VILLAIN, Street.PREFLOP, "raise", 300, 1),
            _act(VILLAIN2, Street.PREFLOP, "call", 300, 2),
        ],
    )
    assert compute_hand_stats(hand, HERO).saw_flop_hands == 0


def test_won_at_showdown_hand():
    hand = _hand(
        Street.RIVER,
        had_showdown=True,
        players=[_hp(HERO, position="BTN", is_winner=True, amount_won=500), _hp(VILLAIN, position="BB")],
        actions=[
            _act(HERO, Street.PREFLOP, "raise", 300, 0),
            _act(VILLAIN, Street.PREFLOP, "call", 300, 1),
            _act(HERO, Street.RIVER, "call", 0, 2),
            _act(VILLAIN, Street.RIVER, "call", 0, 3),
        ],
    )
    counts = compute_hand_stats(hand, HERO)
    assert counts.showdown_hands == 1
    assert counts.won_at_showdown_hands == 1


def test_position_split():
    hand = _hand(
        Street.PREFLOP,
        had_showdown=False,
        players=[_hp(HERO, position="CO"), _hp(VILLAIN, position="BB")],
        actions=[
            _act(HERO, Street.PREFLOP, "raise", 300, 0),
            _act(VILLAIN, Street.PREFLOP, "fold", 0, 1),
        ],
    )
    counts = compute_hand_stats(hand, HERO)
    assert "CO" in counts.by_position
    assert counts.by_position["CO"].pfr_hands == 1
    assert counts.by_position["CO"].hands_dealt == 1


def test_table_size_split_uses_each_hands_active_player_count():
    eight_handed = _hand(
        Street.PREFLOP, False,
        [_hp(HERO, position="BTN"), _hp(VILLAIN, position="BB")],
        [_act(HERO, Street.PREFLOP, "raise", 300, 0)],
    )
    eight_handed.active_player_count = 8
    six_handed = _hand(
        Street.PREFLOP, False,
        [_hp(HERO, position="CO"), _hp(VILLAIN, position="BB")],
        [_act(HERO, Street.PREFLOP, "fold", 0, 0)],
    )
    six_handed.active_player_count = 6

    display = to_display(
        compute_hand_stats(eight_handed, HERO) + compute_hand_stats(six_handed, HERO)
    )

    assert display["vpip"] == {"pct": 50.0, "n": 1, "d": 2}
    assert display["by_table_size"]["8"]["vpip"] == {"pct": 100.0, "n": 1, "d": 1}
    assert display["by_table_size"]["6"]["vpip"] == {"pct": 0.0, "n": 0, "d": 1}


def test_aggression_factor_components():
    hand = _hand(
        Street.RIVER,
        had_showdown=False,
        players=[_hp(HERO, position="BTN"), _hp(VILLAIN, position="BB")],
        actions=[
            _act(HERO, Street.PREFLOP, "raise", 300, 0),
            _act(VILLAIN, Street.PREFLOP, "call", 300, 1),
            _act(HERO, Street.FLOP, "raise", 200, 2),
            _act(VILLAIN, Street.FLOP, "call", 200, 3),
            _act(HERO, Street.TURN, "call", 0, 4),
            _act(VILLAIN, Street.TURN, "raise", 100, 5),
            _act(HERO, Street.TURN, "call", 100, 6),
        ],
    )
    counts = compute_hand_stats(hand, HERO)
    # Postflop: checks are CALL amount=0 in storage and must not enter AF.
    assert counts.postflop_bets_raises == 1
    assert counts.postflop_calls == 1


def test_aggression_factor_with_no_calls_is_infinite_not_zero():
    display = to_display(RawStatCounts(postflop_bets_raises=3, postflop_calls=0))
    assert display["aggression_factor"] == {"ratio": None, "infinite": True, "n": 3, "d": 0}


def test_rollup_is_sum_not_average():
    """The rollup correctness test, required with an exact numeric case.

    Game A: 3 VPIP hands out of 10 (30%). Game B: 1 VPIP hand out of 20 (5%).
    Summed: VPIP = 4/30 ~= 13.3%, NOT 17.5% (the arithmetic mean of 30% and 5%).
    """
    game_a = RawStatCounts(hands_dealt=10, vpip_hands=3)
    game_b = RawStatCounts(hands_dealt=20, vpip_hands=1)
    combined = game_a + game_b

    assert combined.hands_dealt == 30
    assert combined.vpip_hands == 4

    display = to_display(combined)
    assert display["vpip"]["n"] == 4
    assert display["vpip"]["d"] == 30
    assert abs(display["vpip"]["pct"] - 13.3) < 0.05
    assert abs(display["vpip"]["pct"] - 17.5) > 1.0


def test_to_display_zero_denominator_is_undefined_not_zero():
    counts = RawStatCounts()
    display = to_display(counts)
    assert display["vpip"] == {"pct": None, "n": 0, "d": 0}
    assert display["hands_dealt"] == 0
