"""Relational schema for poker game records.

Modeled for a future online, multi-user platform:

  users          one row per *human* account (bots are transient)
  games          one row per game (a single ``start_poker`` run)
  game_players   every seat in a game + per-game stats; bots live only here
  hands          one row per hand, from the hero's perspective
  hand_players   per-hand participation; hidden-info rule lives here
  actions        one row per betting action (full replay)

The hidden-information rule: an opponent's ``hole_cards`` are only stored when
that seat reached showdown (its uuid appears in PyPokerEngine's ``hand_info``);
otherwise the column is NULL and ``revealed`` is False. The hero's cards are
always stored.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from poker_engine.db.base import Base


class Street(str, enum.Enum):
    PREFLOP = "preflop"
    FLOP = "flop"
    TURN = "turn"
    RIVER = "river"
    SHOWDOWN = "showdown"


class BotStyle(str, enum.Enum):
    TAG = "tag"
    LAG = "lag"
    STATION = "station"
    ROCK = "rock"


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class User(Base):
    """A human account. Prepares for the online, multi-user launch."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    games: Mapped[list["Game"]] = relationship(back_populates="hero", foreign_keys="Game.hero_user_id")


class Game(Base):
    """One game = one ``start_poker`` run."""

    __tablename__ = "games"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    small_blind: Mapped[int] = mapped_column(Integer)
    big_blind: Mapped[int] = mapped_column(Integer)
    ante: Mapped[int] = mapped_column(Integer, default=0)
    buy_in: Mapped[int] = mapped_column(Integer)
    max_round: Mapped[int] = mapped_column(Integer)
    hero_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    rule: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    hero: Mapped["User | None"] = relationship(back_populates="games", foreign_keys=[hero_user_id])
    players: Mapped[list["GamePlayer"]] = relationship(
        back_populates="game", cascade="all, delete-orphan"
    )
    hands: Mapped[list["Hand"]] = relationship(
        back_populates="game", cascade="all, delete-orphan"
    )


class GamePlayer(Base):
    """A seat in a game plus its per-game stats.

    Bots are transient and exist only as a row here (``is_bot=True`` with a
    ``bot_style`` and a ``bot_params`` snapshot). The human seat links to a
    ``users`` row via ``user_id``.
    """

    __tablename__ = "game_players"
    __table_args__ = (UniqueConstraint("game_id", "seat_index", name="uq_game_seat"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    game_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("games.id"))
    seat_index: Mapped[int] = mapped_column(Integer)
    display_name: Mapped[str] = mapped_column(String(100))
    engine_uuid: Mapped[str] = mapped_column(String(64), index=True)  # PyPokerEngine seat uuid

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False)
    bot_style: Mapped[BotStyle | None] = mapped_column(Enum(BotStyle), nullable=True)
    bot_params: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    starting_stack: Mapped[int] = mapped_column(Integer)
    final_stack: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Per-game stats (basic trainer metrics).
    hands_played: Mapped[int] = mapped_column(Integer, default=0)
    hands_won: Mapped[int] = mapped_column(Integer, default=0)
    total_winnings: Mapped[int] = mapped_column(Integer, default=0)  # net chips
    vpip_count: Mapped[int] = mapped_column(Integer, default=0)
    pfr_count: Mapped[int] = mapped_column(Integer, default=0)

    game: Mapped["Game"] = relationship(back_populates="players")
    hand_entries: Mapped[list["HandPlayer"]] = relationship(back_populates="game_player")
    actions: Mapped[list["Action"]] = relationship(back_populates="game_player")


class Hand(Base):
    """One hand/round, recorded from the hero's perspective."""

    __tablename__ = "hands"
    __table_args__ = (UniqueConstraint("game_id", "round_count", name="uq_game_round"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    game_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("games.id"))
    round_count: Mapped[int] = mapped_column(Integer)
    button_pos: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sb_pos: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bb_pos: Mapped[int | None] = mapped_column(Integer, nullable=True)
    street_reached: Mapped[Street] = mapped_column(Enum(Street))
    board: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    pot_total: Mapped[int] = mapped_column(Integer, default=0)
    had_showdown: Mapped[bool] = mapped_column(Boolean, default=False)
    # The round_state["pot"] structure exactly as PyPokerEngine returns it
    # (main + side pots with amounts and eligible uuids). Stored verbatim — the
    # engine computes side pots and chip distribution; we do not recompute.
    pot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    game: Mapped["Game"] = relationship(back_populates="hands")
    players: Mapped[list["HandPlayer"]] = relationship(
        back_populates="hand", cascade="all, delete-orphan"
    )
    actions: Mapped[list["Action"]] = relationship(
        back_populates="hand", cascade="all, delete-orphan"
    )


class HandPlayer(Base):
    """A player's participation in one hand.

    ``hole_cards`` is NULL unless the cards are known to the hero: always set
    for the hero, set for opponents only when revealed at showdown.
    """

    __tablename__ = "hand_players"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    hand_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("hands.id"))
    game_player_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("game_players.id")
    )
    hole_cards: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    revealed: Mapped[bool] = mapped_column(Boolean, default=False)
    is_winner: Mapped[bool] = mapped_column(Boolean, default=False)
    amount_won: Mapped[int] = mapped_column(Integer, default=0)
    starting_stack: Mapped[int | None] = mapped_column(Integer, nullable=True)
    final_stack: Mapped[int | None] = mapped_column(Integer, nullable=True)

    hand: Mapped["Hand"] = relationship(back_populates="players")
    game_player: Mapped["GamePlayer"] = relationship(back_populates="hand_entries")


class Action(Base):
    """A single betting action within a hand (full replay)."""

    __tablename__ = "actions"
    __table_args__ = (UniqueConstraint("hand_id", "seq", name="uq_hand_seq"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    hand_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("hands.id"), index=True)
    game_player_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("game_players.id")
    )
    street: Mapped[Street] = mapped_column(Enum(Street))
    action: Mapped[str] = mapped_column(String(20))  # fold/call/raise/smallblind/...
    amount: Mapped[int] = mapped_column(Integer, default=0)
    seq: Mapped[int] = mapped_column(Integer)  # order within the hand
    pot_after: Mapped[int | None] = mapped_column(Integer, nullable=True)

    hand: Mapped["Hand"] = relationship(back_populates="actions")
    game_player: Mapped["GamePlayer"] = relationship(back_populates="actions")
