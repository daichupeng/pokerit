"""Game configuration: blinds, buy-in, and the seat lineup.

Blinds follow PyPokerEngine's convention where the big blind is twice the
small blind, and the buy-in is the initial stack every seat starts with.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class SeatKind(str, Enum):
    """What occupies a seat at the table."""

    HUMAN = "human"
    TAG = "tag"
    LAG = "lag"
    STATION = "station"
    ROCK = "rock"

    @property
    def is_bot(self) -> bool:
        return self is not SeatKind.HUMAN


@dataclass
class SeatSpec:
    """One seat in the game.

    ``params`` overrides the bot style's default parameters (ignored for the
    human seat). ``name`` is the display name shown in the game and stored in
    the record.
    """

    name: str
    kind: SeatKind
    params: dict[str, float] = field(default_factory=dict)
    email: str | None = None  # only meaningful for the human seat

    @property
    def is_bot(self) -> bool:
        return self.kind.is_bot


@dataclass
class GameConfig:
    """Parameters for a single game (one ``start_poker`` run)."""

    small_blind: int
    buy_in: int
    seats: list[SeatSpec]
    max_round: int = 20
    ante: int = 0

    @property
    def big_blind(self) -> int:
        # PyPokerEngine derives BB as 2 * SB; we mirror that here for records.
        return self.small_blind * 2

    def validate(self) -> None:
        if len(self.seats) < 2:
            raise ValueError("A game needs at least 2 seats.")
        if self.small_blind <= 0:
            raise ValueError("small_blind must be positive.")
        if self.buy_in <= 0:
            raise ValueError("buy_in must be positive.")
        if self.ante < 0:
            raise ValueError("ante cannot be negative.")
        human_seats = [s for s in self.seats if not s.is_bot]
        if len(human_seats) > 1:
            raise ValueError("This step supports at most one human seat.")
        names = [s.name for s in self.seats]
        if len(names) != len(set(names)):
            raise ValueError("Seat names must be unique.")

    @property
    def hero_seat(self) -> SeatSpec | None:
        """The human (recording POV) seat, if any."""
        for seat in self.seats:
            if not seat.is_bot:
                return seat
        return None
