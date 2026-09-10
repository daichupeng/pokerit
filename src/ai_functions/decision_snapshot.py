"""Point-in-time decision inputs shared by review agents.

Snapshots intentionally omit later actions, later board cards, showdown cards,
and results. They separate engine facts, explicit assumptions, deterministic
calculations, simulation metadata, and versioned range references.
"""

from __future__ import annotations

from typing import Any

from ai_functions.preflop_ranges import get_range_pack, normalize_starting_hand
from poker_engine.db.models import Game, Hand
from shared_services.decision_facts import build_hand_facts, normalize_action_rows
from shared_services.hand_formatter import pos_label

SCHEMA_VERSION = "decision_snapshot.v2"


def _style_value(player) -> str | None:
    style = getattr(player, "bot_style", None)
    return getattr(style, "value", style) if style else None


def _matching_pack_id(
    game_format: str,
    players: int,
    hero_stack_bb: float,
    ante_type: str,
    ante_bb: float,
) -> str | None:
    fmt = (game_format or "cash").lower()
    if (
        fmt == "cash"
        and ante_type == "none"
        and ante_bb == 0
        and 98 <= hero_stack_bb <= 102
        and players in (6, 8)
    ):
        return f"cash_{players}max_100bb_v1"
    if (
        fmt in {"mtt", "tournament"}
        and ante_type == "big_blind"
        and ante_bb == 1
        and 38 <= hero_stack_bb <= 42
        and players in (6, 8)
    ):
        return f"mtt_bba_{players}max_40bb_v1"
    return None


def _base_evidence_sources(styles: list[str] | None = None) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = [
        {"type": "engine_state", "label": "Recorded hand state before this decision"},
        {"type": "deterministic_calculation", "label": "Pot, stack and size arithmetic from recorded chips"},
        {"type": "heuristic_inference", "label": "Coach range and strategy reasoning; no live solver node was run"},
    ]
    if styles:
        sources.append({
            "type": "simulation_metadata",
            "label": "Configured bot styles (not a solver result or observed population read)",
            "styles": sorted(set(styles)),
        })
    return sources


