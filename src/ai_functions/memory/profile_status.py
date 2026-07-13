"""Pure mapping from a profile (as it stood BEFORE this game) plus this game's
leak tags to a per-tag ``profile_status`` label, used by synthesis.py to badge
each report section. Computed in code, never trusted from the LLM (decision 5).
"""

from __future__ import annotations

_RETURNING_STATUSES = frozenset({"flagged", "confirmed"})


def compute_profile_status(profile_state: dict | None, leak_tags: list[dict]) -> dict[str, str]:
    """For each tag present in this game's ``leak_tags``, decide whether it's
    ``new`` (no prior profile record, or the record never actually appeared —
    shouldn't happen, but treated as new defensively), ``returning`` (matches
    a currently flagged/confirmed profile tag), or ``regressing`` (matches a
    currently resolved profile tag — this game undoes that progress).

    ``profile_state`` must be the profile as it stood before this game's own
    fold — never contaminated by this game's own result (decision 4/5).
    """
    records_by_tag = {r["tag"]: r for r in (profile_state or {}).get("leaks", [])}

    statuses = {}
    for leak in leak_tags:
        tag = leak["tag"]
        record = records_by_tag.get(tag)
        if record is None or record["status"] is None:
            statuses[tag] = "new"
        elif record["status"] in _RETURNING_STATUSES:
            statuses[tag] = "returning"
        elif record["status"] == "resolved":
            statuses[tag] = "regressing"
        else:
            statuses[tag] = "new"
    return statuses
