"""The profile fold — pure, deterministic logic that turns evaluation history
into the per-tag trend-state machine described in the feature spec.

``fold_evaluation`` is the one-step primitive: given a profile state and one
already-folded-in evaluation's data, it returns the next state. Everything
else (incremental day-to-day folding, and ``rebuild_profile``'s full replay)
is built by calling it repeatedly — there is exactly one place the state
machine's rules live.

A profile state is ``{"evaluations_folded": int, "leaks": list[dict]}``, and
each leak record is ``{"tag", "kind", "status", "occurrences",
"absent_streak", "regressed", "first_seen", "last_seen"}`` per the spec.
``leaks`` is always sorted by tag name so that incremental folding and a full
rebuild serialize byte-identically for the same inputs — this is the
load-bearing invariant the whole correction loop depends on.
"""

from __future__ import annotations

from ai_functions.game_review import leak_taxonomy
from ai_functions.memory import persistence

EMPTY_PROFILE_STATE = {"evaluations_folded": 0, "leaks": []}

_ALL_TAGS = frozenset(leak_taxonomy.ALL_STAT_TAGS) | frozenset(leak_taxonomy.JUDGMENT_TAGS)


def _new_record(tag: str, kind: str) -> dict:
    return {
        "tag": tag,
        "kind": kind,
        "status": None,
        "occurrences": 0,
        "absent_streak": 0,
        "regressed": False,
        "first_seen": None,
        "last_seen": None,
    }


def _apply_appearance(record: dict, eval_ref: dict) -> None:
    record["occurrences"] += 1
    record["absent_streak"] = 0
    prev_status = record["status"]
    if prev_status is None:
        record["status"] = "flagged"
        record["regressed"] = False
    elif prev_status == "flagged":
        record["status"] = "confirmed"
        record["regressed"] = False
    elif prev_status == "resolved":
        record["status"] = "confirmed"
        record["regressed"] = True
    # else: already confirmed — status and regressed are left as-is.
    if record["first_seen"] is None:
        record["first_seen"] = eval_ref
    record["last_seen"] = eval_ref


def _apply_absence(record: dict) -> None:
    record["absent_streak"] += 1
    if record["absent_streak"] >= 3:
        record["status"] = "resolved"
        record["regressed"] = False


def _has_opportunity(tag: str, kind: str, stats_display: dict) -> bool:
    if kind == "judgment":
        return True  # opportunity = the game was evaluated at all
    d = leak_taxonomy.stat_tag_opportunity(tag, stats_display)
    return d is not None and d >= leak_taxonomy.MIN_OPPORTUNITY_FLOOR


def fold_evaluation(profile_state: dict, evaluation: dict) -> dict:
    """Fold one evaluation into ``profile_state``, returning a new state.

    ``evaluation`` is ``{"eval_id", "date", "leak_tags", "disputed_tags",
    "stats_snapshot"}`` — ``leak_tags`` the evaluation's merged leak-tag list
    (``GameEvaluation.leak_tags``), ``stats_snapshot`` its game-level
    ``to_display()`` dict, ``disputed_tags`` tag names to skip entirely (they
    contribute nothing this evaluation, neither as an appearance nor as an
    absence — the user disputed the finding, so this game is not evidence
    either way).

    Never mutates ``profile_state`` or its records in place.
    """
    tags_by_name = {r["tag"]: dict(r) for r in profile_state.get("leaks", [])}

    leak_tags = evaluation.get("leak_tags") or []
    disputed = set(evaluation.get("disputed_tags") or [])
    stats_display = evaluation.get("stats_snapshot") or {}
    present_by_tag = {lt["tag"]: lt for lt in leak_tags if lt["tag"] not in disputed}

    universe = set(tags_by_name) | set(present_by_tag) | _ALL_TAGS
    eval_ref = {"eval_id": evaluation["eval_id"], "date": evaluation["date"]}

    for tag in universe:
        if tag in disputed:
            continue

        if tag in present_by_tag:
            kind = present_by_tag[tag]["kind"]
            record = tags_by_name.get(tag) or _new_record(tag, kind)
            _apply_appearance(record, eval_ref)
            tags_by_name[tag] = record
            continue

        record = tags_by_name.get(tag)
        if record is None or record["status"] not in ("flagged", "confirmed"):
            continue  # never appeared, or already resolved — no change
        if not _has_opportunity(tag, record["kind"], stats_display):
            continue  # absence without opportunity — streak neither grows nor resets
        _apply_absence(record)

    leaks = sorted(tags_by_name.values(), key=lambda r: r["tag"])
    return {
        "evaluations_folded": profile_state.get("evaluations_folded", 0) + 1,
        "leaks": leaks,
    }


def rebuild_profile(db, user_id, reset_at=None) -> dict:
    """Replay a user's entire folded evaluation history from scratch.

    Must always produce a state identical to whatever incremental folding
    would have produced for the same inputs — this is verified directly in
    tests, and every correction route relies on it. ``reset_at`` defaults to
    the existing profile row's own ``reset_at`` (if any) so callers that
    aren't the reset route itself don't need to look it up separately.
    """
    if reset_at is None:
        existing = persistence.load_profile_row(db, user_id)
        reset_at = existing.reset_at if existing else None
    evaluations = persistence.query_folded_evaluations(db, user_id, reset_at)
    state = dict(EMPTY_PROFILE_STATE)
    for evaluation in evaluations:
        state = fold_evaluation(state, persistence.evaluation_to_fold_input(evaluation))
    return state
