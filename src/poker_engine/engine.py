"""GameEngine: builds the table from a GameConfig, runs it, records it.

This is the management layer on top of PyPokerEngine. It translates a
``GameConfig`` into engine players, runs the hand loop via ``start_poker``,
and persists the game from the hero's perspective through ``PerspectiveRecorder``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pypokerengine.api.game import setup_config, start_poker

from poker_engine.bots.styles import STYLE_REGISTRY
from poker_engine.config import GameConfig, SeatSpec
from poker_engine.players.console import ConsolePlayer
from poker_engine.recorder import PerspectiveRecorder


@dataclass
class GameResult:
    """Outcome of a run: final stacks plus the persisted game id (if recorded)."""

    players: list[dict]  # [{name, stack, state}, ...] from start_poker
    game_id: object | None = None


class GameEngine:
    def __init__(
        self,
        config: GameConfig,
        seed: int | None = None,
        hero_index: int | None = None,
    ):
        """Build the table from ``config``.

        ``hero_index`` chooses the recording-perspective seat. By default it is
        the human seat. When all seats are bots (e.g. automated runs), pass an
        explicit index so a game can still be recorded from one seat's view.
        """
        config.validate()
        self.config = config
        self.seed = seed
        # Build engine players, remembering the hero's player object so we can
        # read the uuid the engine assigns it.
        self._players: list[tuple[SeatSpec, object]] = []
        self._hero_player = None
        for offset, spec in enumerate(config.seats):
            player = self._build_player(spec, offset)
            self._players.append((spec, player))
            if hero_index is None and not spec.is_bot:
                self._hero_player = player
        if hero_index is not None:
            self._hero_player = self._players[hero_index][1]
        self._hero_index = hero_index

    def _build_player(self, spec: SeatSpec, offset: int):
        if not spec.is_bot:
            return ConsolePlayer()
        bot_cls = STYLE_REGISTRY[spec.kind.value]
        seed = None if self.seed is None else self.seed + offset
        return bot_cls(seed=seed, **(spec.params or {}))

    def run(self, record: bool = True, session_factory=None) -> GameResult:
        cfg = setup_config(
            max_round=self.config.max_round,
            initial_stack=self.config.buy_in,
            small_blind_amount=self.config.small_blind,
            ante=self.config.ante,
        )

        recorder: PerspectiveRecorder | None = None
        if record and self._hero_player is not None:
            recorder = PerspectiveRecorder()
            recorder.attach(self._hero_player)

        for spec, player in self._players:
            cfg.register_player(name=spec.name, algorithm=player)

        started_at = datetime.now().astimezone()
        result = start_poker(cfg, verbose=1)
        ended_at = datetime.now().astimezone()

        game_id = None
        if recorder is not None:
            hero_uuid = getattr(self._hero_player, "uuid", None)
            if session_factory is None:
                from poker_engine.db.base import SessionLocal

                session_factory = SessionLocal
            bot_params = {
                player.uuid: player.params.as_dict()
                for spec, player in self._players
                if spec.is_bot and getattr(player, "uuid", None) is not None
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
                game_id = game.id

        return GameResult(players=result["players"], game_id=game_id)
