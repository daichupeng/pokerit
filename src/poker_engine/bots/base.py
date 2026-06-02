"""Win-rate-driven, parameterized bot.

The bot estimates its equity with a Monte Carlo simulation (reusing
PyPokerEngine's ``estimate_hole_card_win_rate``) and maps that equity plus a
handful of style parameters onto a fold / call / raise decision. Concrete
styles (TAG, LAG, etc.) are just preset parameter sets — see ``styles.py``.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass

from pypokerengine.players import BasePokerPlayer
from pypokerengine.utils.card_utils import estimate_hole_card_win_rate, gen_cards


@dataclass
class StyleParams:
    """Tunable knobs for a bot's playing style (all 0..1 unless noted)."""

    tightness: float = 0.5  # min win-rate to keep playing a non-free hand
    aggression: float = 0.5  # propensity to raise rather than call
    bluff_freq: float = 0.05  # chance to bluff-raise a weak hand
    raise_sizing: float = 0.6  # raise target as a fraction of the pot
    nb_simulation: int = 200  # Monte Carlo trials for the equity estimate

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


class StyleBot(BasePokerPlayer):
    """A bot whose behaviour is fully determined by its ``StyleParams``.

    Pass ``seed`` for reproducible games. ``style_name`` is recorded with the
    game so the record knows which archetype this seat was.
    """

    style_name: str = "custom"

    def __init__(self, params: StyleParams | None = None, seed: int | None = None):
        super().__init__()
        self.params = params or StyleParams()
        self._rng = random.Random(seed)
        self._nb_player = 2  # refreshed at game start

    # -- decision -----------------------------------------------------------

    def declare_action(self, valid_actions, hole_card, round_state):
        win_rate = self._estimate_win_rate(hole_card, round_state)

        call = _find_action(valid_actions, "call")
        fold = _find_action(valid_actions, "fold")
        raise_action = _find_action(valid_actions, "raise")
        call_amount = call["amount"]

        # A free look (check) is never worse than folding.
        can_check = call_amount == 0

        strong = win_rate >= self.params.tightness
        wants_to_raise = strong and self._rng.random() < self.params.aggression
        bluffing = (
            not strong and not can_check and self._rng.random() < self.params.bluff_freq
        )

        if (wants_to_raise or bluffing) and _raise_is_available(raise_action):
            amount = self._raise_amount(raise_action, round_state)
            if amount is not None:
                return "raise", amount

        if strong or can_check:
            return "call", call_amount

        return fold["action"], fold["amount"]

    # -- helpers ------------------------------------------------------------

    def _estimate_win_rate(self, hole_card, round_state) -> float:
        community = round_state.get("community_card", [])
        return estimate_hole_card_win_rate(
            nb_simulation=self.params.nb_simulation,
            nb_player=self._nb_player,
            hole_card=gen_cards(hole_card),
            community_card=gen_cards(community),
        )

    def _raise_amount(self, raise_action, round_state) -> int | None:
        bounds = raise_action["amount"]
        lo, hi = bounds["min"], bounds["max"]
        if lo == -1 or hi == -1:  # engine signals "raise not allowed"
            return None
        pot = _pot_total(round_state)
        target = int(pot * self.params.raise_sizing)
        return max(lo, min(target, hi))

    # -- lifecycle callbacks ------------------------------------------------

    def receive_game_start_message(self, game_info):
        self._nb_player = game_info.get("player_num", self._nb_player)

    def receive_round_start_message(self, round_count, hole_card, seats):
        pass

    def receive_street_start_message(self, street, round_state):
        pass

    def receive_game_update_message(self, action, round_state):
        pass

    def receive_round_result_message(self, winners, hand_info, round_state):
        pass


def _find_action(valid_actions, name):
    return next(a for a in valid_actions if a["action"] == name)


def _raise_is_available(raise_action) -> bool:
    bounds = raise_action["amount"]
    return bounds["min"] != -1 and bounds["max"] != -1


def _pot_total(round_state) -> int:
    pot = round_state.get("pot", {})
    main = pot.get("main", {}).get("amount", 0)
    side = sum(s.get("amount", 0) for s in pot.get("side", []))
    return main + side
