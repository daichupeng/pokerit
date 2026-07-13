"""Python implementations backing the tool schemas in ``schemas.py``.

Each ``make_*_tool`` factory binds ``db``/``game_id``/``user`` at construction
time (one tool instance per evaluation job) and returns a plain callable whose
signature matches only the LLM-visible parameters from the corresponding
schema. ``game_id`` and ``user`` are never accepted as arguments to the
returned callable, so the model has no way to supply or override them.
"""

from __future__ import annotations

from typing import Callable

from sqlalchemy.orm import Session

from poker_engine import pk_adapter, stats
from poker_engine.db.models import User


def make_hand_lookup_tool(db: Session, game_id: str, user: User) -> Callable[[int], dict]:
    def _hand_lookup(round_count: int) -> dict:
        from poker_trainer.api.games import _load_owned_game, hand_detail
        from shared_services.hand_formatter import format_hand

        game = _load_owned_game(db, game_id, user)
        detail = hand_detail(game_id, round_count, user, db)
        text = format_hand(detail, game.small_blind, game.big_blind)
        return {"context": text, "round_count": round_count}

    return _hand_lookup


def make_equity_calculator_tool() -> Callable[[list[str], list[str], int], dict]:
    def _equity_calculator(hole: list[str], board: list[str], n_active_players: int) -> dict:
        win_rate = pk_adapter.mc_win_rate(hole, board, n_active_players)
        return {
            "win_rate": win_rate,
            "note": "Equity vs random opponent hands, not a specific or hypothesized villain range.",
        }

    return _equity_calculator


def make_stats_query_tool(db: Session, game_id: str, user: User) -> Callable[..., dict]:
    def _stats_query(position: str | None = None, street: str | None = None) -> dict:
        from poker_trainer.api.games import _hero_seat, _load_owned_game

        game = _load_owned_game(db, game_id, user)
        hero = _hero_seat(game)
        counts = stats.compute_game_stats(db, game.id, hero.id) if hero else stats.RawStatCounts()
        display = stats.to_display(counts)

        if position:
            display = display["by_position"].get(position, stats.to_display(stats.RawStatCounts()))
            display.pop("by_position", None)

        if street:
            display = {
                "cbet": display["cbet"].get(street),
                "fold_to_cbet": display["fold_to_cbet"].get(street),
            }

        return display

    return _stats_query
