"""GameSession: one interactive game driven by the PyPokerEngine Emulator.

The emulator lets us step the game one action at a time. The web client drives
the hero seat (via ``apply_hero_action``); bots act automatically inside the
``advance`` loop until it is the hero's turn again, a round finishes, or the game
finishes. Completed games are persisted with the existing PerspectiveRecorder.
"""

from __future__ import annotations

import uuid as uuidlib
from datetime import datetime

from pypokerengine.api.emulator import Emulator, Event
from pypokerengine.engine.poker_constants import PokerConstants as Const

from poker_engine.bots.styles import STYLE_REGISTRY
from poker_engine.config import GameConfig, SeatKind
from poker_engine.recorder import PerspectiveRecorder
from poker_trainer.game import serialize
from poker_trainer.game.human import HumanPlaceholder


class GameSession:
    def __init__(self, config: GameConfig, hero_index: int = 0, seed: int | None = None):
        config.validate()
        self.config = config
        self.game_id = str(uuidlib.uuid4())
        self.hero_index = hero_index
        self.seed = seed

        self.emulator = Emulator()
        self.emulator.set_game_rule(
            player_num=len(config.seats),
            max_round=config.max_round,
            small_blind_amount=config.small_blind,
            ante_amount=config.ante,
        )

        # Build players, assign uuids, register with the emulator. Keep maps for
        # serialization (style/hidden), bot decisions, and recording.
        self.seat_uuids: list[str] = []
        self.seat_meta: dict[str, dict] = {}
        self._bot_players: dict[str, object] = {}
        self._bot_params_by_uuid: dict[str, dict] = {}
        self._hero_player = HumanPlaceholder()

        players_info: dict[str, dict] = {}
        for index, spec in enumerate(config.seats):
            seat_uuid = f"seat-{index}-{uuidlib.uuid4().hex[:8]}"
            self.seat_uuids.append(seat_uuid)
            is_hero = index == hero_index
            if is_hero:
                player = self._hero_player
                self.hero_uuid = seat_uuid
            else:
                bot_cls = STYLE_REGISTRY[spec.kind.value]
                bot_seed = None if seed is None else seed + index
                player = bot_cls(seed=bot_seed, **(spec.params or {}))
                self._bot_players[seat_uuid] = player
                self._bot_params_by_uuid[seat_uuid] = player.params.as_dict()
            self.emulator.register_player(seat_uuid, player)
            players_info[seat_uuid] = {"name": spec.name, "stack": config.buy_in}
            self.seat_meta[seat_uuid] = {
                "is_bot": spec.is_bot,
                "style": spec.kind.value if spec.is_bot else None,
                "hidden": spec.hidden if spec.is_bot else False,
            }

        # The Emulator does not deliver notifications to registered players, so
        # we drive the recorder directly from events (see _record_* calls below)
        # rather than wrapping the hero player's callbacks.
        self.recorder = PerspectiveRecorder(hero_engine_uuid=self.hero_uuid)
        self._game_info = {
            "player_num": len(config.seats),
            "seats": [
                {"name": spec.name, "uuid": self.seat_uuids[i], "stack": config.buy_in}
                for i, spec in enumerate(config.seats)
            ],
        }
        self.recorder._record_game_start(self._game_info)

        self.game_state = self.emulator.generate_initial_game_state(players_info)
        self.started_at = datetime.now().astimezone()
        self.finished = False
        self._pending_ask: dict | None = None
        self._last_round_state: dict | None = None
        # Quick-bet presets (set by the API; sensible defaults otherwise).
        # Preflop values are big-blind multiples; postflop are pot percentages.
        self.preflop_quick: list[float] = [2.0, 2.5, 3.0, 4.0]
        self.postflop_quick: list[float] = [33.0, 50.0, 75.0, 100.0]

    def table_config(self) -> dict:
        """Static config the client needs to render controls (blinds, presets)."""
        return {
            "small_blind": self.config.small_blind,
            "big_blind": self.config.big_blind,
            "buy_in": self.config.buy_in,
            "preflop_quick": self.preflop_quick,
            "postflop_quick": self.postflop_quick,
        }

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> list[dict]:
        """Begin the first round and advance to the first hero decision."""
        self.game_state, events = self.emulator.start_new_round(self.game_state)
        self._record_round_start()
        return self._process(events)

    def _record_round_start(self) -> None:
        """Feed the recorder a round-start observation built from live state."""
        hero_hole = serialize.hero_hole_cards(self.game_state, self.hero_uuid)
        seats = [
            {"name": p.name, "uuid": p.uuid, "stack": p.stack, "state": "participating"}
            for p in self.game_state["table"].seats.players
        ]
        self.recorder._record_round_start(
            self.game_state["round_count"], hero_hole, seats
        )

    def apply_hero_action(self, action: str, amount: int) -> list[dict]:
        """Apply the hero's action, then advance through bot turns."""
        if self.finished:
            return []
        action, amount = self._validate_action(action, amount)
        self.game_state, events = self.emulator.apply_action(self.game_state, action, amount)
        return self._process(events)

    # -- core loop ----------------------------------------------------------

    def _process(self, events: list[dict]) -> list[dict]:
        """Translate engine events to browser events, driving bots as needed.

        Returns an ordered list of browser-facing event dicts. Continues looping
        while the next actor is a bot; stops at the hero's ask, or terminal state.
        """
        out: list[dict] = []
        while True:
            for event in events:
                out.extend(self._translate(event))

            if self.finished:
                break

            ask = self._find_ask(events)
            if ask is None:
                # No ask in this batch: either a round just finished (start next)
                # or nothing left. Detect round finish to roll to the next hand.
                if any(e["type"] == Event.ROUND_FINISH for e in events) and not self.finished:
                    self.game_state, events = self.emulator.start_new_round(self.game_state)
                    if not any(e["type"] == Event.GAME_FINISH for e in events):
                        self._record_round_start()
                    continue
                break

            if ask["uuid"] == self.hero_uuid:
                self._pending_ask = ask
                out.append(self._hero_ask_event(ask))
                break

            # Bot's turn: decide and apply one action, then loop.
            events = self._bot_act(ask)

        return out

    def _bot_act(self, ask: dict) -> list[dict]:
        bot = self._bot_players[ask["uuid"]]
        round_state = ask["round_state"]
        hole = serialize.hero_hole_cards(self.game_state, ask["uuid"])
        action, amount = bot.declare_action(ask["valid_actions"], hole, round_state)
        self.game_state, events = self.emulator.apply_action(self.game_state, action, amount)
        return events

    # -- event translation --------------------------------------------------

    def _translate(self, event: dict) -> list[dict]:
        etype = event["type"]
        if etype == Event.NEW_STREET:
            self._last_round_state = event["round_state"]
            return [{
                "type": "new_street",
                "street": event["street"],
                "view": self._view(event["round_state"]),
            }]
        if etype == Event.ASK_PLAYER:
            self._last_round_state = event["round_state"]
            actor = event["uuid"]
            if actor != self.hero_uuid:
                # Surface that a bot is about to act so the UI can highlight it.
                return [{"type": "to_act", "uuid": actor, "view": self._view(event["round_state"])}]
            return []  # hero ask is emitted separately by _process
        if etype == Event.ROUND_FINISH:
            self._last_round_state = event["round_state"]
            # Record the finished hand from the (patched) event payload, then read
            # back the showdown reveals (exact cards for showdown participants
            # only — folded/unrevealed seats are never included).
            self.recorder._record_round_result(
                event.get("winners", []),
                event.get("hand_info", []),
                event["round_state"],
            )
            revealed = self.recorder.last_showdown_reveals(exclude_uuid=self.hero_uuid)
            return [{
                "type": "round_finish",
                "winners": event["winners"],
                "revealed": revealed,
                "view": self._view(event["round_state"]),
            }]
        if etype == Event.GAME_FINISH:
            self.finished = True
            return [{"type": "game_finish", "players": event["players"]}]
        return []

    def _hero_ask_event(self, ask: dict) -> dict:
        return {
            "type": "ask",
            "valid_actions": ask["valid_actions"],
            "view": self._view(ask["round_state"]),
        }

    def _view(self, round_state: dict) -> dict:
        hero_hole = serialize.hero_hole_cards(self.game_state, self.hero_uuid)
        return serialize.public_view(round_state, self.hero_uuid, self.seat_meta, hero_hole)

    def current_view(self) -> dict:
        rs = self._last_round_state
        if rs is None:
            return {"seats": [], "community_card": [], "pot": {"main": {"amount": 0}, "side": []}}
        return self._view(rs)

    def pending_ask(self) -> dict | None:
        if self._pending_ask is None or self.finished:
            return None
        return self._hero_ask_event(self._pending_ask)

    # -- validation ---------------------------------------------------------

    def _validate_action(self, action: str, amount: int) -> tuple[str, int]:
        valid = self.emulator.generate_possible_actions(self.game_state)
        by_name = {a["action"]: a for a in valid}
        if action == "fold":
            return "fold", 0
        if action in ("call", "check"):
            return "call", by_name["call"]["amount"]
        if action in ("raise", "bet"):
            bounds = by_name["raise"]["amount"]
            lo, hi = bounds["min"], bounds["max"]
            if lo == -1 or hi == -1:
                # Raising illegal — fall back to call/check.
                return "call", by_name["call"]["amount"]
            return "raise", max(lo, min(int(amount), hi))
        # Unknown action: safest is to call/check.
        return "call", by_name["call"]["amount"]

    def _find_ask(self, events: list[dict]) -> dict | None:
        for event in events:
            if event["type"] == Event.ASK_PLAYER:
                return event
        return None

    # -- persistence --------------------------------------------------------

    def persist(self, session) -> object | None:
        """Persist the finished game via the PerspectiveRecorder."""
        ended_at = datetime.now().astimezone()
        game = self.recorder.flush(
            session,
            self.config,
            hero_engine_uuid=self.hero_uuid,
            bot_params_by_uuid=self._bot_params_by_uuid,
            started_at=self.started_at,
            ended_at=ended_at,
        )
        return game
