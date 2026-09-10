from ai_functions.decision_snapshot import (
    build_decision_snapshots,
    build_live_preflop_snapshot,
)
from ai_functions.preflop_ranges import build_preflop_request
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

    assert snapshot["schema_version"] == "decision_snapshot.v2"
    assert snapshot["known_facts"]["action_history_before"] == []
    # A later fold must not hide the opponent from this earlier decision.
    assert snapshot["known_facts"]["opponent_stacks"] == [
        {"position": "BB", "starting_stack_bb": 100.0},
    ]
    assert snapshot["known_facts"]["hero_action"] == {
        "action": "raise", "raw_action": "raise",
        "amount_paid": 200, "amount_to": 200, "all_in": False,
    }
    assert snapshot["known_facts"]["hero_hand"]["category"] == "preflop"
    source_types = {item["type"] for item in snapshot["evidence_sources"]}
    assert "simulation_metadata" in source_types
    assert "range_knowledge_base" in source_types
    style_source = next(
        item for item in snapshot["evidence_sources"] if item["type"] == "simulation_metadata"
    )
    assert style_source["styles"] == ["tag"]


def test_live_preflop_snapshot_links_matching_local_rfi_pack():
    seats = [
        {"uuid": f"p{i}", "name": f"P{i}", "stack": 10000, "state": "participating"}
        for i in range(6)
    ]
    seats[5]["uuid"] = "hero"
    round_state = {
        "street": "preflop",
        "round_count": 3,
        "dealer_btn": 0,
        "active_seats": [0, 1, 2, 3, 4, 5],
        "next_player": 5,
        "small_blind_amount": 50,
        "big_blind_amount": 100,
        "ante": 0,
        "ante_type": "none",
        "game_format": "cash",
        "scenario": "cash_6max_100bb",
        "seats": seats,
        "hole_cards_by_uuid": {"hero": ["As", "Kh"]},
        "pot": {"main": {"amount": 150}, "side": []},
        "action_histories": {"preflop": [
            {"uuid": "p3", "action": "FOLD", "amount": 0, "stack_after": 10000},
            {"uuid": "p4", "action": "FOLD", "amount": 0, "stack_after": 10000},
        ]},
    }

    snapshot = build_live_preflop_snapshot(round_state, "hero")

    assert snapshot["known_facts"]["hero_position"] == "CO"
    assert snapshot["derived_calculations"]["hero_stack_bb_at_decision"] == 100
    assert {o["position"] for o in snapshot["known_facts"]["opponent_stacks"]} == {"BTN", "SB", "BB"}
    source = next(
        item for item in snapshot["evidence_sources"]
        if item["type"] == "range_knowledge_base"
    )
    assert source["pack_id"] == "cash_6max_100bb_v1"
    assert source["exact_frequencies_available"] is False

    round_state["seats"][5]["stack"] = 9700
    round_state["seats"][0]["stack"] = 19100
    round_state["action_histories"]["preflop"].extend([
        {"uuid": "hero", "action": "RAISE", "amount": 300, "stack_after": 9700},
        {"uuid": "p0", "action": "RAISE", "amount": 900, "stack_after": 9100},
    ])
    later_snapshot = build_live_preflop_snapshot(round_state, "hero")

    assert snapshot["decision_id"] == "3:preflop:2"
    assert later_snapshot["decision_id"] == "3:preflop:4"
    request = build_preflop_request(later_snapshot)
    assert request is not None
    assert request["_pokerit"]["use_range_endpoint"] is True
    assert next(o for o in later_snapshot["known_facts"]["opponent_stacks"] if o["position"] == "BTN")["starting_stack_bb"] == 200.0
