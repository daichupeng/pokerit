"""REST endpoints for game setup and (stubbed) review."""

from __future__ import annotations

import random

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from poker_engine import pk_adapter
from poker_engine.bots.styles import STYLE_REGISTRY
from poker_engine.bots.llm_styles import LLM_STYLE_REGISTRY
from poker_engine.config import GameConfig, SeatKind, SeatSpec
from poker_engine.db.models import Game, GamePlayer, Hand, User
from poker_trainer.auth.deps import get_db, require_user
from poker_trainer.game.manager import manager
from poker_trainer.game.session import GameSession

router = APIRouter(prefix="/api", tags=["games"])

# Derived from both registries — single source of truth.
BOT_STYLES = [SeatKind(v) for v in list(STYLE_REGISTRY) + list(LLM_STYLE_REGISTRY)]

@router.get("/bot-styles")
def list_bot_styles() -> list[dict]:
    """Return all available bot styles for the game setup UI."""
    return [{"value": kind.value, "label": kind.value} for kind in BOT_STYLES]


# Bot names are "Adjective Noun" pairs drawn from these 30×30 = 900 combos,
# sampled uniquely per game.
_BOT_ADJECTIVES = [
    "vivid", "hollow", "brisk", "damp", "quiet", "zesty", "plump", "faint", "sharp", "grim", "lanky", 
    "stark", "jaunty", "coarse", "numb", "witty", "bland", "rough", "keen", "meek", "droll", "salty", 
    "puffy", "harsh", "dim", "odd", "lush", "tepid", "giddy", "tame", "chubby", "fit", "sly", "vast", 
    "firm", "apt", "snug", "grand", "rank", "wary", "calm", "foul", "exotic", "dull", "wild", "prime", 
    "slow", "bleak", "tart", "nice", "mild", "slim", "glad", "hoarse", "full", "kind", "grisly", "pale", 
    "gruff", "vague", "light", "crisp", "warm", "quick", "dear", "rare", "loose", "fast", "sore", "cold",
    "lucid", "plain", "short", "deep", "tough", "neat", "just", "hard", "busy", "rich", "long", "main", 
    "base", "able", "sweet", "flat", "curt", "fres", "sure", "broad", "sick", "true", "thin", "dank", 
    "high", "pure", "wise", "real", "arid", "open"
]
_BOT_NOUNS = [
    "Kite", "Zebra", "Bolt", "Fjord", "Quartz", "Mace", "Dusk", "Vex", "Jolt", "Haze", "Pike", "Wisp", 
    "Grit", "Tusk", "Brim", "Loom", "Cove", "Nook", "Rift", "Spire", "Yarn", "Flux", "Omen", "Knoll", 
    "Bask", "Swale", "Drake", "Quill", "Jive", "Vane", "Helm", "Cleft", "Pith", "Zeal", "Gale", "Root", 
    "Finch", "Kindle", "Mirth", "Scion", "Wren", "Plume", "Trove", "Basil", "Ibis", "Chord", "Drift", 
    "Knot", "Glade", "Nerve", "Apex", "Brine", "Forge", "Husk", "Vista", "Quirk", "Yoke", "Crest", "Lens", 
    "Pulse", "Shard", "Verve", "Bough", "Gorge", "Kin", "Mist", "Prism", "Silt", "Vale", "Warp", "Aura", 
    "Blaze", "Crypt", "Fawn", "Grove", "Haven", "Ivy", "Junction", "Knack", "Lark", "Mote", "Niche", 
    "Oasis", "Peak", "Quarry", "Reef", "Stark", "Thorn", "Urn", "Vault", "Wedge", "Xylem", "Yard", 
    "Zenith", "Anchor", "Cliff", "Cairn", "Dune", "Echo", "Frost"
]


def _random_bot_names(count: int, rng: random.Random) -> list[str]:
    """Sample `count` unique 'Adjective Noun' names (up to 900 combinations)."""
    combos = [f"{a}{s}{n}" for a in _BOT_ADJECTIVES for n in _BOT_NOUNS for s in ("_", "-",".")]
    return rng.sample(combos, min(count, len(combos)))

