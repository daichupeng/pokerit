"""Pure merge of street-agent judgment findings with stat-derived leaks.

No LLM involvement. Judgment-tag severity is purely a function of citation
count across the whole game (``leak_taxonomy.severity_for_judgment_count``);
stat-tag severity/evidence come straight from ``detect_stat_leaks``.
"""

from __future__ import annotations

from collections import defaultdict

from ai_functions.game_review.leak_taxonomy import severity_for_judgment_count
from ai_functions.game_review.stat_leaks import detect_stat_leaks


def merge_findings(street_findings: dict[str, list[dict]], stats_display: dict) -> list[dict]:
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
            by_tag[finding["tag"]].append({
                "hand_id": finding["hand_id"],
                "round_count": finding["round_count"],
                "street": finding["street"],
            })

    judgment_tags = [
        {
            "tag": tag,
            "kind": "judgment",
            "severity": severity_for_judgment_count(len(citations)),
            "citations": citations,
        }
        for tag, citations in by_tag.items()
    ]

    stat_tags = detect_stat_leaks(stats_display)

    return judgment_tags + stat_tags
