"""Exact heads-up Hold'em equity against explicit weighted range assumptions."""

from __future__ import annotations

from itertools import combinations, product
import math
import re
from typing import Any

from poker_engine.pk_adapter import ALL_52, hand_strength_key

CALCULATOR_NAME = "Pokerit Range Equity"
CALCULATOR_VERSION = "range_equity.v1"
MAX_SCENARIOS = 3
MAX_RANGE_ITEMS = 60
MAX_ENUMERATED_OUTCOMES = 500_000

_SUITS = "cdhs"
_CARD_RE = re.compile(r"^[2-9TJQKA][cdhs]$", re.IGNORECASE)
_CLASS_RE = re.compile(r"^([2-9TJQKA])([2-9TJQKA])([so]?)$", re.IGNORECASE)
_MISLEADING_LABEL_RE = re.compile(
    r"(?i)solver|pokerai|preflop\s+strategy|\bgto\b"
)


def _card(value: Any) -> str:
    card = str(value or "").strip()
    if not _CARD_RE.fullmatch(card):
        raise ValueError(f"invalid_card:{card}")
    return card[0].upper() + card[1].lower()


def _known_cards(hole: list[str], board: list[str]) -> tuple[list[str], list[str]]:
    hero = [_card(value) for value in hole]
    community = [_card(value) for value in board]
    if len(hero) != 2:
        raise ValueError("hero_must_have_two_cards")
    if len(community) not in (3, 4, 5):
        raise ValueError("postflop_board_required")
    if len(set(hero + community)) != len(hero) + len(community):
        raise ValueError("duplicate_known_card")
    return hero, community


def _range_token_combos(value: Any) -> set[tuple[str, str]]:
    token = str(value or "").strip()
    if len(token) == 4 and _CARD_RE.fullmatch(token[:2]) and _CARD_RE.fullmatch(token[2:]):
        first, second = _card(token[:2]), _card(token[2:])
        if first == second:
            raise ValueError(f"duplicate_combo_card:{token}")
        return {tuple(sorted((first, second)))}

    match = _CLASS_RE.fullmatch(token)
    if match is None:
        raise ValueError(f"unsupported_range_token:{token}")
    first_rank, second_rank, shape = (
        match.group(1).upper(), match.group(2).upper(), match.group(3).lower()
    )
    if first_rank == second_rank:
        if shape:
            raise ValueError(f"pair_cannot_have_suit_suffix:{token}")
        return {
            tuple(sorted((first_rank + suit_a, first_rank + suit_b)))
            for suit_a, suit_b in combinations(_SUITS, 2)
        }

    if shape == "s":
        suit_pairs = [(suit, suit) for suit in _SUITS]
    elif shape == "o":
        suit_pairs = [(a, b) for a, b in product(_SUITS, repeat=2) if a != b]
    else:
        suit_pairs = list(product(_SUITS, repeat=2))
    return {
        tuple(sorted((first_rank + suit_a, second_rank + suit_b)))
        for suit_a, suit_b in suit_pairs
    }


def _prepare_scenario(
    scenario: dict[str, Any], known: set[str], used_labels: set[str],
) -> dict[str, Any]:
    if not isinstance(scenario, dict):
        raise ValueError("invalid_scenario")
    label = str(scenario.get("label") or "").strip()
    if (
        not label
        or len(label) > 60
        or label in used_labels
        or "\n" in label
        or "\r" in label
        or _MISLEADING_LABEL_RE.search(label)
    ):
        raise ValueError("invalid_or_duplicate_scenario_label")
    used_labels.add(label)

    items = scenario.get("hands")
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_RANGE_ITEMS:
        raise ValueError("invalid_range_item_count")

    combos: dict[tuple[str, str], float] = {}
    requested: list[dict[str, Any]] = []
    blocked_combo_count = 0
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("invalid_range_item")
        token = str(item.get("hand") or "").strip()
        try:
            weight = float(item.get("weight", 1.0))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid_weight:{token}") from exc
        if not math.isfinite(weight) or not 0 < weight <= 1:
            raise ValueError(f"invalid_weight:{token}")

        expanded = _range_token_combos(token)
        legal = {combo for combo in expanded if known.isdisjoint(combo)}
        blocked_combo_count += len(expanded) - len(legal)
        overlap = set(combos) & legal
        if overlap:
            raise ValueError(f"overlapping_range_tokens:{token}")
        combos.update({combo: weight for combo in legal})
        requested.append({"hand": token, "weight": weight})

    if not combos:
        raise ValueError("range_empty_after_blockers")
    return {
        "label": label,
        "requested_range": requested,
        "combos": combos,
        "blocked_combo_count": blocked_combo_count,
    }


