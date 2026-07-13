"""Tests for fold.py's trend-state machine (src/ai_functions/memory/fold.py).

Pure logic tests build fixture "evaluation" dicts directly (no DB) to check
every transition in the spec's Stage 1 "Done when" list. A DB-backed test at
the bottom checks the load-bearing invariant: incremental folding and
rebuild_profile must produce byte-identical leaks state for the same inputs.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from poker_engine.db.models import EvaluationStatus, Game, GameEvaluation, GamePlayer, User

from ai_functions.memory.fold import EMPTY_PROFILE_STATE, fold_evaluation, rebuild_profile
from ai_functions.memory.persistence import evaluation_to_fold_input, save_profile_row


def _eval(eval_id, date, leak_tags, disputed_tags=None, stats_display=None):
    return {
        "eval_id": eval_id,
        "date": date,
        "leak_tags": leak_tags,
        "disputed_tags": disputed_tags or [],
        "stats_snapshot": stats_display or {},
    }


def _leak(tag, kind="judgment"):
    return {"tag": tag, "kind": kind, "severity": 1}


def _record(state, tag):
    return next(r for r in state["leaks"] if r["tag"] == tag)


# A stat display with plenty of opportunity (d >= MIN_OPPORTUNITY_FLOOR) for
# every threshold tag fold.py might check as ABSENT, so "absence with
# opportunity" tests don't need per-tag setup.
_AMPLE_STATS = {
    "vpip": {"pct": 25, "n": 25, "d": 100},
    "pfr": {"pct": 20, "n": 20, "d": 100},
    "three_bet": {"pct": 7, "n": 7, "d": 100},
    "fold_to_3bet": {"pct": 50, "n": 5, "d": 10},
    "wtsd": {"pct": 27, "n": 27, "d": 100},
    "wsd": {"pct": 50, "n": 10, "d": 20},
    "aggression_factor": {"ratio": 2.0, "n": 20, "d": 10},
    "cbet": {"flop": {"pct": 60, "n": 6, "d": 10}, "turn": {"pct": 60, "n": 6, "d": 10}, "river": {"pct": 60, "n": 6, "d": 10}},
    "fold_to_cbet": {"flop": {"pct": 50, "n": 5, "d": 10}, "turn": {"pct": 50, "n": 5, "d": 10}, "river": {"pct": 50, "n": 5, "d": 10}},
    "by_position": {
        "UTG": {"vpip": {"pct": 15, "n": 3, "d": 20}},
        "BTN": {"vpip": {"pct": 40, "n": 8, "d": 20}},
    },
}

# A display with zero opportunity for every stat tag (all denominators 0).
_NO_OPPORTUNITY_STATS = {
    "vpip": {"pct": 0, "n": 0, "d": 0},
    "pfr": {"pct": 0, "n": 0, "d": 0},
    "three_bet": {"pct": 0, "n": 0, "d": 0},
    "fold_to_3bet": {"pct": 0, "n": 0, "d": 0},
    "wtsd": {"pct": 0, "n": 0, "d": 0},
    "wsd": {"pct": 0, "n": 0, "d": 0},
    "aggression_factor": {"ratio": 0, "n": 0, "d": 0},
    "cbet": {"flop": {"pct": 0, "n": 0, "d": 0}, "turn": {"pct": 0, "n": 0, "d": 0}, "river": {"pct": 0, "n": 0, "d": 0}},
    "fold_to_cbet": {"flop": {"pct": 0, "n": 0, "d": 0}, "turn": {"pct": 0, "n": 0, "d": 0}, "river": {"pct": 0, "n": 0, "d": 0}},
    "by_position": {},
}


def test_first_appearance_is_flagged():
    state = fold_evaluation(EMPTY_PROFILE_STATE, _eval("e1", "d1", [_leak("missed_fold")]))
    record = _record(state, "missed_fold")
    assert record["status"] == "flagged"
    assert record["occurrences"] == 1
    assert record["first_seen"] == {"eval_id": "e1", "date": "d1"}
    assert record["last_seen"] == {"eval_id": "e1", "date": "d1"}


def test_second_appearance_confirms():
    state = fold_evaluation(EMPTY_PROFILE_STATE, _eval("e1", "d1", [_leak("missed_fold")]))
    state = fold_evaluation(state, _eval("e2", "d2", [_leak("missed_fold")]))
    record = _record(state, "missed_fold")
    assert record["status"] == "confirmed"
    assert record["occurrences"] == 2
    assert record["last_seen"] == {"eval_id": "e2", "date": "d2"}


def test_absence_without_opportunity_does_not_move_streak():
    state = fold_evaluation(EMPTY_PROFILE_STATE, _eval("e1", "d1", [_leak("low_vpip", "stat")], stats_display=_AMPLE_STATS))
    before = _record(state, "low_vpip")
    assert before["status"] == "flagged"

    # Tag absent this game, AND no opportunity (all denominators 0).
    state = fold_evaluation(state, _eval("e2", "d2", [], stats_display=_NO_OPPORTUNITY_STATS))
    after = _record(state, "low_vpip")
    assert after["status"] == "flagged"
    assert after["absent_streak"] == 0


def test_confirmed_resolves_after_three_opportunity_absences():
    state = fold_evaluation(EMPTY_PROFILE_STATE, _eval("e1", "d1", [_leak("low_vpip", "stat")], stats_display=_AMPLE_STATS))
    state = fold_evaluation(state, _eval("e2", "d2", [_leak("low_vpip", "stat")], stats_display=_AMPLE_STATS))
    assert _record(state, "low_vpip")["status"] == "confirmed"

    for i, eid in enumerate(["e3", "e4", "e5"], start=3):
        state = fold_evaluation(state, _eval(eid, f"d{i}", [], stats_display=_AMPLE_STATS))
        if i < 5:
            assert _record(state, "low_vpip")["status"] == "confirmed"

    resolved = _record(state, "low_vpip")
    assert resolved["status"] == "resolved"
    assert resolved["regressed"] is False


def test_resolved_reappearance_confirms_with_regressed_flag():
    state = fold_evaluation(EMPTY_PROFILE_STATE, _eval("e1", "d1", [_leak("low_vpip", "stat")], stats_display=_AMPLE_STATS))
    state = fold_evaluation(state, _eval("e2", "d2", [_leak("low_vpip", "stat")], stats_display=_AMPLE_STATS))
    for i, eid in enumerate(["e3", "e4", "e5"], start=3):
        state = fold_evaluation(state, _eval(eid, f"d{i}", [], stats_display=_AMPLE_STATS))
    assert _record(state, "low_vpip")["status"] == "resolved"

    state = fold_evaluation(state, _eval("e6", "d6", [_leak("low_vpip", "stat")], stats_display=_AMPLE_STATS))
    record = _record(state, "low_vpip")
    assert record["status"] == "confirmed"
    assert record["regressed"] is True


def test_disputed_tag_contributes_nothing():
    state = fold_evaluation(
        EMPTY_PROFILE_STATE,
        _eval("e1", "d1", [_leak("missed_fold")], disputed_tags=["missed_fold"]),
    )
    assert not any(r["tag"] == "missed_fold" and r["occurrences"] for r in state["leaks"])
    record = next((r for r in state["leaks"] if r["tag"] == "missed_fold"), None)
    if record is not None:
        assert record["status"] is None
        assert record["occurrences"] == 0


def test_evaluations_folded_counter_increments():
    state = fold_evaluation(EMPTY_PROFILE_STATE, _eval("e1", "d1", []))
    state = fold_evaluation(state, _eval("e2", "d2", []))
    assert state["evaluations_folded"] == 2


def _make_user(db, email="hero-fold@test.local"):
    user = User(email=email, display_name="Hero")
    db.add(user)
    db.flush()
    return user


def _make_game(db, user):
    game = Game(started_at=None, ended_at=None, small_blind=50, big_blind=100,
                buy_in=10000, max_round=50, hero_user_id=user.id)
    db.add(game)
    db.flush()
    hero_gp = GamePlayer(game_id=game.id, seat_index=0, display_name="Hero", engine_uuid="hero-uuid",
                          user_id=user.id, is_bot=False, starting_stack=10000)
    db.add(hero_gp)
    db.flush()
    return game


def _make_evaluation(db, user, game, completed_at, leak_tags, stats_display=_AMPLE_STATS, disputed_tags=None):
    evaluation = GameEvaluation(
        game_id=game.id, user_id=user.id, status=EvaluationStatus.COMPLETED,
        stats_snapshot={"game_level": stats_display, "session_dynamics": {}},
        leak_tags=leak_tags, disputed_tags=disputed_tags or [],
        completed_at=completed_at,
    )
    db.add(evaluation)
    db.flush()
    return evaluation


def test_incremental_fold_matches_full_rebuild(db_session):
    db = db_session
    user = _make_user(db)
    base = datetime.now(timezone.utc)

    evaluations = []
    for i in range(4):
        game = _make_game(db, user)
        leak_tags = [_leak("missed_fold")] if i % 2 == 0 else []
        evaluations.append(
            _make_evaluation(db, user, game, base + timedelta(minutes=i), leak_tags)
        )
    db.commit()

    incremental_state = dict(EMPTY_PROFILE_STATE)
    for evaluation in sorted(evaluations, key=lambda e: e.completed_at):
        incremental_state = fold_evaluation(incremental_state, evaluation_to_fold_input(evaluation))

    rebuilt_state = rebuild_profile(db, user.id)

    assert rebuilt_state == incremental_state


def test_rerun_supersedes_older_evaluation_of_same_game(db_session):
    db = db_session
    user = _make_user(db)
    game = _make_game(db, user)
    base = datetime.now(timezone.utc)

    _make_evaluation(db, user, game, base, [_leak("missed_fold")])
    _make_evaluation(db, user, game, base + timedelta(minutes=5), [])
    db.commit()

    state = rebuild_profile(db, user.id)
    assert state["evaluations_folded"] == 1
    # The superseding (later) evaluation had no leak tags, so missed_fold
    # never appears in the folded history — no record at all, not just an
    # unset one.
    assert not any(r["tag"] == "missed_fold" for r in state["leaks"])


def test_discarded_evaluation_excluded_from_rebuild(db_session):
    db = db_session
    user = _make_user(db)
    game = _make_game(db, user)
    evaluation = _make_evaluation(db, user, game, datetime.now(timezone.utc), [_leak("missed_fold")])
    evaluation.discarded_at = datetime.now(timezone.utc)
    db.commit()

    state = rebuild_profile(db, user.id)
    assert state["evaluations_folded"] == 0
