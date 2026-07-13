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


def make_pot_odds_tool() -> Callable[[int, int], dict]:
    def _pot_odds(pot_size: int, amount_to_call: int) -> dict:
        denominator = pot_size + amount_to_call
        required_equity_pct = round(100 * amount_to_call / denominator, 1) if denominator else 0.0
        return {"required_equity_pct": required_equity_pct}

    return _pot_odds


def make_hand_search_tool(db: Session, game_id: str, user: User) -> Callable[..., dict]:
    def _hand_search(
        street_reached: str | None = None,
        had_showdown: bool | None = None,
        hero_action_type: str | None = None,
        min_pot: int | None = None,
        max_pot: int | None = None,
    ) -> dict:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from poker_engine.db.models import Hand
        from poker_trainer.api.games import _hero_seat, _load_owned_game

        game = _load_owned_game(db, game_id, user)
        hero = _hero_seat(game)
        hero_gp_id = hero.id if hero else None

        hands = db.execute(
            select(Hand)
            .where(Hand.game_id == game.id)
            .options(selectinload(Hand.actions))
            .order_by(Hand.round_count)
        ).scalars().all()

        results = []
        for hand in hands:
            if street_reached is not None and hand.street_reached.value != street_reached:
                continue
            if had_showdown is not None and hand.had_showdown != had_showdown:
                continue
            if min_pot is not None and hand.pot_total < min_pot:
                continue
            if max_pot is not None and hand.pot_total > max_pot:
                continue
            if hero_action_type is not None:
                took_action = any(
                    a.game_player_id == hero_gp_id and a.action == hero_action_type
                    for a in hand.actions
                )
                if not took_action:
                    continue

            summary = (
                f"round {hand.round_count}: reached {hand.street_reached.value}, "
                f"pot {hand.pot_total}"
                + (", showdown" if hand.had_showdown else "")
            )
            results.append({"round_count": hand.round_count, "summary": summary})

        return {"hands": results}

    return _hand_search


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