def attach_local_range_evidence(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Attach an exact matching local RFI pack and fail closed elsewhere."""
    if snapshot.get("street") != "preflop":
        return snapshot
    facts = snapshot.get("known_facts") or {}
    history = facts.get("action_history_before") or []
    entered_before = any(
        item.get("action") == "raise"
        or (item.get("action") == "call" and (item.get("amount_paid") or 0) > 0)
        for item in history
    )
    hand = normalize_starting_hand("".join(facts.get("hero_cards") or []))
    if entered_before or hand is None:
        return snapshot

    blinds = facts.get("blinds") or {}
    big_blind = float(blinds.get("big") or 0)
    ante = facts.get("ante") or {}
    pack_id = _matching_pack_id(
        str(facts.get("format") or ""),
        int(facts.get("players_dealt") or 0),
        float((snapshot.get("derived_calculations") or {}).get("hero_stack_bb_at_decision") or 0),
        str(ante.get("type") or "none"),
        float(ante.get("amount") or 0) / big_blind if big_blind else 0,
    )
    pack = get_range_pack(pack_id or "")
    decision = pack.decision(str(facts.get("hero_position") or ""), hand) if pack else None
    if decision:
        snapshot.setdefault("evidence_sources", []).append({
            **decision.evidence_source,
            "decision_id": snapshot.get("decision_id"),
            "hand_class": decision.hand,
            "position": decision.position,
            "acceptable_actions": list(decision.actions),
            "mixed": decision.mixed,
            "exact_frequencies_available": False,
        })
    return snapshot


def build_live_preflop_snapshot(
    round_state: dict[str, Any], hero_uuid: str,
) -> dict[str, Any] | None:
    """Build the current Hero preflop decision without exposing private cards."""
    if round_state.get("street") != "preflop":
        return None
    seats = round_state.get("seats") or []
    active_seats = list(round_state.get("active_seats") or [])
    next_player = round_state.get("next_player")
    if not isinstance(next_player, int) or not 0 <= next_player < len(seats):
        return None
    if seats[next_player].get("uuid") != hero_uuid:
        return None

    button = round_state.get("dealer_btn")
    positions = {
        seat.get("uuid"): pos_label(index, button, active_seats)
        for index, seat in enumerate(seats)
        if index in active_seats
    }
    hero_seat = next((seat for seat in seats if seat.get("uuid") == hero_uuid), None)
    hero_cards = (round_state.get("hole_cards_by_uuid") or {}).get(hero_uuid)
    if hero_seat is None or not hero_cards:
        return None

    small_blind = int(round_state.get("small_blind_amount") or 0)
    big_blind = int(round_state.get("big_blind_amount") or small_blind * 2)
    commitments = {
        uuid_: small_blind if position == "SB" else big_blind
        for uuid_, position in positions.items()
        if position in {"SB", "BB"}
    }
    normalized = normalize_action_rows(
        (round_state.get("action_histories") or {}).get("preflop") or [],
        "preflop",
        commitments,
    )
    styles: list[str] = []
    seat_by_uuid = {seat.get("uuid"): seat for seat in seats}
    action_history: list[dict[str, Any]] = []
    for item in normalized:
        actor_uuid = item.get("uuid")
        seat = seat_by_uuid.get(actor_uuid) or {}
        style = seat.get("bot_style")
        if style:
            styles.append(style)
        action_history.append({
            "actor": "Hero" if actor_uuid == hero_uuid else seat.get("name"),
            "position": positions.get(actor_uuid),
            "action": item.get("canonical_action") or item.get("action"),
            "raw_action": item.get("raw_action") or item.get("action"),
            "amount_paid": item.get("amount_paid"),
            "amount_to": item.get("amount_to"),
            "all_in": item.get("stack_after") == 0,
            "bot_style": style,
        })

    for seat in seats:
        if seat.get("bot_style"):
            styles.append(seat["bot_style"])
    hero_invested = commitments.get(hero_uuid, 0) + sum(
        int(item.get("amount_paid") or 0)
        for item in action_history
        if item.get("actor") == "Hero"
    )
    hero_stack_total = int(hero_seat.get("stack") or 0) + hero_invested
    hero_stack_bb = round(hero_stack_total / big_blind, 2) if big_blind else 0
    folded = {item.get("uuid") for item in normalized if item.get("canonical_action") == "fold"}
    opponent_stacks = []
    for index in active_seats:
        seat = seats[index]
        uuid_ = seat.get("uuid")
        if uuid_ == hero_uuid or uuid_ in folded:
            continue
        invested = commitments.get(uuid_, 0) + sum(
            int(item.get("amount_paid") or 0) for item in normalized if item.get("uuid") == uuid_
        )
        opponent_stacks.append({
            "position": positions.get(uuid_),
            "starting_stack_bb": round((int(seat.get("stack") or 0) + invested) / big_blind, 2) if big_blind else None,
        })
    pot = round_state.get("pot") or {}
    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "decision_id": f"{round_state.get('round_count')}:preflop:{len(action_history)}",
        "round_count": round_state.get("round_count"),
        "street": "preflop",
        "known_facts": {
            "format": round_state.get("game_format"),
            "scenario": round_state.get("scenario"),
            "players_dealt": len(active_seats),
            "blinds": {"small": small_blind, "big": big_blind},
            "ante": {
                "type": round_state.get("ante_type") or "none",
                "amount": round_state.get("ante") or 0,
            },
            "hero_position": positions.get(hero_uuid),
            "hero_cards": list(hero_cards),
            "opponent_stacks": opponent_stacks,
            "board_visible": [],
            "hero_hand": build_hand_facts(hero_cards, []),
            "pot_before_action": (pot.get("main") or {}).get("amount"),
            "hero_stack_before": hero_seat.get("stack"),
            "hero_street_bet_before": hero_invested,
            "action_history_before": action_history,
            "hero_action": None,
        },
        "explicit_assumptions": [],
        "derived_calculations": {"hero_stack_bb_at_decision": hero_stack_bb},
        "evidence_sources": _base_evidence_sources(styles),
    }
    return attach_local_range_evidence(snapshot)


def build_decision_snapshots(game: Game, hand: Hand, hero_gp_id, street: str) -> list[dict[str, Any]]:
    """Return one future-clipped snapshot per hero decision on ``street``."""
    from poker_trainer.api.games import _build_hand_detail

    detail = _build_hand_detail(game, hand, hero_gp_id)
    street_data = (detail.get("streets") or {}).get(street)
    if not street_data:
        return []

    hero = next((p for p in detail.get("players", []) if p.get("is_hero")), {})
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
                "action": item.get("canonical_action") or item.get("action"),
                "raw_action": item.get("raw_action") or item.get("action"),
                "amount_paid": item.get("amount_paid"),
                "amount_to": item.get("amount_to"),
                "all_in": item.get("is_allin", False),
                "bot_style": _style_value(actor) if actor and actor.is_bot else None,
            })

        hero_stack_total = (action.get("stack_before") or 0) + (action.get("street_bet") or 0)
        hero_stack_bb = round(hero_stack_total / game.big_blind, 2) if game.big_blind else 0
        folded_positions = {item.get("position") for item in action_history if item.get("action") == "fold"}
        opponent_stacks = [
            {"position": hp.position,
             "starting_stack_bb": round(hp.starting_stack / game.big_blind, 2) if hp.starting_stack is not None and game.big_blind else None}
            for hp in hand.players
            if hp.game_player_id != hero_gp_id and hp.position not in folded_positions
            and (hp.starting_stack is None or hp.starting_stack > 0)
        ] if street == "preflop" else []
        styles = sorted({
            _style_value(gp) for gp in game.players if gp.is_bot and _style_value(gp)
        })

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
                "opponent_stacks": opponent_stacks,
                "board_visible": street_data.get("board") or [],
                "hero_hand": build_hand_facts(
                    hero.get("hole_cards"), street_data.get("board") or [],
                ),
                "pot_before_action": action.get("pot_before"),
                "hero_stack_before": action.get("stack_before"),
                "hero_street_bet_before": action.get("street_bet"),
                "action_history_before": action_history,
                "hero_action": {
                    "action": action.get("canonical_action") or action.get("action"),
                    "raw_action": action.get("raw_action") or action.get("action"),
                    "amount_paid": action.get("amount_paid"),
                    "amount_to": action.get("amount_to"),
                    "all_in": action.get("is_allin", False),
                },
            },
            "explicit_assumptions": [],
            "derived_calculations": {"hero_stack_bb_at_decision": hero_stack_bb},
            "evidence_sources": _base_evidence_sources(styles),
        }
        snapshots.append(attach_local_range_evidence(snapshot))
    return snapshots
