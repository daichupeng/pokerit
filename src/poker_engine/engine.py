"""GameEngine: builds the table from a GameConfig and runs it.

Non-interactive (bot-only or console) runner used by scripts.
For the interactive web app use GameSession instead.
"""

from __future__ import annotations

import random
import warnings
from dataclasses import dataclass
from datetime import datetime

from pokerkit import Automation, NoLimitTexasHoldem

from poker_engine import pk_adapter
from poker_engine.bots.styles import STYLE_REGISTRY
from poker_engine.config import GameConfig, SeatSpec
from poker_engine.players.console import ConsolePlayer
from poker_engine.recorder import PerspectiveRecorder

_AUTOMATIONS = (
    Automation.ANTE_POSTING,
    Automation.BET_COLLECTION,
    Automation.BLIND_OR_STRADDLE_POSTING,
    Automation.HOLE_CARDS_SHOWING_OR_MUCKING,
    Automation.HAND_KILLING,
    Automation.CHIPS_PUSHING,
    Automation.CHIPS_PULLING,
    # CARD_BURNING is NOT automated: we burn manually so indices stay aligned.
)

_STREET_NAMES = {0: "preflop", 1: "flop", 2: "turn", 3: "river"}
_BOARD_CARDS_PER_STREET = {1: 3, 2: 1, 3: 1}


@dataclass
class GameResult:
    """Outcome of a run: final player stacks plus the persisted game id."""

    players: list[dict]  # [{"name": str, "stack": int}, ...]
    game_id: object | None = None


