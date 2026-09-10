"""Optional PokerAI presolved-preflop integration.

The provider returns solver-produced strategy frequencies, but its preflop
endpoint is a lookup over fixed 6-max packs rather than a live solve.  Pokerit
therefore exposes it as a presolved strategy reference and retains the exact
provider/version/node assumptions in every evidence record.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import math
import os
from typing import Any, Awaitable, Callable

import httpx

from .knowledge import normalize_starting_hand


POKERAI_BASE_URL = "https://pokerai.bet"
DEFAULT_PREFLOP_VERSION = "6max"
PREFLOP_LOOKUP_LIMIT_PER_HAND = 2
_ALLOWED_POSITIONS = frozenset({"SB", "BB", "UTG", "MP", "CO", "BTN"})
_POSITION_MAP = {"HJ": "MP"}
_ALLOWED_ACTIONS = frozenset({"fold", "call", "raise"})
_ALLOWED_SITUATIONS = frozenset({"RFI", "Limp", "Raise", "3-Bet", "4-Bet", "5-Bet"})


@dataclass(frozen=True)
class PokerAIQueryResult:
    evidence: dict[str, Any] | None
    failure: str | None = None
    attempted: bool = False


def configured_api_key() -> str | None:
    value = os.environ.get("POKERAI_API_KEY", "").strip()
    return value or None


def configured_preflop_version() -> str:
    configured = os.environ.get(
        "POKERAI_PREFLOP_VERSION", DEFAULT_PREFLOP_VERSION,
    ).strip()
    return configured or DEFAULT_PREFLOP_VERSION


def _position(value: Any) -> str | None:
    normalized = _POSITION_MAP.get(str(value or "").upper(), str(value or "").upper())
    return normalized if normalized in _ALLOWED_POSITIONS else None


def _cards(value: Any) -> str | None:
    cards = list(value or [])
    if len(cards) != 2:
        return None
    compact = "".join(str(card) for card in cards)
    if len(compact) != 4 or compact[:2].lower() == compact[2:].lower():
        return None
    if any(compact[index].upper() not in "23456789TJQKA" for index in (0, 2)):
        return None
    if any(compact[index].lower() not in "shdc" for index in (1, 3)):
        return None
    return compact[0].upper() + compact[1].lower() + compact[2].upper() + compact[3].lower()


def build_preflop_request(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    """Build one supported PokerAI request, or fail closed.

    PokerAI's single-hand contract accepts the action sequence before Hero's
    first preflop decision. Its whole-range endpoint also exposes later Hero
    decisions, so a re-decision retains the complete observed action line and
    is resolved from that endpoint instead of being rewritten into a new node.
    """
    if snapshot.get("street") != "preflop":
        return None
    facts = snapshot.get("known_facts") or {}
    derived = snapshot.get("derived_calculations") or {}
    ante = facts.get("ante") or {}
    if str(facts.get("format") or "").lower() != "cash":
        return None
    if int(facts.get("players_dealt") or 0) != 6:
        return None
    if ante.get("type") not in {None, "none"} or float(ante.get("amount") or 0) != 0:
        return None
    hero_stack_bb = float(derived.get("hero_stack_bb_at_decision") or 0)
    if not math.isfinite(hero_stack_bb) or hero_stack_bb <= 0:
        return None

    hero_position = _position(facts.get("hero_position"))
    hole_cards = _cards(facts.get("hero_cards"))
    if hero_position is None or hole_cards is None:
        return None

    blinds = facts.get("blinds") or {}
    big_blind = float(blinds.get("big") or 0)
    small_blind = float(blinds.get("small") or 0)
    if big_blind <= 0 or small_blind <= 0:
        return None

    actions: list[dict[str, Any]] = [
        {"position": "SB", "action": "small blind", "amount": small_blind / big_blind},
        {"position": "BB", "action": "big blind", "amount": 1.0},
    ]
    observed_raises: list[float] = []
    hero_acted_before = False
    for item in facts.get("action_history_before") or []:
        if item.get("actor") == "Hero":
            hero_acted_before = True
        position = _position(item.get("position"))
        action = str(item.get("action") or "").lower()
        if position is None or action not in _ALLOWED_ACTIONS:
            return None
        row: dict[str, Any] = {"position": position, "action": action}
        if action != "fold":
            amount_paid = float(item.get("amount_paid") or 0)
            if amount_paid <= 0:
                return None
            row["amount"] = amount_paid / big_blind
        if item.get("all_in"):
            row["allin"] = True
        if action == "raise":
            observed_raises.append(round(float(item.get("amount_to") or 0) / big_blind, 4))
        actions.append(row)

    return {
        "table_size": "6max",
        "hole_cards": hole_cards,
        "positions": {"hero": hero_position},
        "preflop_actions": actions,
        "preflop_version": configured_preflop_version(),
        "_pokerit": {
            "decision_id": snapshot.get("decision_id"),
            "hero_stack_bb": hero_stack_bb,
            "opponent_stacks": facts.get("opponent_stacks") or [],
            "hand_class": normalize_starting_hand(hole_cards),
            "use_range_endpoint": hero_acted_before,
            "observed_raise_sizes_bb": observed_raises,
        },
    }


def _expected_situation(request_body: dict[str, Any]) -> str:
    voluntary_actions = [
        item for item in request_body["preflop_actions"]
        if item.get("action") in _ALLOWED_ACTIONS
    ]
    raises = sum(item.get("action") == "raise" for item in voluntary_actions)
    has_call = any(item.get("action") == "call" for item in voluntary_actions)
    return (
        "Limp" if not raises and has_call else
        "RFI" if not raises else
        "Raise" if raises == 1 else
        "3-Bet" if raises == 2 else
        "4-Bet" if raises == 3 else
        "5-Bet"
    )


def _normalized_strategy(payload: dict[str, Any]) -> list[dict[str, Any]] | None:
    raw = payload.get("strategy")
    if not isinstance(raw, list) or not raw:
        return None
    strategy: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            return None
        action = str(item.get("action") or "").lower()
        if action not in _ALLOWED_ACTIONS:
            return None
        try:
            frequency = float(item.get("frequency"))
        except (TypeError, ValueError):
            return None
        if not math.isfinite(frequency) or not 0 <= frequency <= 1:
            return None
        normalized: dict[str, Any] = {
            "action": action,
            "frequency": round(frequency, 6),
        }
        for key in ("amount_bb", "sizing_pot"):
            if item.get(key) is not None:
                try:
                    value = float(item[key])
                except (TypeError, ValueError):
                    return None
                if not math.isfinite(value):
                    return None
                normalized[key] = value
        if item.get("allin") is True:
            normalized["all_in"] = True
        strategy.append(normalized)
    if not 0.98 <= sum(item["frequency"] for item in strategy) <= 1.02:
        return None
    return strategy


def _evidence_from_response(
    payload: dict[str, Any], request_body: dict[str, Any],
) -> dict[str, Any] | None:
    situation = str(payload.get("situation") or "")
    strategy = _normalized_strategy(payload)
    expected_situation = _expected_situation(request_body)
    if (
        situation not in _ALLOWED_SITUATIONS
        or situation != expected_situation
        or payload.get("hole_cards") != request_body["hole_cards"]
        or strategy is None
    ):
        return None
    private = request_body.get("_pokerit") or {}
    version = request_body["preflop_version"]
    reference_stack = {
        "6max": 100, "6max_RC_100bb_200NL": 100,
        "6max_RC_100bb_100NL": 100, "6max_RC_40bb": 40,
    }.get(version)
    hero_stack = private.get("hero_stack_bb")
    comparisons = []
    for opponent in private.get("opponent_stacks") or []:
        opponent_stack = opponent.get("starting_stack_bb")
        effective = min(hero_stack, opponent_stack) if hero_stack is not None and opponent_stack is not None else None
        comparisons.append({
            "position": opponent.get("position"), "opponent_starting_stack_bb": opponent_stack,
            "effective_stack_bb": effective,
            "difference_bb": round(effective - reference_stack, 2) if effective is not None and reference_stack else None,
            "difference_pct": round(100 * (effective / reference_stack - 1), 2) if effective is not None and reference_stack else None,
        })
    evidence = {
        "type": "preflop_strategy_api",
        "label": f"PokerAI presolved 6-max {reference_stack or 'unknown-depth'}BB preflop reference (fixed pack)",
        "provider": "PokerAI",
        "endpoint": str(private.get("endpoint") or "/v1/gto/preflop"),
        "version": request_body["preflop_version"],
        "decision_id": private.get("decision_id"),
        "node": situation,
        "hero_position": request_body["positions"]["hero"],
        "hero_cards": request_body["hole_cards"],
        "strategy": strategy,
        "observed_raise_sizes_bb": private.get("observed_raise_sizes_bb") or [],
        "solution_assumptions": {
            "table_size": 6,
            "stack_bb": reference_stack,
            "open_to_bb": 3,
            "three_bet_to_bb": 9,
            "four_bet_to_bb": 25,
            "five_bet_to_bb": 100,
            "frequencies_change_with_observed_sizing": False,
            "frequencies_change_with_actual_stack": False,
        },
        "stack_comparison": {
            "basis": "start-of-hand stacks, including chips already committed; opponents not yet folded",
            "reference_stack_bb": reference_stack,
            "hero_starting_stack_bb": hero_stack,
            "opponents": comparisons,
            "effective_stack_known": bool(comparisons) and all(row["effective_stack_bb"] is not None for row in comparisons),
            "interpretation": "Fixed-pack frequencies only. Depth effects require AI strategy judgment, not a computed EV error.",
        },
        "match_status": "presolved_reference",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }
    quota = payload.get("quota")
    if isinstance(quota, dict):
        try:
            used = int(quota.get("used"))
            quota_limit = int(quota.get("limit"))
        except (TypeError, ValueError):
            pass
        else:
            if used >= 0 and quota_limit > 0:
                evidence["quota_after_query"] = {
                    "used": used,
                    "limit": quota_limit,
                }
    return evidence


def _evidence_from_range_response(
    payload: dict[str, Any], request_body: dict[str, Any],
) -> dict[str, Any] | None:
    """Extract the current hand from a whole-range re-decision response."""
    private = request_body.get("_pokerit") or {}
    hand_class = str(private.get("hand_class") or "")
    ranges = payload.get("range")
    frequencies = ranges.get(hand_class) if isinstance(ranges, dict) else None
    if not isinstance(frequencies, dict):
        return None

    normalized_payload = {
        "hole_cards": request_body["hole_cards"],
        "situation": _expected_situation(request_body),
        "strategy": [
            {"action": action, "frequency": frequencies.get(action)}
            for action in ("fold", "call", "raise")
        ],
    }
    if payload.get("quota") is not None:
        normalized_payload["quota"] = payload["quota"]
    range_request = {
        **request_body,
        "_pokerit": {
            **private,
            "endpoint": "/v1/gto/preflop/range",
        },
    }
    return _evidence_from_response(normalized_payload, range_request)


async def query_preflop_strategy(
    snapshot: dict[str, Any],
    *,
    api_key: str | None = None,
    client: httpx.AsyncClient | None = None,
    retry_transient: bool = True,
) -> PokerAIQueryResult:
    request_body = build_preflop_request(snapshot)
    if request_body is None:
        return PokerAIQueryResult(None, "unsupported_spot")
    api_token = api_key or configured_api_key()
    if not api_token:
        return PokerAIQueryResult(None, "not_configured")

    private = request_body.get("_pokerit") or {}
    use_range_endpoint = private.get("use_range_endpoint") is True
    public_body = {
        field: value
        for field, value in request_body.items()
        if field != "_pokerit" and (field != "hole_cards" or not use_range_endpoint)
    }
    endpoint = "/v1/gto/preflop/range" if use_range_endpoint else "/v1/gto/preflop"
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=httpx.Timeout(5.0))
    try:
        attempts = 2 if retry_transient else 1
        for attempt in range(attempts):
            try:
                response = await http.post(
                    f"{POKERAI_BASE_URL}{endpoint}",
                    headers={"Authorization": f"Bearer {api_token}"},
                    json=public_body,
                )
            except httpx.RequestError:
                if attempt + 1 < attempts:
                    await asyncio.sleep(0.25)
                    continue
                return PokerAIQueryResult(None, "network_error", attempted=True)

            if response.status_code == 200:
                try:
                    payload = response.json()
                except ValueError:
                    return PokerAIQueryResult(
                        None, "invalid_response", attempted=True,
                    )
                evidence = (
                    _evidence_from_range_response(payload, request_body)
                    if use_range_endpoint
                    else _evidence_from_response(payload, request_body)
                )
                return PokerAIQueryResult(
                    evidence,
                    None if evidence is not None else "invalid_response",
                    attempted=True,
                )

            retryable = response.status_code >= 500
            if response.status_code == 429:
                try:
                    retryable = response.json().get("status") == "busy"
                except ValueError:
                    retryable = False
            if retryable and attempt + 1 < attempts:
                await asyncio.sleep(0.25)
                continue
            try:
                error_code = str(response.json().get("error") or response.status_code)
            except ValueError:
                error_code = str(response.status_code)
            return PokerAIQueryResult(
                None, f"provider_{error_code}", attempted=True,
            )
        return PokerAIQueryResult(None, "provider_error", attempted=True)
    except Exception:  # noqa: BLE001 - optional provider must always fail closed
        return PokerAIQueryResult(None, "client_error", attempted=True)
    finally:
        if owns_client:
            try:
                await http.aclose()
            except Exception:  # noqa: BLE001 - never break coaching on cleanup
                pass


def apply_pokerai_evidence(
    snapshot: dict[str, Any], evidence: dict[str, Any],
) -> dict[str, Any]:
    """Prefer successful API evidence while preserving local packs as fallback."""
    sources = [
        source
        for source in snapshot.get("evidence_sources") or []
        if source.get("type") != "range_knowledge_base"
    ]
    sources.append(evidence)
    snapshot["evidence_sources"] = sources
    return snapshot


async def query_postgame_snapshots(
    snapshots: list[dict[str, Any]],
    *,
    limit: int,
    query: Callable[[dict[str, Any]], Awaitable[PokerAIQueryResult]] | None = None,
) -> dict[str, Any]:
    """Query up to the per-hand decision limit, capped per evaluation.

    The default provider call does not retry, so ``limit`` is also a strict
    upper bound on post-game HTTP requests, not merely selected decisions.
    """
    limit = max(0, int(limit))
    selected: list[dict[str, Any]] = []
    selected_per_round: dict[int, int] = {}
    for snapshot in snapshots:
        round_count = int(snapshot.get("round_count") or 0)
        if (
            selected_per_round.get(round_count, 0) >= PREFLOP_LOOKUP_LIMIT_PER_HAND
            or build_preflop_request(snapshot) is None
        ):
            continue
        selected.append(snapshot)
        selected_per_round[round_count] = selected_per_round.get(round_count, 0) + 1
        if len(selected) >= limit:
            break

    evidence_by_decision: dict[str, dict[str, Any]] = {}
    failures: list[dict[str, str]] = []
    quota_after: dict[str, int] | None = None
    for snapshot in selected:
        decision_id = str(snapshot.get("decision_id") or "")
        try:
            result = (
                await query(snapshot)
                if query is not None
                else await query_preflop_strategy(snapshot, retry_transient=False)
            )
        except Exception:  # noqa: BLE001 - keep the remaining capped batch usable
            failures.append({"decision_id": decision_id, "reason": "client_error"})
            continue
        if result.evidence is not None:
            evidence_by_decision[decision_id] = result.evidence
            if isinstance(result.evidence.get("quota_after_query"), dict):
                quota_after = result.evidence["quota_after_query"]
        else:
            failures.append({"decision_id": decision_id, "reason": result.failure or "unknown"})

    metadata = {
        "configured": configured_api_key() is not None,
        "version": configured_preflop_version(),
        "call_limit": limit,
        "attempted": len(selected),
        "resolved": len(evidence_by_decision),
        "failures": failures,
        "evidence_by_decision": evidence_by_decision,
    }
    if quota_after is not None:
        metadata["quota_after"] = quota_after
    return metadata
