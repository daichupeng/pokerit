# Upstream Change Guide

Release: **v0.2.0** — 2026-07-29

This document is a reviewer-oriented map of the unreleased working-tree changes
relative to `origin/main` at commit `8aac3e3` (`user profile`), inspected on
2026-07-29. It complements the user-facing [README](../README.md) and
[CHANGELOG](../CHANGELOG.md).

## Executive summary

The change set evolves Pokerit from a generic playable table with AI coaching
into a scenario-aware training system. The largest themes are:

1. durable and privacy-correct hand history;
2. separate 6-max/8-max cash and MTT stack-depth contexts;
3. deterministic, versioned statistics and leak decisions;
4. future-clipped, evidence-typed AI game review;
5. rolling history evaluation; and
6. source-audited preflop RFI drills.

The changes are currently one local working tree, not a published release. For
upstream review they should be split into smaller, dependency-ordered pull
requests rather than submitted as one monolithic PR.

## Change map

### 1. Persistence, showdown correctness, and hidden information

Primary code:

- `src/poker_engine/recorder.py`
- `src/poker_trainer/game/session.py`
- `src/poker_trainer/ws.py`
- `src/poker_trainer/game/serialize.py`
- migrations `0013`–`0015`

Behavior:

- Create the persistent game row when a live session starts.
- Flush each completed hand incrementally and recompute game aggregates.
- Record the number of active/non-busted players for every hand.
- Separate “the hand reached showdown” from “these cards were visible.”
- Never persist or send opponent cards retained internally after a fold finish.
- Exclude zero-stack seats from historical showdown reconstruction.

Review focus:

- transaction boundaries and duplicate-hand protection;
- hero identification during incremental flushes;
- all-in showdowns versus fold wins;
- destructive hidden-card cleanup in migrations `0013`/`0014`.

### 2. Scenarios, BB ante, profile scopes, and statistics

Primary code:

- `src/poker_engine/scenarios.py`
- `src/poker_engine/config.py`
- `src/poker_engine/stats.py`
- `src/poker_trainer/api/games.py`
- `src/poker_trainer/api/profile.py`
- migrations `0009`–`0011` and `0015`

Behavior:

- Add 6-max/8-max cash and three 8-max MTT stack-depth presets.
- Support a big-blind ante throughout engine, UI, persistence, and formatting.
- Scope coaching profiles and statistics by scenario/table/stack context.
- Preserve legacy 6-max MTT history rather than reclassifying it as 8-max.
- Segment statistics by active table size and add limp/open-shove/reshove/
  call-off opportunities.
- Store account-wide, versioned bet shortcuts with validated legacy overrides.

Review focus:

- whether scenario keys are stable API/storage identifiers;
- legacy-profile migration semantics;
- BB-ante chip accounting in hand reconstruction;
- table-size denominators when players bust during one game.

### 3. Deterministic leak taxonomy and profile memory

Primary code:

- `src/ai_functions/game_review/leak_taxonomy.py`
- `src/ai_functions/game_review/stat_leaks.py`
- `src/ai_functions/game_review/merge.py`
- `src/ai_functions/memory/`

Behavior:

- Centralize scenario-specific, versioned threshold profiles.
- Keep sample readiness and leak decisions in code, not in LLM output.
- Suppress metrics below their configured opportunity floor.
- Disable postflop stat tags for the 15BB Push/Fold profile.
- Scope long-term fold/rebuild state by scenario and retain correction workflows.
- Handle infinite aggression factor and undefined denominators explicitly.

Current policy note:

- Threshold version: `2026-08-31.v6`.
- Minimum opportunity floor: 5 for most enabled deterministic metrics; VPIP
  leak tags require 50 supported hands.
- Mixed-table-size VPIP uses hands-weighted reference bounds. These remain
  recorded-session signals, not population-grade or player-pool claims.

### 4. Future-clipped game review and evidence discipline

Primary code:

- `src/ai_functions/decision_snapshot.py`
- `src/ai_functions/game_review/street_agent.py`
- `src/ai_functions/game_review/synthesis.py`
- `src/ai_functions/coach_engine/engine.py`

Behavior:

- Build one versioned Decision Snapshot per hero action.
- Exclude all later actions, runout cards, showdown cards, and results.
- Attach deterministic evidence categories and matching RFI range-pack metadata.
- Require structured reviewer findings with a better line and EV explanation.
- Validate report examples against authoritative hand/street citations.
- Prevent model-created tags, severities, citations, threshold decisions, and AF
  arithmetic.
- Make the interactive coach shorter and explicitly scenario-aware.

Review focus:

- future-information clipping at every street/action boundary;
- snapshot pot/stack reconstruction;
- strict validation and retry behavior for incomplete LLM output;
- the boundary between deterministic evidence and model narration.

### 5. Rolling history evaluation

Primary code:

- `src/ai_functions/history_evaluation/`
- `src/poker_trainer/api/history_evaluation.py`
- `src/poker_trainer/worker.py`
- migration `0012`

Behavior:

- Aggregate a scope-isolated rolling window capped at 500 saved hands.
- Compare the selected latest game with a prior baseline excluding that game.
- Compute sample status, directional trends, and leaks deterministically.
- Use at most one optional tool-free LLM call for prose.
- Complete with deterministic output when narration fails.
- Store threshold/model/statistics versions with each report.
- Keep history reports out of the per-game leak occurrence state machine.

