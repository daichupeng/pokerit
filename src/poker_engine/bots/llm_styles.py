"""Concrete LLM bot archetypes.

Each class sets ``style_name``, ``system_prompt``, ``model``, and
``temperature`` on ``LLMBot``.  The downstream engine sees the same
``declare_action`` / ``set_n_players`` interface as ``StyleBot`` —
no other code needs to change.

To create a custom style, subclass ``LLMBot`` and override the class
attributes.  Register it in ``LLM_STYLE_REGISTRY`` to make it available
by name.

Example::

    class MyBot(LLMBot):
        style_name = "my_style"
        system_prompt = "You are a maniac who never folds..."
        model = "gpt-4.1-mini"
        temperature = 1.2
"""

from __future__ import annotations

from poker_engine.bots.llm_bot_base import LLMBot


class GTOBot(LLMBot):
    """Balanced, exploitability-minimising GTO style."""

    style_name = "AI GTO"
    model = "gpt-4.1-mini"
    temperature = 0.7
    system_prompt = (
        "You are an elite poker bot playing a near-optimal Game Theory Optimal (GTO) strategy in No-Limit Texas Hold'em. "
        "Balance your ranges, mix raises and calls to remain unexploitable, and avoid large deviations from the mixed-strategy equilibrium. "
        "Consider the ranges of possible opponent hands and make decisions that are not easily exploitable by any particular strategy. "
    )


class FishBot(LLMBot):
    """Fish: plays based on gut feeling, no understanding of the game."""

    style_name = "AI Fish"
    model = "gpt-4.1-mini"
    temperature = 1.2
    system_prompt = (
        "You are a Fish poker bot in No-Limit Texas Hold'em. You have no understanding of the game, and play based purely on gut feeling."
        "You get scared and fold easily, and also love to gamble and bluff often."
    )


class CallerBot(LLMBot):
    """Classic calling station: rarely folds or raises."""

    style_name = "AI Station"
    model = "gpt-4.1-mini"
    temperature = 0.5
    system_prompt = (
        "You are a calling-station poker bot in No-Limit Texas Hold'em. "
        "Call almost every bet regardless of pot odds or hand strength. "
        "Raise only with the absolute nuts. "
        "Never bluff. Fold only with a completely empty hand and no draws."
    )



# Registry maps style_name → class, consumed by the game engine or UI.
LLM_STYLE_REGISTRY: dict[str, type[LLMBot]] = {
    GTOBot.style_name: GTOBot,
    FishBot.style_name: FishBot,
    CallerBot.style_name: CallerBot,
}
