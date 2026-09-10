from poker_engine.recorder import PerspectiveRecorder, _HandRecord


def _round_state() -> dict:
    return {
        "dealer_btn": 0,
        "small_blind_pos": 0,
        "big_blind_pos": 1,
        "active_seats": [0, 1],
        "community_card": ["2c", "3d", "4h", "5s", "9c"],
        "street": "river",
        "pot": {"main": {"amount": 200}, "side": []},
        "seats": [
            {"uuid": "hero", "stack": 200},
            {"uuid": "villain", "stack": 0},
        ],
        "action_histories": {},
    }


def test_explicit_showdown_does_not_depend_on_opponent_reveal() -> None:
    recorder = PerspectiveRecorder(hero_engine_uuid="hero")
    hand = _HandRecord(round_count=1, hero_hole=["Ah", "Ad"])
    recorder._current = hand
    recorder._hands.append(hand)

    recorder._record_round_result(
        [{"uuid": "hero"}],
        [
            {"uuid": "hero", "hole_card": ["Ah", "Ad"]},
            {"uuid": "villain", "hole_card": ["Kh", "Kd"]},
        ],
        _round_state(),
        revealed_uuids=set(),
        had_showdown=True,
    )

    assert hand.had_showdown is True
    assert "villain" not in hand.revealed_cards


def test_explicit_fold_finish_ignores_retained_winner_card() -> None:
    recorder = PerspectiveRecorder(hero_engine_uuid="hero")
    hand = _HandRecord(round_count=1, hero_hole=["Ah", "Ad"])
    recorder._current = hand
    recorder._hands.append(hand)

    recorder._record_round_result(
        [{"uuid": "villain"}],
        [{"uuid": "villain", "hole_card": ["Kh", "Kd"]}],
        _round_state(),
        revealed_uuids=set(),
        had_showdown=False,
    )

    assert hand.had_showdown is False
    assert hand.revealed_cards == {}
