"""REST endpoints for game setup and (stubbed) review."""

from __future__ import annotations

import random

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from poker_engine import pk_adapter
from poker_engine.config import GameConfig, SeatKind, SeatSpec
from poker_engine.db.models import Game, GamePlayer, Hand, User
from poker_trainer.auth.deps import get_db, require_user
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
    # The hero is the logged-in user; identity is taken from the session, not
    # from the client. (hero_name/hero_email request fields removed.)
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
    started_at: str | None = None
    small_blind: int
    big_blind: int
    num_hands: int
    hero_net: int  # the hero seat's net chips across the game


def _build_seats(req: CreateGameRequest, hero: User) -> list[SeatSpec]:
    # The hero seat is the logged-in user; the recorder links the game to this
    # account by email.
    hero_name = hero.username or hero.display_name or "you"
    seats: list[SeatSpec] = [
        SeatSpec(name=hero_name, kind=SeatKind.HUMAN, email=hero.email)
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
def create_game(req: CreateGameRequest, hero: User = Depends(require_user)) -> CreateGameResponse:
    if req.big_blind != req.small_blind * 2:
        # The engine derives BB as 2*SB; keep the contract explicit.
        raise HTTPException(400, "big_blind must equal 2 × small_blind.")
    seats = _build_seats(req, hero)
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


# Engine streets in display order; SHOWDOWN actions (if any) are folded into the
# last betting street for display purposes.
_STREET_ORDER = ["preflop", "flop", "turn", "river"]


def _hero_seat(game: Game) -> GamePlayer | None:
    """The hero's seat in a game — the one non-bot seat linked to a user."""
    for gp in game.players:
        if not gp.is_bot and gp.user_id is not None:
            return gp
    return None


def _load_owned_game(db: Session, game_id: str, user: User) -> Game:
    """Fetch a game with hands/players eager-loaded, 404 unless owned by user."""
    try:
        game = db.execute(
            select(Game)
            .where(Game.id == game_id)
            .options(
                selectinload(Game.players),
                selectinload(Game.hands),
            )
        ).scalar_one_or_none()
    except Exception:  # malformed UUID etc.
        game = None
    if game is None or game.hero_user_id != user.id:
        raise HTTPException(404, "Game not found.")
    return game


@router.get("/games", response_model=list[GameSummary])
def list_games(
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> list[GameSummary]:
    games = (
        db.execute(
            select(Game)
            .where(Game.hero_user_id == user.id)
            .options(selectinload(Game.players), selectinload(Game.hands))
            .order_by(Game.started_at.desc().nullslast(), Game.created_at.desc())
        )
        .scalars()
        .all()
    )
    out: list[GameSummary] = []
    for game in games:
        hero = _hero_seat(game)
        out.append(
            GameSummary(
                game_id=str(game.id),
                started_at=game.started_at.isoformat() if game.started_at else None,
                small_blind=game.small_blind,
                big_blind=game.big_blind,
                num_hands=len(game.hands),
                hero_net=hero.total_winnings if hero else 0,
            )
        )
    return out


@router.get("/games/{game_id}/hands")
def list_hands(
    game_id: str,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    game = _load_owned_game(db, game_id, user)
    hero = _hero_seat(game)
    hero_gp_id = hero.id if hero else None

    hands = sorted(game.hands, key=lambda h: h.round_count)
    rows = []
    for hand in hands:
        # Hero's result for this hand, if the hero was dealt in.
        hero_won = False
        hero_amount = 0
        for hp in hand.players:
            if hp.game_player_id == hero_gp_id:
                hero_won = hp.is_winner
                hero_amount = hp.amount_won
                break
        rows.append({
            "round_count": hand.round_count,
            "street_reached": hand.street_reached.value,
            "board": list(hand.board or []),
            "pot_total": hand.pot_total,
            "had_showdown": hand.had_showdown,
            "hero_won": hero_won,
            "hero_amount": hero_amount,
        })

    return {
        "game_id": str(game.id),
        "small_blind": game.small_blind,
        "big_blind": game.big_blind,
        "started_at": game.started_at.isoformat() if game.started_at else None,
        "hands": rows,
    }


@router.get("/games/{game_id}/hands/{round_count}")
def hand_detail(
    game_id: str,
    round_count: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    game = _load_owned_game(db, game_id, user)
    hero = _hero_seat(game)
    hero_gp_id = hero.id if hero else None

    hand = db.execute(
        select(Hand)
        .where(Hand.game_id == game.id, Hand.round_count == round_count)
        .options(
            selectinload(Hand.players),
            selectinload(Hand.actions),
        )
    ).scalar_one_or_none()
    if hand is None:
        raise HTTPException(404, "Hand not found.")

    # game_player_id -> seat metadata, for naming actions/players.
    seat_by_gp = {gp.id: gp for gp in game.players}

    def name_of(gp_id) -> str:
        gp = seat_by_gp.get(gp_id)
        return gp.display_name if gp else "?"

    # Players' hands, in seat order. hole_cards is None unless known to the hero.
    players = []
    for hp in sorted(
        hand.players,
        key=lambda h: (seat_by_gp.get(h.game_player_id).seat_index
                       if seat_by_gp.get(h.game_player_id) else 99),
    ):
        gp = seat_by_gp.get(hp.game_player_id)
        players.append({
            "name": gp.display_name if gp else "?",
            "is_hero": hp.game_player_id == hero_gp_id,
            "hole_cards": list(hp.hole_cards) if hp.hole_cards else None,
            "is_winner": hp.is_winner,
            "amount_won": hp.amount_won,
        })

    # Per-player starting stack at hand start (keyed by game_player_id).
    start_stack: dict = {}
    for hp in hand.players:
        if hp.starting_stack is not None:
            start_stack[hp.game_player_id] = hp.starting_stack

    # Action amounts are the *cumulative total* a player has committed on that
    # street (not the incremental size). Track last-seen total per player to
    # compute the delta for stack accounting and detect all-ins.
    #
    # cumulative_committed[gp_id] = total chips this player has put in across
    # all streets so far (updated at each street boundary and after each action).
    cumulative_committed: dict = {gp_id: 0 for gp_id in start_stack}
    streets_out: dict[str, dict] = {}
    actions_sorted = sorted(hand.actions, key=lambda a: a.seq)

    # Group actions by street first, preserving order.
    raw_streets: dict[str, list] = {s: [] for s in _STREET_ORDER}
    for act in actions_sorted:
        bucket = act.street.value if act.street.value in raw_streets else "river"
        raw_streets[bucket].append(act)

    board = list(hand.board or [])
    board_by_street = {
        "preflop": [],
        "flop": board[:3],
        "turn": board[:4],
        "river": board[:5],
    }

    for st in _STREET_ORDER:
        acts = raw_streets[st]
        st_board = board_by_street[st]

        # Emit a street block whenever there are actions OR community cards
        # (all-in runouts have cards dealt but no betting actions).
        if not acts and not st_board:
            continue

        # Pot at start of this street = sum of all committed chips so far.
        pot_start = sum(cumulative_committed.values())

        # Per-player stack at the start of this street.
        stacks_at_street = {
            gp_id: max(0, start_stack.get(gp_id, 0) - cumulative_committed.get(gp_id, 0))
            for gp_id in start_stack
        }

        pot_info: dict = {"main": pot_start, "side": []}

        # Per-street committed tally (resets each street) for delta calculation.
        street_committed_prev: dict = {gp_id: 0 for gp_id in start_stack}

        action_rows = []
        for act in acts:
            gp_id = act.game_player_id
            amt = act.amount or 0

            if act.action in ("raise", "call", "smallblind", "bigblind", "ante") and amt > 0:
                # amt is the cumulative total this player has put in THIS STREET.
                prev = street_committed_prev.get(gp_id, 0)
                delta = max(0, amt - prev)
                street_committed_prev[gp_id] = amt
                stacks_at_street[gp_id] = max(0, stacks_at_street[gp_id] - delta)
                cumulative_committed[gp_id] = cumulative_committed.get(gp_id, 0) + delta

                # All-in: player's stack reaches zero after this action.
                is_allin = (
                    act.action in ("raise", "call")
                    and delta > 0
                    and stacks_at_street[gp_id] == 0
                )
            else:
                is_allin = False

            action_rows.append({
                "name": name_of(gp_id),
                "is_hero": gp_id == hero_gp_id,
                "action": act.action,
                "amount": amt,
                "is_allin": is_allin,
            })

        # Player stacks at start of this street (skip busted/absent seats).
        player_stacks = [
            {"name": name_of(gp_id), "stack": stk, "is_hero": gp_id == hero_gp_id}
            for gp_id, stk in stacks_at_street.items()
            if start_stack.get(gp_id, 0) > 0
        ]

        streets_out[st] = {
            "actions": action_rows,
            "pot": pot_info,
            "board": st_board,
            "player_stacks": player_stacks,
        }

    # Final pot structure from stored hand.pot (has accurate side pots).
    final_pot = hand.pot or {"main": {"amount": hand.pot_total}, "side": []}

    winners = [
        {"name": p["name"], "is_hero": p["is_hero"], "amount_won": p["amount_won"]}
        for p in players if p["is_winner"] and p["amount_won"] > 0
    ]

    # Hand values at showdown for all revealed players.
    showdown_hands = []
    if hand.had_showdown:
        for hp in hand.players:
            if not hp.hole_cards or not hp.revealed:
                continue
            gp = seat_by_gp.get(hp.game_player_id)
            name = gp.display_name if gp else "?"
            is_hero = hp.game_player_id == hero_gp_id
            try:
                best = pk_adapter.best_five(list(hp.hole_cards), board)
                label = best.get("label", "")
            except Exception:
                label = ""
            showdown_hands.append({
                "name": name,
                "is_hero": is_hero,
                "hole_cards": list(hp.hole_cards),
                "hand_label": label,
                "is_winner": hp.is_winner,
                "amount_won": hp.amount_won,
            })

    return {
        "game_id": str(game.id),
        "round_count": hand.round_count,
        "street_reached": hand.street_reached.value,
        "board": board,
        "pot_total": hand.pot_total,
        "final_pot": final_pot,
        "had_showdown": hand.had_showdown,
        "players": players,
        "streets": streets_out,
        "winners": winners,
        "showdown_hands": showdown_hands,
    }


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
