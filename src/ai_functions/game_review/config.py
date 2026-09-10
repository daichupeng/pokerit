"""Shared configuration for the game-review pipeline's LLM stages.

Single model for all LLM stages (street review agents and synthesis) per the
feature's architecture decisions — no model tiering this phase.
"""

from __future__ import annotations

MODEL = "gpt-5.4-mini"

# One PokerAI presolved lookup per selected hand/decision. In-game lookups are
# separate and are reused only within their live conversation.
POSTGAME_POKERAI_CALL_LIMIT = 15
