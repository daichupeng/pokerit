"""Pure-function tests for merge.py — no DB, no LLM."""

from __future__ import annotations

from ai_functions.game_review.merge import merge_findings


def _stat(pct=None, ratio=None, n=0, d=0):
    out = {"n": n, "d": d}
    if pct is not None:
        out["pct"] = pct
    if ratio is not None:
        out["ratio"] = ratio
    return out


def _display(**overrides):
    base = {
        "vpip": _stat(pct=25, n=25, d=100),
        "pfr": _stat(pct=20, n=20, d=100),
        "three_bet": _stat(pct=6, n=6, d=100),
        "fold_to_3bet": _stat(pct=50, n=10, d=20),
        "wtsd": _stat(pct=25, n=25, d=100),
        "wsd": _stat(pct=50, n=10, d=20),
        "aggression_factor": _stat(ratio=2.0, n=20, d=10),
        "cbet": {
            "flop": _stat(pct=60, n=6, d=10),
            "turn": _stat(pct=60, n=6, d=10),
            "river": _stat(pct=60, n=6, d=10),
        },
        "fold_to_cbet": {
            "flop": _stat(pct=40, n=4, d=10),
            "turn": _stat(pct=40, n=4, d=10),
            "river": _stat(pct=40, n=4, d=10),
        },
        "by_position": {},
    }
    base.update(overrides)
    return base


def test_merge_findings_groups_by_tag_and_computes_occurrence_severity():
    street_findings = {
        "preflop": [
            {"tag": "missed_fold", "hand_id": "h1", "round_count": 1, "street": "preflop", "note": "a"},
        ],
        "flop": [
            {"tag": "missed_fold", "hand_id": "h2", "round_count": 2, "street": "flop", "note": "b"},
        ],
        "turn": [],
        "river": [],
    }
    display = _display()  # no stat leaks triggered by these clean numbers

    merged = merge_findings(street_findings, display)
    judgment = [t for t in merged if t["kind"] == "judgment"]

    assert len(judgment) == 1
    tag = judgment[0]
    assert tag["tag"] == "missed_fold"
    assert tag["severity"] == 2  # 2 occurrences -> moderate band
    assert {c["hand_id"] for c in tag["citations"]} == {"h1", "h2"}
    assert {c["round_count"] for c in tag["citations"]} == {1, 2}


def test_merge_findings_single_occurrence_is_severity_one():
    street_findings = {"preflop": [
        {"tag": "bad_bluff_spot", "hand_id": "h1", "round_count": 1, "street": "preflop", "note": "x"},
    ]}
    merged = merge_findings(street_findings, _display())
    judgment = [t for t in merged if t["kind"] == "judgment"]
    assert judgment[0]["severity"] == 1


def test_merge_findings_four_or_more_is_severity_three():
    street_findings = {"preflop": [
        {"tag": "inconsistent_sizing", "hand_id": f"h{i}", "round_count": i, "street": "preflop", "note": "x"}
        for i in range(4)
    ]}
    merged = merge_findings(street_findings, _display())
    judgment = [t for t in merged if t["kind"] == "judgment"]
    assert judgment[0]["severity"] == 3


def test_merge_findings_combines_with_stat_leaks():
    # low_vpip severe band: pct < 16, d >= 5
    display = _display(vpip=_stat(pct=10, n=10, d=100))
    merged = merge_findings({}, display)

    stat_tags = [t for t in merged if t["kind"] == "stat"]
    assert any(t["tag"] == "low_vpip" and t["severity"] == 3 for t in stat_tags)


def test_merge_findings_no_judgment_findings_returns_only_stat_tags():
    merged = merge_findings({"preflop": [], "flop": [], "turn": [], "river": []}, _display())
    assert all(t["kind"] == "stat" for t in merged)
