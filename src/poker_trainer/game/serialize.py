"""Shape engine state into JSON for the browser, enforcing the hidden-info rule.

The browser must only ever see:
  - public table info (names, stacks, states, bets, board, pot, positions),
  - the hero's own hole cards,
  - opponents' hole cards ONLY at a real showdown.
"""

from __future__ import annotations

from pokerkit import State

from poker_engine import pk_adapter
from poker_engine.config import GameConfig
from shared_services.hand_formatter import pos_label as _pos_label

# street_index -> name used in browser events / recorder
_STREET_NAMES = {0: "preflop", 1: "flop", 2: "turn", 3: "river"}


def last_actions_for_street(
    action_histories: dict[str, list[dict]] | None,
    street: str,
) -> dict[str, dict]:
    """Return each player's latest public action on the current street.

    The browser receives only the current street's transient action badge.
    Fold and all-in persistence is derived from the seat state, so stale calls
    and raises disappear automatically when a new street begins.
    """
    latest: dict[str, dict] = {}
    for entry in (action_histories or {}).get(street, []):
        uuid_ = str(entry.get("uuid", ""))
        action = str(entry.get("action", "")).upper()
        if not uuid_ or not action:
            continue
        latest[uuid_] = {
            "action": action,
            "amount": int(entry.get("amount") or 0),
        }
    return latest


def build_view(
    *,
    config: GameConfig,
    state: State | None,
    seat_uuids: list[str],
    seat_meta: dict[str, dict],
    hero_index: int,
    pk_to_seat: list[int],
    seat_to_pk: list[int],
    stacks: list[int],
    btn_pos: int,
    sb_pos: int,
    bb_pos: int,
    active_seats: list[int],
    current_street_index: int,
    hand_num: int,
    hero_hole: list[str],
    board: list[str],
    action_histories: dict[str, list[dict]] | None = None,
    hero_hole_override: list[str] | None = None,
    community_override: list[str] | None = None,
) -> dict:
    """Build the full frontend view dict from live (or final) game state."""
    n = len(config.seats)
    hero_hole = hero_hole_override if hero_hole_override is not None else hero_hole
    community = community_override if community_override is not None else board
    street = _STREET_NAMES.get(current_street_index, "preflop")
    last_actions = last_actions_for_street(action_histories, street)
    folded_uuids = {
        str(entry.get("uuid"))
        for actions in (action_histories or {}).values()
        for entry in actions
        if entry.get("uuid")
        and str(entry.get("action", "")).upper() == "FOLD"
    }

    if state is not None:
        stacks_view = [state.stacks[seat_to_pk[i]] if seat_to_pk[i] >= 0 else stacks[i] for i in range(n)]
        bets = [state.bets[seat_to_pk[i]] if seat_to_pk[i] >= 0 else 0 for i in range(n)]
        pot = pk_adapter.pot_dict(state)
        pot_with_uuids = {
            "main": pot["main"],
            "side": [
                {"amount": p["amount"], "eligibles": [seat_uuids[pk_to_seat[pk_i]] for pk_i in p["eligibles"]]}
                for p in pot["side"]
            ],
        }
    else:
        stacks_view = list(stacks)
        bets = [0] * n
        pot_with_uuids = {"main": {"amount": 0}, "side": []}

    seats = []
    for i, spec in enumerate(config.seats):
        uuid_ = seat_uuids[i]
        meta = seat_meta[uuid_]
        is_hero = i == hero_index
        pk_i = seat_to_pk[i]
        is_sitting_out = i not in active_seats
        if is_sitting_out or uuid_ in folded_uuids:
            state_str = "folded"
        elif state is not None and state.status and pk_i >= 0 and state.stacks[pk_i] == 0:
            state_str = "allin"
        else:
            state_str = "participating"
        show_style = bool(meta.get("is_bot")) and not meta.get("hidden")
        seat_pos = _pos_label(i, btn_pos, active_seats) if not is_sitting_out else ""
        seats.append({
            "pos": i,
            "uuid": uuid_,
            "name": spec.name,
            "stack": stacks_view[i],
            "state": state_str,
            "is_sitting_out": is_sitting_out,
            "is_hero": is_hero,
            "is_bot": bool(meta.get("is_bot")),
            "style": meta.get("style") if show_style else None,
            "bet": bets[i],
            "is_button": i == btn_pos,
            "is_sb": i == sb_pos,
            "is_bb": i == bb_pos,
            "position": seat_pos,
            "hole_cards": hero_hole if is_hero else None,
            "last_action": last_actions.get(uuid_),
        })

    actor_seat = None
    if state is not None and state.actor_index is not None:
        actor_seat = pk_to_seat[state.actor_index]

    return {
        "street": street,
        "community_card": list(community),
        "pot": pot_with_uuids,
        "dealer_btn": btn_pos,
        "next_player": actor_seat,
        "round_count": hand_num,
        "small_blind_amount": config.small_blind,
        "big_blind_amount": config.big_blind,
        "ante": config.ante,
        "ante_type": config.ante_type,
        "game_format": config.game_format,
        "scenario": config.scenario,
        "tournament_stage": config.tournament_stage,
        "profile_scope": config.profile_scope,
        "seats": seats,
    }


