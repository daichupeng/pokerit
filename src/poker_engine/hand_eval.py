"""Correct best-5-card selection, ranking, and labels for showdown.

PyPokerEngine's own ``HandEvaluator.eval_hand`` packs the player's two *hole*
card ranks into the score even when they are not part of the made hand, so it
can mis-rank kickers and — worse — produce false ties / false non-ties when
players share the board (e.g. both playing a straight on the board). We must
not rely on it for deciding who wins a pot.

This module implements a standard, fully-ordered 5-card evaluation:
``rank5`` returns a comparable tuple ``(category, tiebreakers...)`` so two hands
compare exactly as poker rules dictate (including the A-2-3-4-5 wheel). It is
used to choose each player's best 5 of 7 cards, to determine pot winners
(handling ties correctly), and to build a human-readable label.
"""

from __future__ import annotations

from collections import Counter
from itertools import combinations

from pypokerengine.utils.card_utils import gen_cards

# Hand categories, low → high.
HIGH_CARD, ONE_PAIR, TWO_PAIR, TRIPS, STRAIGHT, FLUSH, FULL_HOUSE, QUADS, STRAIGHT_FLUSH = range(9)

_RANK_NAME = {
    2: "Two", 3: "Three", 4: "Four", 5: "Five", 6: "Six", 7: "Seven",
    8: "Eight", 9: "Nine", 10: "Ten", 11: "Jack", 12: "Queen", 13: "King", 14: "Ace",
}
_RANK_PLURAL = {
    2: "Twos", 3: "Threes", 4: "Fours", 5: "Fives", 6: "Sixes", 7: "Sevens",
    8: "Eights", 9: "Nines", 10: "Tens", 11: "Jacks", 12: "Queens", 13: "Kings", 14: "Aces",
}


def _straight_high(ranks: set[int]) -> int | None:
    """Highest card of a 5-card straight contained in ``ranks`` (A-5 = 5), else None."""
    rs = set(ranks)
    if 14 in rs:
        rs = rs | {1}  # ace plays low
    for high in range(14, 4, -1):
        if all(r in rs for r in range(high, high - 5, -1)):
            return high
    return None


def rank5(cards) -> tuple:
    """Fully-ordered strength of exactly 5 Card objects, as a comparable tuple.

    Larger tuples are stronger hands. The first element is the category; the
    rest are rank tiebreakers ordered by importance.
    """
    ranks = sorted((c.rank for c in cards), reverse=True)
    suits = [c.suit for c in cards]
    counts = Counter(ranks)
    # groups: sort by (count, rank) descending so pairs/trips lead, then kickers.
    groups = sorted(counts.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
    ordered = [rank for rank, _cnt in groups]  # rank list, by group strength then rank
    is_flush = len(set(suits)) == 1
    sh = _straight_high(set(ranks))

    if is_flush and sh:
        return (STRAIGHT_FLUSH, sh)
    if groups[0][1] == 4:
        quad = groups[0][0]
        kicker = max(r for r in ranks if r != quad)
        return (QUADS, quad, kicker)
    if groups[0][1] == 3 and len(groups) > 1 and groups[1][1] >= 2:
        return (FULL_HOUSE, groups[0][0], groups[1][0])
    if is_flush:
        return (FLUSH, *ranks)  # all five, high→low
    if sh:
        return (STRAIGHT, sh)
    if groups[0][1] == 3:
        kickers = sorted((r for r in ranks if r != groups[0][0]), reverse=True)
        return (TRIPS, groups[0][0], *kickers)
    if groups[0][1] == 2 and len(groups) > 1 and groups[1][1] == 2:
        hi, lo = sorted([groups[0][0], groups[1][0]], reverse=True)
        kicker = max(r for r in ranks if r != hi and r != lo)
        return (TWO_PAIR, hi, lo, kicker)
    if groups[0][1] == 2:
        kickers = sorted((r for r in ranks if r != groups[0][0]), reverse=True)
        return (ONE_PAIR, groups[0][0], *kickers)
    return (HIGH_CARD, *ranks)


def _best_combo(cards):
    """The 5-card combo (Card objects) with the highest rank5, from >=5 cards."""
    return max(combinations(cards, 5), key=rank5)


def best_five(hole: list[str], community: list[str]) -> dict:
    """Best 5-card hand from 2 hole + up to 5 community cards.

    Returns ``{"cards": [<=5 card strings], "label": str}`` where ``cards`` is a
    subset of the inputs (so callers can match by equality for highlighting).
    """
    all_strs = list(hole) + list(community)
    if len(all_strs) < 5:
        return {"cards": all_strs, "label": _describe_partial(all_strs)}

    cards = gen_cards(all_strs)
    str_by_obj = {id(c): s for s, c in zip(all_strs, cards)}
    best = _best_combo(cards)
    return {"cards": [str_by_obj[id(c)] for c in best], "label": _label(best)}


def hand_strength(hole: list[str], community: list[str]) -> tuple:
    """Comparable strength of a player's best hand (for ranking/ties)."""
    cards = gen_cards(list(hole) + list(community))
    if len(cards) < 5:
        return (HIGH_CARD, *sorted((c.rank for c in cards), reverse=True))
    return rank5(_best_combo(cards))


def winners(player_cards: dict[str, list[str]], community: list[str]) -> list[str]:
    """Given ``{key: hole_cards}`` and the board, return the winning key(s).

    Ties (equal best hands) return multiple keys; this is the only correct
    source of split-pot information.
    """
    if not player_cards:
        return []
    scored = {k: hand_strength(h, community) for k, h in player_cards.items()}
    best = max(scored.values())
    return [k for k, s in scored.items() if s == best]


def _label(five) -> str:
    r = rank5(five)
    cat = r[0]
    if cat == STRAIGHT_FLUSH:
        return "Royal Flush" if r[1] == 14 else f"Straight Flush, {_RANK_NAME[r[1]]} high"
    if cat == QUADS:
        return f"Four of a Kind, {_RANK_PLURAL[r[1]]}"
    if cat == FULL_HOUSE:
        return f"Full House, {_RANK_PLURAL[r[1]]} full of {_RANK_PLURAL[r[2]]}"
    if cat == FLUSH:
        return f"Flush, {_RANK_NAME[r[1]]} high"
    if cat == STRAIGHT:
        return f"Straight, {_RANK_NAME[r[1]]} high"
    if cat == TRIPS:
        return f"Three of a Kind, {_RANK_PLURAL[r[1]]}"
    if cat == TWO_PAIR:
        return f"Two Pair, {_RANK_PLURAL[r[1]]} and {_RANK_PLURAL[r[2]]}"
    if cat == ONE_PAIR:
        return f"Pair of {_RANK_PLURAL[r[1]]}"
    return f"High Card, {_RANK_NAME[r[1]]}"


def _describe_partial(strs: list[str]) -> str:
    if not strs:
        return ""
    cards = gen_cards(strs)
    return f"High Card, {_RANK_NAME[max(c.rank for c in cards)]}"
