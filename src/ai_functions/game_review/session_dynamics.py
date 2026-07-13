"""Session-dynamics splits: per-segment stats over a game's hand timeline.

Pure, deterministic, produces no leak tags — feeds the synthesis agent
(Stage 3) as context only. Reuses Phase 1's ``stats._sum_hands``/
``stats.to_display`` for every segment rather than duplicating aggregation.
"""

from __future__ import annotations

from poker_engine.stats import _sum_hands, to_display

_THIRDS = ("first_third", "second_third", "third_third")


def _round_range(hands: list) -> list[int]:
    return [hands[0].round_count, hands[-1].round_count]


def _segment(hands: list, hero_gp_id) -> dict:
    return {
        "round_range": _round_range(hands),
        "display": to_display(_sum_hands(hands, hero_gp_id)),
    }


def _split_thirds(hands: list, hero_gp_id) -> list[dict]:
    n = len(hands)
    third = n // 3
    if third == 0:
        bounds = [(0, n)]
    else:
        bounds = [(0, third), (third, 2 * third), (2 * third, n)]

    segments = []
    for label, (start, end) in zip(_THIRDS, bounds):
        segment_hands = hands[start:end]
        if not segment_hands:
            continue
        segments.append({"label": label, **_segment(segment_hands, hero_gp_id)})
    return segments


def _hero_hand_player(hand, hero_gp_id):
    return next((hp for hp in hand.players if hp.game_player_id == hero_gp_id), None)


def _biggest_lost_pot_index(hands: list, hero_gp_id) -> int | None:
    """Index (within ``hands``) of the largest pot the hero did NOT win, or None."""
    best_index = None
    best_pot = -1
    for i, hand in enumerate(hands):
        hero_hp = _hero_hand_player(hand, hero_gp_id)
        if hero_hp is None or hero_hp.is_winner:
            continue
        if hand.pot_total > best_pot:
            best_pot = hand.pot_total
            best_index = i
    return best_index


def _split_biggest_lost_pot(hands: list, hero_gp_id) -> dict | None:
    idx = _biggest_lost_pot_index(hands, hero_gp_id)
    if idx is None:
        return None
    pre_hands = hands[:idx]
    post_hands = hands[idx:]
    if not pre_hands or not post_hands:
        return None
    return {
        "hand_round_count": hands[idx].round_count,
        "pre": _segment(pre_hands, hero_gp_id),
        "post": _segment(post_hands, hero_gp_id),
    }


def compute_session_dynamics(hands: list, hero_gp_id) -> dict:
    """Split ``hands`` (already sorted by ``round_count``, eager-loaded) into
    thirds and a pre/post-biggest-lost-pot pair, with per-segment
    ``to_display()`` output."""
    return {
        "thirds": _split_thirds(hands, hero_gp_id),
        "biggest_lost_pot_split": _split_biggest_lost_pot(hands, hero_gp_id),
    }
