"""Fixture-based tests for triage.py (in-memory Hand objects, no DB)."""

from __future__ import annotations

from poker_engine.db.models import Action, Hand, HandPlayer, Street

from ai_functions.game_review.triage import triage_hands

HERO = "hero-gp"
VILLAIN = "villain-gp"


def _hand(
    round_count: int,
    street_reached: Street,
    had_showdown: bool,
    players: list[HandPlayer],
    actions: list[Action],
    pot_total: int = 100,
) -> Hand:
    h = Hand(
        round_count=round_count,
        street_reached=street_reached,
        had_showdown=had_showdown,
        pot_total=pot_total,
    )
    h.players = players
    h.actions = actions
    return h


def _hp(gp_id: str, position: str | None = None, is_winner: bool = False) -> HandPlayer:
    return HandPlayer(game_player_id=gp_id, position=position, is_winner=is_winner)


def _act(gp_id: str, street: Street, action: str, amount: int, seq: int, stack_after: int | None = None) -> Action:
    return Action(game_player_id=gp_id, street=street, action=action, amount=amount, seq=seq, stack_after=stack_after)


def _routine_fold_hand(round_count: int) -> Hand:
    """Hero folds preflop with no VPIP action and no 3-bet opportunity."""
    return _hand(
        round_count, Street.PREFLOP, had_showdown=False,
        players=[_hp(HERO, "BTN"), _hp(VILLAIN, "BB")],
        actions=[
            _act(VILLAIN, Street.PREFLOP, "bigblind", 100, 0),
            _act(HERO, Street.PREFLOP, "fold", 0, 1),
        ],
        pot_total=100,
    )


def _vpip_hand(round_count: int, pot_total: int = 300) -> Hand:
    return _hand(
        round_count, Street.PREFLOP, had_showdown=False,
        players=[_hp(HERO, "BTN"), _hp(VILLAIN, "BB")],
        actions=[
            _act(HERO, Street.PREFLOP, "raise", 300, 0),
            _act(VILLAIN, Street.PREFLOP, "fold", 0, 1),
        ],
        pot_total=pot_total,
    )


def test_routine_preflop_fold_excluded_from_preflop_pool():
    hands = [_routine_fold_hand(1)] + [_vpip_hand(i) for i in range(2, 12)]
    pools = triage_hands(hands, HERO)
    assert hands[0] not in pools["preflop"]


def test_vpip_hand_included_in_preflop_pool():
    hands = [_vpip_hand(i) for i in range(1, 5)]
    pools = triage_hands(hands, HERO)
    assert all(h in pools["preflop"] for h in hands)


def test_showdown_hand_never_dropped_from_reached_street():
    # Hero folds preflop with no VPIP action (would normally be excluded),
    # but the hand reached showdown, so it's globally notable and must be
    # included in every street pool it reached (just preflop here).
    showdown_hand = _hand(
        1, Street.PREFLOP, had_showdown=True,
        players=[_hp(HERO, "BTN"), _hp(VILLAIN, "BB")],
        actions=[
            _act(VILLAIN, Street.PREFLOP, "bigblind", 100, 0),
            _act(HERO, Street.PREFLOP, "fold", 0, 1),
        ],
        pot_total=100,
    )
    filler = [_vpip_hand(i) for i in range(2, 12)]
    pools = triage_hands([showdown_hand] + filler, HERO)
    assert showdown_hand in pools["preflop"]


def test_allin_hand_never_dropped():
    allin_hand = _hand(
        1, Street.FLOP, had_showdown=False,
        players=[_hp(HERO, "BTN"), _hp(VILLAIN, "BB")],
        actions=[
            _act(VILLAIN, Street.PREFLOP, "bigblind", 100, 0),
            _act(HERO, Street.PREFLOP, "fold", 0, 1),
        ],
        pot_total=100,
    )
    # Hero folded preflop with no VPIP action, but an all-in occurred on the
    # flop between other actions — simulate by adding a flop all-in action
    # from hero on a hand where hero reached the flop (adjust street_reached).
    allin_hand.street_reached = Street.FLOP
    allin_hand.actions.append(Action(game_player_id=VILLAIN, street=Street.FLOP, action="raise", amount=500, seq=2, stack_after=0))
    filler = [_vpip_hand(i) for i in range(2, 12)]
    pools = triage_hands([allin_hand] + filler, HERO)
    assert allin_hand in pools["flop"]


def test_large_pot_hand_never_dropped():
    # n=4, round(0.3*4)=1, so exactly the single largest pot is "notable" —
    # unambiguous regardless of tie-breaking among the 3 equal small pots.
    small_pots = [_routine_fold_hand(i) for i in range(1, 4)]
    big_pot = _routine_fold_hand(4)
    big_pot.pot_total = 100_000
    pools = triage_hands(small_pots + [big_pot], HERO)
    assert big_pot in pools["preflop"]
    # Non-notable routine folds are excluded.
    assert all(h not in pools["preflop"] for h in small_pots)


def test_pool_shrinks_relative_to_total_hands():
    # 12 routine folds (small, equal pots) + 5 vpip hands (much larger pots).
    # n=17, round(0.3*17)=5, exactly matching the vpip hands' count, so no
    # routine fold gets swept in as a "large pot" tie.
    hands = [_routine_fold_hand(i) for i in range(1, 13)] + [_vpip_hand(i, pot_total=1000) for i in range(13, 18)]
    pools = triage_hands(hands, HERO)
    assert len(pools["preflop"]) < len(hands)
    assert len(pools["preflop"]) == 5


def test_postflop_check_facing_bet_qualifies():
    hand = _hand(
        1, Street.FLOP, had_showdown=False,
        players=[_hp(HERO, "BB"), _hp(VILLAIN, "BTN")],
        actions=[
            _act(VILLAIN, Street.PREFLOP, "raise", 300, 0),
            _act(HERO, Street.PREFLOP, "call", 300, 1),
            _act(HERO, Street.FLOP, "check", 0, 2),
            _act(VILLAIN, Street.FLOP, "raise", 200, 3),
            _act(HERO, Street.FLOP, "fold", 0, 4),
        ],
        pot_total=700,
    )
    filler = [_vpip_hand(i) for i in range(2, 12)]
    pools = triage_hands([hand] + filler, HERO)
    assert hand in pools["flop"]
