"""GameSession: one interactive game driven by the PokerKit state machine.

PokerKit's NoLimitTexasHoldem is an imperative state machine.  One State
object per hand.  The web client drives the hero seat (via
``apply_hero_action``); bots act automatically inside the ``_advance`` loop
until it is the hero's turn, a hand finishes, or the game finishes.
Completed games are persisted with the existing PerspectiveRecorder.
"""

from __future__ import annotations

import random
import uuid as uuidlib
from datetime import datetime

from pokerkit import Automation, NoLimitTexasHoldem

from poker_engine import pk_adapter
from poker_engine.bots.styles import STYLE_REGISTRY
from poker_engine.config import GameConfig, SeatKind
from poker_engine.recorder import PerspectiveRecorder
from poker_trainer.game import serialize

# Automations that fire without any explicit call:
#   ANTE_POSTING           post antes at hand start
#   BET_COLLECTION         sweep bets to pot when betting ends
#   BLIND_OR_STRADDLE_POSTING   post SB/BB at hand start
#   HOLE_CARDS_SHOWING_OR_MUCKING  auto-muck / show at showdown
#   HAND_KILLING           kill dead hands
#   CHIPS_PUSHING          push chips to winners after showdown
#   CHIPS_PULLING          pull chips into stacks after push
#   CARD_BURNING           burn a card before each community deal
_AUTOMATIONS = (
    Automation.ANTE_POSTING,
    Automation.BET_COLLECTION,
    Automation.BLIND_OR_STRADDLE_POSTING,
    Automation.HOLE_CARDS_SHOWING_OR_MUCKING,
    Automation.HAND_KILLING,
    Automation.CHIPS_PUSHING,
    Automation.CHIPS_PULLING,
    # CARD_BURNING is NOT automated: we burn manually from our shuffled deck so
    # card indices stay aligned between our deck list and PokerKit's state.
)

# street_index -> name used in browser events / recorder
_STREET_NAMES = {0: "preflop", 1: "flop", 2: "turn", 3: "river"}
# cards dealt to the board per street
_BOARD_CARDS_PER_STREET = {1: 3, 2: 1, 3: 1}


