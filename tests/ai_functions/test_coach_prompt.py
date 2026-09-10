from types import SimpleNamespace

from ai_functions.coach_engine.engine import (
    CORE_COACH_PROMPT,
    GENERAL_COACH_PROMPT,
    HAND_REVIEW_PROMPT,
    IN_GAME_COACH_PROMPT,
    MAX_REPLY_TOKENS,
    _build_messages,
    _finalize_in_game_response,
    _requested_earlier_board_streets,
    _resolve_response_language,
    build_scenario_context,
)
from ai_functions.tools.loop import ToolCallRecord
from shared_services.table_formatter import format_table


def test_coach_prompts_are_shared_lean_and_mode_specific():
    prompts = (GENERAL_COACH_PROMPT, HAND_REVIEW_PROMPT, IN_GAME_COACH_PROMPT)

    for prompt in prompts:
        assert prompt.count("# Role and objective") == 1
        assert CORE_COACH_PROMPT.strip() in prompt
        assert len(prompt.split()) < 650
        assert "Omit greetings" in prompt
        assert "immediate range definitions" not in prompt
        assert "strictly through the binary lens" not in prompt

    assert "Default maximum: 100 words" in IN_GAME_COACH_PROMPT
    assert "Recorded hand, Exact math, Bot preset style" in IN_GAME_COACH_PROMPT
    assert "Preflop\n  strategy API" in IN_GAME_COACH_PROMPT
    assert "AI strategy judgment, or Solver result" in IN_GAME_COACH_PROMPT
    assert "recorded state" not in IN_GAME_COACH_PROMPT
    assert "heuristic inference" not in IN_GAME_COACH_PROMPT
    assert "never say you can calculate" in IN_GAME_COACH_PROMPT
    assert "explicit calculator result and its provenance" in IN_GAME_COACH_PROMPT
    assert "call the range-equity tool" in IN_GAME_COACH_PROMPT
    assert "never derive" in IN_GAME_COACH_PROMPT
    assert "Default maximum: 200 words" in GENERAL_COACH_PROMPT
    assert "80–150 words" in HAND_REVIEW_PROMPT
    assert MAX_REPLY_TOKENS == 2048


def test_live_output_names_presolved_api_evidence_without_calling_it_solver():
    result = _finalize_in_game_response(
        "Action: fold\nWhy: the supplied presolved mix folds this hand.",
        {"category": "preflop", "made_hand_label": "Preflop", "equity_calculation": None},
        "English",
        evidence_sources=[
            {"type": "engine_state"},
            {"type": "preflop_strategy_api"},
        ],
    )

    assert result.endswith(
        "Evidence: Recorded hand, Preflop strategy API, AI strategy judgment"
    )
    assert "Solver result" not in result


def test_message_layers_keep_authoritative_context_before_user_history():
    messages = _build_messages(
        [],
        "What is the best action?",
        pinned_context="Pinned hand",
        live_context="Live table",
        system_prompt=IN_GAME_COACH_PROMPT,
        scenario_context="Tournament 25BB",
    )

    assert messages == [
        {"role": "system", "content": IN_GAME_COACH_PROMPT},
        {"role": "system", "content": "Tournament 25BB"},
        {"role": "system", "content": "Pinned hand"},
        {"role": "system", "content": "Live table"},
        {"role": "user", "content": "What is the best action?"},
    ]


def test_in_game_language_follows_current_explicit_user_message():
    history = [
        SimpleNamespace(role="user", content="这里怎么打"),
        SimpleNamespace(role="assistant", content="中文回答"),
    ]

    assert _resolve_response_language("Should I fold here?", history) == "English"
    assert _resolve_response_language("opener挺松，能不能3-bet？", history) == "Chinese"


def test_ambiguous_language_uses_last_clear_user_message_not_assistant():
    history = [
        SimpleNamespace(role="user", content="Please analyze this hand"),
        SimpleNamespace(role="assistant", content="这是助手的中文回答"),
        SimpleNamespace(role="user", content="2400/2100...?"),
    ]

    assert _resolve_response_language("...?", history) == "English"


