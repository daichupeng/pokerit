# Poker Trainer

A poker webapp backend that uses [PokerKit](https://github.com/uoftcprg/pokerkit)
to drive the game engine and hand evaluation, a game-management + recording layer
in `poker_engine/`, and an **LLM-driven AI coach** plus **LLM-powered opponent
bots** in `ai_functions/`.

## Stack

- **Python 3.11**, managed with [uv](https://github.com/astral-sh/uv)
- **FastAPI** + uvicorn for the web backend
- **PokerKit** (v0.7.4+) — production-quality NL Hold'em engine with correct
  wheel (A-2-3-4-5) handling, transparent side-pot objects, and 99% test
  coverage validated against real WSOP hand histories
- **Postgres 16** + **SQLAlchemy 2.0** for game records and coach conversations
- **LLM backends** via the OpenAI SDK — OpenAI (GPT), MiniMax, and a local
  [Ollama](https://ollama.com/) server are all reachable through one client
  wrapper. Powers both the AI coach and the LLM opponent bots.

## The `poker_engine` package

- `config.py` — `GameConfig`/`SeatSpec`: blinds, buy-in, and the seat lineup.
- `pk_adapter.py` — thin adapter over PokerKit: card utilities, hand evaluation
  (`best_five`, `winners_from_cards`), Monte Carlo equity estimation, and pot
  serialization helpers.
- `bots/` — two families of bots behind one `declare_action` / `set_n_players`
  interface, so the engine treats them identically:
  - `styles.py` — `StyleBot` plus TAG / LAG / Calling-station / Rock archetypes.
    These estimate equity via a Monte Carlo simulation using PokerKit's hand
    evaluator (fast, deterministic, no network).
  - `llm_bot_base.py` / `llm_styles.py` — `LLMBot`, a drop-in replacement that
    asks an LLM for its action. Concrete archetypes **AI GTO** (`GTOBot`),
    **AI Fish** (`FishBot`), and **AI Station** (`CallerBot`) each carry a
    tailored system prompt, model, and temperature, and are exposed by name via
    `LLM_STYLE_REGISTRY`. The bot's decision prompt is a compact text snapshot of
    the table (see `shared_services/table_formatter.py`) and it must reply with a
    strict JSON action object that is parsed and clamped to the legal bet range.
- `players/console.py` — `ConsolePlayer`, a human seat driven from stdin.
- `db/` — SQLAlchemy models: `users`, `oauth_identities`, `games`,
  `game_players`, `hands`, `hand_players`, `actions`, plus `conversations` and
  `messages` for the AI coach, and `game_evaluations` + `coaching_profiles` for
  the game-review pipeline. Bots are transient (rows in `game_players` only);
  only humans get a `users` account.
- `recorder.py` — `PerspectiveRecorder`: records each game **from the hero's
  view**. Opponent hole cards are stored only when revealed at showdown; folded
  or unknown hands are stored as `NULL`. Side pots are stored verbatim.
- `engine.py` — `GameEngine`: builds the table, runs the hand loop, records it.
- `stats.py` — deterministic, hero-only poker stats: VPIP, PFR, 3-bet frequency,
  C-bet frequency, fold-to-aggression, and more. Pure functions over recorded
  `Hand`/`HandPlayer`/`Action` rows; no judgment calls, safe for live or finished
  games. Entry points: `compute_game_stats(db, game_id, game_player_id)` and
  `compute_player_stats(db, user_id)` roll up counts across games and normalize
  to percentages via `to_display()`.

## AI coach (`ai_functions/`)

An LLM coaching layer that reviews hands and advises during live play, plus an
async multi-stage pipeline for game-level leak detection and synthesis.

### In-game coaching (`coach_engine/`)

- `engine.py` — the single entry point for a coaching turn. It builds the
  prompt (system prefix + optional pinned context + a live table snapshot + a
  trimmed rolling window of recent turns), streams the reply from the LLM, and
  persists both the user and assistant messages with token counts.
  Three coaching personas are selected per turn:
  - **hand_review** — blunt, range-based post-hand analysis of a saved hand.
  - **in_game** — next-best-action advice against the current table state.
  - **generic** — free-form Q&A with the GTO coach.
- Conversations are keyed by `entry_point` (`hand_history` / `in_game` /
  `generic`) and may pin an un-trimmable context block plus a per-turn live
  context. The short-term memory window and a token budget bound the prompt size.

### Game-level coaching (`game_review/`)

A fully asynchronous pipeline that reads finished games, triages hands into
leak categories, and synthesizes structured feedback. Powered by tools (agents
with schema-validated outputs) and a per-street analyzer.

- `pipeline.py` — the orchestration harness. Stages execute serially or
  in parallel; agents are spawned with strict input/output schemas.
  1. **Triage** — categorize hands by leak type (positional, aggression, etc.).
  2. **Stat leaks** — filter to hands that diverge from peer benchmarks.
  3. **Street agents** — per-street analysis (preflop position, flop texture, etc.).
  4. **Merge** — consolidate findings across streets.
  5. **Synthesis** — LLM writer composes a guided improvement plan.
- `leak_taxonomy.py` — 20+ leak types with scoring and confidence.
  Hands are routed to appropriate review agents.
- `street_agent.py` — street-specific decision analysis with hand strength
  estimation, equity breakdowns, and action frequencies.
- `synthesis.py` — generates a narrative improvement plan from triaged findings.
- `session_dynamics.py` — table conditions, villain shapes, and stack dynamics.
- `triage.py` — initial hand categorization and urgency scoring.
- `hand_context.py` — context builders (hand strength, stack-to-pot ratios).
- `config.py` — feature flags and LLM/schema configuration.

### Tools layer (`tools/`)

Schema-validated tool executors and loop runners that power the game-review pipeline.

- `executors.py` — `ToolExecutor` spawns an LLM agent with a strict JSON schema,
  retries on parse failures, and returns the validated output. Logs every call.
- `schemas.py` — Pydantic models for tool inputs/outputs (hand triage, leak
  scoring, street analysis, narrative synthesis).
- `loop.py` — retry loop for tools with `retry_count` and exponential backoff.

### Long-term coaching profile (`memory/`)

Persistent tracking of leak states, correction loops (discard/restore/dispute),
and stat trends across all evaluated games.

- `persistence.py` — build/load/persist the coaching profile row. Fold
  completed evaluations into a profile that tracks leak status (flagged /
  confirmed / resolved), playstyle summary, and when it was reset.

## Shared services (`shared_services/`)

- `llm.py` — one process-wide client wrapper over the OpenAI SDK that routes by
  model name to OpenAI, MiniMax, or a local Ollama server, with both streaming
  and non-streaming helpers, token-usage accounting, and reasoning-model
  (`reasoning_effort`) handling. Every call is written to a JSONL prompt audit
  log (`logs/prompts.jsonl`).
- `table_formatter.py` — renders a `round_state` dict into the compact,
  hero-relative text table that both the coach and the LLM bots consume.
- `hand_formatter.py` — hand-history / position formatting helpers.

## Web app (`poker_trainer/`)

An interactive poker table served by FastAPI with a vanilla-JS single-page UI.
Bots run server-side via PokerKit's imperative state machine (one action at a
time); the human plays over a WebSocket. The hidden-information rule is enforced
end to end — the browser only ever receives the hero's own cards plus opponents'
cards revealed at showdown.

- `main.py` — FastAPI app: REST setup, WebSocket play, serves the SPA at `/`.
- `api/auth.py` — Google OAuth login/callback/logout (see below);
  `api/games.py` — create game, list games, get state;
  `api/profile.py` — user profile CRUD, player stats rollup, coaching profile read/reset;
  `api/coach.py` — the AI coach: create/fetch conversations and a
  streaming (SSE) chat endpoint that injects the live table state as context;
  `api/game_evaluation.py` — game-level coaching review pipeline (enqueue, poll, read).
- `game/session.py` — `GameSession` wraps the PokerKit state machine and the bot
  loop (LLM bots run in a worker thread so their async LLM calls don't block the
  event loop); `game/manager.py` — in-memory live games.
- `game/serialize.py` — builds the hero-perspective round-state payloads.
- `ws.py` — the play loop (streams events, receives the hero's action).
- `worker.py` — async job worker for background game evaluations via [arq](https://arq-docs.helpmanual.io/).
- `jobs.py` — Redis pool and job-queue configuration.
- `static/` — SPA: `index.html`, `css/styles.css`, `js/app.js` (router + login/
  main/create screens), `js/table.js` (table render, bet controls, stats/hands
  panel). Cards and felt are drawn in CSS — no downloaded assets, works offline.

User journey: **Login** (skippable) → **Main** (create game / review evaluated games) →
**Create game** (bots, blinds, buy-in; randomize + hide bot styles) → **Table**
(standard play, slider + input bet controls clamped to the rules) with a
collapsible **Stats / Hands** panel → **Game review** (async pipeline triages
hands by leak type, synthesizes feedback, and coaches by street).

### Run the web app

```bash
cp .env.example .env                  # then fill in Google OAuth + LLM creds (see below)
docker compose up -d --build          # starts Postgres, Redis, Ollama, app, and worker
docker compose exec app uv run alembic upgrade head   # create/upgrade schema
# open http://localhost:8000
```

`docker compose` brings up:

- **Postgres 16** for game records, coaching conversations, and user profiles.
- **Redis** as the job queue broker for background game evaluations (arq).
- **Ollama** with a one-shot fetch of `qwen3:4b` so the LLM bots and coach can
  run against a local model without an external API.
- **FastAPI app** on port 8000 serving the web UI and REST API.
- **arq worker** in a separate container (`worker`) that processes game-evaluation
  jobs from the queue.

Set `OPENAI_API_KEY` (and optionally `MINIMAX_API_KEY`) in `.env` to use hosted
backends instead — the client in `shared_services/llm.py` routes by model name.

## LLM configuration

The AI coach and LLM bots reach three backends through one client wrapper,
selected by model-name prefix:

| Backend | Model name prefix | Credentials |
| --- | --- | --- |
| OpenAI | (default, e.g. `gpt-5-mini`, `gpt-4.1-mini`) | `OPENAI_API_KEY` |
| MiniMax | `minimax…` | `MINIMAX_API_KEY` |
| Ollama (local) | `qwen…` / `llama…` / `mistral…` / `ollama…` | none; `OLLAMA_BASE_URL` (default `http://localhost:11434`) |

Every call is appended to a JSONL audit log at `${LOG_DIR}/prompts.jsonl`
(prompt, response, model, latency, and token counts).

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
- `api/coach.py` — `POST /api/coach/conversations`, `GET /api/coach/conversations/{id}`,
  `GET /api/coach/conversations/by-hand/{hand_id}`, and `POST /api/coach/chat`
  (SSE stream). Requires a signed-in user.

The `users` table now holds a full profile (username, avatar, bio, locale,
status/role, timestamps); linked external identities live in `oauth_identities`.

### User profile endpoints

- `GET /api/profile` — retrieve the current user's profile (display name, username,
  bio, avatar, country, timezone, language, preferences, account status).
- `PATCH /api/profile` — update editable profile fields with validation.
- `DELETE /api/profile` — soft-delete account (keeps game history, frees email/username).
- `GET /api/profile/stats` — player's stats rolled up across all games (VPIP, PFR,
  3-bet frequency, C-bet frequency, etc.).
- `GET /api/profile/coaching` — long-term coaching profile: leak states grouped by
  status (flagged / confirmed / resolved), stat trends, and playstyle summary.
- `POST /api/profile/reset` — reset the coaching profile to fold all evaluations
  before a certain timestamp, producing an empty profile until new evaluations complete.

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
