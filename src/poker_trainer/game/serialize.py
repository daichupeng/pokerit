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
    hero_hole_override: list[str] | None = None,
    community_override: list[str] | None = None,
) -> dict:
    """Build the full frontend view dict from live (or final) game state."""
    n = len(config.seats)
    hero_hole = hero_hole_override if hero_hole_override is not None else hero_hole
    community = community_override if community_override is not None else board

    if state is not None:
        stacks_view = [state.stacks[seat_to_pk[i]] if seat_to_pk[i] >= 0 else stacks[i] for i in range(n)]
        bets = [state.bets[seat_to_pk[i]] if seat_to_pk[i] >= 0 else 0 for i in range(n)]
        statuses = [state.statuses[seat_to_pk[i]] if seat_to_pk[i] >= 0 else False for i in range(n)]
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
        statuses = [True] * n
        pot_with_uuids = {"main": {"amount": 0}, "side": []}

    seats = []
    for i, spec in enumerate(config.seats):
        uuid_ = seat_uuids[i]
        meta = seat_meta[uuid_]
        is_hero = i == hero_index
        pk_i = seat_to_pk[i]
        is_busted = stacks[i] == 0 and (state is None or pk_i < 0)
        if is_busted:
            state_str = "folded"
        elif statuses[i]:
            state_str = "participating"
            if state is not None and pk_i >= 0 and state.stacks[pk_i] == 0:
                state_str = "allin"
        else:
            state_str = "folded"
        show_style = bool(meta.get("is_bot")) and not meta.get("hidden")
        is_sitting_out = stacks[i] == 0
        seat_pos = _pos_label(i, btn_pos, active_seats) if not is_sitting_out else ""
        seats.append({
            "pos": i,
            "uuid": uuid_,
            "name": spec.name,
            "stack": stacks_view[i],
            "state": state_str,
            "is_hero": is_hero,
            "is_bot": bool(meta.get("is_bot")),
            "style": meta.get("style") if show_style else None,
            "bet": bets[i],
            "is_button": i == btn_pos,
            "is_sb": i == sb_pos,
            "is_bb": i == bb_pos,
            "position": seat_pos,
            "hole_cards": hero_hole if is_hero else None,
        })

    actor_seat = None
    if state is not None and state.actor_index is not None:
        actor_seat = pk_to_seat[state.actor_index]

    return {
        "street": _STREET_NAMES.get(current_street_index, "preflop"),
        "community_card": list(community),
        "pot": pot_with_uuids,
        "dealer_btn": btn_pos,
        "next_player": actor_seat,
        "round_count": hand_num,
        "small_blind_amount": config.small_blind,
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
    statuses = (
        [state.statuses[seat_to_pk[i]] if seat_to_pk[i] >= 0 else False for i in range(n)]
        if state else [True] * n
    )

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

    seats = [
        {
            "uuid": seat_uuids[i],
            "name": config.seats[i].name,
            "stack": effective_stacks[i],
            "state": "participating" if statuses[i] else "folded",
        }
        for i in range(n)
    ]

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
        "seats": seats,
        "action_histories": action_histories,
    }