# Default quick-bet presets. Preflop sizing is in big blinds; postflop in % pot.
DEFAULT_PREFLOP_QUICK = [2.0, 2.5, 3.5, 4.5]   # × BB
DEFAULT_POSTFLOP_QUICK = [33.0, 50.0, 60.0, 100.0]  # % pot


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
            "hand_id": str(hand.id),
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

    # Position is stored per hand_player row — read directly from DB.
    pos_by_gp: dict = {hp.game_player_id: (hp.position or "") for hp in hand.players}

    def pos_of(gp_id) -> str:
        return pos_by_gp.get(gp_id, "")

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
            "position": pos_of(hp.game_player_id),
        })

    # Per-player starting stack at hand start (keyed by game_player_id).
    start_stack: dict = {}
    for hp in hand.players:
        if hp.starting_stack is not None:
            start_stack[hp.game_player_id] = hp.starting_stack

    actions_sorted = sorted(hand.actions, key=lambda a: a.seq)
    streets_out: dict[str, dict] = {}

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

    # current_stacks[gp_id] = stack entering the current street.
    # Initialized from hand-start stacks; updated at the end of each street
    # using stack_after values recorded by the engine.
    current_stacks: dict = dict(start_stack)

    # Players who folded in a *previous* street (excluded from later displays).
    folded_before_street: set = set()

    # Pot accumulated from all previous streets (chips already in the middle).
    pot_carried: int = 0

    for st in _STREET_ORDER:
        acts = raw_streets[st]
        st_board = board_by_street[st]

        if not acts and not st_board:
            continue

        # Stacks at the START of this street — snapshot before any action mutates them.
        stacks_at_street_start = dict(current_stacks)

        folds_this_street: set = set()
        action_rows = []
        chips_added_this_street: int = 0
        # Cumulative chips each player has committed this street (their "current bet").
        # For preflop, pre-seed SB/BB with their posted blinds so action lines
        # show the correct "current bet" and stack before their first voluntary action.
        street_invested: dict = {}
        if st == "preflop":
            gp_by_seat = {gp.seat_index: gp.id for gp in game.players}
            if hand.sb_pos is not None:
                sb_gp_id = gp_by_seat.get(hand.sb_pos)
                if sb_gp_id and sb_gp_id in current_stacks:
                    sb_amt = game.small_blind
                    street_invested[sb_gp_id] = sb_amt
                    current_stacks[sb_gp_id] -= sb_amt
                    chips_added_this_street += sb_amt
            if hand.bb_pos is not None:
                bb_gp_id = gp_by_seat.get(hand.bb_pos)
                if bb_gp_id and bb_gp_id in current_stacks:
                    bb_amt = game.big_blind
                    street_invested[bb_gp_id] = bb_amt
                    current_stacks[bb_gp_id] -= bb_amt
                    chips_added_this_street += bb_amt

        for act in acts:
            gp_id = act.game_player_id
            amt = act.amount or 0

            # Snapshot state BEFORE this action for display purposes.
            street_bet_before = street_invested.get(gp_id, 0)
            stack_before = current_stacks.get(gp_id, 0)

            # stack_after is recorded by the engine right after PokerKit processes
            # the action, so it is always the authoritative post-action stack.
            if act.stack_after is not None:
                chips_put_in = max(0, stack_before - act.stack_after)
                chips_added_this_street += chips_put_in
                current_stacks[gp_id] = act.stack_after
                street_invested[gp_id] = street_bet_before + chips_put_in
                is_allin = (
                    act.action in ("raise", "call")
                    and act.stack_after == 0
                    and chips_put_in > 0
                )
            else:
                # Fallback for legacy rows without stack_after.
                is_allin = False

            if act.action == "fold":
                folds_this_street.add(gp_id)

            action_rows.append({
                "name": name_of(gp_id),
                "is_hero": gp_id == hero_gp_id,
                "action": act.action,
                "amount": amt,
                "is_allin": is_allin,
                "position": pos_of(gp_id),
                "street_bet": street_bet_before,
                "stack_before": stack_before,
            })

        # Player stacks at the START of this street.
        # Include players who were still active entering this street.
        player_stacks = [
            {"name": name_of(gp_id), "stack": stk, "is_hero": gp_id == hero_gp_id, "position": pos_of(gp_id)}
            for gp_id, stk in stacks_at_street_start.items()
            if start_stack.get(gp_id, 0) > 0 and gp_id not in folded_before_street
        ]

        # Folds from this street are excluded from all subsequent street displays.
        folded_before_street |= folds_this_street

        streets_out[st] = {
            "actions": action_rows,
            "pot": {"main": pot_carried, "side": []},
            "board": st_board,
            "player_stacks": player_stacks,
        }

        pot_carried += chips_added_this_street

    # Final pot structure from stored hand.pot (has accurate side pots).
    final_pot = hand.pot or {"main": {"amount": hand.pot_total}, "side": []}

    winners = [
        {"name": p["name"], "is_hero": p["is_hero"], "amount_won": p["amount_won"], "position": p["position"]}
        for p in players if p["is_winner"] and p["amount_won"] > 0
    ]

    # Players who folded at any point (used to exclude hero from showdown display).
    folded_gp_ids = {a.game_player_id for a in hand.actions if a.action == "fold"}

    # Hand values at showdown for all revealed players.
    showdown_hands = []
    if hand.had_showdown:
        for hp in hand.players:
            if not hp.hole_cards or not hp.revealed:
                continue
            if hp.game_player_id == hero_gp_id and hp.game_player_id in folded_gp_ids:
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
                "position": pos_of(hp.game_player_id),
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
        "button_pos": hand.button_pos,
    }


@router.get("/games/{game_id}/hands/{round_count}/context")
def hand_context_text(
    game_id: str,
    round_count: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return a plain-text coach context string for one hand."""
    from shared_services.hand_formatter import format_hand

    game = _load_owned_game(db, game_id, user)
    hand = db.execute(
        select(Hand).where(Hand.game_id == game.id, Hand.round_count == round_count)
    ).scalar_one_or_none()
    if hand is None:
        raise HTTPException(404, "Hand not found.")
    detail = hand_detail(game_id, round_count, user, db)
    text = format_hand(detail, game.small_blind, game.big_blind)
    return {"context": text, "round_count": round_count, "hand_id": str(hand.id)}


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
