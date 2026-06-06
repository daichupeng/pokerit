"""Win-rate-driven, parameterized bot.

The bot estimates its equity via Monte Carlo simulation (using PokerKit's
hand evaluator) and maps that equity plus style parameters onto a
fold / call / raise decision. Concrete styles (TAG, LAG, etc.) are just
preset parameter sets — see ``styles.py``.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass

from poker_engine.pk_adapter import mc_win_rate


@dataclass
class StyleParams:
    """Tunable knobs for a bot's playing style (all 0..1 unless noted)."""

    tightness: float = 0.5      # min win-rate to keep playing a non-free hand
    aggression: float = 0.5     # propensity to raise rather than call
    bluff_freq: float = 0.05    # chance to bluff-raise a weak hand
    raise_sizing: float = 0.6   # raise target as a fraction of the pot
    nb_simulation: int = 200    # Monte Carlo trials for the equity estimate

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


class StyleBot:
    """A bot whose behaviour is fully determined by its ``StyleParams``.

    Pass ``seed`` for reproducible games. ``style_name`` is recorded with the
    game so the record knows which archetype this seat was.

    The bot receives the PokerKit State at decision time via ``declare_action``,
    which returns ``("fold"|"call"|"raise", amount)``.
    """

    style_name: str = "custom"

    def __init__(self, params: StyleParams | None = None, seed: int | None = None):
        self.params = params or StyleParams()
        self._rng = random.Random(seed)
        self._n_players = 2  # updated when the hand starts

    # -- decision -----------------------------------------------------------

    def declare_action(
        self,
        valid_actions: list[dict],
        hole_card: list[str],
        round_state: dict,
    ) -> tuple[str, int]:
        """Decide an action given the PyPokerEngine-style ``valid_actions`` dict.

        ``valid_actions`` is ``[{"action": "fold", "amount": 0},
                                  {"action": "call", "amount": N},
                                  {"action": "raise", "amount": {"min": M, "max": X}}]``.
        """
        community = round_state.get("community_card", [])
        win_rate = mc_win_rate(
            hole=list(hole_card),
            board=list(community),
            n_active_players=self._n_players,
            n_sim=self.params.nb_simulation,
            rng=self._rng,
        )

        call = _find_action(valid_actions, "call")
        fold = _find_action(valid_actions, "fold")
        raise_action = _find_action(valid_actions, "raise")
        call_amount = call["amount"]

        can_check = call_amount == 0
        strong = win_rate >= self.params.tightness
        wants_to_raise = strong and self._rng.random() < self.params.aggression
        bluffing = (
            not strong and self._rng.random() < self.params.bluff_freq
        )

        if (wants_to_raise or bluffing) and _raise_is_available(raise_action):
            amount = self._raise_amount(raise_action, round_state)
            if amount is not None:
                return "raise", amount

        if strong or can_check:
            return "call", call_amount

        return fold["action"], fold["amount"]

    # -- helpers ------------------------------------------------------------

    def _raise_amount(self, raise_action: dict, round_state: dict) -> int | None:
        bounds = raise_action["amount"]
        lo, hi = bounds["min"], bounds["max"]
        if lo == -1 or hi == -1:
            return None
        pot = _pot_total(round_state)
        target = int(pot * self.params.raise_sizing)
        return max(lo, min(target, hi))

    def set_n_players(self, n: int) -> None:
        """Inform the bot of the table size for equity estimation."""
        self._n_players = max(2, n)


def _find_action(valid_actions: list[dict], name: str) -> dict:
    return next(a for a in valid_actions if a["action"] == name)


def _raise_is_available(raise_action: dict) -> bool:
    bounds = raise_action["amount"]
    return bounds["min"] != -1 and bounds["max"] != -1


def _pot_total(round_state: dict) -> int:
    pot = round_state.get("pot", {})
    main = pot.get("main", {}).get("amount", 0)
    side = sum(s.get("amount", 0) for s in pot.get("side", []))
    return main + side
