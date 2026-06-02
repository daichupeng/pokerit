"""Bot-vs-bot game to verify the PyPokerEngine integration works.

Runs a short heads-up no-limit hold'em match between two simple bots and
prints the final stacks. This is a smoke test for the environment, not a
real strategy — the webapp will drive the engine programmatically the same
way (via setup_config / start_poker, or the Emulator for finer control).
"""

from pypokerengine.api.game import setup_config, start_poker
from pypokerengine.players import BasePokerPlayer


class CallBot(BasePokerPlayer):
    """Always calls (checks when free); never folds, never raises."""

    def declare_action(self, valid_actions, hole_card, round_state):
        call = next(a for a in valid_actions if a["action"] == "call")
        return call["action"], call["amount"]

    def receive_game_start_message(self, game_info):
        pass

    def receive_round_start_message(self, round_count, hole_card, seats):
        pass

    def receive_street_start_message(self, street, round_state):
        pass

    def receive_game_update_message(self, action, round_state):
        pass

    def receive_round_result_message(self, winners, hand_info, round_state):
        pass


class FoldBot(BasePokerPlayer):
    """Calls when free, otherwise folds. A tighter, weaker style."""

    def declare_action(self, valid_actions, hole_card, round_state):
        call = next(a for a in valid_actions if a["action"] == "call")
        if call["amount"] == 0:
            return call["action"], call["amount"]
        fold = next(a for a in valid_actions if a["action"] == "fold")
        return fold["action"], fold["amount"]

    def receive_game_start_message(self, game_info):
        pass

    def receive_round_start_message(self, round_count, hole_card, seats):
        pass

    def receive_street_start_message(self, street, round_state):
        pass

    def receive_game_update_message(self, action, round_state):
        pass

    def receive_round_result_message(self, winners, hand_info, round_state):
        pass


def main() -> None:
    config = setup_config(max_round=10, initial_stack=100, small_blind_amount=5)
    config.register_player(name="caller", algorithm=CallBot())
    config.register_player(name="folder", algorithm=FoldBot())

    result = start_poker(config, verbose=1)

    print("\n=== Final result ===")
    for player in result["players"]:
        print(f"{player['name']:>8}: stack={player['stack']} state={player['state']}")


if __name__ == "__main__":
    main()
