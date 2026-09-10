"""Deterministic poker facts shared by coaching and game review.

This module deliberately stops at code-owned facts.  Draw counts describe the
remaining cards of a rank or suit; they are not clean outs and they do not imply
equity against an opponent range.
"""

from __future__ import annotations

from collections import Counter
import re
from typing import Any

from poker_engine.pk_adapter import best_five, hand_strength_key

_HERO_ONLY_PAIR_RE = re.compile(
    r"(?is)(?:你(?:的牌)?只有.{0,12}(?:一对|pair)|you\s+(?:only|just)\s+have.{0,12}pair|hero\s+(?:only|just)\s+has.{0,12}pair)"
)
_RANK_VALUE = {
    "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7,
    "8": 8, "9": 9, "T": 10, "J": 11, "Q": 12, "K": 13, "A": 14,
}
_CATEGORY_NAMES = (
    "high_card",
    "one_pair",
    "two_pair",
    "three_of_a_kind",
    "straight",
    "flush",
    "full_house",
    "four_of_a_kind",
    "straight_flush",
)
_SUIT_NAMES = {"c": "clubs", "d": "diamonds", "h": "hearts", "s": "spades"}


def _pair_context(hole: list[str], board: list[str], category: str) -> str | None:
    if category != "one_pair" or len(hole) != 2 or not board:
        return None

    hole_ranks = [card[0] for card in hole]
    board_ranks = [card[0] for card in board]
    if hole_ranks[0] == hole_ranks[1] and hole_ranks[0] not in board_ranks:
        pair_value = _RANK_VALUE[hole_ranks[0]]
        return "overpair" if pair_value > max(_RANK_VALUE[r] for r in board_ranks) else "pocket_pair_below_top_card"

    matched = {rank for rank in hole_ranks if rank in board_ranks}
    if matched:
        paired_rank = max(matched, key=_RANK_VALUE.__getitem__)
        distinct_board = sorted(set(board_ranks), key=_RANK_VALUE.__getitem__, reverse=True)
        ordinal = distinct_board.index(paired_rank)
        labels = ("top_pair", "second_pair", "third_pair", "fourth_pair", "fifth_pair")
        return labels[min(ordinal, len(labels) - 1)]

    if any(count >= 2 for count in Counter(board_ranks).values()):
        return "board_pair"
    return None


def _draw_structures(hole: list[str], board: list[str], category: str) -> list[dict[str, Any]]:
    if len(board) not in (3, 4):
        return []

    cards = hole + board
    draws: list[dict[str, Any]] = []
    suit_counts = Counter(card[1] for card in cards)
    if category not in {"flush", "straight_flush"}:
        for suit, count in sorted(suit_counts.items()):
            if count == 4 and any(card[1] == suit for card in hole):
                draws.append({
                    "type": "flush_draw",
                    "suit": _SUIT_NAMES[suit],
                    "cards_remaining_in_suit": 13 - count,
                })

    if category not in {"straight", "straight_flush"}:
        ranks = {_RANK_VALUE[card[0]] for card in cards}
        hole_ranks = {_RANK_VALUE[card[0]] for card in hole}
        windows = [set(range(high - 4, high + 1)) for high in range(5, 15)]
        windows[0] = {14, 2, 3, 4, 5}
        missing: set[int] = set()
        for window in windows:
            present = ranks & window
            if len(present) == 4 and hole_ranks & window:
                missing.update(window - present)
        if missing:
            rank_codes = {value: code for code, value in _RANK_VALUE.items()}
            draws.append({
                "type": "straight_draw",
                "missing_ranks": [rank_codes[value] for value in sorted(missing, reverse=True)],
                "cards_remaining_per_rank": 4,
            })
    return draws


def build_hand_facts(hole: list[str] | None, board: list[str] | None) -> dict[str, Any]:
    """Return code-owned made-hand, best-five, pair, and draw facts."""
    hole_cards = list(hole or [])
    board_cards = list(board or [])
    if len(hole_cards) != 2 or len(hole_cards) + len(board_cards) < 5:
        return {
            "category": "preflop" if not board_cards else "incomplete_board",
            "made_hand_label": "Preflop holding" if not board_cards else "Incomplete board",
            "best_five": [],
            "rank_key": [],
            "pair_context": None,
            "draws": [],
            "equity_calculation": None,
        }

    rank_key = tuple(hand_strength_key(hole_cards, board_cards))
    category = _CATEGORY_NAMES[rank_key[0]]
    best = best_five(hole_cards, board_cards)
    return {
        "category": category,
        "made_hand_label": best.get("label", ""),
        "best_five": list(best.get("cards") or []),
        "rank_key": list(rank_key),
        "pair_context": _pair_context(hole_cards, board_cards, category),
        "draws": _draw_structures(hole_cards, board_cards, category),
        # Populated only for a concrete calculation turn. Numeric equity stays
        # unsupported until explicit calculator provenance is available.
        "equity_calculation": None,
    }


