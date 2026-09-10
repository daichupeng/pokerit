"""Deterministic RFI findings for first-in non-SB limps.

The versioned range packs already know whether a matching first-in node allows
raise, limp, and/or fold.  This module turns a recorded limp that is absent
from that node into an auditable judgment finding, without asking an LLM to
reconstruct chart contents from a source label.
"""

from __future__ import annotations

from ai_functions.decision_snapshot import build_decision_snapshots


def detect_rfi_limp_findings(game, hands: list, hero_gp_id) -> list[dict]:
    findings = []
    for hand in hands:
        snapshots = build_decision_snapshots(game, hand, hero_gp_id, "preflop")
        for snapshot in snapshots:
            facts = snapshot.get("known_facts") or {}
            action = facts.get("hero_action") or {}
            if facts.get("hero_position") == "SB" \
                    or action.get("action") != "call" \
                    or int(action.get("amount_paid") or 0) <= 0:
                continue

            range_source = next(
                (
                    source for source in snapshot.get("evidence_sources") or []
                    if source.get("type") == "range_knowledge_base"
                ),
                None,
            )
            if range_source is None:
                continue
            acceptable = set(range_source.get("acceptable_actions") or [])
            if "limp" in acceptable:
                continue

            mixed = bool(range_source.get("mixed"))
            if "raise" in acceptable:
                tag = "missed_open_raise"
                better_line = (
                    "Raise or fold according to the chart mix; do not open-limp."
                    if "fold" in acceptable
                    else "Raise first in."
                )
                issue = (
                    "The matching RFI range allows a raise/fold mix but not a limp."
                    if mixed
                    else "The matching RFI range enters this hand by raising, not limping."
                )
            else:
                tag = "missed_fold"
                better_line = "Fold first in."
                issue = "The matching RFI range does not enter this hand voluntarily."

            findings.append({
                "tag": tag,
                "hand_id": str(hand.id),
                "round_count": hand.round_count,
                "street": "preflop",
                "hero_action": f"open-limped {int(action.get('amount_paid') or 0)}",
                "issue": issue,
                "better_line": better_line,
                "why": (
                    "Following the supported RFI branch avoids surrendering initiative "
                    "with a hand whose chart node does not contain a limp."
                ),
                "confidence": "medium" if mixed else "high",
                "evidence_sources": snapshot.get("evidence_sources") or [],
            })
            # Only the first-in decision can carry RFI evidence.
            break
    return findings
