"""Confirms game_id/user_id cannot appear as model-settable arguments on the
hand_lookup or stats_query tool schemas actually sent to the OpenAI API.
"""

from __future__ import annotations

from ai_functions.tools.schemas import (
    ALL_TOOL_SCHEMAS,
    EQUITY_CALCULATOR_SCHEMA,
    HAND_LOOKUP_SCHEMA,
    HAND_SEARCH_SCHEMA,
    POT_ODDS_SCHEMA,
    RANGE_EQUITY_CALCULATOR_SCHEMA,
    STATS_QUERY_SCHEMA,
)

_FORBIDDEN = {"game_id", "user_id"}


def test_hand_lookup_schema_excludes_scoping_params():
    props = HAND_LOOKUP_SCHEMA["function"]["parameters"]["properties"]
    assert set(props) == {"round_count"}
    assert _FORBIDDEN.isdisjoint(props)


def test_pot_odds_schema_excludes_scoping_params():
    props = POT_ODDS_SCHEMA["function"]["parameters"]["properties"]
    assert set(props) == {"pot_size", "amount_to_call"}
    assert _FORBIDDEN.isdisjoint(props)


def test_hand_search_schema_excludes_scoping_params():
    props = HAND_SEARCH_SCHEMA["function"]["parameters"]["properties"]
    assert _FORBIDDEN.isdisjoint(props)


def test_stats_query_schema_excludes_scoping_params():
    props = STATS_QUERY_SCHEMA["function"]["parameters"]["properties"]
    assert _FORBIDDEN.isdisjoint(props)


def test_equity_calculator_description_states_random_opponent_equity():
    desc = EQUITY_CALCULATOR_SCHEMA["function"]["description"].lower()
    assert "random opponent" in desc
    assert "not" in desc


def test_range_equity_schema_keeps_live_cards_code_bound():
    props = RANGE_EQUITY_CALCULATOR_SCHEMA["function"]["parameters"]["properties"]

    assert set(props) == {"villain_ranges", "board_street"}
    assert {"hole", "board", "hero_cards", "community_cards"}.isdisjoint(props)
    assert props["board_street"]["enum"] == ["current", "flop", "turn", "river"]
    assert RANGE_EQUITY_CALCULATOR_SCHEMA not in ALL_TOOL_SCHEMAS


def test_no_schema_ever_exposes_scoping_params():
    for schema in ALL_TOOL_SCHEMAS:
        props = schema["function"]["parameters"]["properties"]
        assert _FORBIDDEN.isdisjoint(props), schema["function"]["name"]