def format_hand_facts(facts: dict[str, Any]) -> list[str]:
    """Format deterministic facts as a compact prompt block."""
    if facts.get("category") in {"preflop", "incomplete_board"}:
        return []
    pair_context = facts.get("pair_context")
    context = f"; pair context: {pair_context}" if pair_context else ""
    lines = [
        "Deterministic hand facts (authoritative; no opponent range assumed):",
        f"- Made hand: {facts.get('made_hand_label')} (category: {facts.get('category')}{context})",
        "- Best five: " + " ".join(facts.get("best_five") or []),
    ]
    draw_parts = []
    for draw in facts.get("draws") or []:
        if draw.get("type") == "flush_draw":
            draw_parts.append(
                f"flush draw in {draw.get('suit')} "
                f"({draw.get('cards_remaining_in_suit')} unseen cards of that suit)"
            )
        elif draw.get("type") == "straight_draw":
            draw_parts.append(
                "straight draw missing rank(s) " + ", ".join(draw.get("missing_ranks") or [])
            )
    lines.append("- Draw structures: " + ("; ".join(draw_parts) if draw_parts else "none"))
    lines.append(
        "- Draw counts above are structural cards remaining, not clean outs or equity. "
        "No numeric equity has been calculated."
    )
    return lines


def normalize_action_rows(
    actions: list[dict[str, Any]] | None,
    street: str,
    initial_commitments: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Copy action rows and add canonical action/payment semantics.

    PokerKit records checks as ``CALL 0`` and the first postflop bet as
    ``RAISE``.  Raw fields remain untouched; consumers use the added canonical
    fields so persistence and showdown rules keep their original semantics.
    """
    invested = dict(initial_commitments or {})
    current_wager = max(invested.values(), default=0)
    normalized: list[dict[str, Any]] = []

    for original in actions or []:
        row = dict(original)
        actor = str(row.get("uuid") or row.get("name") or "")
        raw_action = str(row.get("action") or "").lower()
        raw_amount = int(row.get("amount") or 0)
        before = int(row.get("street_bet") if row.get("street_bet") is not None else invested.get(actor, 0))

        if raw_action == "call" and raw_amount == 0:
            canonical = "check"
        elif raw_action == "raise" and street != "preflop" and current_wager == 0:
            canonical = "bet"
        else:
            canonical = raw_action

        authoritative_paid = "chips_put_in" in row and row.get("stack_after") is not None
        if authoritative_paid:
            amount_paid = max(0, int(row.get("chips_put_in") or 0))
        elif canonical in {"call", "check"}:
            amount_paid = max(0, raw_amount)
        elif canonical in {"bet", "raise"}:
            amount_paid = max(0, raw_amount - before)
        elif canonical in {"smallblind", "bigblind", "ante"}:
            amount_paid = max(0, raw_amount)
        else:
            amount_paid = 0

        amount_to = before + amount_paid
        if canonical in {"bet", "raise"} and not authoritative_paid:
            amount_to = max(before, raw_amount)
        if canonical in {"fold", "check"}:
            amount_to = before

        row.update({
            "raw_action": raw_action,
            "canonical_action": canonical,
            "amount_paid": amount_paid,
            "amount_to": amount_to,
        })
        normalized.append(row)

        if canonical not in {"fold", "ante"}:
            invested[actor] = amount_to
        if canonical in {"bet", "raise"}:
            current_wager = max(current_wager, amount_to)

    return normalized


def meets_slowplay_strength_floor(hand_facts: dict[str, Any]) -> bool:
    """Conservative necessary condition for accepting ``slowplay_risk``."""
    category = hand_facts.get("category")
    if category == "one_pair":
        return hand_facts.get("pair_context") == "overpair"
    return category in {
        "two_pair", "three_of_a_kind", "straight", "flush",
        "full_house", "four_of_a_kind", "straight_flush",
    }


def hand_description_conflicts(text: str, hand_facts: dict[str, Any] | None) -> bool:
    """Detect a conservative, explicit downgrade of hero's made hand."""
    if not hand_facts:
        return False
    stronger_than_pair = hand_facts.get("category") in {
        "two_pair", "three_of_a_kind", "straight", "flush", "full_house",
        "four_of_a_kind", "straight_flush",
    }
    return bool(stronger_than_pair and _HERO_ONLY_PAIR_RE.search(text))
