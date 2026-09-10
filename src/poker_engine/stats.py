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
from poker_engine.scenarios import profile_scope_for_game

_VPIP_ACTIONS = {"call", "raise"}
_STREETS = ("preflop", "flop", "turn", "river")
_POSTFLOP_STREETS = ("flop", "turn", "river")

@dataclass
class RawStatCounts:
    hands_dealt: int = 0
    vpip_hands: int = 0
    pfr_hands: int = 0
    limp_hands: int = 0
    three_bet_opportunities: int = 0
    three_bet_hands: int = 0
    faced_3bet_after_raise: int = 0
    folded_to_3bet: int = 0

    open_shove_opportunities: int = 0
    open_shove_hands: int = 0
    reshove_opportunities: int = 0
    reshove_hands: int = 0
    call_off_opportunities: int = 0
    call_off_hands: int = 0

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
    by_table_size: dict[int, "RawStatCounts"] = field(default_factory=dict)

    def __add__(self, other: "RawStatCounts") -> "RawStatCounts":
        if not isinstance(other, RawStatCounts):
            return NotImplemented
        out = RawStatCounts()
        for f in fields(self):
            if f.name in {"by_position", "by_table_size"}:
                continue
            setattr(out, f.name, getattr(self, f.name) + getattr(other, f.name))
        positions = set(self.by_position) | set(other.by_position)
        for pos in positions:
            a = self.by_position.get(pos, RawStatCounts())
            b = other.by_position.get(pos, RawStatCounts())
            out.by_position[pos] = a + b
        table_sizes = set(self.by_table_size) | set(other.by_table_size)
        for table_size in table_sizes:
            a = self.by_table_size.get(table_size, RawStatCounts())
            b = other.by_table_size.get(table_size, RawStatCounts())
            out.by_table_size[table_size] = a + b
        return out


def _flat_counts(counts: RawStatCounts) -> RawStatCounts:
    """Copy scalar counters without recursively copying breakdowns."""
    return RawStatCounts(**{
        f.name: getattr(counts, f.name)
        for f in fields(counts)
        if f.name not in {"by_position", "by_table_size"}
    })


def _active_player_count(hand: Hand) -> int | None:
    """Return the dealt-in player count for new and legacy hand rows."""
    stored = getattr(hand, "active_player_count", None)
    if stored:
        return int(stored)
    active_rows = [
        hp for hp in hand.players
        if getattr(hp, "starting_stack", None) is not None and hp.starting_stack > 0
    ]
    if active_rows:
        return len(active_rows)
    # Unit fixtures and very old rows may not carry starting-stack snapshots.
    return len(hand.players) or None


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


def _is_positive_call(action: Action) -> bool:
    """A voluntary call, excluding PokerKit's ``CALL amount=0`` check encoding."""
    return action.action == "call" and action.amount > 0


def _is_positive_bet_or_raise(action: Action) -> bool:
    return action.action == "raise" and action.amount > 0


def _continuation_action(actions: list[Action], aggressor_id) -> tuple[bool, bool, int | None]:
    """Return opportunity, bet-made, and bet sequence for a continuation action.

    Checks before the aggressor are harmless.  A positive bet before the
    aggressor removes the opportunity (it is a donk/lead), and a missing action
    means the aggressor was all-in or the hand ended before they could act.
    """
    positive_bet_seen = False
    for action in actions:
        if action.game_player_id == aggressor_id:
            if positive_bet_seen:
                return False, False, None
            if _is_positive_bet_or_raise(action):
                return True, True, action.seq
            if action.action == "call" and action.amount == 0:
                return True, False, None
            return False, False, None
        if _is_positive_bet_or_raise(action):
            positive_bet_seen = True
    return False, False, None


