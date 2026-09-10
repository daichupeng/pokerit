from poker_trainer.game.serialize import last_actions_for_street


def test_last_actions_only_include_latest_action_on_current_street():
    histories = {
        "preflop": [
            {"uuid": "villain", "action": "RAISE", "amount": 300},
            {"uuid": "hero", "action": "CALL", "amount": 250},
        ],
        "flop": [
            {"uuid": "villain", "action": "CALL", "amount": 0},
            {"uuid": "hero", "action": "RAISE", "amount": 400},
            {"uuid": "villain", "action": "CALL", "amount": 400},
        ],
    }

    assert last_actions_for_street(histories, "flop") == {
        "hero": {"action": "RAISE", "amount": 400},
        "villain": {"action": "CALL", "amount": 400},
    }


def test_last_actions_clear_when_a_new_street_has_no_actions():
    histories = {
        "preflop": [{"uuid": "villain", "action": "FOLD", "amount": 0}],
        "flop": [],
    }

    assert last_actions_for_street(histories, "flop") == {}
