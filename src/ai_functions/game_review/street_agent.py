"""One parameterized LLM agent for street-level hand review (preflop/flop/turn/river).

Per the feature's architecture decisions: this is ONE agent implementation
configured per street (not four near-duplicate modules), it has NO tools, it
receives hands PUSHED to it in fixed-size batches, and it judges only
decisions on its own street even though each hand is provided in full (all
streets) for context. Findings never carry model-invented severities or
numbers — those come from ``leak_taxonomy``/``merge`` in code.
"""

from __future__ import annotations

import json
import logging

from poker_engine.db.models import Game, Hand
from shared_services.llm import chat_model_with_usage

from ai_functions.game_review import config
from ai_functions.game_review.hand_context import build_hand_text
from ai_functions.game_review.leak_taxonomy import JUDGMENT_TAGS

_prompt_log = logging.getLogger("prompts")

STREETS = ("preflop", "flop", "turn", "river")
BATCH_SIZE = 20
MAX_REPLY_TOKENS = 4096

_SYSTEM_PROMPT_TEMPLATE = """\
You are a poker hand-review agent reviewing only the {street} street.

You will be given several complete hands (all streets, for context) from a
single game. For each hand, judge ONLY the hero's decision(s) made on the
{street} street. Do not judge decisions the hero made on other streets.

Rules you MUST follow:
- Evaluate each {street} decision using only information that was available
  to the hero at that decision point. The eventual outcome of the hand
  (showdown result, later run-out, whether the hero ultimately won or lost
  the pot) must NEVER be used as evidence that a decision was good or bad.
  A decision that lost can still have been correct; a decision that won can
  still have been a mistake.
- Only use tags from this exact vocabulary: {tags}. Never invent a tag.
- Cite the exact `round_count` printed at the top of the hand block for every
  finding.
- Do not compute or state any statistic, percentage, or count in your notes —
  a one or two sentence qualitative note only.
- If nothing on the {street} street across these hands qualifies for a
  finding, return an empty list.

Respond with ONLY a JSON array (no prose, no code fences) where each element
is exactly:
{{"tag": "<one of {tags}>", "round_count": <int>, "note": "<one or two sentences>"}}
"""


def _batches(items: list, size: int) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _build_batch_message(street: str, batch: list[Hand], game: Game, hero_gp_id) -> str:
    blocks = []
    for hand in batch:
        text = build_hand_text(game, hand, hero_gp_id)
        blocks.append(f"round_count={hand.round_count}\n{text}")
    return "\n\n---\n\n".join(blocks)


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


def parse_findings(raw_text: str, batch: list[Hand], street: str) -> list[dict]:
    """Validate raw model output against the batch and the taxonomy.

    Drops (and logs) any finding whose tag isn't in ``JUDGMENT_TAGS`` or whose
    ``round_count`` doesn't belong to a hand in this batch. Never raises on
    malformed JSON — returns an empty list instead, so one bad batch can't
    crash the whole street-agent run.
    """
    try:
        raw = json.loads(_strip_fences(raw_text))
    except json.JSONDecodeError:
        _prompt_log.warning(
            "game_review.street_agent.parse_error",
            extra={"street": street, "raw_text": raw_text},
        )
        return []

    if not isinstance(raw, list):
        _prompt_log.warning(
            "game_review.street_agent.non_list_output",
            extra={"street": street, "raw_text": raw_text},
        )
        return []

    hands_by_round: dict[int, Hand] = {h.round_count: h for h in batch}
    findings: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        tag = item.get("tag")
        round_count = item.get("round_count")
        note = item.get("note", "")

        if tag not in JUDGMENT_TAGS:
            _prompt_log.warning(
                "game_review.street_agent.unknown_tag",
                extra={"street": street, "tag": tag, "round_count": round_count},
            )
            continue
        hand = hands_by_round.get(round_count)
        if hand is None:
            _prompt_log.warning(
                "game_review.street_agent.round_count_outside_batch",
                extra={"street": street, "tag": tag, "round_count": round_count},
            )
            continue

        findings.append({
            "tag": tag,
            "hand_id": str(hand.id),
            "round_count": round_count,
            "street": street,
            "note": note,
        })

    return findings


async def run_batch(
    street: str,
    batch: list[Hand],
    game: Game,
    hero_gp_id,
    model: str = config.MODEL,
) -> list[dict]:
    """Run one street-review batch: one non-streaming LLM call, no tools.

    This is the atomic, checkpointable unit of street-agent work — the async
    pipeline (Stage 4) calls this directly per ``game_evaluation_batches``
    row so a crash mid-run never has to recompute a completed batch.
    """
    tags_str = ", ".join(sorted(JUDGMENT_TAGS))
    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(street=street, tags=tags_str)
    user_content = _build_batch_message(street, batch, game, hero_gp_id)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
    result = await chat_model_with_usage(
        messages=messages,
        model=model,
        max_tokens=MAX_REPLY_TOKENS,
        temperature=1,  # gpt-5-mini only supports the default temperature
        log_context={"game_id": str(game.id), "street": street},
    )
    return parse_findings(result.text, batch, street)


async def run_street_agent(
    street: str,
    hands: list[Hand],
    game: Game,
    hero_gp_id,
    model: str = config.MODEL,
) -> list[dict]:
    """Run the street-review agent over ``hands`` (this street's triaged pool).

    Batches ``hands`` into fixed-size groups and calls ``run_batch`` per
    batch (sequentially — Stage 2/3's non-persistent, non-concurrent use;
    Stage 4's pipeline dispatches batches concurrently itself). Returns the
    flattened, validated findings across all batches.
    """
    if not hands:
        return []

    all_findings: list[dict] = []
    for batch in _batches(hands, BATCH_SIZE):
        all_findings.extend(await run_batch(street, batch, game, hero_gp_id, model))

    return all_findings