def _hero_response_to_cbet(actions: list[Action], hero_id, bet_seq: int) -> Action | None:
    """Hero's direct response to a c-bet, or ``None`` if another raise intervened."""
    for action in actions:
        if action.seq <= bet_seq:
            continue
        if action.game_player_id == hero_id:
            return action
        if _is_positive_bet_or_raise(action):
            return None
    return None


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
    if any(_is_positive_call(a) or a.action == "raise" for a in hero_preflop):
        counts.vpip_hands = 1
    if any(a.action == "raise" for a in hero_preflop):
        counts.pfr_hands = 1
    raises_before_action = 0
    for action in preflop:
        if action.game_player_id == game_player_id and _is_positive_call(action) \
                and raises_before_action == 0:
            counts.limp_hands = 1
            break
        if action.action == "raise":
            raises_before_action += 1

    # -- 3-bet opportunity / hit / fold-to-3bet -----------------------------
    # A 3-bet opportunity only exists at an actual hero decision with exactly
    # one raise already made.  This excludes raises after hero folded and cold
    # 4-bet spots where two raises already precede hero.
    raises_seen = 0
    for act in preflop:
        if act.game_player_id == game_player_id:
            if act.action in {"fold", "call", "raise"} and raises_seen == 1:
                counts.three_bet_opportunities = 1
                if act.action == "raise":
                    counts.three_bet_hands = 1
            if act.action == "raise":
                raises_seen += 1
        elif act.action == "raise":
            raises_seen += 1

    # Fold-to-3bet applies only when hero made the first raise and then had an
    # actual response to the second raise.  Folding a 3-bet to a 4-bet is not
    # folded-to-3bet.
    first_raise = next((a for a in preflop if a.action == "raise"), None)
    if first_raise is not None and first_raise.game_player_id == game_player_id:
        second_raise = next(
            (a for a in preflop if a.seq > first_raise.seq and a.action == "raise"),
            None,
        )
        if second_raise is not None:
            response = None
            for action in preflop:
                if action.seq <= second_raise.seq:
                    continue
                if action.game_player_id == game_player_id \
                        and action.action in {"fold", "call", "raise"}:
                    response = action
                    break
                if action.action == "raise":
                    # Another player cold-4-bet before hero could respond;
                    # hero's eventual action is against that 4-bet, not the
                    # original 3-bet.
                    break
            if response is not None:
                counts.faced_3bet_after_raise = 1
                if response.action == "fold":
                    counts.folded_to_3bet = 1

    # -- deterministic short-stack frequency counters -----------------------
    prior_voluntary_action = False
    prior_allin_raise = False
    raises_seen = 0
    for act in preflop:
        is_voluntary = act.action == "raise" or _is_positive_call(act)
        if act.game_player_id == game_player_id and act.action in {"fold", "call", "raise"}:
            if not prior_voluntary_action:
                counts.open_shove_opportunities = 1
                if act.action == "raise" and act.stack_after == 0:
                    counts.open_shove_hands = 1
            if raises_seen == 1:
                counts.reshove_opportunities = 1
                if act.action == "raise" and act.stack_after == 0:
                    counts.reshove_hands = 1
            if prior_allin_raise:
                counts.call_off_opportunities = 1
                if _is_positive_call(act):
                    counts.call_off_hands = 1
        if act.game_player_id != game_player_id and act.action == "raise":
            raises_seen += 1
            prior_allin_raise = act.stack_after == 0
        elif act.action == "raise":
            raises_seen += 1
        if is_voluntary:
            prior_voluntary_action = True

    # -- c-bet / fold-to-cbet per street -------------------------------------
    continuation_aggressor = _aggressor_of_street(by_street, "preflop")
    for street in _POSTFLOP_STREETS:
        street_reached = _street_was_reached(hand, street)
        acts = by_street[street]
        opportunity = did_cbet = False
        bet_seq = None
        if continuation_aggressor is not None and street_reached:
            opportunity, did_cbet, bet_seq = _continuation_action(acts, continuation_aggressor)

        if continuation_aggressor == game_player_id and opportunity:
            setattr(counts, f"cbet_opportunities_{street}",
                    getattr(counts, f"cbet_opportunities_{street}") + 1)
            if did_cbet:
                setattr(counts, f"cbet_{street}", getattr(counts, f"cbet_{street}") + 1)

        if continuation_aggressor is not None and continuation_aggressor != game_player_id \
                and did_cbet and bet_seq is not None:
            response = _hero_response_to_cbet(acts, game_player_id, bet_seq)
            if response is not None:
                setattr(counts, f"faced_cbet_opportunities_{street}",
                        getattr(counts, f"faced_cbet_opportunities_{street}") + 1)
                setattr(counts, f"faced_cbet_{street}", getattr(counts, f"faced_cbet_{street}") + 1)
                if response.action == "fold":
                    setattr(counts, f"folded_to_cbet_{street}",
                            getattr(counts, f"folded_to_cbet_{street}") + 1)

        # Turn/river continuation requires the same aggressor to have made the
        # prior street's c-bet and retained the betting lead.  A checked-through
        # street, donk, or check-raise ends this chain.
        if not did_cbet or _aggressor_of_street(by_street, street) != continuation_aggressor:
            continuation_aggressor = None

    # -- WTSD / showdown / won-at-showdown -----------------------------------
    folded_preflop = any(a.action == "fold" for a in hero_preflop)
    saw_flop = _street_was_reached(hand, "flop") and not folded_preflop
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
            if _is_positive_bet_or_raise(act):
                counts.postflop_bets_raises += 1
            elif _is_positive_call(act):
                counts.postflop_calls += 1

    if hero_hp.position:
        counts.by_position[hero_hp.position] = _flat_counts(counts)

    table_size = _active_player_count(hand)
    if table_size is not None:
        counts.by_table_size[table_size] = _flat_counts(counts)

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


