"""Render an already-loaded ``Hand`` ORM object as coach-context text.

Goes straight from loaded ``Game``/``Hand`` objects to ``format_hand()`` via
``api.games._build_hand_detail`` — avoids the N redundant DB round-trips per
street-agent batch that calling the ``hand_detail()`` endpoint function per
hand would cost.
"""

from __future__ import annotations

from poker_engine.db.models import Game, Hand
from shared_services.hand_formatter import format_hand


def build_hand_text(game: Game, hand: Hand, hero_gp_id) -> str:
    from poker_trainer.api.games import _build_hand_detail

    detail = _build_hand_detail(game, hand, hero_gp_id)
    return format_hand(detail, game.small_blind, game.big_blind)
