from ai_functions.decision_snapshot import build_decision_snapshots
from poker_engine.db.models import (
    Action,
    BotStyle,
    Game,
    GamePlayer,
    Hand,
    HandPlayer,
    Street,
    User,
)


def test_snapshot_clips_future_action_and_labels_bot_style_as_metadata(db_session):
    user = User(email="snapshot@test.local", display_name="Hero")
    db_session.add(user)
    db_session.flush()
    game = Game(
        small_blind=50, big_blind=100, buy_in=10000, max_round=10,
        hero_user_id=user.id, game_format="cash", scenario="cash_6max_100bb",
        ante_type="none",
    )
    db_session.add(game)
    db_session.flush()
    hero = GamePlayer(
        game_id=game.id, seat_index=0, display_name="Hero", engine_uuid="hero",
        user_id=user.id, is_bot=False, starting_stack=10000,
    )
    villain = GamePlayer(
        game_id=game.id, seat_index=1, display_name="Bot", engine_uuid="bot",
        is_bot=True, bot_style=BotStyle.TAG, starting_stack=10000,
    )
    db_session.add_all([hero, villain])
    db_session.flush()
    hand = Hand(
        game_id=game.id, round_count=1, active_player_count=6,
        street_reached=Street.PREFLOP, board=[], pot_total=250, had_showdown=False,
    )
    db_session.add(hand)
    db_session.flush()
    db_session.add_all([
        HandPlayer(
            hand_id=hand.id, game_player_id=hero.id, position="BTN",
            hole_cards=["As", "Kh"], starting_stack=10000,
        ),
        HandPlayer(
            hand_id=hand.id, game_player_id=villain.id, position="BB",
            starting_stack=10000,
        ),
        Action(
            hand_id=hand.id, game_player_id=hero.id, street=Street.PREFLOP,
            action="raise", amount=200, seq=0, stack_after=9800,
        ),
        Action(
            hand_id=hand.id, game_player_id=villain.id, street=Street.PREFLOP,
            action="fold", amount=0, seq=1, stack_after=9900,
        ),
    ])
    db_session.flush()

    snapshot = build_decision_snapshots(game, hand, hero.id, "preflop")[0]

    assert snapshot["known_facts"]["action_history_before"] == []
    assert snapshot["known_facts"]["hero_action"] == {
        "action": "raise", "amount": 200, "all_in": False,
    }
    source_types = {item["type"] for item in snapshot["evidence_sources"]}
    assert "simulation_metadata" in source_types
    assert "range_knowledge_base" in source_types
    style_source = next(
        item for item in snapshot["evidence_sources"] if item["type"] == "simulation_metadata"
    )
    assert style_source["styles"] == ["tag"]