class GameSession:
    def __init__(self, config: GameConfig, hero_index: int = 0, seed: int | None = None):
        config.validate()
        self.config = config
        self.game_id = str(uuidlib.uuid4())
        self.hero_index = hero_index
        self.seed = seed
        self._rng = random.Random(seed)

        n = len(config.seats)
        self.seat_uuids: list[str] = [
            f"seat-{i}-{uuidlib.uuid4().hex[:8]}" for i in range(n)
        ]
        self.hero_uuid = self.seat_uuids[hero_index]

        self.seat_meta: dict[str, dict] = {}
        self._bot_players: dict[int, object] = {}       # index -> StyleBot
        self._bot_params_by_uuid: dict[str, dict] = {}

        for index, spec in enumerate(config.seats):
            if spec.is_bot:
                bot_cls = STYLE_REGISTRY[spec.kind.value]
                bot_seed = None if seed is None else seed + index
                bot = bot_cls(seed=bot_seed, **(spec.params or {}))
                bot.set_n_players(n)
                self._bot_players[index] = bot
                self._bot_params_by_uuid[self.seat_uuids[index]] = bot.params.as_dict()
            self.seat_meta[self.seat_uuids[index]] = {
                "is_bot": spec.is_bot,
                "style": spec.kind.value if spec.is_bot else None,
                "hidden": spec.hidden if spec.is_bot else False,
            }

        self._stacks: list[int] = [config.buy_in] * n
        self._hand_num: int = 0
        # Dealer button rotates: hand 0 → BTN=n-1, hand 1 → BTN=0, etc.
        self._btn_offset: int = 0

        self._state = None          # current PokerKit State
        self._hero_hole: list[str] = []
        self._all_hole_cards_at_deal: dict[str, list[str]] = {}  # uuid → cards, captured right after deal
        self._board: list[str] = []
        self._action_histories: dict[str, list[dict]] = {}
        self._current_street_index: int = 0
        # Seat starting stacks captured at hand start for recording.
        self._starting_stacks: list[int] = []

        self.recorder = PerspectiveRecorder(hero_engine_uuid=self.hero_uuid)
        game_info = {
            "player_num": n,
            "seats": [
                {"name": spec.name, "uuid": self.seat_uuids[i], "stack": config.buy_in}
                for i, spec in enumerate(config.seats)
            ],
        }
        self.recorder._record_game_start(game_info)

        self.started_at = datetime.now().astimezone()
        self.finished = False
        self._pending_ask: dict | None = None
        self._last_view: dict | None = None
        self.preflop_quick: list[float] = [2.0, 2.5, 3.0, 4.0]
        self.postflop_quick: list[float] = [33.0, 50.0, 75.0, 100.0]

    # -- public config -------------------------------------------------------

    def table_config(self) -> dict:
        return {
            "small_blind": self.config.small_blind,
            "big_blind": self.config.big_blind,
            "buy_in": self.config.buy_in,
            "preflop_quick": self.preflop_quick,
            "postflop_quick": self.postflop_quick,
        }

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> list[dict]:
        """Begin the first hand and advance to the first hero decision."""
        return self._start_hand()

    def apply_hero_action(self, action: str, amount: int) -> list[dict]:
        if self.finished or self._state is None:
            return []
        self._pending_ask = None
        self._apply_action(action, amount)
        return self._advance()

    # -- hand lifecycle ------------------------------------------------------

    def _start_hand(self) -> list[dict]:
        """Create a new PokerKit State, deal cards, and advance to first ask."""
        n = len(self.config.seats)
        self._hand_num += 1
        self._action_histories = {s: [] for s in ("preflop", "flop", "turn", "river")}
        self._board = []
        self._current_street_index = 0

        # Active seats only (busted players sit out).
        active_seats = [i for i in range(n) if self._stacks[i] > 0]
        n_active = len(active_seats)

        # Rotate dealer button among active seats.
        btn_active_idx = (self._hand_num - 1) % n_active
        btn_pos = active_seats[btn_active_idx]
        sb_active_idx = (btn_active_idx + 1) % n_active
        bb_active_idx = (btn_active_idx + 2) % n_active
        sb_pos = active_seats[sb_active_idx]
        self._sb_pos = sb_pos
        self._bb_pos = active_seats[bb_active_idx]
        self._btn_pos = btn_pos

        # Rotate active seats so SB is PokerKit index 0.
        rotated_active = [active_seats[(sb_active_idx + i) % n_active] for i in range(n_active)]
        rotated_stacks = [self._stacks[seat_i] for seat_i in rotated_active]

        # Mapping: PokerKit index i -> seat index
        self._pk_to_seat: list[int] = rotated_active
        self._seat_to_pk: list[int] = [-1] * n
        for pk_i, seat_i in enumerate(self._pk_to_seat):
            self._seat_to_pk[seat_i] = pk_i

        # Hero's PokerKit index
        self._hero_pk_index = self._seat_to_pk[self.hero_index]

        self._starting_stacks = list(self._stacks)

        self._state = NoLimitTexasHoldem.create_state(
            automations=_AUTOMATIONS,
            ante_trimming_status=True,
            raw_antes=self.config.ante,
            raw_blinds_or_straddles=(self.config.small_blind, self.config.big_blind),
            min_bet=self.config.big_blind,
            raw_starting_stacks=rotated_stacks,
            player_count=n_active,
        )

        # Shuffle and deal hole cards
        deck = list(self._state.deck_cards)
        self._rng.shuffle(deck)
        card_idx = 0
        for _ in range(2):
            for i in range(n_active):
                self._state.deal_hole(deck[card_idx])
                card_idx += 1
        self._remaining_deck = deck[card_idx:]

        # Capture hero's hole cards in internal format (for evaluation/recording).
        # _hero_hole_fe is the frontend-format version sent to the browser.
        self._hero_hole = pk_adapter.cards_to_strs(
            self._state.hole_cards[self._hero_pk_index]
        )

        # Capture ALL players' hole cards now — PokerKit clears them when players fold/muck,
        # so by the time _finish_hand runs, folded players' cards would be gone.
        self._all_hole_cards_at_deal = {
            self.seat_uuids[self._pk_to_seat[pk_i]]: pk_adapter.cards_to_strs(self._state.hole_cards[pk_i])
            for pk_i in range(n_active)
            if self._state.hole_cards[pk_i]
        }

        # Record round start
        seats_for_recorder = [
            {"name": self.config.seats[seat_i].name,
             "uuid": self.seat_uuids[seat_i],
             "stack": self._stacks[seat_i]}
            for seat_i in range(n)
        ]
        self.recorder._record_round_start(self._hand_num, self._hero_hole, seats_for_recorder)

        self._last_view = self._build_view()
        out: list[dict] = [{"type": "new_street", "street": "preflop", "view": self._last_view}]
        out.extend(self._advance())
        return out

    def _advance(self) -> list[dict]:
        """Drive the game forward, emitting events until the hero must act or hand ends."""
        out: list[dict] = []
        state = self._state

        while True:
            if state is None or not state.status:
                # Hand is over.
                out.extend(self._finish_hand())
                return out

            actor = state.actor_index

            if actor is None:
                # No actor: burn + deal the next street, or hand is over.
                if state.can_burn_card() or state.can_deal_board():
                    out.extend(self._deal_next_street())
                    continue
                # Hand over (chips already pushed by automation).
                out.extend(self._finish_hand())
                return out

            # Translate PokerKit index to seat index
            seat_i = self._pk_to_seat[actor]
            uuid_ = self.seat_uuids[seat_i]

            if seat_i == self.hero_index:
                # Hero's turn: emit ask and stop.
                ask = self._build_ask()
                self._pending_ask = ask
                self._last_view = self._build_view()
                out.append({"type": "to_act", "uuid": uuid_, "view": self._last_view})
                out.append({"type": "ask", "valid_actions": ask["valid_actions"], "view": self._last_view})
                return out

            # Bot's turn
            self._last_view = self._build_view()
            out.append({"type": "to_act", "uuid": uuid_, "view": self._last_view})
            self._bot_act(seat_i, actor)

        return out  # unreachable

    def _deal_next_street(self) -> list[dict]:
        """Deal the next community street and emit a new_street event."""
        state = self._state
        next_street_index = self._current_street_index + 1
        n_cards = _BOARD_CARDS_PER_STREET.get(next_street_index, 0)
        if n_cards == 0:
            return []

        # Burn one card before the street, then deal n_cards community cards.
        if state.can_burn_card():
            state.burn_card(self._remaining_deck.pop(0))
        for i in range(n_cards):
            state.deal_board(self._remaining_deck.pop(0))

        self._current_street_index = next_street_index
        self._board = pk_adapter.cards_to_strs(
            c for group in state.board_cards for c in group
        )
        street = _STREET_NAMES.get(next_street_index, "river")
        self._last_view = self._build_view()
        return [{"type": "new_street", "street": street, "view": self._last_view}]

    def _bot_act(self, seat_i: int, pk_index: int) -> None:
        """Have the bot at ``seat_i`` decide and apply one action."""
        state = self._state
        bot = self._bot_players[seat_i]
        valid_actions = self._build_valid_actions(pk_index)
        round_state = self._build_round_state_dict()
        action_name, amount = bot.declare_action(valid_actions, self._bot_hole_strs(pk_index), round_state)
        self._apply_action(action_name, amount, actor_pk=pk_index)

    def _bot_hole_strs(self, pk_index: int) -> list[str]:
        return pk_adapter.cards_to_strs(self._state.hole_cards[pk_index])

    def _apply_action(self, action: str, amount: int, actor_pk: int | None = None) -> None:
        """Apply a fold/call/raise to the current PokerKit state and record it."""
        state = self._state
        if actor_pk is None:
            actor_pk = state.actor_index

        seat_i = self._pk_to_seat[actor_pk]
        uuid_ = self.seat_uuids[seat_i]
        street_name = _STREET_NAMES.get(self._current_street_index, "preflop")

        if action == "fold":
            state.fold()
            self._record_action(uuid_, street_name, "FOLD", 0)
        elif action in ("call", "check"):
            call_amount = state.checking_or_calling_amount
            state.check_or_call()
            self._record_action(uuid_, street_name, "CALL", call_amount)
        elif action in ("raise", "bet"):
            lo = state.min_completion_betting_or_raising_to_amount
            hi = state.max_completion_betting_or_raising_to_amount
            if lo is None or hi is None or not state.can_complete_bet_or_raise_to():
                # Raise not legal; fall back to call/check
                call_amount = state.checking_or_calling_amount
                state.check_or_call()
                self._record_action(uuid_, street_name, "CALL", call_amount)
            else:
                clamped = max(lo, min(int(amount), hi))
                state.complete_bet_or_raise_to(clamped)
                self._record_action(uuid_, street_name, "RAISE", clamped)
        else:
            call_amount = state.checking_or_calling_amount
            state.check_or_call()
            self._record_action(uuid_, street_name, "CALL", call_amount)

    def _record_action(self, uuid_: str, street: str, action: str, amount: int) -> None:
        self._action_histories.setdefault(street, []).append(
            {"uuid": uuid_, "action": action, "amount": amount}
        )

    def _finish_hand(self) -> list[dict]:
        """Emit round_finish event, update stacks, record, maybe start next hand."""
        state = self._state
        n = len(self.config.seats)

        # Build final community cards (may be incomplete if hand ended early)
        community = pk_adapter.cards_to_strs(c for group in state.board_cards for c in group)

        # Collect all hole cards (both revealed at showdown and unrevealed)
        n_active = len(self._pk_to_seat)
        hole_by_pk: dict[int, list[str]] = {}
        for pk_i in range(n_active):
            cards = state.hole_cards[pk_i]
            if cards:
                hole_by_pk[pk_i] = pk_adapter.cards_to_strs(cards)

        # Capture payoffs and starting stacks for pot reconstruction
        payoffs = list(state.payoffs or [0] * n_active)
        starting_stacks_pk = [self._starting_stacks[self._pk_to_seat[pk_i]] for pk_i in range(n_active)]

        # Update stacks from PokerKit
        for pk_i, new_stack in enumerate(state.stacks):
            self._stacks[self._pk_to_seat[pk_i]] = new_stack

        # Pot winners — use payoffs because chips_pushing has already fired
        seat_uuids_for_pk = [self.seat_uuids[self._pk_to_seat[pk_i]] for pk_i in range(n_active)]
        pot_winners = pk_adapter.pot_winners_from_payoffs(
            payoffs=payoffs,
            seat_uuids_for_pk=seat_uuids_for_pk,
            hole_cards_by_pk_index=hole_by_pk,
            community=community,
            starting_stacks_by_pk=starting_stacks_pk,
        )

        # Overall winners from payoffs
        winner_uuids = [
            self.seat_uuids[self._pk_to_seat[pk_i]]
            for pk_i, payoff in enumerate(payoffs)
            if payoff > 0
        ]
        if not winner_uuids and pot_winners:
            winner_uuids = [u for p in pot_winners for u in p["winners"]]

        # Showdown: players whose cards are known (not the hero — shown separately)
        showdown = []
        hero_hole = list(self._hero_hole)  # internal format for evaluation
        for pk_i, hole in hole_by_pk.items():
            seat_i = self._pk_to_seat[pk_i]
            best = pk_adapter.best_five(hole, community)
            showdown.append({
                "uuid": self.seat_uuids[seat_i],
                "hand_label": best["label"],
                "best_cards": best["cards"],
            })

        # Revealed: opponents' cards at showdown (exclude hero)
        revealed = {
            self.seat_uuids[self._pk_to_seat[pk_i]]: hole
            for pk_i, hole in hole_by_pk.items()
            if self._pk_to_seat[pk_i] != self.hero_index
        }

        # Record hand result
        winner_dicts = [{"uuid": u} for u in winner_uuids]
        # Use cards captured at deal time so folded/mucked players are included.
        hand_info = [
            {"uuid": uuid_, "hole_card": hole}
            for uuid_, hole in self._all_hole_cards_at_deal.items()
        ]
        round_state_dict = self._build_round_state_dict(
            community=community,
            final_stacks=self._stacks,
        )
        self.recorder._record_round_result(winner_dicts, hand_info, round_state_dict)

        # Build the view with hero hole cards preserved
        final_view = self._build_view(hero_hole_override=hero_hole, community_override=community)
        self._last_view = final_view

        out = [{
            "type": "round_finish",
            "winners": winner_uuids,
            "revealed": revealed,
            "pot_winners": pot_winners,
            "showdown": showdown,
            "view": final_view,
        }]

        self._state = None

        # Check if game is over
        players_with_chips = sum(1 for s in self._stacks if s > 0)
        hero_busted = self._stacks[self.hero_index] == 0
        if self._hand_num >= self.config.max_round or players_with_chips <= 1 or hero_busted:
            self.finished = True
            final_players = [
                {"name": self.config.seats[i].name, "stack": self._stacks[i]}
                for i in range(n)
            ]
            out.append({"type": "game_finish", "players": final_players})
        else:
            out.extend(self._start_hand())

        return out

    # -- view / serialization ------------------------------------------------

    def _build_view(self, hero_hole_override: list[str] | None = None, community_override: list[str] | None = None) -> dict:
        state = self._state
        n = len(self.config.seats)
        hero_hole = hero_hole_override if hero_hole_override is not None else self._hero_hole
        community = community_override if community_override is not None else self._board

        if state is not None:
            n_active = len(self._pk_to_seat)
            stacks = [state.stacks[self._seat_to_pk[i]] if self._seat_to_pk[i] >= 0 else self._stacks[i] for i in range(n)]
            bets = [state.bets[self._seat_to_pk[i]] if self._seat_to_pk[i] >= 0 else 0 for i in range(n)]
            statuses = [state.statuses[self._seat_to_pk[i]] if self._seat_to_pk[i] >= 0 else False for i in range(n)]
            pot = pk_adapter.pot_dict(state)
            pot_with_uuids = {
                "main": pot["main"],
                "side": [
                    {"amount": p["amount"], "eligibles": [self.seat_uuids[self._pk_to_seat[pk_i]] for pk_i in p["eligibles"]]}
                    for p in pot["side"]
                ]
            }
        else:
            stacks = list(self._stacks)
            bets = [0] * n
            statuses = [True] * n
            pot_with_uuids = {"main": {"amount": 0}, "side": []}

        seats = []
        for i, spec in enumerate(self.config.seats):
            uuid_ = self.seat_uuids[i]
            meta = self.seat_meta[uuid_]
            is_hero = i == self.hero_index
            pk_i = self._seat_to_pk[i] if hasattr(self, '_seat_to_pk') else -1
            is_busted = self._stacks[i] == 0 and (state is None or pk_i < 0)
            if is_busted:
                state_str = "folded"
            elif statuses[i]:
                state_str = "participating"
                if state is not None and pk_i >= 0 and state.stacks[pk_i] == 0:
                    state_str = "allin"
            else:
                state_str = "folded"
            show_style = bool(meta.get("is_bot")) and not meta.get("hidden")
            seats.append({
                "pos": i,
                "uuid": uuid_,
                "name": spec.name,
                "stack": stacks[i],
                "state": state_str,
                "is_hero": is_hero,
                "is_bot": bool(meta.get("is_bot")),
                "style": meta.get("style") if show_style else None,
                "bet": bets[i],
                "is_button": i == self._btn_pos,
                "is_sb": i == self._sb_pos,
                "is_bb": i == self._bb_pos,
                "hole_cards": hero_hole if is_hero else None,
            })

        actor_seat = None
        if state is not None and state.actor_index is not None:
            actor_seat = self._pk_to_seat[state.actor_index]

        return {
            "street": _STREET_NAMES.get(self._current_street_index, "preflop"),
            "community_card": list(community),
            "pot": pot_with_uuids,
            "dealer_btn": self._btn_pos,
            "next_player": actor_seat,
            "round_count": self._hand_num,
            "small_blind_amount": self.config.small_blind,
            "seats": seats,
        }

    def _build_valid_actions(self, pk_index: int) -> list[dict]:
        state = self._state
        actions = [
            {"action": "fold", "amount": 0},
            {"action": "call", "amount": state.checking_or_calling_amount},
        ]
        if state.can_complete_bet_or_raise_to():
            lo = state.min_completion_betting_or_raising_to_amount
            hi = state.max_completion_betting_or_raising_to_amount
            actions.append({"action": "raise", "amount": {"min": lo, "max": hi}})
        else:
            actions.append({"action": "raise", "amount": {"min": -1, "max": -1}})
        return actions

    def _build_ask(self) -> dict:
        return {
            "valid_actions": self._build_valid_actions(self._hero_pk_index),
            "round_state": self._build_round_state_dict(),
        }

    def _build_round_state_dict(
        self,
        community: list[str] | None = None,
        final_stacks: list[int] | None = None,
    ) -> dict:
        """Build a round_state dict compatible with the recorder's expected format."""
        n = len(self.config.seats)
        community = community or self._board
        stacks = final_stacks or (
            [self._state.stacks[self._seat_to_pk[i]] if self._seat_to_pk[i] >= 0 else self._stacks[i] for i in range(n)]
            if self._state else list(self._stacks)
        )
        statuses = (
            [self._state.statuses[self._seat_to_pk[i]] if self._seat_to_pk[i] >= 0 else False for i in range(n)]
            if self._state else [True] * n
        )

        pot = {"main": {"amount": 0}, "side": []}
        if self._state:
            pot_raw = pk_adapter.pot_dict(self._state)
            pot = {
                "main": pot_raw["main"],
                "side": [
                    {"amount": p["amount"],
                     "eligibles": [self.seat_uuids[self._pk_to_seat[pk_i]] for pk_i in p["eligibles"]]}
                    for p in pot_raw["side"]
                ],
            }

        seats = [
            {
                "uuid": self.seat_uuids[i],
                "name": self.config.seats[i].name,
                "stack": stacks[i],
                "state": "participating" if statuses[i] else "folded",
            }
            for i in range(n)
        ]

        return {
            "street": _STREET_NAMES.get(self._current_street_index, "preflop"),
            "community_card": list(community),
            "pot": pot,
            "dealer_btn": self._btn_pos,
            "small_blind_pos": self._sb_pos,
            "big_blind_pos": self._bb_pos,
            "next_player": (
                self._pk_to_seat[self._state.actor_index]
                if self._state and self._state.actor_index is not None else None
            ),
            "round_count": self._hand_num,
            "small_blind_amount": self.config.small_blind,
            "seats": seats,
            "action_histories": self._action_histories,
        }

    # -- public state accessors ----------------------------------------------

    def current_view(self) -> dict:
        if self._last_view is None:
            n = len(self.config.seats)
            return {"seats": [], "community_card": [], "pot": {"main": {"amount": 0}, "side": []}}
        return self._last_view

    def pending_ask(self) -> dict | None:
        if self._pending_ask is None or self.finished:
            return None
        return {
            "type": "ask",
            "valid_actions": self._pending_ask["valid_actions"],
            "view": self._last_view,
        }

    def _validate_action(self, action: str, amount: int) -> tuple[str, int]:
        state = self._state
        if action == "fold":
            return "fold", 0
        if action in ("call", "check"):
            return "call", state.checking_or_calling_amount
        if action in ("raise", "bet"):
            if not state.can_complete_bet_or_raise_to():
                return "call", state.checking_or_calling_amount
            lo = state.min_completion_betting_or_raising_to_amount
            hi = state.max_completion_betting_or_raising_to_amount
            return "raise", max(lo, min(int(amount), hi))
        return "call", state.checking_or_calling_amount

    def apply_hero_action(self, action: str, amount: int) -> list[dict]:
        if self.finished or self._state is None:
            return []
        self._pending_ask = None
        action, amount = self._validate_action(action, amount)
        self._apply_action(action, amount, actor_pk=self._hero_pk_index)
        return self._advance()

    # -- persistence ---------------------------------------------------------

    def _flush(self, session, ended_at: datetime | None) -> object:
        return self.recorder.flush_incremental(
            session,
            self.config,
            hero_engine_uuid=self.hero_uuid,
            bot_params_by_uuid=self._bot_params_by_uuid,
            started_at=self.started_at,
            ended_at=ended_at,
        )

    def persist_start(self, session) -> object:
        return self._flush(session, ended_at=None)

    def persist_incremental(self, session) -> object:
        ended_at = datetime.now().astimezone() if self.finished else None
        return self._flush(session, ended_at=ended_at)

    def persist(self, session) -> object | None:
        ended_at = datetime.now().astimezone()
        return self._flush(session, ended_at=ended_at)
