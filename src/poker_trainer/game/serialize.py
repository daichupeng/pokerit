"""Shape engine state into JSON for the browser, enforcing the hidden-info rule.

The browser must only ever see:
  - public table info (names, stacks, states, bets, board, pot, positions),
  - the hero's own hole cards,
  - opponents' hole cards ONLY at a real showdown, and only for non-folded seats.

Opponent hole cards never appear in the Emulator's event ``round_state`` (seats
carry only name/stack/state), so the only place they can leak is showdown
reveal, which we compute deliberately from the live table here.
"""

from __future__ import annotations

def hero_hole_cards(game_state, hero_uuid: str) -> list[str]:
    """Read the hero's own hole cards from the live table (always allowed)."""
    for player in game_state["table"].seats.players:
        if player.uuid == hero_uuid:
            return [str(c) for c in player.hole_card]
    return []


def public_view(round_state: dict, hero_uuid: str, seat_meta: dict, hero_hole: list[str]) -> dict:
    """Build the table view sent to the browser for rendering.

    ``seat_meta`` maps uuid -> {"style": str|None, "hidden": bool, "is_bot": bool}
    so the client can label (or deliberately hide) bot styles.
    """
    seats = []
    bets = _current_bets(round_state)
    for pos, seat in enumerate(round_state["seats"]):
        uuid_ = seat["uuid"]
        meta = seat_meta.get(uuid_, {})
        is_hero = uuid_ == hero_uuid
        show_style = bool(meta.get("is_bot")) and not meta.get("hidden")
        seats.append(
            {
                "pos": pos,
                "uuid": uuid_,
                "name": seat["name"],
                "stack": seat["stack"],
                "state": seat["state"],  # participating | folded | allin
                "is_hero": is_hero,
                "is_bot": bool(meta.get("is_bot")),
                "style": meta.get("style") if show_style else None,
                "bet": bets.get(uuid_, 0),
                "is_button": pos == round_state.get("dealer_btn"),
                "is_sb": pos == round_state.get("small_blind_pos"),
                "is_bb": pos == round_state.get("big_blind_pos"),
                # Hero cards always; opponents hidden during play.
                "hole_cards": list(hero_hole) if is_hero else None,
            }
        )

    return {
        "street": round_state.get("street"),
        "community_card": list(round_state.get("community_card", [])),
        "pot": round_state.get("pot", {"main": {"amount": 0}, "side": []}),
        "dealer_btn": round_state.get("dealer_btn"),
        "next_player": round_state.get("next_player"),
        "round_count": round_state.get("round_count"),
        "small_blind_amount": round_state.get("small_blind_amount"),
        "seats": seats,
    }


def _current_bets(round_state: dict) -> dict[str, int]:
    """Sum each player's paid chips on the current street (for bet display)."""
    histories = round_state.get("action_histories", {})
    street = round_state.get("street")
    entries = histories.get(street, []) if isinstance(street, str) else []
    bets: dict[str, int] = {}
    for entry in entries:
        uuid_ = entry.get("uuid")
        paid = entry.get("paid", 0) or 0
        if uuid_ is not None:
            bets[uuid_] = bets.get(uuid_, 0) + paid
    return bets
