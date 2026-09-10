from types import SimpleNamespace

from ai_functions.coach_engine.engine import (
    CORE_COACH_PROMPT,
    GENERAL_COACH_PROMPT,
    HAND_REVIEW_PROMPT,
    IN_GAME_COACH_PROMPT,
    MAX_REPLY_TOKENS,
    _build_messages,
    build_scenario_context,
)
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
    assert "Default maximum: 200 words" in GENERAL_COACH_PROMPT
    assert "80–150 words" in HAND_REVIEW_PROMPT
    assert MAX_REPLY_TOKENS == 2048


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
        "seats": [
            {"uuid": "hero", "name": "Hero", "stack": 2350, "state": "participating"},
            {"uuid": "villain", "name": "Villain", "stack": 1800, "state": "participating"},
        ],
        "hole_cards_by_uuid": {"hero": ["As", "Kd"]},
        "pot": {"main": {"amount": 150}, "side": []},
        "action_histories": {},
    }

    table = format_table(round_state, "hero")

    assert "Player (BTN): 2350 (23.5 BB behind)" in table
    assert "Villain (BB): 1800 (18.0 BB behind)" in table
