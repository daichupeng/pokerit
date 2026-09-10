"""Deterministic sample readiness and direction-aware history comparisons."""

from __future__ import annotations

from dataclasses import dataclass

from ai_functions.game_review.leak_taxonomy import (
    EP_POSITIONS,
    LP_POSITIONS,
    MIN_OPPORTUNITY_FLOOR,
    POSITIONAL_TAG,
    ThresholdProfile,
)


@dataclass(frozen=True)
class MetricSpec:
    metric: str
    path: tuple[str, ...]
    value_key: str
    required: int
    tags: tuple[str, ...]
    opportunity: str = "denominator"
    material_delta: float = 3.0


METRICS = (
    MetricSpec("vpip", ("vpip",), "pct", MIN_OPPORTUNITY_FLOOR, ("low_vpip", "high_vpip")),
    MetricSpec("pfr", ("pfr",), "pct", MIN_OPPORTUNITY_FLOOR, ("limps_too_wide",)),
    MetricSpec("limp", ("limp",), "pct", MIN_OPPORTUNITY_FLOOR, ("limps_too_wide",)),
    MetricSpec("three_bet", ("three_bet",), "pct", MIN_OPPORTUNITY_FLOOR, ("under_3bet", "over_3bet")),
    MetricSpec("fold_to_3bet", ("fold_to_3bet",), "pct", MIN_OPPORTUNITY_FLOOR, ("overfolds_to_3bet",)),
    MetricSpec("aggression_factor", ("aggression_factor",), "ratio", MIN_OPPORTUNITY_FLOOR,
               ("too_passive_postflop", "too_aggressive_postflop"), "actions", 0.25),
    MetricSpec("wtsd", ("wtsd",), "pct", MIN_OPPORTUNITY_FLOOR,
               ("underplays_to_showdown", "overplays_to_showdown")),
    MetricSpec("wsd", ("wsd",), "pct", MIN_OPPORTUNITY_FLOOR, ("weak_at_showdown",)),
    MetricSpec("positional_gap", ("by_position",), "gap_pct", MIN_OPPORTUNITY_FLOOR,
               (POSITIONAL_TAG,), "positional"),
    *tuple(
        spec
        for street in ("flop", "turn", "river")
        for spec in (
            MetricSpec(f"cbet_{street}", ("cbet", street), "pct", MIN_OPPORTUNITY_FLOOR,
                       (f"under_cbet_{street}", f"over_cbet_{street}")),
            MetricSpec(f"fold_to_cbet_{street}", ("fold_to_cbet", street), "pct", MIN_OPPORTUNITY_FLOOR,
                       (f"overfolds_to_cbet_{street}",)),
        )
    ),
)

PUSH_FOLD_METRICS = (
    MetricSpec("open_shove", ("open_shove",), "pct", MIN_OPPORTUNITY_FLOOR, (), material_delta=5.0),
    MetricSpec("reshove", ("reshove",), "pct", MIN_OPPORTUNITY_FLOOR, (), material_delta=5.0),
    MetricSpec("call_off", ("call_off",), "pct", MIN_OPPORTUNITY_FLOOR, (), material_delta=5.0),
)


def _combined_position_vpip(display: dict, positions: frozenset[str]) -> tuple[int, int]:
    n = d = 0
    for position, position_display in (display.get("by_position") or {}).items():
        if position not in positions:
            continue
        node = position_display.get("vpip") or {}
        n += int(node.get("n", 0))
        d += int(node.get("d", 0))
    return n, d


def _node(display: dict, spec: MetricSpec) -> dict:
    if spec.opportunity == "positional":
        ep_n, ep_d = _combined_position_vpip(display, EP_POSITIONS)
        lp_n, lp_d = _combined_position_vpip(display, LP_POSITIONS)
        ep_pct = round(100 * ep_n / ep_d, 1) if ep_d else None
        lp_pct = round(100 * lp_n / lp_d, 1) if lp_d else None
        gap = round(lp_pct - ep_pct, 1) if ep_pct is not None and lp_pct is not None else None
        return {
            "gap_pct": gap,
            "ep_pct": ep_pct,
            "lp_pct": lp_pct,
            "ep_n": ep_n,
            "ep_d": ep_d,
            "lp_n": lp_n,
            "lp_d": lp_d,
        }
    value = display
    for key in spec.path:
        value = value.get(key, {}) if isinstance(value, dict) else {}
    return value if isinstance(value, dict) else {}


