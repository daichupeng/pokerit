"""Versioned, validated account preferences used by game sessions."""

from __future__ import annotations

from typing import Any


BET_SHORTCUTS_KEY = "bet_shortcuts_v1"
SHOWDOWN_VISIBILITY_KEY = "showdown_visibility_v1"
DEFAULT_PREFLOP_QUICK = [2.0, 2.5, 6.0, 7.5]
DEFAULT_POSTFLOP_QUICK = [33.0, 50.0, 65.0, 100.0]
DEFAULT_SHOWDOWN_VISIBILITY = "realistic"
SHOWDOWN_VISIBILITY_MODES = frozenset({"realistic", "training"})


def validate_quick_sizes(values: Any, *, field: str) -> list[float]:
    """Validate one quick-size row and return a normalized copy."""
    if not isinstance(values, list):
        raise ValueError(f"{field} must be a list.")
    if not 1 <= len(values) <= 5:
        raise ValueError(f"{field} must contain between 1 and 5 sizes.")
    normalized: list[float] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{field} sizes must be numbers.")
        number = float(value)
        if number <= 0 or number > 1000:
            raise ValueError(f"{field} sizes must be greater than 0 and at most 1000.")
        normalized.append(number)
    return normalized


def bet_shortcuts_from_preferences(preferences: dict | None) -> tuple[list[float], list[float]]:
    """Read account shortcuts, falling back field-by-field to product defaults."""
    raw = (preferences or {}).get(BET_SHORTCUTS_KEY)
    if not isinstance(raw, dict):
        return list(DEFAULT_PREFLOP_QUICK), list(DEFAULT_POSTFLOP_QUICK)
    try:
        preflop = validate_quick_sizes(raw.get("preflop"), field="preflop")
    except ValueError:
        preflop = list(DEFAULT_PREFLOP_QUICK)
    try:
        postflop = validate_quick_sizes(raw.get("postflop"), field="postflop")
    except ValueError:
        postflop = list(DEFAULT_POSTFLOP_QUICK)
    return preflop, postflop


def validate_showdown_visibility(value: Any) -> str:
    """Validate the account-wide showdown visibility mode."""
    if not isinstance(value, str) or value not in SHOWDOWN_VISIBILITY_MODES:
        allowed = ", ".join(sorted(SHOWDOWN_VISIBILITY_MODES))
        raise ValueError(f"showdown visibility must be one of: {allowed}.")
    return value


def showdown_visibility_from_preferences(preferences: dict | None) -> str:
    """Return the saved visibility mode, falling back to realistic rules."""
    raw = (preferences or {}).get(SHOWDOWN_VISIBILITY_KEY)
    try:
        return validate_showdown_visibility(raw)
    except ValueError:
        return DEFAULT_SHOWDOWN_VISIBILITY


def merge_preferences(current: dict | None, update: dict) -> dict:
    """Shallow-merge preferences while validating the versioned known section."""
    merged = dict(current or {})
    for key, value in update.items():
        if key == SHOWDOWN_VISIBILITY_KEY:
            merged[key] = validate_showdown_visibility(value)
            continue
        if key != BET_SHORTCUTS_KEY:
            merged[key] = value
            continue
        if not isinstance(value, dict):
            raise ValueError(f"{BET_SHORTCUTS_KEY} must be an object.")
        preflop = validate_quick_sizes(value.get("preflop"), field="preflop")
        postflop = validate_quick_sizes(value.get("postflop"), field="postflop")
        merged[BET_SHORTCUTS_KEY] = {
            "preflop": preflop,
            "postflop": postflop,
        }
    return merged
