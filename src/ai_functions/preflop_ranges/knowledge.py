"""Strict resolver for Pokerit's versioned RFI range packs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .data import CASH_6MAX_100_SOURCE, CASH_9MAX_100_SOURCE, MTT_8MAX_40_SOURCE

RANKS = "AKQJT98765432"
ALL_HANDS = frozenset(
    RANKS[i] * 2 if i == j else RANKS[i] + RANKS[j] + "s" if i < j else RANKS[j] + RANKS[i] + "o"
    for i in range(13) for j in range(13)
)


@dataclass(frozen=True)
class RangeDecision:
    pack_id: str
    position: str
    hand: str
    actions: tuple[str, ...]
    mixed: bool
    evidence_source: dict


@dataclass(frozen=True)
class RangePack:
    id: str
    title: str
    game_format: str
    table_size: int
    stack_bb: int
    ante_type: str
    version: str
    source_url: str
    source_sha256: str
    source_label: str
    position_map: Mapping[str, str]
    source_ranges: Mapping[str, Mapping[str, str]]
    derivation: str | None = None

    @property
    def positions(self) -> tuple[str, ...]:
        return tuple(self.position_map)

    def decision(self, position: str, hand: str) -> RangeDecision | None:
        source_position = self.position_map.get(position)
        normalized = normalize_starting_hand(hand)
        if source_position is None or normalized is None:
            return None
        row = self.source_ranges[source_position]
        raises = frozenset(row.get("raise", "").split())
        limps = frozenset(row.get("limp", "").split())
        mixed = normalized in frozenset(row.get("mixed", "").split())
        actions: list[str] = []
        if normalized in raises:
            actions.append("raise")
        if normalized in limps:
            actions.append("limp")
        # A mixed hand with only one explicitly coloured voluntary action mixes
        # that action with fold. Otherwise a hand absent from both sets folds.
        if not actions or (mixed and len(actions) == 1):
            actions.append("fold")
        return RangeDecision(
            pack_id=self.id,
            position=position,
            hand=normalized,
            actions=tuple(actions),
            mixed=len(actions) > 1,
            evidence_source={
                "type": "range_knowledge_base",
                "label": self.source_label,
                "pack_id": self.id,
                "version": self.version,
                "source_url": self.source_url,
                "derived": self.derivation is not None,
            },
        )

    def public_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "game_format": self.game_format,
            "table_size": self.table_size,
            "stack_bb": self.stack_bb,
            "ante_type": self.ante_type,
            "node": "RFI",
            "version": self.version,
            "positions": list(self.positions),
            "source": {
                "label": self.source_label,
                "url": self.source_url,
                "derived": self.derivation is not None,
                "derivation": self.derivation,
            },
        }


def normalize_starting_hand(hand: str) -> str | None:
    """Normalize ``AsKh``/``As Kh`` or a canonical class such as ``AKo``."""
    compact = hand.replace(" ", "").replace("-", "")
    if compact in ALL_HANDS:
        return compact
    if len(compact) != 4:
        return None
    r1, s1, r2, s2 = compact[0].upper(), compact[1].lower(), compact[2].upper(), compact[3].lower()
    if r1 not in RANKS or r2 not in RANKS or s1 not in "shdc" or s2 not in "shdc" or compact[:2].lower() == compact[2:].lower():
        return None
    if r1 == r2:
        return r1 * 2
    high, low = sorted((r1, r2), key=RANKS.index)
    return f"{high}{low}{'s' if s1 == s2 else 'o'}"


_MTT_URL = "https://rangeconverter.com/articles/poker-charts-8max-mtt-40bb-no-limit-texas-holdem-tournaments"
_CASH9_URL = "https://rangeconverter.com/articles/poker-charts-9-max-100bb-no-limit-texas-holdem"
_CASH6_URL = "https://rangeconverter.com/articles/poker-charts-6-max-100bb-no-limit-texas-holdem"

RANGE_PACKS: dict[str, RangePack] = {
    "mtt_bba_8max_40bb_v1": RangePack(
        id="mtt_bba_8max_40bb_v1", title="MTT · BB ante · 8-max · 40BB",
        game_format="mtt", table_size=8, stack_bb=40, ante_type="big_blind", version="1.0.0",
        source_url=_MTT_URL, source_sha256="c194bb530a484bb31002a9ed5beb52633d33289be73e673daa39eb23bef6fe48",
        source_label="RangeConverter 8-max MTT 40BB RFI (1BB ante)",
        position_map={"UTG": "UTG", "UTG+1": "UTG+1", "HJ-1": "MP", "HJ": "HJ", "CO": "CO", "BTN": "BTN", "SB": "SB"},
        source_ranges=MTT_8MAX_40_SOURCE,
    ),
    "mtt_bba_6max_40bb_v1": RangePack(
        id="mtt_bba_6max_40bb_v1", title="MTT · BB ante · 6-max · 40BB",
        game_format="mtt", table_size=6, stack_bb=40, ante_type="big_blind", version="1.0.0",
        source_url=_MTT_URL, source_sha256="c194bb530a484bb31002a9ed5beb52633d33289be73e673daa39eb23bef6fe48",
        source_label="RangeConverter 8-max MTT 40BB RFI (1BB ante), mapped by players behind",
        position_map={"UTG": "MP", "HJ": "HJ", "CO": "CO", "BTN": "BTN", "SB": "SB"},
        source_ranges=MTT_8MAX_40_SOURCE,
        derivation="Same 1BB BB-ante pot and 40BB stack; positions mapped by number of players behind. Card bunching is not modelled.",
    ),
    "cash_8max_100bb_v1": RangePack(
        id="cash_8max_100bb_v1", title="Cash · 8-max · 100BB",
        game_format="cash", table_size=8, stack_bb=100, ante_type="none", version="1.0.0",
        source_url=_CASH9_URL, source_sha256="0feb70db01ab74db6d6a8cb6e9761358f6eb04879468452f8429e027c6770b27",
        source_label="RangeConverter full-ring cash 100BB RFI, mapped by players behind",
        position_map={"UTG": "UTG+1", "UTG+1": "MP", "HJ-1": "LJ", "HJ": "HJ", "CO": "CO", "BTN": "BTN", "SB": "SB"},
        source_ranges=CASH_9MAX_100_SOURCE,
        derivation="Full-ring nodes mapped to 8-max positions by number of players behind. Card bunching is not modelled.",
    ),
    "cash_6max_100bb_v1": RangePack(
        id="cash_6max_100bb_v1", title="Cash · 6-max · 100BB",
        game_format="cash", table_size=6, stack_bb=100, ante_type="none", version="1.0.0",
        source_url=_CASH6_URL, source_sha256="65af3a9466c4cbd8cec927b532167a237097282390e1a5b0ee567d06d8cb7a38",
        source_label="RangeConverter 6-max cash 100BB RFI",
        position_map={"UTG": "UTG", "HJ": "MP", "CO": "CO", "BTN": "BTN", "SB": "SB"},
        source_ranges=CASH_6MAX_100_SOURCE,
    ),
}


def get_range_pack(pack_id: str) -> RangePack | None:
    return RANGE_PACKS.get(pack_id)


def list_range_packs() -> list[dict]:
    return [pack.public_dict() for pack in RANGE_PACKS.values()]
