"""Pure merge of street-agent judgment findings with stat-derived leaks.

No LLM involvement. Judgment-tag severity is a per-50-hand normalized citation
rate (preserving the original bands for sessions up to 50 hands); stat-tag
severity/evidence come straight from ``detect_stat_leaks``.
"""

from __future__ import annotations

from collections import defaultdict

from ai_functions.game_review.leak_taxonomy import (
    judgment_occurrences_per_50,
    severity_for_judgment_count,
)
from ai_functions.game_review.stat_leaks import detect_stat_leaks


def merge_findings(
    street_findings: dict[str, list[dict]],
    stats_display: dict,
    profile_key: str | None = None,
) -> list[dict]:
    """Combine all street agents' findings with stat-derived leaks.

    ``street_findings`` maps street name -> list of validated finding dicts
    (as produced by ``street_agent.parse_findings``), each with
    ``{"tag", "hand_id", "round_count", "street", "note"}``.

    Returns the final ``leak_tags`` list: judgment tags grouped by tag with a
    ``citations`` list and occurrence-count severity, plus every stat-derived
    tag from ``detect_stat_leaks``.
    """
    by_tag: dict[str, list[dict]] = defaultdict(list)
    for findings in street_findings.values():
        for finding in findings:
            citation = {
                "hand_id": finding["hand_id"],
                "round_count": finding["round_count"],
                "street": finding["street"],
            }
            # The old merge discarded the street agent's explanation, leaving
            # synthesis with only a hand number. Preserve both new structured
            # fields and legacy notes so the final report can explain the spot.
            for key in ("hero_action", "issue", "better_line", "why", "future_plan", "confidence", "evidence_sources", "note"):
                value = finding.get(key)
                if value:
                    citation[key] = value
            by_tag[finding["tag"]].append(citation)

    hands_dealt = int(stats_display.get("hands_dealt", 0) or 0)
    judgment_tags = [
        {
            "tag": tag,
            "kind": "judgment",
            "severity": severity_for_judgment_count(len(citations), hands_dealt),
            "citations": citations,
            "evidence": {
                "occurrences": len(citations),
                "hands_dealt": hands_dealt,
                "occurrences_per_50": judgment_occurrences_per_50(
                    len(citations), hands_dealt,
                ),
                "severity_basis": "judgment occurrences normalized to 50 hands",
            },
        }
        for tag, citations in by_tag.items()
    ]

    stat_tags = detect_stat_leaks(stats_display, profile_key)
    for leak in stat_tags:
        leak["evidence_sources"] = [{
            "type": "deterministic_statistics",
            "label": "Recorded actions aggregated by code and checked against a versioned threshold profile",
            "threshold_profile": profile_key,
        }]

    return judgment_tags + stat_tags