def _opportunities(node: dict, spec: MetricSpec) -> int:
    if spec.opportunity == "positional":
        return min(int(node.get("ep_d", 0)), int(node.get("lp_d", 0)))
    if spec.opportunity == "actions":
        return int(node.get("n", 0)) + int(node.get("d", 0))
    return int(node.get("d", 0))


def _sample(node: dict, spec: MetricSpec) -> dict:
    observed = _opportunities(node, spec)
    return {
        "observed": observed,
        "required": spec.required,
        "status": "ready" if observed >= spec.required else "insufficient_sample",
    }


def _value(node: dict, spec: MetricSpec):
    if spec.value_key == "ratio" and node.get("infinite"):
        return None
    return node.get(spec.value_key)


def _distance_to_healthy(value: float, spec: MetricSpec, profile: ThresholdProfile) -> float:
    if spec.metric == "limp":
        return max(0.0, value - profile.gap_moderate)
    if spec.metric == "positional_gap":
        return max(0.0, profile.positional_moderate - value)
    thresholds = [profile.thresholds[tag] for tag in spec.tags if tag in profile.thresholds]
    lower = next((t.moderate_bound for t in thresholds if t.direction == "low"), None)
    upper = next((t.moderate_bound for t in thresholds if t.direction == "high"), None)
    if lower is not None and value < lower:
        return lower - value
    if upper is not None and value > upper:
        return value - upper
    return 0.0


def enabled_metric_specs(profile: ThresholdProfile) -> tuple[MetricSpec, ...]:
    enabled = tuple(
        spec for spec in METRICS
        if any(tag in profile.enabled_stat_tags for tag in spec.tags)
    )
    if profile.key == "mtt_8max_15bb":
        enabled += PUSH_FOLD_METRICS
    return enabled


def compare_latest_to_baseline(current: dict, baseline: dict, profile: ThresholdProfile) -> list[dict]:
    comparisons = []
    for spec in enabled_metric_specs(profile):
        current_node = _node(current, spec)
        baseline_node = _node(baseline, spec)
        current_sample = _sample(current_node, spec)
        baseline_sample = _sample(baseline_node, spec)
        current_value = _value(current_node, spec)
        baseline_value = _value(baseline_node, spec)
        current_infinite = bool(current_node.get("infinite"))
        baseline_infinite = bool(baseline_node.get("infinite"))

        status = "insufficient_sample"
        delta = None
        current_known = current_value is not None or current_infinite
        baseline_known = baseline_value is not None or baseline_infinite
        if current_sample["status"] == baseline_sample["status"] == "ready" \
                and current_known and baseline_known:
            current_numeric = float("inf") if current_infinite else current_value
            baseline_numeric = float("inf") if baseline_infinite else baseline_value
            if not current_infinite and not baseline_infinite:
                delta = round(current_numeric - baseline_numeric, 2)
            if not spec.tags:  # frequency only; strategic direction is deliberately unknown
                status = "stable"
            elif current_infinite and baseline_infinite:
                status = "stable"
            else:
                current_distance = _distance_to_healthy(current_numeric, spec, profile)
                baseline_distance = _distance_to_healthy(baseline_numeric, spec, profile)
                improvement = baseline_distance - current_distance
                if improvement >= spec.material_delta:
                    status = "improving"
                elif improvement <= -spec.material_delta:
                    status = "worsening"
                else:
                    status = "stable"

        comparisons.append({
            "metric": spec.metric,
            "current": {**current_node, "value": current_value, "sample": current_sample},
            "baseline": {**baseline_node, "value": baseline_value, "sample": baseline_sample},
            "delta": delta,
            "delta_unit": "ratio" if spec.value_key == "ratio" else "percentage_points",
            "material_delta": spec.material_delta,
            "trend_status": status,
        })
    return comparisons


def history_sample_status(display: dict, profile: ThresholdProfile) -> dict:
    metrics = []
    for spec in enabled_metric_specs(profile):
        node = _node(display, spec)
        metrics.append({"metric": spec.metric, **_sample(node, spec), "snapshot": node})
    return {"profile": profile.key, "version": profile.version, "metrics": metrics}
