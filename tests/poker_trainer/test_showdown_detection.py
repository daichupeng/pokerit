from poker_trainer.game.session import _showdown_contender_uuids


def test_fold_winner_is_not_a_showdown() -> None:
    contenders = _showdown_contender_uuids(
        ["hero", "villain", "third"],
        {
            "preflop": [{"uuid": "third", "action": "FOLD"}],
            "flop": [{"uuid": "hero", "action": "FOLD"}],
        },
    )

    assert contenders == {"villain"}


def test_two_all_in_players_reach_showdown_without_revealed_cards() -> None:
    contenders = _showdown_contender_uuids(
        ["hero", "villain", "third"],
        {
            "preflop": [
                {"uuid": "third", "action": "fold"},
                {"uuid": "hero", "action": "RAISE"},
                {"uuid": "villain", "action": "CALL"},
            ],
        },
    )

    assert contenders == {"hero", "villain"}
