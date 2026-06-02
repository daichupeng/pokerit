"""In-memory registry of active GameSessions.

Live game state (the Emulator's Table object) is kept in this process and only
persisted to Postgres when a game finishes. This is sufficient for single-process
development; a multi-worker deployment would move this to Redis or serialize the
game state to the DB after each action.
"""

from __future__ import annotations

import asyncio

from poker_trainer.game.session import GameSession


class SessionManager:
    def __init__(self):
        self._sessions: dict[str, GameSession] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def add(self, session: GameSession) -> None:
        self._sessions[session.game_id] = session
        self._locks[session.game_id] = asyncio.Lock()

    def get(self, game_id: str) -> GameSession | None:
        return self._sessions.get(game_id)

    def lock(self, game_id: str) -> asyncio.Lock:
        return self._locks.setdefault(game_id, asyncio.Lock())

    def remove(self, game_id: str) -> None:
        self._sessions.pop(game_id, None)
        self._locks.pop(game_id, None)


# Process-wide manager instance.
manager = SessionManager()
