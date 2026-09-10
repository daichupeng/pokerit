"""Training-scenario presets and profile-scope helpers.

The engine still runs one fixed blind level per game.  Tournament presets are
therefore stack-depth training scenarios, not a full tournament clock/ICM
simulation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from fractions import Fraction
import hashlib
import json
import re


CUSTOM_SCENARIO = "custom"
DEFAULT_PROFILE_SCOPE = "cash_6max_100bb"


@dataclass(frozen=True)
class ScenarioPreset:
    key: str
    label: str
    game_format: str
    num_bots: int
    small_blind: int
    big_blind: int
    buy_in: int
    ante: int
    ante_type: str
    tournament_stage: str | None
    profile_scope: str
    description: str

    def to_public_dict(self) -> dict:
        return asdict(self)


SCENARIO_PRESETS: dict[str, ScenarioPreset] = {
    "cash_6max_100bb": ScenarioPreset(
        key="cash_6max_100bb",
        label="现金桌 6-max，100BB",
        game_format="cash",
        num_bots=5,
        small_blind=50,
        big_blind=100,
        buy_in=10_000,
        ante=0,
        ante_type="none",
        tournament_stage=None,
        profile_scope="cash_6max_100bb",
        description="6-max cash-game practice at 100 big blinds.",
    ),
    "cash_8max_100bb": ScenarioPreset(
        key="cash_8max_100bb",
        label="现金桌 8-max，100BB",
        game_format="cash",
        num_bots=7,
        small_blind=50,
        big_blind=100,
        buy_in=10_000,
        ante=0,
        ante_type="none",
        tournament_stage=None,
        profile_scope="cash_8max_100bb",
        description="8-max cash-game practice at 100 big blinds.",
    ),
    "mtt_8max_40bb": ScenarioPreset(
        key="mtt_8max_40bb",
        label="MTT 8-max 常规，40BB + BB Ante",
        game_format="tournament",
        num_bots=7,
        small_blind=50,
        big_blind=100,
        buy_in=4_000,
        ante=100,
        ante_type="big_blind",
        tournament_stage="standard",
        profile_scope="mtt_8max_40bb",
        description="Fixed-level 8-max tournament practice at 40BB with a 1BB big-blind ante.",
    ),
    "mtt_8max_25bb": ScenarioPreset(
        key="mtt_8max_25bb",
        label="MTT 8-max 中短码，25BB + BB Ante",
        game_format="tournament",
        num_bots=7,
        small_blind=50,
        big_blind=100,
        buy_in=2_500,
        ante=100,
        ante_type="big_blind",
        tournament_stage="middle_short",
        profile_scope="mtt_8max_25bb",
        description="Fixed-level 8-max middle/short-stack tournament practice at 25BB.",
    ),
    "mtt_8max_15bb": ScenarioPreset(
        key="mtt_8max_15bb",
        label="MTT 8-max Push/Fold，10–15BB + BB Ante",
        game_format="tournament",
        num_bots=7,
        small_blind=50,
        big_blind=100,
        buy_in=1_500,
        ante=100,
        ante_type="big_blind",
        tournament_stage="push_fold",
        profile_scope="mtt_8max_15bb",
        description="Fixed-level 8-max 10–15BB push/fold practice (15BB default) with a 1BB big-blind ante.",
    ),
}


SCENARIO_ALIASES: dict[str, str] = {
    "cash_100bb": "cash_6max_100bb",
    "mtt_40bb": "mtt_8max_40bb",
    "mtt_25bb": "mtt_8max_25bb",
    "mtt_push_fold": "mtt_8max_15bb",
}


def canonical_scenario_key(scenario: str | None) -> str:
    key = scenario or CUSTOM_SCENARIO
    return SCENARIO_ALIASES.get(key, key)


def get_scenario_preset(scenario: str | None) -> ScenarioPreset | None:
    return SCENARIO_PRESETS.get(canonical_scenario_key(scenario))


ACTIVE_PROFILE_SCOPE_LABELS: dict[str, str] = {
    "cash_6max_100bb": "现金桌 6-max 100BB",
    "cash_8max_100bb": "现金桌 8-max 100BB",
    "mtt_8max_40bb": "MTT 8-max 40BB",
    "mtt_8max_25bb": "MTT 8-max 25BB",
    "mtt_8max_15bb": "MTT 8-max ≤15BB",
}

LEGACY_PROFILE_SCOPE_LABELS: dict[str, str] = {
    "custom": "旧版：自定义混合范围（请重新评估）",
    "cash_100bb": "旧版：现金桌 100BB",
    "cash_custom": "旧版：现金桌自定义",
    "mtt_25_40bb": "旧版：MTT 25–40BB",
    "mtt_15bb": "旧版：MTT ≤15BB",
    "mtt_40plus": "旧版：MTT >40BB",
}

PROFILE_SCOPE_LABELS: dict[str, str] = {
    **ACTIVE_PROFILE_SCOPE_LABELS,
    **LEGACY_PROFILE_SCOPE_LABELS,
}


def is_custom_profile_scope(scope_key: str) -> bool:
    return bool(re.fullmatch(r"custom_[0-9a-f]{32}", scope_key))


def is_profile_scope(scope_key: str) -> bool:
    return scope_key in PROFILE_SCOPE_LABELS or is_custom_profile_scope(scope_key)


def _custom_scope(values: list) -> str:
    payload = json.dumps(values, ensure_ascii=True, separators=(",", ":"))
    # 39 characters fits the existing scope columns; exact normalized ratios
    # preserve fractional BB depths without introducing rounded buckets.
    return "custom_" + hashlib.blake2b(payload.encode(), digest_size=16).hexdigest()


def profile_scope_for_settings(
    *, game_format: str, buy_in: int, big_blind: int, scenario: str = CUSTOM_SCENARIO,
    num_players: int | None = None, ante: int = 0, ante_type: str = "none",
    tournament_stage: str | None = None,
) -> str:
    preset = get_scenario_preset(scenario)
    if preset is not None:
        return preset.profile_scope
    if not num_players or big_blind <= 0 or buy_in <= 0:
        return CUSTOM_SCENARIO  # incomplete legacy metadata cannot define a scope
    return _custom_scope([
        "v1", game_format, num_players, str(Fraction(buy_in, big_blind)),
        ante_type, str(Fraction(ante, big_blind)), tournament_stage,
    ])


def custom_profile_label(game) -> str:
    table_size = len(getattr(game, "players", []) or [])
    big_blind = getattr(game, "big_blind", 0) or 0
    depth = f"{game.buy_in / big_blind:g}BB" if big_blind else "筹码深度未知"
    format_label = "现金桌" if game.game_format == "cash" else "MTT"
    ante = getattr(game, "ante", 0) or 0
    ante_label = f"BB ante {ante / big_blind:g}BB" if ante and big_blind else "无 ante"
    stage = getattr(game, "tournament_stage", None)
    return f"自定义 · {format_label} · {table_size}人 · {depth} · {ante_label}" + (f" · {stage}" if stage else "")


def profile_scope_for_game(game) -> str:
    """Return the stable profile bucket for a persisted or legacy Game row."""
    raw_scenario = getattr(game, "scenario", None)
    explicit = getattr(game, "profile_scope", None)
    if raw_scenario in {"mtt_40bb", "mtt_25bb", "mtt_push_fold"} and explicit in PROFILE_SCOPE_LABELS:
        return explicit
    preset = get_scenario_preset(getattr(game, "scenario", None))
    if preset is not None:
        return preset.profile_scope
    if explicit and is_custom_profile_scope(explicit):
        return explicit
    if explicit in PROFILE_SCOPE_LABELS and explicit != CUSTOM_SCENARIO:
        return explicit
    rule = getattr(game, "rule", None) or {}
    if rule.get("profile_scope") and rule["profile_scope"] != CUSTOM_SCENARIO:
        return rule["profile_scope"]
    scope = profile_scope_for_settings(
        game_format=getattr(game, "game_format", None) or rule.get("game_format") or "cash",
        buy_in=getattr(game, "buy_in", 0),
        big_blind=getattr(game, "big_blind", 0),
        scenario=getattr(game, "scenario", None) or rule.get("scenario") or CUSTOM_SCENARIO,
        num_players=len(getattr(game, "players", []) or []) or rule.get("num_players"),
        ante=getattr(game, "ante", 0) or rule.get("ante", 0),
        ante_type=getattr(game, "ante_type", None) or rule.get("ante_type", "none"),
        tournament_stage=getattr(game, "tournament_stage", None) or rule.get("tournament_stage"),
    )
    return scope if scope != CUSTOM_SCENARIO else _custom_scope(["unknown", str(game.id)])


def profile_scope_label(scope_key: str) -> str:
    if is_custom_profile_scope(scope_key):
        return "自定义训练范围"
    return PROFILE_SCOPE_LABELS.get(scope_key, scope_key.replace("_", " ").title())
