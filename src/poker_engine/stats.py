"""Deterministic, hero-only poker stats.

Pure functions over already-recorded ``Hand``/``HandPlayer``/``Action`` rows —
no LLM involvement, no judgment calls about hand strength or correctness.
Everything here is a count of actions actually taken, safe to run against a
finished game or an in-progress one (a live game persists completed hands
incrementally; see ``ws.py``'s ``_save_soft`` / ``GameSession.persist_incremental``).

Two entry points fetch rows from the DB and fold them through the pure counting
function below:

    compute_game_stats(db, game_id, game_player_id) -> RawStatCounts
    compute_player_stats(db, user_id)               -> RawStatCounts
    to_display(counts)                               -> dict

``RawStatCounts`` is summed (never averaged) across games — this is what makes
cross-game rollup correct: combining Game A (3/10 VPIP) and Game B (1/20 VPIP)
must yield 4/30, not the mean of the two percentages.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from poker_engine.db.models import Action, Game, GamePlayer, Hand, HandPlayer, Street

_VPIP_ACTIONS = {"call", "raise"}
_STREETS = ("preflop", "flop", "turn", "river")
_POSTFLOP_STREETS = ("flop", "turn", "river")

@dataclass
class RawStatCounts:
    hands_dealt: int = 0
    vpip_hands: int = 0
    pfr_hands: int = 0
    three_bet_opportunities: int = 0
    three_bet_hands: int = 0
    faced_3bet_after_raise: int = 0
    folded_to_3bet: int = 0

    cbet_flop: int = 0
    cbet_turn: int = 0
    cbet_river: int = 0
    cbet_opportunities_flop: int = 0
    cbet_opportunities_turn: int = 0
    cbet_opportunities_river: int = 0
    faced_cbet_flop: int = 0
    faced_cbet_turn: int = 0
    faced_cbet_river: int = 0
    faced_cbet_opportunities_flop: int = 0
    faced_cbet_opportunities_turn: int = 0
    faced_cbet_opportunities_river: int = 0
    folded_to_cbet_flop: int = 0
    folded_to_cbet_turn: int = 0
    folded_to_cbet_river: int = 0

    saw_flop_hands: int = 0
    wtsd_hands: int = 0
    showdown_hands: int = 0
    won_at_showdown_hands: int = 0

    postflop_bets_raises: int = 0
    postflop_calls: int = 0

    by_position: dict[str, "RawStatCounts"] = field(default_factory=dict)

    def __add__(self, other: "RawStatCounts") -> "RawStatCounts":
        if not isinstance(other, RawStatCounts):
            return NotImplemented
        out = RawStatCounts()
        for f in fields(self):
            if f.name == "by_position":
                continue
            setattr(out, f.name, getattr(self, f.name) + getattr(other, f.name))
        positions = set(self.by_position) | set(other.by_position)
        for pos in positions:
            a = self.by_position.get(pos, RawStatCounts())
            b = other.by_position.get(pos, RawStatCounts())
            out.by_position[pos] = a + b
        return out


def _aggressor_of_street(actions_by_street: dict[str, list[Action]], street: str) -> str | None:
    """The ``game_player_id`` whose bet/raise stood as the street's last aggressor.

    A street's aggressor is whoever made the last unmatched raise on it (i.e.
    the last ``raise`` action, since a further ``raise`` would represent a new
    aggressor). Returns ``None`` if nobody raised on that street (a checked-
    through street has no aggressor, so there is no c-bet opportunity on the
    next street).
    """
    last_raiser = None
    for act in actions_by_street.get(street, []):
        if act.action == "raise":
            last_raiser = act.game_player_id
    return last_raiser


def _hand_actions_by_street(hand: Hand) -> dict[str, list[Action]]:
    by_street: dict[str, list[Action]] = {s: [] for s in _STREETS}
    for act in sorted(hand.actions, key=lambda a: a.seq):
        street = act.street.value if isinstance(act.street, Street) else str(act.street)
        if street in by_street:
            by_street[street].append(act)
    return by_street


def compute_hand_stats(hand: Hand, game_player_id) -> RawStatCounts:
    """Compute raw counts for one hero seat in one hand.

    ``hand`` must have ``actions`` and ``players`` populated (a list of
    ``Action``/``HandPlayer``-shaped rows, sorted by nothing in particular —
    this function sorts by ``seq`` itself). ``game_player_id`` identifies the
    hero's seat within this hand.
    """
    counts = RawStatCounts(hands_dealt=1)

    hero_hp = next((hp for hp in hand.players if hp.game_player_id == game_player_id), None)
    if hero_hp is None:
        # Caller guarantees hero has a hand_players row; defensive no-op.
        return counts

    by_street = _hand_actions_by_street(hand)
    preflop = by_street["preflop"]

    hero_preflop = [a for a in preflop if a.game_player_id == game_player_id]
    if any(a.action in _VPIP_ACTIONS for a in hero_preflop):
        counts.vpip_hands = 1
    if any(a.action == "raise" for a in hero_preflop):
        counts.pfr_hands = 1

    # -- 3-bet opportunity / hit / fold-to-3bet -----------------------------
    # Walk preflop actions in order, tracking raises seen so far and whether
    # hero has made their own (first) raise yet.
    raises_before_hero_raise = 0
    hero_raised = False
    hero_raise_seq = None
    faced_opportunity = False
    took_3bet = False
    for act in preflop:
        if act.game_player_id == game_player_id:
            if act.action == "raise" and not hero_raised:
                # Hero opportunity to 3-bet exists if a raise already happened
                # before this action of hero's.
                if raises_before_hero_raise >= 1:
                    faced_opportunity = True
                    took_3bet = True
                hero_raised = True
                hero_raise_seq = act.seq
        else:
            if act.action == "raise":
                if not hero_raised:
                    raises_before_hero_raise += 1
                    if raises_before_hero_raise >= 1:
                        # Hero faced a raise before their own next action —
                        # opportunity exists regardless of what hero does next.
                        faced_opportunity = True

    if faced_opportunity:
        counts.three_bet_opportunities = 1
        if took_3bet:
            counts.three_bet_hands = 1

    # Fold-to-3bet: hero raised preflop, then a further raise came from
    # someone else, then hero folded.
    if hero_raised:
        further_raise = False
        hero_folded_after = False
        for act in preflop:
            if act.seq <= hero_raise_seq:
                continue
            if act.game_player_id != game_player_id and act.action == "raise":
                further_raise = True
            elif act.game_player_id == game_player_id:
                if further_raise and act.action == "fold":
                    hero_folded_after = True
                break
        if further_raise:
            counts.faced_3bet_after_raise = 1
            if hero_folded_after:
                counts.folded_to_3bet = 1

    # -- c-bet / fold-to-cbet per street -------------------------------------
    prev_aggressor = _aggressor_of_street(by_street, "preflop")
    for street in _POSTFLOP_STREETS:
        street_reached = _street_was_reached(hand, street)
        acts = by_street[street]

        if prev_aggressor == game_player_id and street_reached:
            counts_field = f"cbet_opportunities_{street}"
            setattr(counts, counts_field, getattr(counts, counts_field) + 1)
            first_action = acts[0] if acts else None
            if first_action is not None and first_action.game_player_id == game_player_id \
                    and first_action.action == "raise" and first_action.amount > 0:
                field_name = f"cbet_{street}"
                setattr(counts, field_name, getattr(counts, field_name) + 1)

        if prev_aggressor is not None and prev_aggressor != game_player_id and street_reached:
            bettor_amount_seen = False
            hero_folded = False
            for act in acts:
                if act.game_player_id == prev_aggressor and act.action == "raise" and act.amount > 0:
                    bettor_amount_seen = True
                    continue
                if bettor_amount_seen and act.game_player_id == game_player_id:
                    if act.action == "fold":
                        hero_folded = True
                    break
            if bettor_amount_seen:
                setattr(counts, f"faced_cbet_opportunities_{street}",
                        getattr(counts, f"faced_cbet_opportunities_{street}") + 1)
                setattr(counts, f"faced_cbet_{street}",
                        getattr(counts, f"faced_cbet_{street}") + 1)
                if hero_folded:
                    setattr(counts, f"folded_to_cbet_{street}",
                            getattr(counts, f"folded_to_cbet_{street}") + 1)

        prev_aggressor = _aggressor_of_street(by_street, street) or prev_aggressor

    # -- WTSD / showdown / won-at-showdown -----------------------------------
    saw_flop = _street_was_reached(hand, "flop")
    if saw_flop:
        counts.saw_flop_hands = 1
    reached_showdown = bool(hand.had_showdown) and hero_hp.game_player_id is not None \
        and _hero_present_at_showdown(hand, hero_hp)
    if reached_showdown:
        counts.showdown_hands = 1
        if saw_flop:
            counts.wtsd_hands = 1
        if hero_hp.is_winner and hero_hp.amount_won > 0:
            counts.won_at_showdown_hands = 1

    # -- aggression factor components ----------------------------------------
    for street in _POSTFLOP_STREETS:
        for act in by_street[street]:
            if act.game_player_id != game_player_id:
                continue
            if act.action == "raise":
                counts.postflop_bets_raises += 1
            elif act.action == "call":
                counts.postflop_calls += 1

    if hero_hp.position:
        pos_counts = RawStatCounts(**{
            f.name: getattr(counts, f.name) for f in fields(counts) if f.name != "by_position"
        })
        counts.by_position[hero_hp.position] = pos_counts

    return counts


def _street_was_reached(hand: Hand, street: str) -> bool:
    order = {"preflop": 0, "flop": 1, "turn": 2, "river": 3, "showdown": 4}
    reached = hand.street_reached.value if isinstance(hand.street_reached, Street) else str(hand.street_reached)
    return order.get(reached, 0) >= order.get(street, 0)


def _hero_present_at_showdown(hand: Hand, hero_hp: HandPlayer) -> bool:
    """Hero reached showdown iff hero never folded during the hand."""
    return not any(
        a.game_player_id == hero_hp.game_player_id and a.action == "fold"
        for a in hand.actions
    )


def _sum_hands(hands: list[Hand], game_player_id) -> RawStatCounts:
    total = RawStatCounts()
    for hand in hands:
        if not any(hp.game_player_id == game_player_id for hp in hand.players):
            continue
        total = total + compute_hand_stats(hand, game_player_id)
    return total


def compute_game_stats(db, game_id, game_player_id) -> RawStatCounts:
    """Hero's raw stat counts for one game. Works whether the game is finished or not."""
    hands = db.execute(
        select(Hand)
        .where(Hand.game_id == game_id)
        .options(selectinload(Hand.actions), selectinload(Hand.players))
        .order_by(Hand.round_count)
    ).scalars().all()
    return _sum_hands(hands, game_player_id)


