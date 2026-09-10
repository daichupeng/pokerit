"""One parameterized LLM agent for street-level hand review (preflop/flop/turn/river).

Per the feature's architecture decisions: this is ONE agent implementation
configured per street (not four near-duplicate modules), it has NO tools, it
receives point-in-time Decision Snapshots in fixed-size batches, and it judges
only decisions on its own street. Findings never carry model-invented severities or
numbers — those come from ``leak_taxonomy``/``merge`` in code.
"""

from __future__ import annotations

import json
import logging

from poker_engine.db.models import Game, Hand
from ai_functions.coach_engine.engine import build_scenario_context
from ai_functions.decision_snapshot import build_decision_snapshots
from shared_services.llm import chat_model_with_usage

from ai_functions.game_review import config
from ai_functions.game_review.leak_taxonomy import (
    ALL_JUDGMENT_TAGS,
    judgment_tags_for_profile,
    threshold_profile_key_for_game,
)

_prompt_log = logging.getLogger("prompts")

STREETS = ("preflop", "flop", "turn", "river")
BATCH_SIZE = 20
MAX_REPLY_TOKENS = 4096

_SYSTEM_PROMPT_TEMPLATE = """\
You are a poker hand-review agent reviewing only the {street} street.

You will be given point-in-time Decision Snapshots from a single game. For each
snapshot, judge ONLY the hero's decision on the {street} street.

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
- Do not compute or state game-level statistics, percentages, or frequencies.
  Exact actions and sizes already printed in the hand history may be quoted.
- For every finding, identify the hero's actual action, the strategic problem,
  a better realistic line, and why that line has higher expected value. Do not
  use the eventual result as the reason.
- If nothing on the {street} street across these hands qualifies for a
  finding, return an empty list.
- Treat configured bot styles (for example TAG or AI GTO) only as simulation
  metadata. They are not observed population reads and AI GTO is not proof a
  matching solver node was used.
- Name the evidence category behind the conclusion. Exact solver frequencies
  or EV are forbidden unless a `solver_node` evidence source is present.

Respond with ONLY a JSON array (no prose, no code fences) where each element
is exactly:
{{"tag": "<one of {tags}>", "round_count": <int>,
  "hero_action": "<the action being reviewed>",
  "issue": "<what is strategically wrong>",
  "better_line": "<a better action or size>",
  "why": "<why the alternative gains EV>",
  "future_plan": "<optional next-street plan>",
  "confidence": "high|medium|low"}}
"""

_PUSH_FOLD_FOCUS = """\
This is a short-stack Push/Fold profile. On preflop, prioritize only:
- open-shove selection,
- reshove selection after an open,
- call-off selection facing a shove.
Use the dedicated shove/reshove/call-off tags. Do not substitute postflop
aggression or C-bet concepts for these preflop decisions.
"""


def _batches(items: list, size: int) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _build_batch_message(street: str, batch: list[Hand], game: Game, hero_gp_id) -> tuple[str, dict[int, list[dict]]]:
    snapshots = []
    evidence_by_round: dict[int, list[dict]] = {}
    for hand in batch:
        hand_snapshots = build_decision_snapshots(game, hand, hero_gp_id, street)
        snapshots.extend(hand_snapshots)
        evidence_by_round[hand.round_count] = [
            source
            for snapshot in hand_snapshots
            for source in snapshot.get("evidence_sources", [])
        ]
    return json.dumps(snapshots, ensure_ascii=False, indent=2), evidence_by_round


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


def parse_findings(
    raw_text: str,
    batch: list[Hand],
    street: str,
    allowed_tags: frozenset[str] = ALL_JUDGMENT_TAGS,
    require_explanation: bool = False,
) -> list[dict]:
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

        if tag not in allowed_tags:
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

        required = ("hero_action", "issue", "better_line", "why")
        if require_explanation and any(
            not isinstance(item.get(key), str) or not item[key].strip()
            for key in required
        ):
            raise ValueError(
                f"Incomplete {street} finding for round_count={round_count}; "
                "hero_action, issue, better_line, and why are required"
            )

        finding = {
            "tag": tag,
            "hand_id": str(hand.id),
            "round_count": round_count,
            "street": street,
            "note": note,
        }
        # Preserve the structured decision explanation for synthesis. Keeping
        # legacy ``note`` support makes resumed pre-upgrade batches readable.
        for key in ("hero_action", "issue", "better_line", "why", "future_plan", "confidence"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                finding[key] = value.strip()
        findings.append(finding)

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
    profile_key = threshold_profile_key_for_game(game)
    allowed_tags = judgment_tags_for_profile(profile_key, street)
    tags_str = ", ".join(sorted(allowed_tags))
    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(street=street, tags=tags_str)
    if profile_key == "mtt_8max_15bb" and street == "preflop":
        system_prompt += "\n" + _PUSH_FOLD_FOCUS
    user_content, evidence_by_round = _build_batch_message(street, batch, game, hero_gp_id)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "system", "content": build_scenario_context(game)},
        {"role": "user", "content": user_content},
    ]
    result = await chat_model_with_usage(
        messages=messages,
        model=model,
        max_tokens=MAX_REPLY_TOKENS,
        temperature=1,  # Ignored by the wrapper for reasoning models.
        log_context={"game_id": str(game.id), "street": street},
    )
    findings = parse_findings(
        result.text, batch, street, allowed_tags, require_explanation=True,
    )
    for finding in findings:
        # Evidence labels come from code-built snapshots, never model text.
        deduped = {}
        for source in evidence_by_round.get(finding["round_count"], []):
            deduped[(source.get("type"), source.get("pack_id"))] = source
        finding["evidence_sources"] = list(deduped.values())
    return findings


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
