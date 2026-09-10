from types import SimpleNamespace
from uuid import uuid4

from poker_engine.db.models import Street
from poker_trainer.api.games import _build_hand_detail


def _showdown_detail(*, bot_revealed: bool, bot_folded: bool = False) -> dict:
    hero_id = uuid4()
    bot_id = uuid4()
    game = SimpleNamespace(
        id=uuid4(),
        players=[
            SimpleNamespace(
                id=hero_id, seat_index=0, display_name="Hero",
            ),
            SimpleNamespace(
                id=bot_id, seat_index=1, display_name="cold.Quill",
            ),
        ],
        ante_type="none",
        ante=0,
        small_blind=5,
        big_blind=10,
    )
    players = [
        SimpleNamespace(
            game_player_id=hero_id,
            position="BTN",
            hole_cards=["As", "Ad"],
            revealed=True,
            is_winner=True,
            amount_won=200,
            starting_stack=100,
        ),
        SimpleNamespace(
            game_player_id=bot_id,
            position="BB",
            hole_cards=["Kh", "Kd"] if bot_revealed else None,
            revealed=bot_revealed,
            is_winner=False,
            amount_won=0,
            starting_stack=100,
        ),
    ]
    actions = []
    if bot_folded:
        actions.append(SimpleNamespace(
            game_player_id=bot_id,
            street=Street.RIVER,
            action="fold",
            amount=0,
            seq=0,
            stack_after=50,
        ))
    hand = SimpleNamespace(
        id=uuid4(),
        players=players,
        actions=actions,
        board=["2c", "3d", "4h", "5s", "9c"],
        pot={"main": {"amount": 200}, "side": []},
        pot_total=200,
        round_count=4,
        active_player_count=2,
        street_reached=Street.RIVER,
        had_showdown=True,
        button_pos=0,
        sb_pos=0,
        bb_pos=1,
    )
    return _build_hand_detail(game, hand, hero_id)


def test_hand_detail_lists_unrevealed_showdown_contender_as_mucked() -> None:
    detail = _showdown_detail(bot_revealed=False)

    assert [player["name"] for player in detail["showdown_hands"]] == ["Hero"]
    assert detail["mucked_players"] == [{
        "name": "cold.Quill",
        "is_hero": False,
        "position": "BB",
    }]


def test_hand_detail_keeps_history_visible_cards_in_showdown_section() -> None:
    detail = _showdown_detail(bot_revealed=True)

    assert {player["name"] for player in detail["showdown_hands"]} == {
        "Hero", "cold.Quill",
    }
    assert detail["mucked_players"] == []


def test_hand_detail_never_lists_a_folded_player_as_mucked() -> None:
    detail = _showdown_detail(bot_revealed=False, bot_folded=True)

    assert detail["mucked_players"] == []
