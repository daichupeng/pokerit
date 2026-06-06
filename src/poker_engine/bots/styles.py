"""Concrete bot archetypes as preset parameter sets over ``StyleBot``."""

from __future__ import annotations

from poker_engine.bots.base import StyleBot, StyleParams


class TAGBot(StyleBot):
    """Tight-aggressive: plays few hands, but bets/raises them hard."""

    style_name = "tag"

    def __init__(self, seed: int | None = None, **overrides: float):
        params = StyleParams(
            tightness=0.58,
            aggression=0.85,
            bluff_freq=0.07,
            raise_sizing=2.5,
            nb_simulation=10000,
        )
        _apply(params, overrides)
        super().__init__(params, seed=seed)


class LAGBot(StyleBot):
    """Loose-aggressive: plays many hands and applies maximum pressure."""

    style_name = "lag"

    def __init__(self, seed: int | None = None, **overrides: float):
        params = StyleParams(
            tightness=0.15,
            aggression=0.85,
            bluff_freq=0.20,
            raise_sizing=2.5,
            nb_simulation=10000
        )
        _apply(params, overrides)
        super().__init__(params, seed=seed)


class CallingStationBot(StyleBot):
    """Calling station: plays loose and almost never raises or folds."""

    style_name = "station"

    def __init__(self, seed: int | None = None, **overrides: float):
        params = StyleParams(
            tightness=0.10,
            aggression=0.10,
            bluff_freq=0.15,
            raise_sizing=0.4,
            nb_simulation=10000,
        )
        _apply(params, overrides)
        super().__init__(params, seed=seed)


class RockBot(StyleBot):
    """Rock: extremely tight, value-only, essentially no bluffing."""

    style_name = "rock"

    def __init__(self, seed: int | None = None, **overrides: float):
        params = StyleParams(
            tightness=0.70,
            aggression=0.55,
            bluff_freq=0.0,
            raise_sizing=0.6,
            nb_simulation=10000,
        )
        _apply(params, overrides)
        super().__init__(params, seed=seed)


# Maps the SeatKind value (also the recorded style name) to its bot class.
STYLE_REGISTRY: dict[str, type[StyleBot]] = {
    TAGBot.style_name: TAGBot,
    LAGBot.style_name: LAGBot,
    CallingStationBot.style_name: CallingStationBot,
    RockBot.style_name: RockBot,
}


def _apply(params: StyleParams, overrides: dict[str, float]) -> None:
    for key, value in overrides.items():
        if not hasattr(params, key):
            raise ValueError(f"Unknown style parameter: {key!r}")
        setattr(params, key, value)
