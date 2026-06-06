"""Records a game from the hero (human) player's perspective.

The recorder attaches to a single seat by wrapping that player's ``receive_*``
callbacks, so it only ever sees what that seat can see. During the game it
buffers plain Python structures; after ``start_poker`` returns, ``flush``
writes everything to the database in one transaction.

The hidden-information rule lives in ``_record_round_result``: an opponent's
hole cards are captured only when its uuid appears in PyPokerEngine's
``hand_info`` (i.e. it reached showdown). Otherwise they stay ``None`` and the
``hand_players`` row stores NULL with ``revealed=False``. The hero's own cards,
delivered every round in ``receive_round_start``, are always recorded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from poker_engine.config import GameConfig
from poker_engine.db.models import (
    Action,
    BotStyle,
    Game,
    GamePlayer,
    Hand,
    HandPlayer,
    Street,
)

# PyPokerEngine action-history "action" values (uppercase) → our lowercase tags.
_ACTION_NAMES = {
    "FOLD": "fold",
    "CALL": "call",
    "RAISE": "raise",
    "SMALLBLIND": "smallblind",
    "BIGBLIND": "bigblind",
    "ANTE": "ante",
}

_VPIP_ACTIONS = {"call", "raise"}


@dataclass
class _ActionRecord:
    engine_uuid: str
    street: Street
    action: str
    amount: int
    seq: int


@dataclass
class _HandRecord:
    round_count: int
    hero_hole: list[str]
    button_pos: int | None = None
    sb_pos: int | None = None
    bb_pos: int | None = None
    starting_stacks: dict[str, int] = field(default_factory=dict)
    street_reached: Street = Street.PREFLOP
    board: list[str] = field(default_factory=list)
    pot_total: int = 0
    pot: dict | None = None
    had_showdown: bool = False
    actions: list[_ActionRecord] = field(default_factory=list)
    # engine_uuid -> hole cards, for all players (revealed at showdown or not).
    all_hole_cards: dict[str, list[str]] = field(default_factory=dict)
    # engine_uuid -> hole cards, ONLY for seats whose cards are known to hero (shown in UI).
    revealed_cards: dict[str, list[str]] = field(default_factory=dict)
    winners: set[str] = field(default_factory=set)
    final_stacks: dict[str, int] = field(default_factory=dict)


class PerspectiveRecorder:
    """Observes one seat and buffers the game for later persistence."""

    def __init__(self, hero_engine_uuid: str | None = None):
        # When the hero seat's uuid is not known up front (assigned by the
        # engine), it is inferred at the first round start from the seat whose
        # hole cards we receive. We store it once learned.
        self._hero_uuid = hero_engine_uuid
        self._seats: list[dict] = []  # game-start seat order: {name, uuid, stack}
        self._hands: list[_HandRecord] = []
        self._current: _HandRecord | None = None
        # Incremental persistence state (used by ``flush_incremental``). The
        # one-shot ``flush`` ignores these.
        self._game_id = None
        self._persisted_rounds: set[int] = set()

    # -- live accessors -----------------------------------------------------

    def last_showdown_reveals(self, exclude_uuid: str | None = None) -> dict[str, list[str]]:
        """Exact hole cards revealed at the most recently finished hand.

        Populated from the (patched) ``hand_info`` of the round-result message,
        so it contains only seats that reached showdown. Pass the hero uuid to
        ``exclude_uuid`` to omit the hero (the UI shows the hero separately).
        Returns ``{}`` when the last hand had no showdown.
        """
        if not self._hands:
            return {}
        reveals = self._hands[-1].revealed_cards
        return {u: list(c) for u, c in reveals.items() if u != exclude_uuid}

    def last_hero_hole(self) -> list[str]:
        """The hero's own hole cards for the most recently recorded hand.

        Captured at round start, so it is available even after the engine clears
        the table at showdown (when reading the live table would return nothing).
        """
        if not self._hands:
            return []
        return list(self._hands[-1].hero_hole)

    # -- attachment ---------------------------------------------------------

    def attach(self, player) -> None:
        """Wrap ``player``'s receive callbacks so we observe its view."""
        self._wrap(player, "receive_game_start_message", self._record_game_start)
        self._wrap(player, "receive_round_start_message", self._record_round_start)
        self._wrap(player, "receive_round_result_message", self._record_round_result)

    def _wrap(self, player, method_name, hook):
        original = getattr(player, method_name)

        def wrapped(*args, **kwargs):
            result = original(*args, **kwargs)
            hook(*args, **kwargs)
            return result

        setattr(player, method_name, wrapped)

    # -- observation hooks --------------------------------------------------

    def _record_game_start(self, game_info):
        self._seats = [
            {"name": s["name"], "uuid": s["uuid"], "stack": s["stack"]}
            for s in game_info.get("seats", [])
        ]

    def _record_round_start(self, round_count, hole_card, seats):
        # The hero is the seat whose hole cards we just received. Identify it by
        # the seat ordering captured at game start (uuids are stable).
        hand = _HandRecord(round_count=round_count, hero_hole=list(hole_card))
        hand.starting_stacks = {s["uuid"]: s["stack"] for s in seats}
        self._current = hand
        self._hands.append(hand)

    def _record_round_result(self, winners, hand_info, round_state, revealed_uuids: set[str] | None = None):
        hand = self._current
        if hand is None:
            return

        hand.button_pos = round_state.get("dealer_btn")
        hand.sb_pos = round_state.get("small_blind_pos")
        hand.bb_pos = round_state.get("big_blind_pos")
        hand.board = list(round_state.get("community_card", []))
        hand.street_reached = _street(round_state.get("street"))
        hand.pot = round_state.get("pot")
        hand.pot_total = _pot_total(hand.pot)
        hand.had_showdown = bool(revealed_uuids) if revealed_uuids is not None else bool(hand_info)
        hand.winners = {w["uuid"] for w in winners}
        hand.final_stacks = {s["uuid"]: s["stack"] for s in round_state.get("seats", [])}

        # Identify hero by matching its hole cards into the revealed map below.
        self._hero_uuid = self._infer_hero_uuid(round_state, hand)
        if self._hero_uuid:
            hand.revealed_cards[self._hero_uuid] = list(hand.hero_hole)

        # All players' hole cards: store all (including folded), but only mark as revealed
        # those who actually showed their cards at showdown (passed in revealed_uuids).
        for entry in hand_info or []:
            cards = _extract_hole(entry)
            if cards is not None:
                hand.all_hole_cards[entry["uuid"]] = cards
                if entry["uuid"] != self._hero_uuid and (revealed_uuids is None or entry["uuid"] in revealed_uuids):
                    hand.revealed_cards[entry["uuid"]] = cards

        hand.actions = self._flatten_actions(round_state.get("action_histories", {}))
        self._current = None

    # -- parsing helpers ----------------------------------------------------

    def _infer_hero_uuid(self, round_state, hand: _HandRecord) -> str | None:
        if self._hero_uuid:
            return self._hero_uuid
        # Fall back: the hero is the only seat whose hole cards we hold. Without
        # an explicit uuid we cannot map blindly, so we leave it to the engine
        # layer to pass the uuid in. As a safety net, return None.
        return None

    def _flatten_actions(self, action_histories: dict) -> list[_ActionRecord]:
        records: list[_ActionRecord] = []
        seq = 0
        for street_name in ("preflop", "flop", "turn", "river"):
            street = _street(street_name)
            for entry in action_histories.get(street_name, []) or []:
                action = _ACTION_NAMES.get(entry.get("action"), entry.get("action", "").lower())
                records.append(
                    _ActionRecord(
                        engine_uuid=entry["uuid"],
                        street=street,
                        action=action,
                        amount=int(entry.get("amount", 0) or 0),
                        seq=seq,
                    )
                )
                seq += 1
        return records

    # -- persistence --------------------------------------------------------

    def flush(
        self,
        session,
        config: GameConfig,
        hero_engine_uuid: str | None,
        bot_params_by_uuid: dict[str, dict] | None = None,
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
    ):
        """Persist the whole game to the database and return the Game row.

        ``bot_params_by_uuid`` maps each bot seat's engine uuid to the resolved
        style parameters it actually played with (stored as ``bot_params``).
        """
        bot_params_by_uuid = bot_params_by_uuid or {}
        if hero_engine_uuid:
            self._hero_uuid = hero_engine_uuid
            # Backfill hero cards on hands recorded before the uuid was known.
            for hand in self._hands:
                hand.revealed_cards.setdefault(hero_engine_uuid, list(hand.hero_hole))

        hero_user = self._upsert_hero_user(session, config)
        game, gp_by_uuid = self._create_game_and_seats(
            session, config, hero_user, bot_params_by_uuid, started_at, ended_at
        )

        # Per-hand rows.
        for hand_rec in self._hands:
            self._persist_hand(session, game, hand_rec, gp_by_uuid)

        self._accumulate_stats(gp_by_uuid)
        session.commit()
        return game

    def _create_game_and_seats(
        self, session, config, hero_user, bot_params_by_uuid, started_at, ended_at
    ) -> tuple[Game, dict[str, GamePlayer]]:
        """Create the Game row and one GamePlayer per seat (game-start order).

        Shared by ``flush`` and ``flush_incremental``. Adds rows to the session
        but does not commit.
        """
        seat_specs = {spec.name: spec for spec in config.seats}
        game = Game(
            started_at=started_at,
            ended_at=ended_at,
            small_blind=config.small_blind,
            big_blind=config.big_blind,
            ante=config.ante,
            buy_in=config.buy_in,
            max_round=config.max_round,
            hero_user_id=hero_user.id if hero_user else None,
            rule={
                "small_blind": config.small_blind,
                "big_blind": config.big_blind,
                "ante": config.ante,
                "buy_in": config.buy_in,
                "max_round": config.max_round,
            },
        )
        session.add(game)

        gp_by_uuid: dict[str, GamePlayer] = {}
        for index, seat in enumerate(self._seats):
            spec = seat_specs.get(seat["name"])
            is_bot = spec.is_bot if spec else seat["uuid"] != self._hero_uuid
            gp = GamePlayer(
                game=game,
                seat_index=index,
                display_name=seat["name"],
                engine_uuid=seat["uuid"],
                user_id=hero_user.id if (hero_user and not is_bot) else None,
                is_bot=is_bot,
                bot_style=BotStyle(spec.kind.value) if (spec and is_bot) else None,
                bot_params=bot_params_by_uuid.get(seat["uuid"]) if is_bot else None,
                starting_stack=config.buy_in,
                final_stack=self._final_stack(seat["uuid"]),
                # Initialize counters Python-side: column defaults only apply at
                # INSERT, but we increment them before committing.
                hands_played=0,
                hands_won=0,
                total_winnings=0,
                vpip_count=0,
                pfr_count=0,
            )
            gp_by_uuid[seat["uuid"]] = gp
            session.add(gp)
        return game, gp_by_uuid

    def flush_incremental(
        self,
        session,
        config: GameConfig,
        hero_engine_uuid: str | None,
        bot_params_by_uuid: dict[str, dict] | None = None,
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
    ):
        """Persist progressively: create the game once, then append new hands.

        Idempotent and safe to call repeatedly. On the first call it creates the
        ``Game`` and ``GamePlayer`` rows; every call writes only hands whose
        ``round_count`` has not been persisted yet and recomputes per-seat
        aggregate stats from all buffered hands. Each call runs in its own
        session, so ORM rows are always re-resolved by id rather than cached
        across sessions.
        """
        bot_params_by_uuid = bot_params_by_uuid or {}
        if hero_engine_uuid:
            self._hero_uuid = hero_engine_uuid
            for hand in self._hands:
                hand.revealed_cards.setdefault(hero_engine_uuid, list(hand.hero_hole))

        if self._game_id is None:
            hero_user = self._upsert_hero_user(session, config)
            game, gp_by_uuid = self._create_game_and_seats(
                session, config, hero_user, bot_params_by_uuid, started_at, ended_at
            )
            session.flush()  # assign PKs
            self._game_id = game.id
        else:
            game = session.get(Game, self._game_id)
            # Re-resolve seats by id within this live session (the cached ORM
            # objects from a prior call are detached now).
            gp_by_uuid = {
                gp.engine_uuid: gp
                for gp in session.query(GamePlayer).filter_by(game_id=self._game_id)
            }
            if ended_at is not None:
                game.ended_at = ended_at

        # Persist only *completed* hands. ``self._current`` is the hand still in
        # progress (recorded at round start, but its board/actions/winners are
        # not filled in until ``_record_round_result``). Writing it now would
        # persist an empty shell and, via the round dedup below, prevent its real
        # contents from ever being saved.
        completed = [h for h in self._hands if h is not self._current]

        # Append hands not yet written.
        for hand_rec in completed:
            if hand_rec.round_count in self._persisted_rounds:
                continue
            self._persist_hand(session, game, hand_rec, gp_by_uuid)
            self._persisted_rounds.add(hand_rec.round_count)

        # Recompute aggregate stats + final stacks from all completed hands.
        for gp in gp_by_uuid.values():
            gp.hands_played = 0
            gp.hands_won = 0
            gp.total_winnings = 0
            gp.vpip_count = 0
            gp.pfr_count = 0
            gp.final_stack = self._final_stack(gp.engine_uuid)
        self._accumulate_stats(gp_by_uuid, hands=completed)

        session.commit()
        return game

    def _persist_hand(self, session, game, hand_rec, gp_by_uuid):
        hand = Hand(
            game=game,
            round_count=hand_rec.round_count,
            button_pos=hand_rec.button_pos,
            sb_pos=hand_rec.sb_pos,
            bb_pos=hand_rec.bb_pos,
            street_reached=hand_rec.street_reached,
            board=hand_rec.board,
            pot_total=hand_rec.pot_total,
            had_showdown=hand_rec.had_showdown,
            pot=hand_rec.pot,
        )
        session.add(hand)

        for uuid_, gp in gp_by_uuid.items():
            start = hand_rec.starting_stacks.get(uuid_)
            final = hand_rec.final_stacks.get(uuid_)
            # Store all hole cards (both revealed and unrevealed)
            cards = hand_rec.all_hole_cards.get(uuid_)
            # A player's cards are "revealed" only if they were shown in the UI (hero or showdown)
            is_revealed = uuid_ in hand_rec.revealed_cards
            won = uuid_ in hand_rec.winners
            amount_won = (final - start) if (final is not None and start is not None) else 0
            session.add(
                HandPlayer(
                    hand=hand,
                    game_player=gp,
                    hole_cards=cards,
                    revealed=is_revealed,
                    is_winner=won,
                    amount_won=amount_won,
                    starting_stack=start,
                    final_stack=final,
                )
            )

        for act in hand_rec.actions:
            gp = gp_by_uuid.get(act.engine_uuid)
            if gp is None:
                continue
            session.add(
                Action(
                    hand=hand,
                    game_player=gp,
                    street=act.street,
                    action=act.action,
                    amount=act.amount,
                    seq=act.seq,
                )
            )

    def _accumulate_stats(self, gp_by_uuid, hands=None):
        hands = self._hands if hands is None else hands
        for uuid_, gp in gp_by_uuid.items():
            for hand_rec in hands:
                if uuid_ not in hand_rec.starting_stacks:
                    continue
                gp.hands_played += 1
                if uuid_ in hand_rec.winners:
                    gp.hands_won += 1
                start = hand_rec.starting_stacks.get(uuid_)
                final = hand_rec.final_stacks.get(uuid_)
                if start is not None and final is not None:
                    gp.total_winnings += final - start
                preflop_actions = [
                    a for a in hand_rec.actions
                    if a.engine_uuid == uuid_ and a.street == Street.PREFLOP
                ]
                if any(a.action in _VPIP_ACTIONS for a in preflop_actions):
                    gp.vpip_count += 1
                if any(a.action == "raise" for a in preflop_actions):
                    gp.pfr_count += 1

    def _upsert_hero_user(self, session, config: GameConfig):
        from poker_engine.db.models import User

        hero_spec = config.hero_seat
        if hero_spec is None:
            return None
        email = hero_spec.email or f"{hero_spec.name}@local.poker"
        user = session.query(User).filter_by(email=email).one_or_none()
        if user is None:
            user = User(email=email, display_name=hero_spec.name)
            session.add(user)
            session.flush()
        return user

    def _final_stack(self, uuid_: str) -> int | None:
        # Use the most recent hand that actually has final stacks recorded. The
        # in-progress hand (during incremental saves) has an empty
        # ``final_stacks``, so skip it and fall back to the last completed hand.
        for hand_rec in reversed(self._hands):
            if hand_rec.final_stacks:
                return hand_rec.final_stacks.get(uuid_)
        return None


def _street(name) -> Street:
    if name is None:
        return Street.PREFLOP
    try:
        return Street(str(name).lower())
    except ValueError:
        return Street.SHOWDOWN


def _pot_total(pot) -> int:
    if not pot:
        return 0
    main = pot.get("main", {}).get("amount", 0)
    side = sum(s.get("amount", 0) for s in pot.get("side", []))
    return main + side


def _extract_hole(hand_info_entry) -> list[str] | None:
    """Pull the exact hole-card strings from a showdown hand_info entry.

    Relies on the vendored PyPokerEngine patch that adds a ``hole_card`` list
    of card strings to each showdown participant's entry.
    """
    hole = hand_info_entry.get("hole_card")
    if isinstance(hole, list) and hole:
        return [str(c) for c in hole]
    return None
