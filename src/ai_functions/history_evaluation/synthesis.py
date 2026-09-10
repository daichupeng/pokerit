"""One optional, tool-free LLM narration over deterministic history JSON."""

from __future__ import annotations

import json

from ai_functions.game_review import config
from shared_services.llm import chat_model_with_usage

MAX_REPLY_TOKENS = 1200
MAX_SUMMARY_CHARS = 1800

SYSTEM_PROMPT = """You summarize a deterministic poker statistics history report.
All percentages, sample statuses, trend directions, leak tags, and severities have
already been computed by code. Never calculate, alter, add, or imply a leak that
is not in deterministic_stat_leaks. Never imply a conclusion for a metric marked
insufficient_sample. Do not mention individual hands or citations. Clearly call
the latest-game values current-game observations and rolling-window leaks
rolling-history conclusions. Return JSON only:
{"summary":"...","sections":[{"tag":"existing tag","narrative":"..."}]}
"""


def _fallback(leaks: list[dict]) -> dict:
    return {
        "summary": "Deterministic rolling statistics are available below. Sample readiness is shown per metric.",
        "sections": [{"tag": leak["tag"], "narrative": "This rolling-window conclusion passed its configured sample floor."}
                     for leak in leaks],
    }


def _usage_dict(usage) -> dict:
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", 0),
        "completion_tokens": getattr(usage, "completion_tokens", 0),
    }


async def synthesize(payload: dict, model: str = config.MODEL) -> tuple[dict, dict]:
    leaks = payload.get("deterministic_stat_leaks") or []
    allowed = {leak["tag"]: leak for leak in leaks}
    fallback = _fallback(leaks)
    result = await chat_model_with_usage(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload)},
        ],
        model=model,
        max_tokens=MAX_REPLY_TOKENS,
        temperature=1,
        reasoning_effort="none",
        log_context={"stage": "history_synthesis"},
    )
    try:
        parsed = json.loads(result.text.strip())
    except (json.JSONDecodeError, AttributeError):
        return fallback, _usage_dict(result.usage)
    sections = []
    seen = set()
    for item in parsed.get("sections") or []:
        tag = item.get("tag") if isinstance(item, dict) else None
        if tag not in allowed or tag in seen:
            continue
        seen.add(tag)
        sections.append({**allowed[tag], "narrative": str(item.get("narrative", ""))})
    report = {
        "summary": str(parsed.get("summary", ""))[:MAX_SUMMARY_CHARS],
        "sections": sections,
    }
    return report, _usage_dict(result.usage)
