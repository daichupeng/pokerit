from poker_engine.config import GameConfig, SeatKind, SeatSpec
from poker_trainer.game.session import (
    GameSession,
    _showdown_contender_uuids,
    _showdown_visibility_uuids,
    _terminal_statuses,
)


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


def test_called_all_in_tables_every_live_hand_but_never_a_folded_hand() -> None:
    histories = {
        "preflop": [
            {"uuid": "third", "action": "FOLD", "stack_after": 900},
            {"uuid": "hero", "action": "RAISE", "stack_after": 0},
            {"uuid": "villain", "action": "CALL", "stack_after": 500},
        ],
        "flop": [], "turn": [], "river": [],
    }

    visibility = _showdown_visibility_uuids(
        contenders={"hero", "villain"},
        winners={"villain"},
        action_histories=histories,
        active_uuids=["hero", "villain", "third"],
        button_uuid="third",
        mode="realistic",
    )

    assert visibility["table_all"] is True
    assert visibility["live"] == {"hero", "villain"}
    assert visibility["history"] == {"hero", "villain"}
    assert "third" not in visibility["live"]


def test_realistic_river_showdown_mucks_losing_caller_live_but_keeps_history_visibility() -> None:
    histories = {
        "preflop": [], "flop": [], "turn": [],
        "river": [
            {"uuid": "caller", "action": "CALL", "amount": 0, "stack_after": 1000},
            {"uuid": "bettor", "action": "RAISE", "amount": 500, "stack_after": 500},
            {"uuid": "caller", "action": "CALL", "amount": 500, "stack_after": 500},
        ],
    }

    visibility = _showdown_visibility_uuids(
        contenders={"bettor", "caller"},
        winners={"bettor"},
        action_histories=histories,
        active_uuids=["bettor", "caller"],
        button_uuid="bettor",
        mode="realistic",
    )

    assert visibility["live"] == {"bettor"}
    assert visibility["history"] == {"bettor", "caller"}


def test_realistic_showdown_tables_losing_aggressor_and_winning_caller() -> None:
    histories = {
        "preflop": [], "flop": [], "turn": [],
        "river": [
            {"uuid": "bettor", "action": "RAISE", "amount": 500, "stack_after": 500},
            {"uuid": "caller", "action": "CALL", "amount": 500, "stack_after": 500},
        ],
    }

    visibility = _showdown_visibility_uuids(
        contenders={"bettor", "caller"},
        winners={"caller"},
        action_histories=histories,
        active_uuids=["bettor", "caller"],
        button_uuid="caller",
        mode="realistic",
    )

    assert visibility["live"] == {"bettor", "caller"}


def test_training_mode_tables_every_showdown_contender() -> None:
    visibility = _showdown_visibility_uuids(
        contenders={"hero", "bot_a", "bot_b"},
        winners={"bot_b"},
        action_histories={"preflop": [], "flop": [], "turn": [], "river": []},
        active_uuids=["hero", "bot_a", "bot_b"],
        button_uuid="hero",
        mode="training",
    )

    assert visibility["live"] == {"hero", "bot_a", "bot_b"}
    assert visibility["history"] == visibility["live"]


def test_terminal_statuses_distinguish_showdown_muck_and_fold() -> None:
    statuses = _terminal_statuses(
        dealt_uuids=["winner", "shown", "mucked", "folded"],
        contenders={"winner", "shown", "mucked"},
        winners={"winner"},
        live_revealed={"winner", "shown"},
        all_in={"shown"},
    )

    assert statuses == {
        "winner": {"status": "win", "was_allin": False},
        "shown": {"status": "showdown", "was_allin": True},
        "mucked": {"status": "mucked", "was_allin": False},
        "folded": {"status": "fold", "was_allin": False},
    }


def test_heads_up_called_all_in_reveals_before_board_runout() -> None:
    config = GameConfig(
        small_blind=5,
        buy_in=100,
        max_round=1,
        seats=[
            SeatSpec(name="Hero", kind=SeatKind.HUMAN, email="showdown@test.local"),
            SeatSpec(name="Bot", kind=SeatKind.ROCK),
        ],
    )
    session = GameSession(config, hero_index=0, seed=7)
    bot_uuid = session.seat_uuids[1]
    session._bot_players[1].declare_action = lambda valid, *_: (
        "call",
        next(item for item in valid if item["action"] == "call")["amount"],
    )

    session.start()
    valid_actions = session.pending_ask()["valid_actions"]
    raise_max = next(
        item for item in valid_actions if item["action"] == "raise"
    )["amount"]["max"]
    events = session.apply_hero_action("raise", raise_max)
    event_types = [event["type"] for event in events]

    reveal_index = event_types.index("showdown_reveal")
    assert reveal_index < event_types.index("new_street")
    reveal_event = events[reveal_index]
    assert set(reveal_event["contenders"]) == set(session.seat_uuids)
    assert reveal_event["revealed"][bot_uuid]

    finish = next(event for event in events if event["type"] == "round_finish")
    assert finish["revealed"][bot_uuid]
    assert {
        terminal["status"] for terminal in finish["terminal_statuses"].values()
    } == {"win", "showdown"}
    assert {
        seat["state"] for seat in finish["view"]["seats"]
    } == {"participating"}