def build_round_state(
    *,
    config: GameConfig,
    state: State | None,
    seat_uuids: list[str],
    pk_to_seat: list[int],
    seat_to_pk: list[int],
    stacks: list[int],
    btn_pos: int,
    sb_pos: int,
    bb_pos: int,
    active_seats: list[int],
    current_street_index: int,
    board: list[str],
    action_histories: dict[str, list[dict]],
    hand_num: int,
    community: list[str] | None = None,
    final_stacks: list[int] | None = None,
    pot_total_override: int | None = None,
) -> dict:
    """Build a round_state dict compatible with the recorder and bot interface."""
    n = len(config.seats)
    community = community or board
    effective_stacks = final_stacks or (
        [state.stacks[seat_to_pk[i]] if seat_to_pk[i] >= 0 else stacks[i] for i in range(n)]
        if state else list(stacks)
    )
    folded_uuids = {
        str(entry.get("uuid"))
        for actions in action_histories.values()
        for entry in actions
        if entry.get("uuid")
        and str(entry.get("action", "")).upper() == "FOLD"
    }

    pot = {"main": {"amount": 0}, "side": []}
    if state:
        pot_raw = pk_adapter.pot_dict(state)
        pot = {
            "main": pot_raw["main"],
            "side": [
                {"amount": p["amount"],
                 "eligibles": [seat_uuids[pk_to_seat[pk_i]] for pk_i in p["eligibles"]]}
                for p in pot_raw["side"]
            ],
        }
    if pot_total_override is not None:
        pot["main"]["amount"] = pot_total_override

    seats = []
    for i in range(n):
        pk_i = seat_to_pk[i]
        uuid_ = seat_uuids[i]
        if i not in active_seats or uuid_ in folded_uuids:
            state_str = "folded"
        elif state and state.status and pk_i >= 0 and state.stacks[pk_i] == 0:
            state_str = "allin"
        else:
            state_str = "participating"
        seats.append({
            "uuid": uuid_,
            "name": config.seats[i].name,
            "stack": effective_stacks[i],
            "state": state_str,
        })

    return {
        "street": _STREET_NAMES.get(current_street_index, "preflop"),
        "community_card": list(community),
        "pot": pot,
        "dealer_btn": btn_pos,
        "small_blind_pos": sb_pos,
        "big_blind_pos": bb_pos,
        "active_seats": list(active_seats),
        "next_player": (
            pk_to_seat[state.actor_index]
            if state and state.actor_index is not None else None
        ),
        "round_count": hand_num,
        "small_blind_amount": config.small_blind,
        "big_blind_amount": config.big_blind,
        "ante": config.ante,
        "ante_type": config.ante_type,
        "game_format": config.game_format,
        "scenario": config.scenario,
        "tournament_stage": config.tournament_stage,
        "profile_scope": config.profile_scope,
        "seats": seats,
        "action_histories": action_histories,
    }
