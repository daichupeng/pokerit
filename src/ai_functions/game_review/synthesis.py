"""Synthesis agent — the one LLM stage that PULLS via tools.

Receives the stats snapshot, session dynamics, and all merged leak tags as
pinned context, and has all five tools (hand_lookup, equity_calculator,
stats_query, pot_odds, hand_search) to verify claims before making them.
Severity/kind/citations for each report section always come from the
already-merged ``leak_tags`` (code), never from the model — the model only
supplies the narrative text per tag and must ground every number in pinned
context or a tool result.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

from poker_engine.db.models import User

from ai_functions.game_review import config
from ai_functions.tools.executors import (
    make_equity_calculator_tool,
    make_hand_lookup_tool,
    make_hand_search_tool,
    make_pot_odds_tool,
    make_stats_query_tool,
)
from ai_functions.tools.loop import run_tool_loop
from ai_functions.tools.schemas import ALL_TOOL_SCHEMAS

_prompt_log = logging.getLogger("prompts")

MAX_REPLY_TOKENS = 4096

SYSTEM_PROMPT = """\
You are a poker coaching synthesis agent. You are given, as pinned context, \
a hero's game-level stats snapshot, a session-dynamics breakdown, and a list \
of already-identified leak tags (each with its severity and citations or \
evidence already computed). Your job is to write the coaching report.

Rules you MUST follow:
- Every numeric claim in your narrative (a percentage, a count, a chip \
amount) must come directly from the pinned context or from a tool result you \
obtained in this conversation. Never state a number you did not get from one \
of those two sources. Use the tools (hand_lookup, equity_calculator, \
stats_query, pot_odds, hand_search) to verify specific claims before making \
them, rather than asserting them from memory.
- Reconcile findings from multiple street agents on the same hand into one \
coherent, line-level narrative rather than listing them separately.
- Structure your report around the highest-severity leak tags first.
- Do not invent a severity, a kind, or a citation — those are already fixed \
by the pinned leak tags; only add narrative text.
- Cite round_counts for any hand you reference.

Respond with ONLY a JSON object (no prose, no code fences) of the exact shape:
{"summary": "<2-4 sentence overall assessment>",
 "sections": [{"tag": "<a tag from the pinned leak_tags>", "narrative": "<coaching narrative for this tag>"}]}
"""


def _strip_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines)
    return stripped.strip()


def _validate_sections(raw_sections: list, leak_tags_by_tag: dict[str, dict]) -> list[dict]:
    sections = []
    seen_tags = set()
    for item in raw_sections:
        if not isinstance(item, dict):
            continue
        tag = item.get("tag")
        if tag in seen_tags:
            continue
        leak = leak_tags_by_tag.get(tag)
        if leak is None:
            _prompt_log.warning("game_review.synthesis.unknown_tag", extra={"tag": tag})
            continue
        seen_tags.add(tag)
        sections.append({**leak, "narrative": item.get("narrative", "")})
    return sections


def _parse_report(raw_text: str, leak_tags: list[dict]) -> dict:
    leak_tags_by_tag = {lt["tag"]: lt for lt in leak_tags}
    try:
        parsed = json.loads(_strip_fences(raw_text))
    except json.JSONDecodeError:
        _prompt_log.warning("game_review.synthesis.parse_error", extra={"raw_text": raw_text})
        return {"summary": "", "sections": []}

    if not isinstance(parsed, dict):
        return {"summary": "", "sections": []}

    sections = _validate_sections(parsed.get("sections") or [], leak_tags_by_tag)
    sections.sort(key=lambda s: -s["severity"])

    return {"summary": parsed.get("summary", ""), "sections": sections}


async def run_synthesis(
    stats_snapshot: dict,
    session_dynamics: dict,
    leak_tags: list[dict],
    db: Session,
    game_id: str,
    user: User,
    model: str = config.MODEL,
) -> dict:
    """Run the synthesis agent and return the parsed report plus tool-call/usage history."""
    pinned_context = json.dumps({
        "stats_snapshot": stats_snapshot,
        "session_dynamics": session_dynamics,
        "leak_tags": leak_tags,
    })

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": pinned_context},
    ]

    executors = {
        "hand_lookup": make_hand_lookup_tool(db, game_id, user),
        "equity_calculator": make_equity_calculator_tool(),
        "stats_query": make_stats_query_tool(db, game_id, user),
        "pot_odds": make_pot_odds_tool(),
        "hand_search": make_hand_search_tool(db, game_id, user),
    }

    result = await run_tool_loop(
        messages=messages,
        model=model,
        tools=ALL_TOOL_SCHEMAS,
        executors=executors,
        max_tokens=MAX_REPLY_TOKENS,
        temperature=1,  # gpt-5-mini only supports the default temperature
        log_context={"game_id": str(game_id), "user_id": str(user.id)},
    )

    report = _parse_report(result.final_text, leak_tags)

    return {"report": report, "tool_calls": result.tool_calls, "usage": result.usage}
