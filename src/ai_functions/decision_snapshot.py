"""Point-in-time decision inputs shared by review agents.

Snapshots intentionally omit later actions, later board cards, showdown cards,
and results. They separate engine facts, explicit assumptions, deterministic
calculations, simulation metadata, and versioned range references.
"""

from __future__ import annotations

from typing import Any

from ai_functions.preflop_ranges import get_range_pack, normalize_starting_hand
from poker_engine.db.models import Game, Hand

SCHEMA_VERSION = "decision_snapshot.v1"


def _style_value(player) -> str | None:
    style = getattr(player, "bot_style", None)
    return getattr(style, "value", style) if style else None


def _matching_pack_id(game: Game, hand: Hand, hero_stack_bb: float) -> str | None:
    players = hand.active_player_count or sum(
        1 for hp in hand.players if (hp.starting_stack or 0) > 0
    )
    fmt = (game.game_format or "cash").lower()
    if fmt == "cash" and 98 <= hero_stack_bb <= 102 and players in (6, 8):
        return f"cash_{players}max_100bb_v1"
    if fmt in {"mtt", "tournament"} and game.ante_type == "big_blind" and 38 <= hero_stack_bb <= 42 and players in (6, 8):
        return f"mtt_bba_{players}max_40bb_v1"
    return None


def build_decision_snapshots(game: Game, hand: Hand, hero_gp_id, street: str) -> list[dict[str, Any]]:
    """Return one future-clipped snapshot per hero decision on ``street``."""
    from poker_trainer.api.games import _build_hand_detail

    detail = _build_hand_detail(game, hand, hero_gp_id)
    street_data = (detail.get("streets") or {}).get(street)
    if not street_data:
        return []

    hero = next((p for p in detail.get("players", []) if p.get("is_hero")), {})
    hero_hand = normalize_starting_hand("".join(hero.get("hole_cards") or []))
    player_by_name = {gp.display_name: gp for gp in game.players}
    actions = street_data.get("actions") or []
    snapshots: list[dict[str, Any]] = []
    for action_index, action in enumerate(actions):
        if not action.get("is_hero"):
            continue
        prior = actions[:action_index]
        action_history = []
        for item in prior:
            actor = player_by_name.get(item.get("name"))
            action_history.append({
                "actor": "Hero" if item.get("is_hero") else item.get("name"),
                "position": item.get("position"),
                "action": item.get("action"),
                "amount": item.get("amount"),
                "bot_style": _style_value(actor) if actor and actor.is_bot else None,
            })

        hero_stack_total = (action.get("stack_before") or 0) + (action.get("street_bet") or 0)
        hero_stack_bb = round(hero_stack_total / game.big_blind, 1) if game.big_blind else 0
        evidence_sources = [
            {"type": "engine_state", "label": "Recorded hand state before this decision"},
            {"type": "deterministic_calculation", "label": "Pot, stack and size arithmetic from recorded chips"},
            {"type": "heuristic_inference", "label": "Coach range and strategy reasoning; no solver node was run"},
        ]
        styles = sorted({
            _style_value(gp) for gp in game.players if gp.is_bot and _style_value(gp)
        })
        if styles:
            evidence_sources.append({
                "type": "simulation_metadata",
                "label": "Configured bot styles (not a solver result or observed population read)",
                "styles": styles,
            })

        # The first voluntary preflop decision can use an exact RFI chart pack
        # only when format, live player count, ante and stack all match.
        voluntary_before = [a for a in prior if a.get("action") not in {"smallblind", "bigblind", "ante"}]
        if street == "preflop" and not voluntary_before and hero_hand:
            pack = get_range_pack(_matching_pack_id(game, hand, hero_stack_bb) or "")
            decision = pack.decision(hero.get("position", ""), hero_hand) if pack else None
            if decision:
                evidence_sources.append(decision.evidence_source)

        snapshot = {
            "schema_version": SCHEMA_VERSION,
            "decision_id": f"{hand.round_count}:{street}:{action_index}",
            "round_count": hand.round_count,
            "street": street,
            "known_facts": {
                "format": game.game_format,
                "scenario": game.scenario,
                "players_dealt": detail.get("active_player_count"),
                "blinds": {"small": game.small_blind, "big": game.big_blind},
                "ante": {"type": game.ante_type, "amount": game.ante},
                "hero_position": hero.get("position"),
                "hero_cards": hero.get("hole_cards"),
                "board_visible": street_data.get("board") or [],
                "pot_before_action": action.get("pot_before"),
                "hero_stack_before": action.get("stack_before"),
                "hero_street_bet_before": action.get("street_bet"),
                "action_history_before": action_history,
                "hero_action": {
                    "action": action.get("action"),
                    "amount": action.get("amount"),
                    "all_in": action.get("is_allin", False),
                },
            },
            "explicit_assumptions": [],
            "derived_calculations": {"hero_stack_bb_at_decision": hero_stack_bb},
            "evidence_sources": evidence_sources,
        }
        snapshots.append(snapshot)
    return snapshots