def test_earlier_board_selection_requires_an_explicit_user_request():
    assert _requested_earlier_board_streets("先不看第五张牌，算 equity") == {"turn"}
    assert _requested_earlier_board_streets("What was my turn equity before river?") == {"turn"}
    assert _requested_earlier_board_streets("回到翻牌，算当时 equity") == {"flop"}
    assert _requested_earlier_board_streets("现在 equity 是多少？") == set()


def test_scenario_context_distinguishes_starting_from_current_stack():
    source = SimpleNamespace(
        game_format="tournament",
        scenario="mtt_25bb",
        small_blind=50,
        big_blind=100,
        buy_in=2500,
        ante=100,
        ante_type="big_blind",
        tournament_stage="middle_short",
    )

    context = build_scenario_context(source)

    assert "Configured starting stack: 25.0 BB" in context
    assert "use current stacks from the table state" in context
    assert "assume chip EV" in context


def test_live_table_expresses_remaining_stacks_in_chips_and_bb():
    round_state = {
        "dealer_btn": 0,
        "active_seats": [0, 1],
        "small_blind_amount": 50,
        "big_blind_amount": 100,
        "street": "preflop",
        "round_count": 12,
        "next_player": 0,
        "seats": [
            {"uuid": "hero", "name": "Hero", "stack": 2350, "state": "participating"},
            {"uuid": "villain", "name": "Villain", "stack": 1800, "state": "participating"},
        ],
        "hole_cards_by_uuid": {"hero": ["As", "Kd"]},
        "pot": {"main": {"amount": 150}, "side": []},
        "action_histories": {},
    }

    table = format_table(
        round_state,
        "hero",
        valid_actions=[
            {"action": "fold", "amount": 0},
            {"action": "call", "amount": 100},
            {"action": "raise", "amount": {"min": 200, "max": 2350}},
        ],
    )

    assert "Player (BTN): 2350 (23.5 BB behind)" in table
    assert "Villain (BB): 1800 (18.0 BB behind)" in table
    assert "Current hand: #12" in table
    assert "Street: Preflop" in table
    assert "Current actor: Player (BTN)" in table
    assert "Player to act now: yes" in table
    assert "To call: 100" in table
    assert "Legal actions: fold; call 100; raise to 200–2350" in table


def test_live_table_includes_authoritative_hand_and_canonical_action_facts():
    round_state = {
        "dealer_btn": 0,
        "active_seats": [0, 1],
        "small_blind_amount": 50,
        "big_blind_amount": 100,
        "street": "river",
        "seats": [
            {"uuid": "hero", "name": "Hero", "stack": 8000, "state": "participating"},
            {"uuid": "villain", "name": "Villain", "stack": 8000, "state": "participating"},
        ],
        "hole_cards_by_uuid": {"hero": ["9c", "6c"]},
        "community_card": ["9h", "Th", "7c", "Qc", "Ac"],
        "pot": {"main": {"amount": 2150}, "side": []},
        "action_histories": {
            "turn": [
                {"uuid": "hero", "action": "CALL", "amount": 0},
                {"uuid": "villain", "action": "RAISE", "amount": 1000},
                {"uuid": "hero", "action": "CALL", "amount": 1000},
            ],
        },
    }

    table = format_table(round_state, "hero")

    assert "Made hand: Flush, Ace high (category: flush)" in table
    assert "No numeric equity has been calculated" in table
    assert "Player (BTN) checks" in table
    assert "Villain (BB) bets 1000" in table
    assert "Player (BTN) calls 1000" in table


def test_in_game_output_gate_rejects_unproven_equity_interval():
    facts = {
        "category": "one_pair", "made_hand_label": "Pair of Nines",
        "equity_calculation": None,
    }

    result = _finalize_in_game_response(
        "Action: call\nWhy: equity 大约 24%–27%\nEvidence: Exact math",
        facts,
        "Chinese",
    )

    assert "已拦截" in result
    assert "24%" not in result
    assert result.endswith("Evidence: Recorded hand")


def test_in_game_output_gate_uses_equity_question_when_answer_omits_the_word():
    facts = {
        "category": "one_pair", "made_hand_label": "Pair of Nines",
        "equity_calculation": None,
    }

    result = _finalize_in_game_response(
        "Action: call\nWhy: 大约 24%–27%。",
        facts,
        "Chinese",
        "请直接算 equity 区间",
    )

    assert "已拦截" in result
    assert "24%" not in result