def _pct(numerator: float, denominator: float) -> float:
    return round(100 * numerator / denominator, 2) if denominator else 0.0


def calculate_range_equity(
    hole: list[str],
    board: list[str],
    villain_ranges: list[dict[str, Any]],
) -> dict[str, Any]:
    """Enumerate exact equity for one villain under 1-3 explicit range scenarios."""
    calculator = {
        "name": CALCULATOR_NAME,
        "version": CALCULATOR_VERSION,
        "method": "exact_enumeration",
    }
    try:
        hero, community = _known_cards(hole, board)
        if not isinstance(villain_ranges, list) or not 1 <= len(villain_ranges) <= MAX_SCENARIOS:
            raise ValueError("invalid_scenario_count")
        known = set(hero + community)
        used_labels: set[str] = set()
        scenarios = [
            _prepare_scenario(scenario, known, used_labels)
            for scenario in villain_ranges
        ]
        board_needed = 5 - len(community)
        runouts_per_combo = math.comb(52 - len(known) - 2, board_needed)
        estimated_outcomes = runouts_per_combo * sum(
            len(scenario["combos"]) for scenario in scenarios
        )
        if estimated_outcomes > MAX_ENUMERATED_OUTCOMES:
            raise ValueError(
                f"calculation_too_large:{estimated_outcomes}>{MAX_ENUMERATED_OUTCOMES}"
            )
    except ValueError as exc:
        return {"status": "error", "error": str(exc), "calculator": calculator}

    base_deck = [card for card in ALL_52 if card not in known]
    runouts = []
    for runout in combinations(base_deck, board_needed):
        final_board = community + list(runout)
        runouts.append((runout, final_board, hand_strength_key(hero, final_board)))

    results: list[dict[str, Any]] = []
    total_outcomes = 0
    for scenario in scenarios:
        wins = ties = losses = total_weight = 0.0
        outcomes_evaluated = 0
        for combo, weight in scenario["combos"].items():
            villain_cards = list(combo)
            combo_set = set(combo)
            for runout, final_board, hero_score in runouts:
                if not combo_set.isdisjoint(runout):
                    continue
                villain_score = hand_strength_key(villain_cards, final_board)
                outcomes_evaluated += 1
                total_weight += weight
                if hero_score > villain_score:
                    wins += weight
                elif hero_score == villain_score:
                    ties += weight
                else:
                    losses += weight

        equity = _pct(wins + ties / 2, total_weight)
        results.append({
            "label": scenario["label"],
            "equity_pct": equity,
            "win_pct": _pct(wins, total_weight),
            "tie_pct": _pct(ties, total_weight),
            "loss_pct": _pct(losses, total_weight),
            "combo_count": len(scenario["combos"]),
            "blocked_combo_count": scenario["blocked_combo_count"],
            "outcomes_evaluated": outcomes_evaluated,
            "requested_range": scenario["requested_range"],
        })
        total_outcomes += outcomes_evaluated

    equities = [result["equity_pct"] for result in results]
    return {
        "status": "ok",
        "calculator": {
            **calculator,
            "enumerated_outcomes": total_outcomes,
            "heads_up_only": True,
        },
        "hero_cards": hero,
        "board": community,
        "range_definition_source": "explicit_tool_input_assumption",
        "scenarios": results,
        "scenario_equity_interval_pct": {
            "low": min(equities),
            "high": max(equities),
            "basis": "minimum_and_maximum_across_supplied_range_scenarios",
        },
        "provenance": {
            "calculator": CALCULATOR_NAME,
            "version": CALCULATOR_VERSION,
            "method": "exact_enumeration",
            "range_assumptions_are_recorded_facts": False,
            "calculator_consumed_preflop_strategy_api": False,
        },
    }
