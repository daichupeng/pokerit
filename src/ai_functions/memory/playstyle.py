"""Playstyle summary — one non-streaming LLM call over the structured profile
only (leak states + trends + evaluation count), producing a short narrative
paragraph. Regenerated (fully rewritten, never appended) after every
fold/rebuild, per decision 1/5: the LLM never computes any profile number, it
only narrates numbers it's given.
"""

from __future__ import annotations

import json

from ai_functions.game_review import config
from shared_services.llm import chat_model_with_usage

MAX_SUMMARY_CHARS = 600
# Reasoning models (e.g. gpt-5-mini) spend part of this budget on invisible
# reasoning tokens before emitting visible text — too low a max_tokens here
# starves the completion entirely (observed: empty response, tokens fully
# consumed). Matches the budget the street/synthesis stages already use.
MAX_REPLY_TOKENS = 4096

SYSTEM_PROMPT = f"""\
You are a poker coaching assistant writing a short playstyle summary from a \
player's structured coaching profile (leak trend states, stat trends, and \
evaluation count — all already computed).

Rules you MUST follow:
- Never invent a number, percentage, or count that is not present in the \
input JSON. Every figure you mention must come directly from it.
- Do not compute or state a trend direction, severity, or status yourself — \
use only the labels already given in the input.
- Write a short, encouraging but honest paragraph covering overall strengths \
and the most notable active leaks, in prose — no bullet points, no headers.
- Hard limit: {MAX_SUMMARY_CHARS} characters. Stay well under it.

Respond with ONLY the summary paragraph — no prose, no JSON, no code fences.
"""


async def generate_playstyle_summary(
    profile_state: dict,
    trends: dict,
    model: str = config.MODEL,
) -> str:
    """Return a fresh playstyle summary, or ``""`` without any LLM call when
    the profile has no folded evaluations yet."""
    if not profile_state.get("evaluations_folded"):
        return ""

    payload = json.dumps({
        "evaluations_folded": profile_state["evaluations_folded"],
        "leaks": profile_state["leaks"],
        "trends": trends,
    })

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": payload},
    ]

    result = await chat_model_with_usage(
        messages=messages,
        model=model,
        max_tokens=MAX_REPLY_TOKENS,
        temperature=1,
        log_context={"stage": "playstyle_summary"},
    )

    return result.text.strip()[:MAX_SUMMARY_CHARS]
