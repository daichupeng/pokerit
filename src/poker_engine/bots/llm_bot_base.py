"""LLM-driven bot base.

Drop-in replacement for StyleBot: exposes the same ``declare_action`` /
``set_n_players`` interface so the engine needs no changes.

Subclass ``LLMBot`` to define ``style_name``, ``system_prompt``, ``model``,
and optionally ``temperature`` — see ``llm_styles.py`` for examples.
"""

from __future__ import annotations

import asyncio
import json
import re
import threading

from shared_services.llm import chat_model
from shared_services.table_formatter import format_table

# Each thread gets its own event loop so asyncio.run() doesn't conflict with
# the main loop when declare_action is called from asyncio.to_thread().
_thread_local = threading.local()


def _run_sync(coro):
    """Run an async coroutine synchronously from any thread."""
    try:
        loop = _thread_local.loop
    except AttributeError:
        loop = asyncio.new_event_loop()
        _thread_local.loop = loop
    return loop.run_until_complete(coro)


DEFAULT_MODEL = "gpt-4.1-mini"
DEFAULT_TEMPERATURE = 0.7

_ACTION_SCHEMA = """\
Respond with a single JSON object and nothing else:
  {"action": "fold"}
  {"action": "call"}
  {"action": "raise", "amount": <integer>}
Do NOT include any explanation outside the JSON."""


class LLMBot:
    """LLM-powered bot with the same interface as StyleBot.

    Subclasses set class-level attributes to customise behaviour:
      - ``style_name``   – recorded in the game log
      - ``system_prompt`` – injected as the system message
      - ``model``         – any model supported by shared_services.llm
      - ``temperature``   – sampling temperature (default 0.7)
    """

    style_name: str = "llm"
    system_prompt: str = (
        "You are a poker bot playing No-Limit Texas Hold'em. "
        "Play rationally and aim for a GTO-adjacent strategy."
    )
    model: str = DEFAULT_MODEL
    temperature: float = DEFAULT_TEMPERATURE

    def __init__(self) -> None:
        self._n_players = 2

    def set_n_players(self, n: int) -> None:
        self._n_players = max(2, n)

    # ------------------------------------------------------------------
    # Core decision
    # ------------------------------------------------------------------

    def declare_action(
        self,
        valid_actions: list[dict],
        hole_card: list[str],
        round_state: dict,
    ) -> tuple[str, int]:
        community = round_state.get("community_card", [])


        user_message = _build_prompt(valid_actions, hole_card, round_state)
        system = f"{self.system_prompt}\n\n{_ACTION_SCHEMA}"

        raw = _run_sync(
            chat_model(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_message},
                ],
                model=self.model,
                max_tokens=1024,
                temperature=self.temperature,
            )
        )
        # Strip reasoning blocks (<think>...</think>) produced by models like qwen3.
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        return _parse_response(raw, valid_actions)


# ------------------------------------------------------------------
# Prompt builder
# ------------------------------------------------------------------

_BOT_SENTINEL_UUID = "__bot__"


def _build_prompt(
    valid_actions: list[dict],
    hole_card: list[str],
    round_state: dict,
) -> str:
    # Identify the bot's uuid by matching hole cards; fall back to sentinel.
    hole_cards_by_uuid: dict[str, list[str]] = round_state.get("hole_cards_by_uuid", {})
    hero_uuid = next(
        (uuid for uuid, cards in hole_cards_by_uuid.items() if sorted(cards) == sorted(hole_card)),
        _BOT_SENTINEL_UUID,
    )

    # Inject hole cards under sentinel if not found (e.g. not yet stored).
    rs = round_state
    if hero_uuid == _BOT_SENTINEL_UUID:
        rs = {**round_state, "hole_cards_by_uuid": {**hole_cards_by_uuid, _BOT_SENTINEL_UUID: hole_card}}

    table_summary = format_table(rs, hero_uuid)

    call_action = next((a for a in valid_actions if a["action"] == "call"), None)
    raise_action = next((a for a in valid_actions if a["action"] == "raise"), None)

    call_amount = call_action["amount"] if call_action else 0
    raise_min = raise_max = None
    if raise_action:
        bounds = raise_action.get("amount", {})
        if isinstance(bounds, dict) and bounds.get("min", -1) != -1:
            raise_min = bounds["min"]
            raise_max = bounds["max"]

    lines = [table_summary, ""]
    if raise_min is not None:
        lines.append(f"To call: {call_amount}  |  Raise range: {raise_min}–{raise_max}")
    else:
        lines.append(f"To call: {call_amount}  |  Raise: not available")

    lines.append("\nDecide your action.")
    return "\n".join(lines)


# ------------------------------------------------------------------
# Response parser
# ------------------------------------------------------------------

def _parse_response(text: str, valid_actions: list[dict]) -> tuple[str, int]:
    fold = next((a for a in valid_actions if a["action"] == "fold"), None)
    call = next((a for a in valid_actions if a["action"] == "call"), None)
    raise_action = next((a for a in valid_actions if a["action"] == "raise"), None)

    # Try JSON first
    try:
        match = re.search(r"\{.*?\}", text, re.DOTALL)
        if match:
            obj = json.loads(match.group())
            action = obj.get("action", "").lower()
            if action == "fold" and fold:
                return "fold", 0
            if action in ("call", "check") and call:
                return "call", call["amount"]
            if action == "raise" and raise_action:
                amt = int(obj.get("amount", 0))
                amt = _clamp_raise(amt, raise_action)
                if amt is not None:
                    return "raise", amt
    except (json.JSONDecodeError, ValueError):
        pass

    # Fallback: keyword scan
    t = text.strip().lower()
    if t.startswith("fold"):
        return ("fold", 0) if fold else ("call", call["amount"] if call else 0)
    if t.startswith(("call", "check")):
        return "call", (call["amount"] if call else 0)
    if t.startswith("raise") and raise_action:
        nums = re.findall(r"\d+", t)
        amt = int(nums[0]) if nums else None
        clamped = _clamp_raise(amt, raise_action) if amt is not None else None
        if clamped is not None:
            return "raise", clamped

    # Default: call / check if possible, else fold
    if call:
        return "call", call["amount"]
    return "fold", 0


def _clamp_raise(amount: int, raise_action: dict) -> int | None:
    bounds = raise_action.get("amount", {})
    if not isinstance(bounds, dict):
        return None
    lo, hi = bounds.get("min", -1), bounds.get("max", -1)
    if lo == -1 or hi == -1:
        return None
    return max(lo, min(amount, hi))
