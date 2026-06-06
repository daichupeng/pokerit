# Poker Trainer

A poker webapp backend that uses [PokerKit](https://github.com/uoftcprg/pokerkit)
to drive the game engine and hand evaluation, plus a game-management + recording
layer in `poker_engine/`.

## Stack

- **Python 3.11**, managed with [uv](https://github.com/astral-sh/uv)
- **FastAPI** + uvicorn for the web backend
- **PokerKit** (v0.7.4+) — production-quality NL Hold'em engine with correct
  wheel (A-2-3-4-5) handling, transparent side-pot objects, and 99% test
  coverage validated against real WSOP hand histories
- **Postgres 16** + **SQLAlchemy 2.0** for game records

## The `poker_engine` package

- `config.py` — `GameConfig`/`SeatSpec`: blinds, buy-in, and the seat lineup.
- `pk_adapter.py` — thin adapter over PokerKit: card utilities, hand evaluation
  (`best_five`, `winners_from_cards`), Monte Carlo equity estimation, and pot
  serialization helpers.
- `bots/` — `StyleBot` plus TAG / LAG / Calling-station / Rock archetypes. Bots
  estimate equity via a Monte Carlo simulation using PokerKit's hand evaluator.
- `players/console.py` — `ConsolePlayer`, a human seat driven from stdin.
- `db/` — SQLAlchemy models: `users`, `games`, `game_players`, `hands`,
  `hand_players`, `actions`. Bots are transient (rows in `game_players` only);
  only humans get a `users` account.
- `recorder.py` — `PerspectiveRecorder`: records each game **from the hero's
  view**. Opponent hole cards are stored only when revealed at showdown; folded
  or unknown hands are stored as `NULL`. Side pots are stored verbatim.
- `engine.py` — `GameEngine`: builds the table, runs the hand loop, records it.

## Web app (`poker_trainer/`)

An interactive poker table served by FastAPI with a vanilla-JS single-page UI.
Bots run server-side via PokerKit's imperative state machine (one action at a
time); the human plays over a WebSocket. The hidden-information rule is enforced
end to end — the browser only ever receives the hero's own cards plus opponents'
cards revealed at showdown.

- `main.py` — FastAPI app: REST setup, WebSocket play, serves the SPA at `/`.
- `api/auth.py` — login stub (no password yet); `api/games.py` — create game,
  list games (stub), get state.
- `game/session.py` — `GameSession` wraps the PokerKit state machine and the bot
  loop; `game/manager.py` — in-memory live games.
- `ws.py` — the play loop (streams events, receives the hero's action).
- `static/` — SPA: `index.html`, `css/styles.css`, `js/app.js` (router + login/
  main/create screens), `js/table.js` (table render, bet controls, stats/hands
  panel). Cards and felt are drawn in CSS — no downloaded assets, works offline.

User journey: **Login** (skippable) → **Main** (create game / review stub) →
**Create game** (bots, blinds, buy-in; randomize + hide bot styles) → **Table**
(standard play, slider + input bet controls clamped to the rules) with a
collapsible **Stats / Hands** panel.

### Run the web app

```bash
cp .env.example .env                  # then fill in Google OAuth creds (see below)
docker compose up -d --build          # starts Postgres + the web app
docker compose exec app uv run alembic upgrade head   # create/upgrade schema
# open http://localhost:8000
```

## Accounts & authentication

Sign-in is **Google OAuth2** (server-side flow via authlib), with signed
httpOnly cookie sessions (Starlette `SessionMiddleware`). Login is required to
create or play a game; the game record links to your account by email.

- `auth/` — OAuth registry, session config, account-linking service, and the
  `get_db` / `current_user` / `require_user` FastAPI dependencies.
- `api/auth.py` — `GET /api/auth/google/login`, `…/callback`, `POST /api/auth/logout`,
  `GET /api/auth/me`, `GET /api/auth/config`.
- `api/profile.py` — `GET/PATCH/DELETE /api/profile` (display name, username,
  bio, country, timezone, language, avatar, preferences; soft-delete).

The `users` table now holds a full profile (username, avatar, bio, locale,
status/role, timestamps); linked external identities live in `oauth_identities`.

### Google Cloud setup

1. Google Cloud Console → APIs & Services → **Credentials** → Create **OAuth
   client ID** → *Web application*.
2. Add an **Authorized redirect URI**: `${APP_BASE_URL}/api/auth/google/callback`
   (e.g. `http://localhost:8000/api/auth/google/callback`).
3. Put the client id/secret and a random `SESSION_SECRET` in `.env` (see
   `.env.example`). `.env` is gitignored — never commit it.

### Schema migrations (Alembic)

```bash
docker compose exec app uv run alembic upgrade head     # apply migrations
docker compose exec app uv run alembic revision -m "msg" --autogenerate  # new migration
```

`scripts/init_db.py` (`create_all`) still works for a fresh throwaway DB, but
Alembic is the canonical path and preserves existing data.

## CLI game + Docker (engine layer)

```bash
docker compose up -d db                                   # start Postgres
docker compose exec app uv run python scripts/init_db.py  # create schema
docker compose run --rm app uv run python scripts/play_game.py --auto   # bot-only, recorded
docker compose exec db psql -U poker -d poker             # inspect records
```

Interactive console play (human vs bots):

```bash
docker compose run --rm app uv run python scripts/play_game.py
```

## Local development (without Docker)

```bash
uv sync                                  # create .venv and install dependencies
export DATABASE_URL=postgresql+psycopg://poker:poker@localhost:5432/poker
uv run python scripts/init_db.py
uv run python scripts/play_game.py       # play vs bots
```