class GameEngine:
    def __init__(
        self,
        config: GameConfig,
        seed: int | None = None,
        hero_index: int | None = None,
    ):
        config.validate()
        self.config = config
        self.seed = seed
        self._rng = random.Random(seed)
        self._hero_index = hero_index

        n = len(config.seats)
        self._players: list[tuple[SeatSpec, object]] = []
        self._hero_player_index: int | None = None

        for i, spec in enumerate(config.seats):
            if spec.is_bot:
                bot_cls = STYLE_REGISTRY[spec.kind.value]
                bot_seed = None if seed is None else seed + i
                player = bot_cls(seed=bot_seed, **(spec.params or {}))
                player.set_n_players(n)
            else:
                player = ConsolePlayer()
            self._players.append((spec, player))

            if hero_index is None and not spec.is_bot:
                self._hero_player_index = i
        if hero_index is not None:
            self._hero_player_index = hero_index

    def run(self, record: bool = True, session_factory=None) -> GameResult:
        from poker_engine.recorder import PerspectiveRecorder

        config = self.config
        n = len(config.seats)
        stacks = [config.buy_in] * n
        recorder = PerspectiveRecorder() if record and self._hero_player_index is not None else None

        hero_uuid = None
        if self._hero_player_index is not None:
            hero_uuid = f"seat-{self._hero_player_index}-engine"

        if recorder:
            from datetime import datetime as dt
            game_info = {
                "player_num": n,
                "seats": [
                    {"name": spec.name, "uuid": f"seat-{i}-engine", "stack": config.buy_in}
                    for i, (spec, _) in enumerate(self._players)
                ],
            }
            recorder._record_game_start(game_info)

        started_at = datetime.now().astimezone()

        for hand_num in range(1, config.max_round + 1):
            sb_pos = (hand_num - 1) % n
            bb_pos = (hand_num) % n

            rotated = [stacks[(sb_pos + i) % n] for i in range(n)]
            pk_to_seat = [(sb_pos + i) % n for i in range(n)]
            seat_to_pk = [0] * n
            for pk_i, seat_i in enumerate(pk_to_seat):
                seat_to_pk[seat_i] = pk_i

            state = NoLimitTexasHoldem.create_state(
                automations=_AUTOMATIONS,
                ante_trimming_status=True,
                raw_antes=config.ante,
                raw_blinds_or_straddles=(config.small_blind, config.big_blind),
                min_bet=config.big_blind,
                raw_starting_stacks=rotated,
                player_count=n,
            )

            deck = list(state.deck_cards)
            self._rng.shuffle(deck)
            card_idx = 0
            for _ in range(2):
                for i in range(n):
                    state.deal_hole(deck[card_idx])
                    card_idx += 1
            remaining = deck[card_idx:]
            rem_idx = 0

            if recorder:
                hero_hole = pk_adapter.cards_to_strs(state.hole_cards[seat_to_pk[self._hero_player_index]])
                seats_rec = [
                    {"name": spec.name, "uuid": f"seat-{i}-engine", "stack": stacks[i]}
                    for i, (spec, _) in enumerate(self._players)
                ]
                recorder._record_round_start(hand_num, hero_hole, seats_rec)

            action_histories: dict[str, list] = {s: [] for s in ("preflop", "flop", "turn", "river")}
            current_street = 0

            while state.status:
                actor = state.actor_index
                if actor is None:
                    if state.can_burn_card():
                        state.burn_card(remaining[rem_idx]); rem_idx += 1
                    elif state.can_deal_board():
                        next_street = current_street + 1
                        n_cards = _BOARD_CARDS_PER_STREET.get(next_street, 0)
                        for _ in range(n_cards):
                            state.deal_board(remaining[rem_idx]); rem_idx += 1
                        current_street = next_street
                    continue

                seat_i = pk_to_seat[actor]
                spec, player = self._players[seat_i]
                uuid_ = f"seat-{seat_i}-engine"

                community = pk_adapter.cards_to_strs(c for g in state.board_cards for c in g)
                hole_strs = pk_adapter.cards_to_strs(state.hole_cards[actor])
                round_state_dict = {
                    "street": _STREET_NAMES.get(current_street, "preflop"),
                    "community_card": community,
                    "pot": {"main": {"amount": state.total_pot_amount}, "side": []},
                }

                if spec.is_bot:
                    valid_actions = [
                        {"action": "fold", "amount": 0},
                        {"action": "call", "amount": state.checking_or_calling_amount},
                        {"action": "raise", "amount": {
                            "min": state.min_completion_betting_or_raising_to_amount if state.can_complete_bet_or_raise_to() else -1,
                            "max": state.max_completion_betting_or_raising_to_amount if state.can_complete_bet_or_raise_to() else -1,
                        }},
                    ]
                    action_name, amount = player.declare_action(valid_actions, hole_strs, round_state_dict)
                else:
                    # Console player — pass PyPE-style dicts
                    valid_actions = [
                        {"action": "fold", "amount": 0},
                        {"action": "call", "amount": state.checking_or_calling_amount},
                        {"action": "raise", "amount": {
                            "min": state.min_completion_betting_or_raising_to_amount if state.can_complete_bet_or_raise_to() else -1,
                            "max": state.max_completion_betting_or_raising_to_amount if state.can_complete_bet_or_raise_to() else -1,
                        }},
                    ]
                    action_name, amount = player.declare_action(valid_actions, hole_strs, round_state_dict)

                street_key = _STREET_NAMES.get(current_street, "preflop")
                if action_name == "fold":
                    state.fold()
                    action_histories[street_key].append({"uuid": uuid_, "action": "FOLD", "amount": 0})
                elif action_name in ("call", "check"):
                    call_amt = state.checking_or_calling_amount
                    state.check_or_call()
                    action_histories[street_key].append({"uuid": uuid_, "action": "CALL", "amount": call_amt})
                else:
                    if state.can_complete_bet_or_raise_to():
                        lo = state.min_completion_betting_or_raising_to_amount
                        hi = state.max_completion_betting_or_raising_to_amount
                        clamped = max(lo, min(int(amount), hi))
                        state.complete_bet_or_raise_to(clamped)
                        action_histories[street_key].append({"uuid": uuid_, "action": "RAISE", "amount": clamped})
                    else:
                        call_amt = state.checking_or_calling_amount
                        state.check_or_call()
                        action_histories[street_key].append({"uuid": uuid_, "action": "CALL", "amount": call_amt})

            # Hand finished: update stacks
            for pk_i, new_stack in enumerate(state.stacks):
                stacks[pk_to_seat[pk_i]] = new_stack

            if recorder:
                community = pk_adapter.cards_to_strs(c for g in state.board_cards for c in g)
                hole_by_pk = {
                    pk_i: pk_adapter.cards_to_strs(cards)
                    for pk_i, cards in enumerate(state.hole_cards) if cards
                }
                winner_uuids = [
                    f"seat-{pk_to_seat[pk_i]}-engine"
                    for pk_i, p in enumerate(state.payoffs or []) if p > 0
                ]
                hand_info = [
                    {"uuid": f"seat-{pk_to_seat[pk_i]}-engine", "hole_card": hole}
                    for pk_i, hole in hole_by_pk.items()
                ]
                rs = {
                    "street": _STREET_NAMES.get(current_street, "preflop"),
                    "community_card": community,
                    "pot": {"main": {"amount": 0}, "side": []},
                    "dealer_btn": (sb_pos - 1) % n,
                    "small_blind_pos": sb_pos,
                    "big_blind_pos": bb_pos,
                    "seats": [
                        {"uuid": f"seat-{i}-engine", "name": spec.name, "stack": stacks[i], "state": "participating"}
                        for i, (spec, _) in enumerate(self._players)
                    ],
                    "action_histories": action_histories,
                    "round_count": hand_num,
                    "small_blind_amount": config.small_blind,
                }
                recorder._record_round_result(
                    [{"uuid": u} for u in winner_uuids], hand_info, rs
                )

            players_with_chips = sum(1 for s in stacks if s > 0)
            if players_with_chips <= 1:
                break

        ended_at = datetime.now().astimezone()
        final_players = [
            {"name": spec.name, "stack": stacks[i]}
            for i, (spec, _) in enumerate(self._players)
        ]

        game_id = None
        if recorder and hero_uuid:
            if session_factory is None:
                from poker_engine.db.base import SessionLocal
                session_factory = SessionLocal
            bot_params = {
                f"seat-{i}-engine": player.params.as_dict()
                for i, (spec, player) in enumerate(self._players)
                if spec.is_bot and hasattr(player, "params")
            }
            with session_factory() as session:
                game = recorder.flush(
                    session,
                    self.config,
                    hero_engine_uuid=hero_uuid,
                    bot_params_by_uuid=bot_params,
                    started_at=started_at,
                    ended_at=ended_at,
                )
                game_id = game.id if game else None

        return GameResult(players=final_players, game_id=game_id)