def test_in_game_output_gate_rejects_next_message_work_promises():
    facts = {
        "category": "one_pair", "made_hand_label": "Pair of Nines",
        "equity_calculation": None,
    }

    result = _finalize_in_game_response(
        "Action: call\nPlan: 如果你想，我下一条可以把 outs 分组。",
        facts,
        "Chinese",
    )

    assert "已拦截" in result
    assert "下一条可以" not in result


def test_in_game_output_gate_rejects_pair_downgrade_after_flush_arrives():
    facts = {
        "category": "flush", "made_hand_label": "Flush, Ace high",
        "equity_calculation": None,
    }

    result = _finalize_in_game_response(
        "Action: check\nWhy: 你只有一对9，不能价值下注。",
        facts,
        "Chinese",
    )

    assert "已拦截" in result
    assert "Flush, Ace high" in result
    assert result.endswith("Evidence: Recorded hand")


def _range_tool_call(equity: float = 62.5) -> ToolCallRecord:
    result = {
        "status": "ok",
        "calculator": {
            "name": "Pokerit Range Equity",
            "version": "range_equity.v1",
            "method": "exact_enumeration",
            "enumerated_outcomes": 88,
            "heads_up_only": True,
        },
        "analysis_street": "turn",
        "board": ["9h", "Th", "7c", "Qc"],
        "scenarios": [
            {
                "label": "value-heavy",
                "equity_pct": equity,
                "combo_count": 2,
                "blocked_combo_count": 4,
                "outcomes_evaluated": 88,
                "requested_range": [{"hand": "QQ", "weight": 1.0}],
            },
        ],
        "scenario_equity_interval_pct": {"low": equity, "high": equity},
    }
    return ToolCallRecord(
        name="range_equity_calculator",
        arguments={"villain_ranges": []},
        result=result,
        latency_ms=1,
    )


def test_in_game_output_uses_only_matching_calculated_equity_and_provenance():
    facts = {
        "category": "one_pair", "made_hand_label": "Pair of Nines",
        "equity_calculation": None,
    }

    result = _finalize_in_game_response(
        "Action: call\nWhy: 对 value-heavy 范围有 62.5% equity。",
        facts,
        "Chinese",
        "算 turn equity",
        tool_calls=[_range_tool_call()],
    )

    assert "已拦截" not in result
    assert "Calculation: Pokerit Range Equity range_equity.v1" in result
    assert "[QQ] -> 62.5% equity (2 legal combos; 4 blocked; 88 outcomes)" in result
    assert "assumptions, not recorded facts or solver output" in result
    assert result.endswith("Evidence: Recorded hand, Exact math, AI strategy judgment")


def test_in_game_output_rejects_number_that_disagrees_with_calculator():
    facts = {
        "category": "one_pair", "made_hand_label": "Pair of Nines",
        "equity_calculation": None,
    }

    result = _finalize_in_game_response(
        "Action: call\nWhy: equity 大约 24%–27%。",
        facts,
        "Chinese",
        "算 turn equity",
        tool_calls=[_range_tool_call(62.5)],
    )

    assert "已拦截" in result
    assert "24%" not in result
    assert "精确枚举结果不一致" in result


def test_numeric_equity_request_fails_closed_when_model_skips_tool():
    facts = {
        "category": "one_pair", "made_hand_label": "Pair of Nines",
        "equity_calculation": None,
    }

    result = _finalize_in_game_response(
        "Action: call\nWhy: 这个点很接近。",
        facts,
        "Chinese",
        "请算 equity 区间",
        require_range_equity=True,
    )

    assert "已拦截" in result
    assert "没有得到有效的范围枚举结果" in result


def test_range_calculation_and_preflop_evidence_keep_separate_labels():
    facts = {
        "category": "one_pair", "made_hand_label": "Pair of Nines",
        "equity_calculation": None,
    }

    result = _finalize_in_game_response(
        "Action: call\nWhy: 62.5% equity。",
        facts,
        "Chinese",
        tool_calls=[_range_tool_call()],
        evidence_sources=[{"type": "preflop_strategy_api"}],
    )

    assert result.endswith(
        "Evidence: Recorded hand, Exact math, Preflop strategy API, AI strategy judgment"
    )
    assert "Solver result" not in result
