"""Format a hand_detail API dict into a compact text description for the AI coach."""

from __future__ import annotations

_STREET_LABELS = {
    "preflop": "Preflop",
    "flop": "Flop",
    "turn": "Turn",
    "river": "River",
}

_POSITION_NAMES = ["BTN", "SB", "BB", "UTG", "HJ", "CO", "UTG+1", "UTG+2", "CO-1"]


def _action_line(a: dict) -> str:
    who = "Player" if a.get("is_hero") else a["name"]
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
    """Return a compact text summary of a hand suitable for coach context."""
    lines: list[str] = []

    # Header: player's hole cards and position.
    hero_cards = None
    for p in hand.get("players", []):
        if p.get("is_hero") and p.get("hole_cards"):
            hero_cards = p["hole_cards"]
            break

    if hero_cards:
        lines.append(f"Player's hand: {_cards(hero_cards)}")
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
                who = "Player" if ps.get("is_hero") else ps["name"]
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
            who = "Player" if sh.get("is_hero") else sh["name"]
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
                who = "Player" if w.get("is_hero") else w["name"]
                lines.append(f"{who}: wins {w['amount_won']}")

    return "\n".join(lines).strip()
