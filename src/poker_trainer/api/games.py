"""REST endpoints for game setup and (stubbed) review."""

from __future__ import annotations

import random

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from poker_engine.config import GameConfig, SeatKind, SeatSpec
from poker_trainer.game.manager import manager
from poker_trainer.game.session import GameSession

router = APIRouter(prefix="/api", tags=["games"])

BOT_STYLES = [SeatKind.TAG, SeatKind.LAG, SeatKind.STATION, SeatKind.ROCK]

# Bot names are "Adjective Noun" pairs drawn from these 30×30 = 900 combos,
# sampled uniquely per game.
_BOT_ADJECTIVES = [
    "Beautiful", "Crazy", "Clever", "Attacking", "Lucky", "Silent", "Savage",
    "Calm", "Bold", "Sneaky", "Ruthless", "Wild", "Cool", "Fierce", "Sly",
    "Brave", "Mighty", "Slick", "Cunning", "Reckless", "Steady", "Grumpy",
    "Happy", "Shadow", "Iron", "Golden", "Furious", "Mellow", "Daring", "Loose",
]
_BOT_NOUNS = [
    "King", "Fish", "Rock", "Ace", "Beat", "Hand", "Shark", "Bluff", "River",
    "Flush", "Dealer", "Joker", "Chip", "Whale", "Nit", "Donk", "Cooler",
    "Boat", "Tilt", "Maniac", "Grinder", "Gambler", "Caller", "Raiser", "Bandit",
    "Snap", "Bullet", "Stack", "Outlaw", "Hustler",
]


def _random_bot_names(count: int, rng: random.Random) -> list[str]:
    """Sample `count` unique 'Adjective Noun' names (up to 900 combinations)."""
    combos = [f"{a} {n}" for a in _BOT_ADJECTIVES for n in _BOT_NOUNS]
    return rng.sample(combos, min(count, len(combos)))

# Default quick-bet presets. Preflop sizing is in big blinds; postflop in % pot.
DEFAULT_PREFLOP_QUICK = [2.0, 2.5, 3.0, 4.0]   # × BB
DEFAULT_POSTFLOP_QUICK = [33.0, 50.0, 75.0, 100.0]  # % pot


class CreateGameRequest(BaseModel):
    num_bots: int = Field(default=8, ge=1, le=8)
    small_blind: int = Field(default=50, ge=1)
    big_blind: int = Field(default=100, ge=2)
    buy_in: int = Field(default=10000, ge=1)
    max_round: int = Field(default=50, ge=1, le=500)
    randomize_styles: bool = True
    hide_styles: bool = True
    # Optional explicit per-bot styles (used when randomize_styles is False).
    styles: list[str] | None = None
    hero_name: str = "you"
    hero_email: str | None = None
    seed: int | None = None
    # Quick-bet presets (besides All-in), up to 5 each. Preflop values are
    # big-blind multiples; postflop values are pot percentages.
    preflop_quick: list[float] | None = None
    postflop_quick: list[float] | None = None


class CreateGameResponse(BaseModel):
    game_id: str
    ws_url: str
    num_seats: int


class GameSummary(BaseModel):
    game_id: str
    created_at: str | None = None


def _build_seats(req: CreateGameRequest) -> list[SeatSpec]:
    seats: list[SeatSpec] = [
        SeatSpec(name=req.hero_name, kind=SeatKind.HUMAN, email=req.hero_email)
    ]
    rng = random.Random(req.seed)
    names = _random_bot_names(req.num_bots, rng)
    for i in range(req.num_bots):
        if req.randomize_styles or not req.styles:
            kind = rng.choice(BOT_STYLES)
        else:
            try:
                kind = SeatKind(req.styles[i % len(req.styles)])
            except ValueError:
                raise HTTPException(400, f"Unknown bot style: {req.styles[i]!r}")
            if kind == SeatKind.HUMAN:
                raise HTTPException(400, "Bot style cannot be 'human'.")
        seats.append(
            SeatSpec(name=names[i], kind=kind, hidden=req.hide_styles)
        )
    return seats


@router.post("/games", response_model=CreateGameResponse)
def create_game(req: CreateGameRequest) -> CreateGameResponse:
    if req.big_blind != req.small_blind * 2:
        # The engine derives BB as 2*SB; keep the contract explicit.
        raise HTTPException(400, "big_blind must equal 2 × small_blind.")
    seats = _build_seats(req)
    config = GameConfig(
        small_blind=req.small_blind,
        buy_in=req.buy_in,
        seats=seats,
        max_round=req.max_round,
    )
    try:
        config.validate()
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    preflop = req.preflop_quick if req.preflop_quick is not None else DEFAULT_PREFLOP_QUICK
    postflop = req.postflop_quick if req.postflop_quick is not None else DEFAULT_POSTFLOP_QUICK
    if len(preflop) > 5 or len(postflop) > 5:
        raise HTTPException(400, "At most 5 quick-bet presets per street are allowed.")
    preflop = [v for v in preflop if v > 0]
    postflop = [v for v in postflop if v > 0]

    session = GameSession(config, hero_index=0, seed=req.seed)
    session.preflop_quick = preflop
    session.postflop_quick = postflop
    manager.add(session)
    return CreateGameResponse(
        game_id=session.game_id,
        ws_url=f"/ws/games/{session.game_id}",
        num_seats=len(seats),
    )


@router.get("/games", response_model=list[GameSummary])
def list_games() -> list[GameSummary]:
    # Review-games is a later phase; return an empty list for now so the main
    # page can render its "no games yet" state.
    return []


@router.get("/games/{game_id}/state")
def game_state(game_id: str) -> dict:
    session = manager.get(game_id)
    if session is None:
        raise HTTPException(404, "Game not found or already finished.")
    return {
        "game_id": game_id,
        "view": session.current_view(),
        "pending_ask": session.pending_ask(),
        "finished": session.finished,
    }
