"""Per-street deterministic hand selection for the street-review agents.

Each street agent (preflop/flop/turn/river) only reviews hands where the hero
actually faced a decision on that street, plus any hand that is "globally
notable" regardless of whether hero had a decision there. No LLM, no
duplicated stat-counting logic — this reuses Phase 1's
``compute_hand_stats``/``_street_was_reached`` and scans ``Action`` rows
directly for the parts those don't already expose.
"""

from __future__ import annotations

from poker_engine.db.models import Action, Hand
from poker_engine.stats import _street_was_reached, compute_hand_stats

_STREETS = ("preflop", "flop", "turn", "river")
_POSTFLOP_STREETS = ("flop", "turn", "river")

# Top-30%-of-pots cutoff for the "large pot" notability rule.
_NOTABLE_POT_FRACTION = 0.3


def _street_value(street) -> str:
    return street.value if hasattr(street, "value") else str(street)


def _large_pot_hand_ids(hands: list[Hand]) -> set[int]:
    """id()s of the top-30%-by-pot_total hands in this game.

    Ranks by ``pot_total`` and takes exactly the top ``k`` hands (ties broken
    by original order) rather than a ``>=`` threshold comparison — a threshold
    would over-include whenever several hands tie at the boundary value.
    """
    if not hands:
        return set()
    k = max(1, round(_NOTABLE_POT_FRACTION * len(hands)))
    ranked = sorted(range(len(hands)), key=lambda i: hands[i].pot_total, reverse=True)
    return {id(hands[i]) for i in ranked[:k]}


def _hand_has_allin(hand: Hand) -> bool:
    """A call/raise that leaves the actor's stack at 0 — same heuristic as
    ``api/games.py::hand_detail``'s ``is_allin`` flag, reused here rather than
    reinvented."""
    return any(
        act.action in ("raise", "call") and act.amount > 0 and act.stack_after == 0
        for act in hand.actions
    )


def _is_notable(hand: Hand, large_pot_ids: set[int]) -> bool:
    return bool(hand.had_showdown) or _hand_has_allin(hand) or id(hand) in large_pot_ids


def _streets_reached(hand: Hand) -> list[str]:
    return [s for s in _STREETS if _street_was_reached(hand, s)]


def _hero_has_nonfold_action(hand: Hand, hero_gp_id, street: str) -> bool:
    return any(
        act.game_player_id == hero_gp_id and _street_value(act.street) == street and act.action != "fold"
        for act in hand.actions
    )


def triage_hands(hands: list[Hand], hero_gp_id) -> dict[str, list[Hand]]:
    """Return each street's pool of hands that qualify for its review agent.

    ``hands`` must have ``.actions``/``.players`` eager-loaded (same
    convention as ``stats.compute_game_stats``).
    """
    pools: dict[str, list[Hand]] = {street: [] for street in _STREETS}
    large_pot_ids = _large_pot_hand_ids(hands)

    for hand in hands:
        reached = _streets_reached(hand)
        notable = _is_notable(hand, large_pot_ids)
        counts = compute_hand_stats(hand, hero_gp_id)

        if "preflop" in reached:
            qualifies = counts.vpip_hands == 1 or counts.three_bet_opportunities == 1
            if qualifies or notable:
                pools["preflop"].append(hand)

        for street in _POSTFLOP_STREETS:
            if street not in reached:
                continue
            qualifies = _hero_has_nonfold_action(hand, hero_gp_id, street)
            if qualifies or notable:
                pools[street].append(hand)

    return pools
