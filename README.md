# Poker Trainer

Current release: **v0.2.0** — 2026-07-29

A local-first No-Limit Hold'em training application built with
[PokerKit](https://github.com/uoftcprg/pokerkit), FastAPI, PostgreSQL, and LLM-
assisted coaching. It combines playable cash/MTT practice tables, persistent
hand histories, deterministic statistics, structured game reviews, rolling
history reports, and focused preflop drills.

This release contains substantial training and analysis improvements on top of
[`daichupeng/pokerit`](https://github.com/daichupeng/pokerit). See
[CHANGELOG.md](CHANGELOG.md) for the user-facing change history and
[docs/UPSTREAM_CHANGES.md](docs/UPSTREAM_CHANGES.md) for a reviewer-oriented
map of the changes relative to upstream.

## Highlights

- Play 6-max or 8-max 100BB cash, three 8-max MTT stack-depth presets with a
  big-blind ante, or a custom fixed-level game.
- Practice against deterministic archetype bots or LLM-powered opponents.
- Ask a concise, scenario-aware AI coach during play or from a saved hand.
- Save every completed hand incrementally instead of waiting for a game to end.
- Run a structured single-game review using future-clipped Decision Snapshots.
- Track scope-isolated coaching profiles and rolling statistics over up to 500
  saved hands.
- Train source-audited RFI boundaries in persisted ten-question drill sessions.
- Keep hidden opponent cards out of the browser and database unless they were
  actually revealed at showdown.

## Training modes

### Playable scenarios

| Scenario key | Table | Starting stack | Ante |
| --- | ---: | ---: | --- |
| `cash_6max_100bb` | 6-max | 100BB | None |
| `cash_8max_100bb` | 8-max | 100BB | None |
| `mtt_8max_40bb` | 8-max | 40BB | 1BB big-blind ante |
| `mtt_8max_25bb` | 8-max | 25BB | 1BB big-blind ante |
| `mtt_8max_15bb` | 8-max | 15BB default | 1BB big-blind ante |
| `custom` | Configurable | Configurable | None or BB ante |

MTT presets are fixed-level stack-depth training environments. They do **not**
simulate blind increases, payouts, field size, bubble pressure, or ICM. When
payout context is unavailable, the coach is instructed to reason in chip EV.

### Preflop decision drills

The drill screen uses four versioned RFI range packs:

- 6-max and 8-max cash at 100BB;
- 6-max and 8-max MTT at 40BB with a 1BB BB ante.

Each persisted session keeps one pack and one RFI node constant for ten
boundary/control decisions. Mixed chart cells accept every source-supported
action without inventing exact frequencies. The current packs are transcribed
from [RangeConverter's public charts](https://rangeconverter.com/free-poker-charts)
and retain source URLs, hashes, position mappings, and derivation notes.

## Coaching and evaluation

### Interactive coach

The coach has separate prompts for completed-hand review, live next-action
advice, and general poker questions. It receives authoritative scenario/table
context, answers in the user's language, leads with the decision, and avoids
generic filler. It must distinguish recorded state, deterministic math,
configured bot style, versioned range knowledge, heuristic inference,
user-supplied reads, and actual solver evidence.

`AI GTO` is a configured simulation style; it is never presented as proof that
a solver node was queried.

### Single-game evaluation

`Evaluate Game` runs asynchronously through Redis/arq:

1. Compute deterministic game statistics and session dynamics.
2. Triage candidate hands by street.
3. Build a versioned Decision Snapshot for each hero decision, clipped at the
   moment of action so later actions, board cards, showdown cards, and results
   cannot leak into the judgment.
4. Ask street reviewers for structured explanations: actual action, issue,
   better line, EV rationale, optional future plan, and confidence.
5. Merge judgment findings with deterministic statistical findings.
6. Synthesize a concise report while preserving code-owned tags, severities,
   citations, sample status, and evidence categories.

Reports record the scenario threshold profile and threshold version used.
Undefined `0/0` metrics remain undefined, and aggression factor is always
defined as `(postflop bets + raises) / postflop calls`.

### Rolling history evaluation

`Evaluate History` is separate from a single-game review. It:

- stays inside one scenario/profile scope;
- aggregates the most recent 500 saved hands (or a smaller requested window);
- compares the selected latest game with a prior-500-hand baseline that
  excludes that game;
- computes sample readiness, trends, and leak tags deterministically;
- optionally asks one tool-free LLM call to narrate the already-computed JSON;
- still completes with numeric output if narration fails; and
- never folds itself into the per-game leak occurrence state machine.

### Leak thresholds and sample handling

Leak thresholds are centralized, scenario-specific, and versioned. The current
development profile is `2026-07-23.v3` and uses a deliberately permissive
minimum of five relevant opportunities for each deterministic metric. Below
that floor the UI shows `insufficient sample` and code emits no statistical
leak. Findings that clear five opportunities should still be interpreted as
early signals, not settled long-term conclusions.

The 15BB Push/Fold profile disables postflop statistical leak tags and instead
prioritizes descriptive open-shove, reshove, and call-off statistics plus
preflop shove/reshove/call-off judgment tags.

### Long-term coaching profiles

Completed single-game evaluations fold into a profile scoped by scenario. Leak
states progress through `flagged`, `confirmed`, and `resolved`, with support for
discard, restore, dispute, regression, and reset workflows. Cash, MTT, table
size, and stack-depth profiles remain isolated; legacy 6-max MTT history is not
silently reclassified as new 8-max data.

## Quick start with Docker

### Prerequisites

- Docker Desktop
- A Google OAuth web client
- An OpenAI API key for the current default AI models

### 1. Configure the environment

```bash
cp .env.example .env
```

Edit `.env` and set at least:

```dotenv
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
SESSION_SECRET=...
OPENAI_API_KEY=...
APP_BASE_URL=http://localhost:8000
```

Generate a session secret with, for example:

```bash
openssl rand -hex 32
```

In Google Cloud Console, create an OAuth client of type **Web application** and
register this exact authorized redirect URI:

```text
http://localhost:8000/api/auth/google/callback
```

The origin in `APP_BASE_URL`, the browser URL, and the registered redirect URI
must agree.

### 2. Start the application

```bash
docker compose up -d --build
docker compose exec app uv run alembic upgrade head
```

Open [http://localhost:8000](http://localhost:8000).

Verify service state with:

```bash
docker compose ps
```

The default Compose stack starts PostgreSQL, Redis, Ollama, the FastAPI app,
and the arq evaluation worker. The web app and worker watch mounted source files
during local development.

### Routine use on a Mac

After sleep/wake, allow Docker Desktop a few seconds to resume and refresh the
page. If the app is unavailable, run:

```bash
docker compose up -d
```

To stop the stack without deleting data:

```bash
docker compose down
```

Do **not** run `docker compose down -v` unless you intentionally want to delete
the PostgreSQL and Ollama volumes.

## Configuration

### LLM backends

The shared client routes requests by model-name prefix:

| Backend | Model-name prefix | Configuration |
| --- | --- | --- |
| OpenAI | Default, including `gpt-5...` | `OPENAI_API_KEY` |
| MiniMax | `minimax...` | `MINIMAX_API_KEY` |
| Ollama | `qwen...`, `llama...`, `mistral...`, `ollama...` | `OLLAMA_BASE_URL` |

Current code defaults are:

| Component | Default model |
| --- | --- |
| Interactive coach | `gpt-5.4-mini` |
| Single-game street review and synthesis | `gpt-5.4-mini` |
| Rolling-history narration | `gpt-5.4-mini` |
| LLM opponent bots | `gpt-5.4-mini` |

These defaults currently live in the corresponding Python configuration
modules; they are not selected by an environment variable. GPT-5 reasoning
models are called without unsupported temperature parameters, and tool-bearing
Chat Completions requests use `reasoning_effort="none"` for compatibility.

### Account preferences

Account Settings stores versioned quick-bet shortcuts used by newly created
games. Defaults are:

- preflop: `2.0`, `2.5`, `6.0`, `7.5` BB;
- postflop: `33`, `50`, `65`, `100` percent pot.

Legacy per-game API overrides remain accepted.

## Data persistence and privacy

- Source code lives in the repository directory.
- PostgreSQL data lives in the Docker volume `pgdata`.
- Games are created in the database at session start, and every completed hand
  is flushed incrementally. A service interruption can lose the hand currently
  in progress, but already completed hands remain stored.
- Normal restarts, Mac sleep/wake, and `docker compose down` do not remove the
  database volume.
- The browser receives only the hero's cards and opponent cards actually
  revealed at showdown.
- Fold winners are not classified as showdowns, and hidden opponent cards are
  removed during the visibility-correction migrations.

Every model call is written to `${LOG_DIR}/prompts.jsonl`, including prompts,
responses, model names, latency, token counts, and contextual identifiers.
Treat this file as sensitive: do not publish it without sanitization.

Never commit `.env`, API keys, OAuth client secrets, session secrets, database
dumps, or unsanitized prompt logs.

## Database migrations

Alembic is the canonical schema-management path:

```bash
docker compose exec app uv run alembic upgrade head
docker compose exec app uv run alembic current
```

Migrations `0009` through `0016` add scenario/profile scoping, rolling-history
evaluations, showdown visibility corrections, per-hand active-player counts,
and persisted drill sessions. See [CHANGELOG.md](CHANGELOG.md) for upgrade notes.

`scripts/init_db.py` remains useful for a fresh throwaway database, but it is
not a replacement for Alembic when upgrading existing data.

## Architecture

| Area | Responsibility |
| --- | --- |
| `src/poker_engine/` | PokerKit game loop, bots, recording, persistence, and deterministic stats |
| `src/ai_functions/coach_engine/` | Interactive coaching prompts and conversation memory |
| `src/ai_functions/game_review/` | Single-game triage, street review, merge, and synthesis |
| `src/ai_functions/history_evaluation/` | Rolling deterministic history reports and optional narration |
| `src/ai_functions/preflop_ranges/` | Versioned RFI range packs and source metadata |
| `src/poker_trainer/` | FastAPI routes, WebSocket sessions, arq worker, and SPA |
| `src/shared_services/` | LLM routing, logging, and hand/table formatting |
| `migrations/versions/` | Alembic schema and data migrations |
| `tests/` | Engine, API, statistics, evaluation, range, drill, and regression tests |

The live game manager is in memory, while completed hand history and reports are
persisted in PostgreSQL. Redis is used only as the background job broker.

## Testing

Run the complete test suite in an isolated app container:

```bash
docker compose run --rm --no-deps \
  -v "$PWD/tests:/app/tests:ro" \
  app uv run --extra dev pytest -q
```

For local development without Docker:

```bash
uv sync --extra dev
uv run pytest -q
```

## Known limitations

- Tournament presets are fixed stack-depth chip-EV drills, not a full
  tournament lifecycle or an ICM engine.
- The versioned range knowledge base currently covers RFI only. It fails closed
  outside matching format, table-size, stack, ante, position, and node data.
- Derived position mappings do not model card bunching.
- LLM outputs remain probabilistic; deterministic stats, tags, citations,
  thresholds, and evidence labels are kept in code to limit that risk.
- The current five-opportunity leak floor is intentionally permissive and should
  be calibrated further before treating findings as population-grade evidence.
- An in-progress live hand is not recoverable after an app restart or broken
  WebSocket connection.

## Versioning and upstream contribution

The Python package and Git tag use version `0.2.0`, released on 2026-07-29.
Release notes follow [Keep a Changelog](https://keepachangelog.com/) categories
and versions follow semantic versioning.

For an upstream pull request, start with
[docs/UPSTREAM_CHANGES.md](docs/UPSTREAM_CHANGES.md), run the full test suite,
apply every migration to a database copied from the previous schema, and remove
all local credentials and prompt logs from the proposed commit.
