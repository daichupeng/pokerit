"""OpenAI function-calling schemas for the Phase 2 tool-calling infrastructure.

Every schema here is the exact JSON the OpenAI API sees. ``game_id`` and
``user_id`` must never appear as a parameter on any of these — that scoping
is bound at tool-executor construction time instead (see ``executors.py``).
"""

from __future__ import annotations

HAND_LOOKUP_SCHEMA = {
    "type": "function",
    "function": {
        "name": "hand_lookup",
        "description": (
            "Look up the full detail of one hand from the current game, "
            "formatted as the same compact text block used elsewhere in the "
            "coaching pipeline (positions, actions per street, board, "
            "showdown result)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "round_count": {
                    "type": "integer",
                    "description": "The hand's round number within the game.",
                },
            },
            "required": ["round_count"],
            "additionalProperties": False,
        },
    },
}

EQUITY_CALCULATOR_SCHEMA = {
    "type": "function",
    "function": {
        "name": "equity_calculator",
        "description": (
            "Estimate hero's equity via Monte Carlo simulation. This is "
            "equity vs random opponent hands, NOT vs a specific or "
            "action-implied villain range — it does not model what "
            "opponents' actions imply about their holdings."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "hole": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 2,
                    "maxItems": 2,
                    "description": "Hero's two hole cards, e.g. [\"As\", \"Kh\"].",
                },
                "board": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 0,
                    "maxItems": 5,
                    "description": "Community cards revealed so far (0-5 cards).",
                },
                "n_active_players": {
                    "type": "integer",
                    "description": "Total players still active in the hand, including hero.",
                },
            },
            "required": ["hole", "board", "n_active_players"],
            "additionalProperties": False,
        },
    },
}

STATS_QUERY_SCHEMA = {
    "type": "function",
    "function": {
        "name": "stats_query",
        "description": (
            "Query hero's deterministic play stats for the current game "
            "(VPIP, PFR, 3-bet, c-bet, WTSD, aggression factor, etc.), "
            "optionally filtered to one position or one postflop street."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "position": {
                    "type": "string",
                    "description": (
                        "Optional: restrict to hands played from this "
                        "position (e.g. BTN, SB, BB, CO, UTG, HJ). Omit for "
                        "stats across all positions."
                    ),
                },
                "street": {
                    "type": "string",
                    "enum": ["flop", "turn", "river"],
                    "description": (
                        "Optional: restrict the c-bet / fold-to-c-bet "
                        "breakdown to this postflop street. Omit for the "
                        "full stat block."
                    ),
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    },
}

ALL_TOOL_SCHEMAS = [HAND_LOOKUP_SCHEMA, EQUITY_CALCULATOR_SCHEMA, STATS_QUERY_SCHEMA]
