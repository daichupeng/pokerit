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
import re

from sqlalchemy.orm import Session

from poker_engine.db.models import Game, User

from ai_functions.game_review import config
from ai_functions.coach_engine.engine import build_scenario_context
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

_AGGRESSION_TAGS = frozenset({"too_passive_postflop", "too_aggressive_postflop"})
_AGGRESSION_CLAIM_RE = re.compile(
    r"aggression factor|\bAF\b|aggressive actions?|passive actions?",
    re.IGNORECASE,
)

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
- For every judgment section, include 1-3 of its cited hands as concrete
  examples. Each example must state the hero's actual action, the strategic
  issue, a better realistic line or size, and why the alternative improves EV.
  Add a future-street plan when useful. A hand number by itself is not an
  explanation. Stat sections may omit examples because one hand cannot prove a
  game-level frequency leak.
- This report evaluates only the current game. Describe its findings as
  current-game observations, never as rolling-history conclusions. A metric
  marked insufficient sample must not be implied to be a leak.
- A percentage whose denominator is zero is undefined, not 0%. Never describe
  a 0/0 metric as success, failure, passivity, aggression, or showdown output.
- Postflop aggression factor has one exact definition here:
  (postflop bets + raises) / postflop calls. For an aggression leak's evidence,
  `bets_raises` is the numerator and `calls` is the denominator. Checks and
  folds are not in either count. Never reverse these counts and never call the
  denominator "passive actions"; it is specifically calls.
- If pinned context includes a "player_profile", it summarizes the hero's \
coaching history from prior games, and each leak_tag may carry a \
"profile_status" of "new", "returning" (a recurring, previously flagged or \
confirmed leak), or "regressing" (a leak the hero had previously resolved \
that has now reappeared). Frame each section's narrative accordingly — \
briefly note when a leak is returning or regressing rather than presenting \
it as if seen for the first time. If the profile lists leaks that are \
"resolved" and NOT present in this game's leak_tags, you may briefly \
acknowledge that progress in the overall summary. Never treat the profile \
itself as evidence for this game: every claim about THIS game must still \
cite this game's own data or a tool result, never the profile.

Respond with ONLY a JSON object (no prose, no code fences) of the exact shape:
{"summary": "<2-4 sentence overall assessment>",
 "sections": [{"tag": "<a tag from the pinned leak_tags>",
   "narrative": "<brief pattern-level coaching narrative for this tag>",
   "examples": [{"round_count": <cited int>, "street": "<cited street>",
     "hero_action": "<what hero did>", "issue": "<what was wrong>",
     "better_line": "<better action/size>", "why": "<why it gains EV>",
     "future_plan": "<optional plan>", "confidence": "high|medium|low"}]}]}
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


def _aggression_evidence_for_context(leak: dict) -> dict:
    """Give the model named AF operands instead of ambiguous ``n``/``d``."""
    enriched = dict(leak)
    if leak.get("tag") not in _AGGRESSION_TAGS:
        return enriched
    evidence = dict(leak.get("evidence") or {})
    evidence.update({
        "formula": "postflop bets+raises / postflop calls",
        "bets_raises": evidence.get("n", 0),
        "calls": evidence.get("d", 0),
    })
    enriched["evidence"] = evidence
    return enriched


def _canonical_aggression_sentence(leak: dict) -> str:
    evidence = leak.get("evidence") or {}
    bets_raises = int(evidence.get("n", 0) or 0)
    calls = int(evidence.get("d", 0) or 0)
    if evidence.get("infinite"):
        value = "infinite"
    else:
        value = str(evidence.get("ratio"))
    aggressive_label = "bet/raise" if bets_raises == 1 else "bets/raises"
    call_label = "call" if calls == 1 else "calls"
    return (
        f"Postflop aggression factor is {value}, calculated from "
        f"{bets_raises} {aggressive_label} and {calls} {call_label}; "
        "checks and folds are excluded from AF."
    )


def _guard_aggression_narrative(narrative: str, leak: dict) -> str:
    """Replace model-written AF arithmetic with one deterministic sentence."""
    sentences = re.split(r"(?<=[.!?])\s+", str(narrative or "").strip())
    qualitative = [sentence for sentence in sentences if not _AGGRESSION_CLAIM_RE.search(sentence)]
    return " ".join([_canonical_aggression_sentence(leak), *qualitative]).strip()


def _guard_summary_aggression_claims(summary: str) -> str:
    """Keep AF arithmetic in its validated section, not free-form summary text."""
    sentences = re.split(r"(?<=[.!?])\s+", str(summary or "").strip())
    return " ".join(
        sentence
        for sentence in sentences
        if not (_AGGRESSION_CLAIM_RE.search(sentence) and re.search(r"\d", sentence))
    ).strip()


def normalize_report_evidence(report: dict | None) -> dict | None:
    """Apply deterministic evidence wording to new and already-saved reports."""
    if not isinstance(report, dict):
        return report
    normalized = dict(report)
    normalized["summary"] = _guard_summary_aggression_claims(report.get("summary", ""))
    sections = []
    for raw_section in report.get("sections") or []:
        section = dict(raw_section)
        if section.get("tag") in _AGGRESSION_TAGS:
            section["narrative"] = _guard_aggression_narrative(
                section.get("narrative", ""), section,
            )
        sections.append(section)
    normalized["sections"] = sections
    return normalized