def compute_player_stats(db, user_id) -> RawStatCounts:
    """Hero's raw stat counts summed across every game they've played."""
    games = db.execute(
        select(Game)
        .where(Game.hero_user_id == user_id)
        .options(selectinload(Game.players))
    ).scalars().all()

    total = RawStatCounts()
    for game in games:
        hero = next((gp for gp in game.players if not gp.is_bot and gp.user_id == user_id), None)
        if hero is None:
            continue
        total = total + compute_game_stats(db, game.id, hero.id)
    return total


def _pct(numerator: int, denominator: int) -> dict:
    pct = round(100 * numerator / denominator, 1) if denominator else 0.0
    return {"pct": pct, "n": numerator, "d": denominator}


def _ratio(numerator: int, denominator: int) -> dict:
    ratio = round(numerator / denominator, 2) if denominator else 0.0
    return {"ratio": ratio, "n": numerator, "d": denominator}


def to_display(counts: RawStatCounts) -> dict:
    """Turn raw counts into percentages + underlying counts, never hiding for sample size."""
    out = {
        "hands_dealt": counts.hands_dealt,
        "vpip": _pct(counts.vpip_hands, counts.hands_dealt),
        "pfr": _pct(counts.pfr_hands, counts.hands_dealt),
        "three_bet": _pct(counts.three_bet_hands, counts.three_bet_opportunities),
        "fold_to_3bet": _pct(counts.folded_to_3bet, counts.faced_3bet_after_raise),
        "wtsd": _pct(counts.wtsd_hands, counts.saw_flop_hands),
        "wsd": _pct(counts.won_at_showdown_hands, counts.showdown_hands),
        # Aggression Factor: postflop-only (bets+raises)/calls. Not a percentage —
        # multiple conventions exist in the wild (some include preflop, some
        # divide by calls+folds); this is the chosen default, noted in the PR.
        "aggression_factor": _ratio(counts.postflop_bets_raises, counts.postflop_calls),
        "cbet": {
            street: _pct(getattr(counts, f"cbet_{street}"), getattr(counts, f"cbet_opportunities_{street}"))
            for street in _POSTFLOP_STREETS
        },
        "fold_to_cbet": {
            street: _pct(
                getattr(counts, f"folded_to_cbet_{street}"),
                getattr(counts, f"faced_cbet_opportunities_{street}"),
            )
            for street in _POSTFLOP_STREETS
        },
        "by_position": {pos: to_display(pc) for pos, pc in counts.by_position.items()},
    }
    return out