Review focus:

- ordering when game timestamps tie;
- latest-game exclusion from the baseline;
- ownership/scope validation;
- idempotency and stuck-job recovery.

### 6. Versioned range knowledge and drills

Primary code:

- `src/ai_functions/preflop_ranges/`
- `src/poker_trainer/api/drills.py`
- migration `0016`

Behavior:

- Add four versioned RFI packs with source URLs and SHA-256 hashes.
- Fail closed outside an exact matching node.
- Mark derived players-behind mappings and the lack of card-bunching modeling.
- Persist ten-question, one-pack drill sessions.
- Hide accepted actions until submission and enforce sequential answers.
- Treat mixed cells as multiple accepted actions without invented frequencies.

Review focus:

- source transcription accuracy and licensing/attribution;
- position mappings for derived packs;
- answer secrecy and user ownership;
- whether source data belongs in code or a generated data artifact.

### 7. Web UI, preferences, models, and development workflow

Primary code:

- `src/poker_trainer/static/`
- `src/poker_trainer/preferences.py`
- `src/shared_services/llm.py`
- `compose.yaml`

Behavior:

- Add scenario selection, drills, rolling reports, scoped profiles, structured
  examples, and account-level bet shortcuts.
- Escape model-authored report text before inserting it into HTML.
- Default coach, review, history narration, and LLM opponents to
  `gpt-5.4-mini`.
- Treat GPT-5 models as reasoning models and keep tool-bearing Chat Completions
  compatible with `reasoning_effort="none"`.
- Auto-reload the development arq worker when mounted source changes.

## Database migration order

| Revision | Dependency | Summary |
| --- | --- | --- |
| `0009_training_scenarios` | `0008_player_profiles` | Scenario fields and composite profile scope |
| `0010_8max_thresholds` | `0009` | Exact new profile keys/defaults |
| `0011_legacy_table_sizes` | `0010` | Restore genuine legacy table-size labels |
| `0012_history_evaluations` | `0011` | Rolling history report storage |
| `0013_fix_showdown_visibility` | `0012` | Showdown backfill and hidden-card removal |
| `0014_exclude_inactive_showdowns` | `0013` | Busted-seat correction |
| `0015_hand_active_players` | `0014` | Active-player count/backfill |
| `0016_drill_sessions` | `0015` | Persisted drill sessions |

Important: the data cleanup in `0013`/`0014` is not reversible because cards
that should never have been stored are deliberately erased.

## Test map

The working tree adds or expands coverage for:

- scenario presets, legacy aliases, BB ante, and profile scopes;
- per-hand stats, active table sizes, limp/shove opportunity accounting, AF,
  and undefined denominators;
- incremental recorder/showdown/card visibility behavior;
- Decision Snapshot clipping and evidence labels;
- street finding validation and synthesis grounding;
- threshold profiles, merge behavior, and profile trend folding;
- rolling history windows, baselines, failure fallback, and APIs;
- preflop range resolution and persisted drills; and
- account preference validation and UI-facing API behavior.

Run:

```bash
docker compose run --rm --no-deps \
  -v "$PWD/tests:/app/tests:ro" \
  app uv run --extra dev pytest -q
```

## Suggested upstream PR sequence

1. **Persistence and showdown correctness**
   - incremental hand persistence;
   - showdown/card-visibility fixes;
   - active-player migration and regression tests.
2. **Scenarios, BB ante, scoped stats, and preferences**
   - scenario storage/API/UI;
   - scoped profile/stat calculations;
   - legacy compatibility migrations.
3. **Deterministic evaluation contracts**
   - versioned thresholds;
   - Decision Snapshots and evidence typing;
   - structured synthesis safeguards.
4. **Rolling history evaluation**
   - schema, deterministic analytics, worker job, API, and UI.
5. **Range packs and decision drills**
   - audited knowledge data, drill persistence/API/UI, and source review.
6. **Documentation and release hardening**
   - README/CHANGELOG;
   - CI, privacy cleanup, model configuration, and release metadata.

Each PR should be independently migratable and tested. If upstream prefers
smaller patches, UI changes can follow their backend contracts in separate PRs.

## Known trade-offs and open decisions

- The five-opportunity leak floor favors early feedback over statistical
  stability and needs product/strategy calibration.
- Default model names are code constants rather than environment settings.
- Live game state remains in memory; only completed hands are durable.
- Tournament scenarios do not model blind progression, payouts, or ICM.
- Range knowledge covers RFI only and two packs use documented derived position
  mappings without card-bunching adjustments.
- Prompt audit logs contain sensitive user/model content and must not be part of
  a public patch.

## Pre-publication blockers

- `logs/prompts.jsonl` is currently tracked and locally modified. Remove it from
  the proposed commit and add an appropriate ignore policy without deleting the
  user's local audit history.
- Confirm that `.env`, credentials, database dumps, notebook outputs, and local
  runtime artifacts are excluded.
- Confirm upstream licensing and RangeConverter attribution/redistribution
  expectations.
- Run the complete test suite and test `alembic upgrade head` against both a
  fresh database and a copy of the previous schema.
- Select a release version only after the final PR scope is known.