_REQUIRED_EXAMPLE_FIELDS = ("hero_action", "issue", "better_line", "why")


def _validated_examples(item: dict, leak: dict) -> list[dict]:
    """Ground model-written examples in authoritative street citations."""
    citations = [c for c in leak.get("citations") or [] if isinstance(c, dict)]
    by_key = {(c.get("round_count"), c.get("street")): c for c in citations}
    by_round = {c.get("round_count"): c for c in citations}

    raw_examples = item.get("examples") or []
    if not isinstance(raw_examples, list):
        raw_examples = []
    # If synthesis omitted examples, structured street findings are still a
    # useful deterministic fallback. Legacy note-only citations are excluded.
    candidates = [*raw_examples, *citations[:3]]
    examples = []
    seen = set()
    for raw in candidates[:3]:
        if not isinstance(raw, dict):
            continue
        round_count = raw.get("round_count")
        street = raw.get("street")
        citation = by_key.get((round_count, street)) or by_round.get(round_count)
        if citation is None:
            continue
        key = (citation.get("round_count"), citation.get("street"))
        if key in seen:
            continue
        merged = {**citation, **raw}
        cleaned = {}
        for field in (*_REQUIRED_EXAMPLE_FIELDS, "future_plan"):
            value = merged.get(field)
            if isinstance(value, str) and value.strip():
                cleaned[field] = value.strip()
        if any(field not in cleaned for field in _REQUIRED_EXAMPLE_FIELDS):
            continue
        confidence = str(merged.get("confidence") or "medium").lower()
        if confidence not in {"high", "medium", "low"}:
            confidence = "medium"
        examples.append({
            "hand_id": citation.get("hand_id"),
            "round_count": citation.get("round_count"),
            "street": citation.get("street"),
            **cleaned,
            "confidence": confidence,
            # Source categories are attached by deterministic snapshot code,
            # never generated or rewritten by synthesis.
            "evidence_sources": citation.get("evidence_sources") or [],
        })
        seen.add(key)
    return examples


def _validate_sections(
    raw_sections: list, leak_tags_by_tag: dict[str, dict], profile_status_by_tag: dict[str, str]
) -> list[dict]:
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
        sections.append({
            **leak,
            "narrative": item.get("narrative", ""),
            "examples": _validated_examples(item, leak),
            # Set from code, never trusted from the model (decision 5).
            "profile_status": profile_status_by_tag.get(tag),
        })
    return sections


def _parse_report(raw_text: str, leak_tags: list[dict], profile_status_by_tag: dict[str, str]) -> dict:
    leak_tags_by_tag = {lt["tag"]: lt for lt in leak_tags}
    try:
        parsed = json.loads(_strip_fences(raw_text))
    except json.JSONDecodeError:
        _prompt_log.warning("game_review.synthesis.parse_error", extra={"raw_text": raw_text})
        return {"summary": "", "sections": []}

    if not isinstance(parsed, dict):
        return {"summary": "", "sections": []}

    sections = _validate_sections(parsed.get("sections") or [], leak_tags_by_tag, profile_status_by_tag)
    sections.sort(key=lambda s: -s["severity"])

    return normalize_report_evidence({
        "summary": _guard_summary_aggression_claims(parsed.get("summary", "")),
        "sections": sections,
    })


async def run_synthesis(
    stats_snapshot: dict,
    session_dynamics: dict,
    leak_tags: list[dict],
    db: Session,
    game_id: str,
    user: User,
    model: str = config.MODEL,
    player_profile: dict | None = None,
    profile_status_by_tag: dict[str, str] | None = None,
    sample_status: dict | None = None,
) -> dict:
    """Run the synthesis agent and return the parsed report plus tool-call/usage history.

    ``player_profile`` (leak states + trends + summary, read BEFORE this
    evaluation folds itself in) and ``profile_status_by_tag`` (this game's
    leak tags mapped to "new"/"returning"/"regressing", computed by
    ``ai_functions.memory.profile_status``) are both omitted cleanly when the
    user has no profile yet — a first-ever evaluation runs with no
    "player_profile" key in pinned context at all.
    """
    profile_status_by_tag = profile_status_by_tag or {}
    leak_tags_for_context = []
    for leak in leak_tags:
        enriched = _aggression_evidence_for_context(leak)
        if leak["tag"] in profile_status_by_tag:
            enriched["profile_status"] = profile_status_by_tag[leak["tag"]]
        leak_tags_for_context.append(enriched)
    context = {
        "stats_snapshot": stats_snapshot,
        "session_dynamics": session_dynamics,
        "leak_tags": leak_tags_for_context,
    }
    if sample_status is not None:
        context["sample_status"] = sample_status
    if player_profile is not None:
        context["player_profile"] = player_profile
    pinned_context = json.dumps(context)

    game = db.get(Game, game_id)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *(
            [{"role": "system", "content": build_scenario_context(game)}]
            if game is not None
            else []
        ),
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
        temperature=1,  # Ignored by the wrapper for reasoning models.
        log_context={"game_id": str(game_id), "user_id": str(user.id)},
    )

    report = _parse_report(result.final_text, leak_tags, profile_status_by_tag)

    return {"report": report, "tool_calls": result.tool_calls, "usage": result.usage}
