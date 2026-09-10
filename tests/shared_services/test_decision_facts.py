from shared_services.decision_facts import build_hand_facts, normalize_action_rows


def test_reported_hand_gets_third_pair_and_structural_draws_on_turn():
    facts = build_hand_facts(["9c", "6c"], ["9h", "Th", "7c", "Qc"])

    assert facts["category"] == "one_pair"
    assert facts["made_hand_label"] == "Pair of Nines"
    assert facts["pair_context"] == "third_pair"
    assert facts["equity_calculation"] is None
    assert {draw["type"] for draw in facts["draws"]} == {
        "flush_draw", "straight_draw",
    }
    flush_draw = next(draw for draw in facts["draws"] if draw["type"] == "flush_draw")
    straight_draw = next(draw for draw in facts["draws"] if draw["type"] == "straight_draw")
    assert flush_draw == {
        "type": "flush_draw", "suit": "clubs", "cards_remaining_in_suit": 9,
    }
    assert straight_draw["missing_ranks"] == ["8"]


def test_reported_river_is_ace_high_flush_with_correct_best_five():
    facts = build_hand_facts(["9c", "6c"], ["9h", "Th", "7c", "Qc", "Ac"])

    assert facts["category"] == "flush"
    assert facts["made_hand_label"] == "Flush, Ace high"
    assert set(facts["best_five"]) == {"9c", "6c", "7c", "Qc", "Ac"}
    assert facts["draws"] == []


def test_action_normalization_separates_check_bet_call_and_paid_vs_to():
    rows = normalize_action_rows([
        {"uuid": "hero", "action": "CALL", "amount": 0},
        {"uuid": "villain", "action": "RAISE", "amount": 1000},
        {"uuid": "hero", "action": "CALL", "amount": 1000},
    ], "turn")

    assert [row["canonical_action"] for row in rows] == ["check", "bet", "call"]
    assert rows[0]["amount_paid"] == 0
    assert rows[1]["amount_paid"] == 1000
    assert rows[1]["amount_to"] == 1000
    assert rows[2]["amount_paid"] == 1000
    assert rows[2]["amount_to"] == 1000
    assert rows[1]["raw_action"] == "raise"


def test_preflop_raise_keeps_raise_semantics_and_blind_payment_delta():
    rows = normalize_action_rows([
        {"uuid": "sb", "action": "CALL", "amount": 50},
        {"uuid": "bb", "action": "RAISE", "amount": 400},
    ], "preflop", {"sb": 50, "bb": 100})

    assert rows[0]["canonical_action"] == "call"
    assert rows[0]["amount_paid"] == 50
    assert rows[0]["amount_to"] == 100
    assert rows[1]["canonical_action"] == "raise"
    assert rows[1]["amount_paid"] == 300
    assert rows[1]["amount_to"] == 400
