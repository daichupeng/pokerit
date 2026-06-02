# Poker Trainer

A poker webapp backend that uses [PyPokerEngine](https://github.com/ishikota/PyPokerEngine)
to drive bot players, plus a game-management + recording layer in `poker_engine/`.

## Stack

- **Python 3.11**, managed with [uv](https://github.com/astral-sh/uv)
- **FastAPI** + uvicorn for the web backend (to be built)
- **PyPokerEngine**, vendored editable under `vendor/PyPokerEngine` so we can
  patch its API (it now exposes exact hole cards at showdown — see below)
- **Postgres 16** + **SQLAlchemy 2.0** for game records

## The `poker_engine` package

- `config.py` — `GameConfig`/`SeatSpec`: blinds, buy-in, and the seat lineup.
- `bots/` — `StyleBot` plus TAG / LAG / Calling-station / Rock archetypes. Bots
  estimate equity via PyPokerEngine's Monte Carlo `estimate_hole_card_win_rate`.
- `players/console.py` — `ConsolePlayer`, a human seat driven from stdin.
- `db/` — SQLAlchemy models: `users`, `games`, `game_players`, `hands`,
  `hand_players`, `actions`. Bots are transient (rows in `game_players` only);
  only humans get a `users` account.
- `recorder.py` — `PerspectiveRecorder`: records each game **from the hero's
  view**. Opponent hole cards are stored only when revealed at showdown; folded
  or unknown hands are stored as `NULL`. Side pots are stored verbatim as the
  engine reports them.
- `engine.py` — `GameEngine`: builds the table, runs `start_poker`, records it.

### Vendored engine patch

`vendor/PyPokerEngine/.../game_evaluator.py` is patched to add a `hole_card`
list (exact card strings) to each showdown participant's `hand_info` entry. The
stock API only exposed rank summaries, which made faithful showdown records
impossible. The patch only fires at a real showdown, preserving the
hidden-information rule.

## Docker (recommended)

```bash
docker compose up -d db                                   # start Postgres
docker compose run --rm app uv run python scripts/init_db.py        # create schema
docker compose run --rm app uv run python scripts/play_game.py --auto   # bot-only, recorded
docker compose exec db psql -U poker -d poker             # inspect records
```

Interactive play (human vs bots):

```bash
docker compose run --rm app uv run python scripts/play_game.py
```

## Local development (without Docker)

```bash
uv sync                                  # create .venv, build vendored engine
export DATABASE_URL=postgresql+psycopg://poker:poker@localhost:5432/poker
uv run python scripts/init_db.py
uv run python scripts/play_game.py       # play vs bots
```