def compute_player_stats(db, user_id, profile_scope: str | None = None) -> RawStatCounts:
    """Hero counts across games, optionally isolated to one profile scope."""
    games = db.execute(
        select(Game)
        .where(Game.hero_user_id == user_id)
        .options(selectinload(Game.players))
    ).scalars().all()

    total = RawStatCounts()
    for game in games:
        if profile_scope and profile_scope_for_game(game) != profile_scope:
            continue
        hero = next((gp for gp in game.players if not gp.is_bot and gp.user_id == user_id), None)
        if hero is None:
            continue
        total = total + compute_game_stats(db, game.id, hero.id)
    return total


def _pct(numerator: int, denominator: int) -> dict:
    pct = round(100 * numerator / denominator, 1) if denominator else None
    return {"pct": pct, "n": numerator, "d": denominator}


def _ratio(numerator: int, denominator: int) -> dict:
    ratio = round(numerator / denominator, 2) if denominator else None
    return {"ratio": ratio, "infinite": bool(numerator and not denominator),
            "n": numerator, "d": denominator}


def to_display(counts: RawStatCounts) -> dict:
    """Turn raw counts into percentages + underlying counts, never hiding for sample size."""
    out = {
        "hands_dealt": counts.hands_dealt,
        "vpip": _pct(counts.vpip_hands, counts.hands_dealt),
        "pfr": _pct(counts.pfr_hands, counts.hands_dealt),
        "limp": _pct(counts.limp_hands, counts.hands_dealt),
        "three_bet": _pct(counts.three_bet_hands, counts.three_bet_opportunities),
        "fold_to_3bet": _pct(counts.folded_to_3bet, counts.faced_3bet_after_raise),
        "open_shove": _pct(counts.open_shove_hands, counts.open_shove_opportunities),
        "reshove": _pct(counts.reshove_hands, counts.reshove_opportunities),
        "call_off": _pct(counts.call_off_hands, counts.call_off_opportunities),
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
        "by_table_size": {
            str(table_size): to_display(table_counts)
            for table_size, table_counts in sorted(counts.by_table_size.items(), reverse=True)
        },
    }
    return out
