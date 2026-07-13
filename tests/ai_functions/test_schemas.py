"""Confirms game_id/user_id cannot appear as model-settable arguments on the
hand_lookup or stats_query tool schemas actually sent to the OpenAI API.
"""

from __future__ import annotations

from ai_functions.tools.schemas import (
    ALL_TOOL_SCHEMAS,
    EQUITY_CALCULATOR_SCHEMA,
    HAND_LOOKUP_SCHEMA,
    STATS_QUERY_SCHEMA,
)

_FORBIDDEN = {"game_id", "user_id"}


def test_hand_lookup_schema_excludes_scoping_params():
    props = HAND_LOOKUP_SCHEMA["function"]["parameters"]["properties"]
    assert set(props) == {"round_count"}
    assert _FORBIDDEN.isdisjoint(props)


def test_stats_query_schema_excludes_scoping_params():
    props = STATS_QUERY_SCHEMA["function"]["parameters"]["properties"]
    assert _FORBIDDEN.isdisjoint(props)


def test_equity_calculator_description_states_random_opponent_equity():
    desc = EQUITY_CALCULATOR_SCHEMA["function"]["description"].lower()
    assert "random opponent" in desc
    assert "not" in desc


def test_no_schema_ever_exposes_scoping_params():
    for schema in ALL_TOOL_SCHEMAS:
        props = schema["function"]["parameters"]["properties"]
        assert _FORBIDDEN.isdisjoint(props), schema["function"]["name"]
