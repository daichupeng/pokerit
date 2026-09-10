from poker_trainer.api.coach import _build_live_equity_context


def _round_state(states: list[str], board: list[str] | None = None) -> dict:
    uuids = ["hero", "villain", "third"][:len(states)]
    return {
        "seats": [
            {"uuid": uuid, "state": state}
            for uuid, state in zip(uuids, states, strict=True)
        ],
        "community_card": board if board is not None else ["Qs", "Jh", "2c"],
        "hole_cards_by_uuid": {
            "hero": ["As", "Kd"],
            "villain": ["Qc", "Qd"],
            "third": ["Ts", "Th"],
        },
    }


def test_live_equity_context_never_copies_opponent_hole_cards():
    context = _build_live_equity_context(
        _round_state(["participating", "allin"]), "hero",
    )

    assert context == {
        "hole": ["As", "Kd"],
        "board": ["Qs", "Jh", "2c"],
        "active_players": 2,
    }
    assert "Qc" not in repr(context)


def test_live_equity_context_fails_closed_for_multiway_or_preflop():
    assert _build_live_equity_context(
        _round_state(["participating", "participating", "allin"]), "hero",
    ) is None
    assert _build_live_equity_context(
        _round_state(["participating", "participating"], board=[]), "hero",
    ) is None


def test_folded_seat_does_not_make_heads_up_spot_multiway():
    context = _build_live_equity_context(
        _round_state(["participating", "participating", "folded"]), "hero",
    )

    assert context is not None
    assert context["active_players"] == 2
