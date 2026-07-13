"""Shared configuration for the game-review pipeline's LLM stages.

Single model for all LLM stages (street review agents and synthesis) per the
feature's architecture decisions — no model tiering this phase.
"""

from __future__ import annotations

MODEL = "gpt-5-mini"
