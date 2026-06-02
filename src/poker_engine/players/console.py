"""A human player that acts via the console (stdin/stdout)."""

from __future__ import annotations

from pypokerengine.players import BasePokerPlayer


class ConsolePlayer(BasePokerPlayer):
    """Prompts the human at the terminal for each decision.

    Input grammar:
      ``f``            fold
      ``c``            call (or check when the call amount is 0)
      ``r <amount>``   raise to <amount> (clamped to the legal min/max)
    """

    def declare_action(self, valid_actions, hole_card, round_state):
        call = _find_action(valid_actions, "call")
        fold = _find_action(valid_actions, "fold")
        raise_action = _find_action(valid_actions, "raise")
        raise_ok = _raise_is_available(raise_action)

        self._print_situation(hole_card, round_state, valid_actions)

        while True:
            try:
                raw = input("Your action [f/c/r <amount>]: ").strip().lower()
            except EOFError:
                # No interactive stdin available: fall back to call/check.
                print("(no input — calling)")
                return "call", call["amount"]

            if not raw:
                continue

            cmd, *rest = raw.split()

            if cmd in ("f", "fold"):
                if call["amount"] == 0:
                    print("You can check for free — folding anyway.")
                return fold["action"], fold["amount"]

            if cmd in ("c", "call", "check"):
                return "call", call["amount"]

            if cmd in ("r", "raise"):
                if not raise_ok:
                    print("Raising is not allowed here.")
                    continue
                amount = self._parse_raise(rest, raise_action)
                if amount is None:
                    continue
                return "raise", amount

            print("Unrecognized input. Use f, c, or r <amount>.")

    # -- helpers ------------------------------------------------------------

    def _parse_raise(self, rest, raise_action) -> int | None:
        bounds = raise_action["amount"]
        lo, hi = bounds["min"], bounds["max"]
        if not rest:
            print(f"Specify an amount between {lo} and {hi}.")
            return None
        try:
            requested = int(rest[0])
        except ValueError:
            print("Raise amount must be a whole number.")
            return None
        clamped = max(lo, min(requested, hi))
        if clamped != requested:
            print(f"Raise clamped to legal range: {clamped} (min {lo}, max {hi}).")
        return clamped

    def _print_situation(self, hole_card, round_state, valid_actions):
        community = round_state.get("community_card", [])
        pot = round_state.get("pot", {}).get("main", {}).get("amount", 0)
        street = round_state.get("street", "?")
        call = _find_action(valid_actions, "call")["amount"]
        raise_action = _find_action(valid_actions, "raise")["amount"]

        print("\n" + "-" * 48)
        print(f"Street: {street}   Pot: {pot}")
        print(f"Your hole cards: {' '.join(hole_card)}")
        print(f"Community: {' '.join(community) if community else '(none)'}")
        if call == 0:
            print("To call: 0 (you can check)")
        else:
            print(f"To call: {call}")
        if raise_action["min"] != -1:
            print(f"Raise range: {raise_action['min']}–{raise_action['max']}")
        else:
            print("Raise: not allowed")

    # -- lifecycle callbacks (concise table narration) ----------------------

    def receive_game_start_message(self, game_info):
        names = [p["name"] for p in game_info.get("seats", [])]
        print(f"\n=== Game start: {', '.join(names)} ===")

    def receive_round_start_message(self, round_count, hole_card, seats):
        print(f"\n>>> Round {round_count} — your cards: {' '.join(hole_card)}")

    def receive_street_start_message(self, street, round_state):
        community = round_state.get("community_card", [])
        if community:
            print(f"  [{street}] board: {' '.join(community)}")

    def receive_game_update_message(self, action, round_state):
        pass

    def receive_round_result_message(self, winners, hand_info, round_state):
        names = ", ".join(w["name"] for w in winners)
        print(f"<<< Round won by: {names}")


def _find_action(valid_actions, name):
    return next(a for a in valid_actions if a["action"] == name)


def _raise_is_available(raise_action) -> bool:
    bounds = raise_action["amount"]
    return bounds["min"] != -1 and bounds["max"] != -1
