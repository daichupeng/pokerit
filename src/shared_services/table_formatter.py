from __future__ import annotations

from shared_services.hand_formatter import pos_label


def _cards(codes: list[str]) -> str:
    return " ".join(codes) if codes else ""


def _action_line(entry: dict, seat_names: dict[str, str], seat_positions: dict[str, str], hero_uuid: str) -> str:
    uuid_ = entry.get("uuid", "")
    is_hero = uuid_ == hero_uuid
    base = "Player" if is_hero else seat_names.get(uuid_, uuid_)
    pos = seat_positions.get(uuid_, "")
    who = f"{base} ({pos})" if pos else base

    action = entry.get("action", "").lower()
    amt = entry.get("amount") or 0
    stack_after = entry.get("stack_after")
    allin = f" (ALL IN)" if stack_after == 0 else ""

    if action == "fold":
        return f"{who} folds"
    if action == "raise":
        return f"{who} raises to {amt}{allin}"
    if action == "call":
        return f"{who} calls {amt}{allin}" if amt > 0 else f"{who} checks"
    if action == "smallblind":
        return f"{who} posts small blind {amt}"
    if action == "bigblind":
        return f"{who} posts big blind {amt}"
    return f"{who} {action}" + (f" {amt}" if amt else "")


def format_table(round_state: dict, hero_uuid: str) -> str:
    """Return a compact text summary of the current live table state for coach context.

    `round_state` is the dict produced by session._build_round_state_dict, which
    includes a `hole_cards_by_uuid` field populated from the session's deal record.
    `hero_uuid` identifies whose perspective is "Player" in the output.
    """
    btn_seat = round_state.get("dealer_btn")
    active_seats = round_state.get("active_seats", [])
    sb_amount = round_state.get("small_blind_amount", 0)
    bb_amount = sb_amount * 2
    street = round_state.get("street", "preflop")
    community = round_state.get("community_card", [])
    pot = round_state.get("pot", {})
    seats: list[dict] = round_state.get("seats", [])
    hole_cards_by_uuid: dict[str, list[str]] = round_state.get("hole_cards_by_uuid", {})

    # Build lookup maps: uuid -> name, uuid -> position
    seat_names: dict[str, str] = {}
    seat_positions: dict[str, str] = {}
    hero_pos = ""
    hero_cards: list[str] = hole_cards_by_uuid.get(hero_uuid, [])

    for i, s in enumerate(seats):
        uuid_ = s["uuid"]
        seat_names[uuid_] = s["name"]
        lbl = pos_label(i, btn_seat, active_seats) if i in active_seats else ""
        seat_positions[uuid_] = lbl
        if uuid_ == hero_uuid:
            hero_pos = lbl

    lines: list[str] = []

    pos_str = f" ({hero_pos})" if hero_pos else ""
    if hero_cards:
        lines.append(f"Player's hand: {_cards(hero_cards)}{pos_str}")
    elif hero_pos:
        lines.append(f"Player's position: {hero_pos}")
    lines.append(f"SB: {sb_amount}; BB: {bb_amount}")
    lines.append("")

    # Stacks
    stack_parts = []
    for i, s in enumerate(seats):
        if i not in active_seats:
            continue
        uuid_ = s["uuid"]
        is_hero = uuid_ == hero_uuid
        base = "Player" if is_hero else s["name"]
        pos = seat_positions.get(uuid_, "")
        who = f"{base} ({pos})" if pos else base
        state_str = s.get("state", "participating")
        suffix = " [folded]" if state_str == "folded" else (" [ALL IN]" if state_str == "allin" else "")
        stack_parts.append(f"{who}: {s['stack']}{suffix}")
    if stack_parts:
        lines.append("Stacks: " + ", ".join(stack_parts))

    # Pot
    pot_main = pot.get("main", {}).get("amount", 0)
    pot_sides = [sp for sp in (pot.get("side") or []) if sp.get("amount", 0) > 0]
    pot_str = f"Pot: {pot_main}"
    for i, sp in enumerate(pot_sides):
        pot_str += f"; Side pot {i + 1}: {sp['amount']}"
    lines.append(pot_str)

    # Community cards
    if community:
        lines.append(f"Board: {_cards(community)}")

    lines.append("")

    # Action histories by street
    action_histories: dict[str, list[dict]] = round_state.get("action_histories", {})
    street_order = ["preflop", "flop", "turn", "river"]
    street_labels = {"preflop": "Preflop", "flop": "Flop", "turn": "Turn", "river": "River"}

    for st in street_order:
        actions = action_histories.get(st, [])
        if not actions:
            continue
        lines.append(f"{street_labels[st]}:")
        for a in actions:
            lines.append(_action_line(a, seat_names, seat_positions, hero_uuid))
        lines.append("")

    # Current street indicator (if no actions recorded yet for it)
    if not action_histories.get(street):
        lines.append(f"Currently on: {street_labels.get(street, street)}")

    return "\n".join(lines).strip()
