"""Format a hand_detail API dict into a compact text description for the AI coach."""

from __future__ import annotations

_STREET_LABELS = {
    "preflop": "Preflop",
    "flop": "Flop",
    "turn": "Turn",
    "river": "River",
}


def _pos_name(offset: int, n: int) -> str:
    """Return the position label for a seat that is `offset` active seats clockwise from BTN.

    `offset` and `n` must count only active (non-sitting-out) players.
    Seat priority: BTN > SB > BB > CO > UTG > HJ > UTG+1 > HJ-1 > UTG+2.
    """
    if n <= 1:
        return "BTN"
    if offset == 0:
        return "BTN"
    if offset == 1:
        return "SB" if n > 2 else "BB"
    if offset == 2 or n <= 3:
        return "BB"
    if offset == n - 1:
        return "CO"
    if offset == 3:
        return "UTG"
    if offset == n - 2:
        return "HJ"
    if offset == 4:
        return "UTG+1"
    if offset == n - 3:
        return "HJ-1"
    return "UTG+2"


def pos_label(seat_index: int, btn_seat: int, active_seats: list[int]) -> str:
    """Return the position label for `seat_index` given the active seat list and button seat.

    `active_seats` is an ordered list of seat indices that are still in play
    (non-zero stack). Seats not in `active_seats` are sitting out and have no
    position label.
    """
    if seat_index not in active_seats:
        return ""
    n = len(active_seats)
    btn_idx = active_seats.index(btn_seat)
    seat_idx = active_seats.index(seat_index)
    offset = (seat_idx - btn_idx) % n
    return _pos_name(offset, n)


def _action_line(a: dict) -> str:
    base = "Player" if a.get("is_hero") else a["name"]
    pos = a.get("position", "")
    street_bet = a.get("street_bet")
    stack_before = a.get("stack_before")
    context = ""
    if street_bet is not None and stack_before is not None:
        context = f" (Current bet: {street_bet}; Stack: {stack_before})"
    who = f"{base} ({pos}){context}" if pos else f"{base}{context}"
    amt = a.get("amount") or 0
    allin = " (ALL IN)" if a.get("is_allin") else ""
    action = a["action"]
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
    if action == "ante":
        return f"{who} posts ante {amt}"
    return f"{who} {action}" + (f" {amt}" if amt else "")


def _cards(codes: list[str]) -> str:
    return " ".join(codes) if codes else ""


def format_hand(hand: dict, game_sb: int, game_bb: int) -> str:
    """Return a compact text summary of a hand suitable for coach context.

    Positions are read directly from the stored `position` field on each player
    dict — no runtime recomputation.
    """
    lines: list[str] = []

    players_list = hand.get("players", [])

    # Header: player's hole cards and position.
    hero_cards = None
    hero_pos = None
    for p in players_list:
        if p.get("is_hero"):
            if p.get("hole_cards"):
                hero_cards = p["hole_cards"]
            hero_pos = p.get("position") or None
            break

    pos_str = f" ({hero_pos})" if hero_pos else ""
    if hero_cards:
        lines.append(f"Player's hand: {_cards(hero_cards)}{pos_str}")
    elif hero_pos:
        lines.append(f"Player's position: {hero_pos}")
    lines.append(f"SB: {game_sb}; BB: {game_bb}")
    lines.append("")

    streets_data = hand.get("streets", {})

    for st_key in ("preflop", "flop", "turn", "river"):
        st = streets_data.get(st_key)
        if not st:
            continue
        label = _STREET_LABELS[st_key]
        lines.append(f"{label}:")

        # Player stacks at start of this street.
        stacks = st.get("player_stacks", [])
        if stacks:
            stack_parts = []
            for ps in stacks:
                base = "Player" if ps.get("is_hero") else ps["name"]
                pos = ps.get("position", "")
                who = f"{base} ({pos})" if pos else base
                stack_parts.append(f"{who}: {ps['stack']}")
            lines.append("Stacks: " + ", ".join(stack_parts))

        # Board cards (flop/turn/river).
        board = st.get("board", [])
        if board:
            lines.append(f"Cards dealt: {_cards(board)}")

        # Pot.
        pot = st.get("pot", {})
        if pot:
            pot_main = pot.get("main", 0)
            pot_sides = [s for s in (pot.get("side") or []) if s.get("amount", 0) > 0]
            pot_str = f"Pot size: {pot_main}"
            for i, sp in enumerate(pot_sides):
                pot_str += f"; Side pot {i + 1}: {sp['amount']}"
            lines.append(pot_str)

        # Actions.
        for a in st.get("actions", []):
            lines.append(_action_line(a))

        lines.append("")

    # Showdown / result section.
    if hand.get("had_showdown") and hand.get("showdown_hands"):
        lines.append("Showdown:")
        for sh in hand["showdown_hands"]:
            base = "Player" if sh.get("is_hero") else sh["name"]
            pos = sh.get("position", "")
            who = f"{base} ({pos})" if pos else base
            cards_str = _cards(sh.get("hole_cards") or [])
            label = sh.get("hand_label", "")
            win_str = f". Wins {sh['amount_won']}" if sh.get("is_winner") and sh.get("amount_won") else ""
            lines.append(f"{who}: {cards_str}. {label}{win_str}")
    else:
        # Hand ended before showdown — only winner shown.
        winners = hand.get("winners", [])
        if winners:
            lines.append("Showdown:")
            for w in winners:
                base = "Player" if w.get("is_hero") else w["name"]
                pos = w.get("position", "")
                who = f"{base} ({pos})" if pos else base
                lines.append(f"{who}: wins {w['amount_won']}")

    return "\n".join(lines).strip()
