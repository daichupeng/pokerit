"""A placeholder human player for the Emulator.

The Emulator requires every seat to be a registered ``BasePokerPlayer``. The
human seat is actually driven by the web client via ``Emulator.apply_action``,
so this placeholder's ``declare_action`` is only a safety fallback (it would be
hit only if the bot loop ever asked the human to auto-act, which it never does).
Its ``receive_*`` callbacks matter: the ``PerspectiveRecorder`` wraps them to
capture the hero's view of each hand, exactly as in the console game.
"""

from __future__ import annotations

from pypokerengine.players import BasePokerPlayer


class HumanPlaceholder(BasePokerPlayer):
    def declare_action(self, valid_actions, hole_card, round_state):
        # Safety fallback only — never used in normal web play. Call/check.
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
