# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.2.0] - 2026-07-29

### Highlights

- Expanded Pokerit from one generic table configuration into scenario-aware
  cash and tournament training with isolated statistics and coaching profiles.
- Made completed hands durable during live sessions and corrected showdown/card
  visibility so saved history reflects only information available to the hero.
- Reworked AI evaluation around future-clipped Decision Snapshots, deterministic
  leak decisions, typed evidence, and structured hand-level explanations.
- Added rolling 500-hand history evaluation and source-audited preflop boundary
  drills.

### Added

- Added fixed-level scenario presets for 6-max/8-max 100BB cash and 8-max MTT
  at 40BB, 25BB, and 15BB, plus custom mode.
- Added big-blind ante support throughout engine configuration, serialization,
  hand formatting, persistence, APIs, UI, and coaching context.
- Added stable scenario/profile scope keys so unlike formats, table sizes, and
  stack depths do not share one coaching profile.
- Added backward-compatible scenario aliases and legacy profile visibility.
- Added per-hand `active_player_count` storage and statistics segmented by live
  table size.
- Added limp, open-shove, reshove, and call-off opportunity statistics.
- Added incremental game persistence: the game row is created at session start
  and every completed hand is flushed without waiting for the full game to end.
- Added versioned Decision Snapshots clipped at each hero action.
- Added typed evidence sources for recorded engine state, deterministic math,
  configured bot metadata, range packs, heuristic inference, user reads, and
  solver nodes.
- Added four versioned RFI range packs: 6-max/8-max cash at 100BB and 6-max/8-max
  MTT at 40BB with a BB ante, including source URLs, hashes, mappings, and
  derivation notes.
- Added persisted ten-question preflop boundary drills with hidden answers,
  sequential submission, mixed-action support, scoring, and source attribution.
- Added scope-isolated rolling history evaluations over up to 500 saved hands.
- Added deterministic latest-game versus prior-500-hand trend comparisons.
- Added tool-free optional history narration with a deterministic fallback when
  the LLM call fails.
- Added account-level, versioned preflop and postflop quick-bet preferences.
- Added UI screens for scenarios, decision drills, game history, scoped coaching
  profiles, structured evaluation examples, and rolling history reports.
- Added regression tests for scenarios, stats, Decision Snapshots, range packs,
  history evaluation, drills, showdown detection, and preference validation.

### Changed

- Changed the interactive coach, game-review pipeline, history narrator, and LLM
  opponent defaults to `gpt-5.4-mini`.
- Rewrote coach prompts to lead with the decision, remove filler, respect
  scenario context, and avoid invented solver frequencies, reads, or ICM.
- Changed street review from complete-hand input to point-in-time Decision
  Snapshots so future information cannot influence the reviewed decision.
- Changed judgment findings from a free-form note to structured fields for the
  actual action, issue, better line, EV rationale, future plan, and confidence.
- Changed report synthesis to preserve deterministic tags, severity, citations,
  sample status, and evidence labels while grounding examples in validated
  street findings.
- Centralized scenario-specific leak thresholds and versioned them; the current
  development threshold version is `2026-07-23.v3`.
- Set the current deterministic sample floor to five relevant opportunities and
  suppress statistical leak conclusions below that floor.
- Changed the 15BB Push/Fold profile to emphasize open-shove, reshove, and
  call-off decisions rather than postflop aggression/C-bet leak tags.
- Made aggression-factor wording deterministic and fixed its definition to
  `(postflop bets + raises) / postflop calls`.
- Made undefined statistics explicit instead of treating a zero denominator as
  a successful or failed `0%` observation.
- Changed quick-bet shortcuts from create-game UI state to validated account
  preferences while retaining legacy per-game API overrides.
- Changed the development arq worker to watch mounted source and resume stuck
  single-game and history evaluations after restart.
- Expanded APIs and hand/table serializers with scenario, ante, table-size,
  stack, and action-level pot/stack context.

### Fixed

- Fixed fold winners being misclassified as showdowns because PokerKit retained
  their cards internally.
- Fixed opponent hole cards being persisted when they were not actually revealed
  to the hero.
- Fixed zero-stack/busted seats being counted as live showdown participants.
- Fixed historical table-size reconstruction by storing the active player count
  on each hand and backfilling existing hands.
- Fixed legacy 6-max MTT history being incorrectly relabeled or folded into new
  8-max coaching scopes.
- Fixed profile rebuild/fold logic so corrections and trends remain isolated by
  scenario scope.
- Fixed history baselines so the selected latest game is excluded even when
  database timestamps tie.
- Fixed GPT-5 reasoning-model requests to omit unsupported temperature values and
  disable non-zero reasoning effort for tool-bearing Chat Completions calls.
- Fixed model-authored aggression arithmetic by replacing it with code-generated
  evidence wording.
- Fixed report rendering of model text by escaping dynamic HTML content.

### Security and privacy

- Enforced hero-perspective card visibility through engine recording, database
  backfill, API responses, and browser serialization.
- Removed hidden opponent hole cards during showdown-correction migrations; this
  cleanup is intentionally not reversible.
- Added clearer evidence labels so configured bot styles cannot be represented as
  solver proof or observed population data.

### Database migrations

Upgrading an existing installation requires:

```bash
docker compose exec app uv run alembic upgrade head
```

| Migration | Purpose |
| --- | --- |
| `0009_training_scenarios` | Add scenario metadata and scoped player profiles |
| `0010_8max_thresholds` | Introduce exact 6-max/8-max scenario/profile keys |
| `0011_legacy_table_sizes` | Preserve true historical table-size labels |
| `0012_history_evaluations` | Add rolling history evaluation snapshots |
| `0013_fix_showdown_visibility` | Correct showdown facts and remove hidden cards |
| `0014_exclude_inactive_showdowns` | Exclude busted seats from showdowns |
| `0015_hand_active_players` | Store/backfill active players per hand |
| `0016_drill_sessions` | Persist preflop drill sessions |

Migrations `0013` and `0014` intentionally delete opponent cards that should
never have been visible. A downgrade cannot reconstruct those cards.

### Compatibility

- Existing completed games, hands, conversations, and reports are retained.
- Legacy scenario keys remain readable.
- Legacy combined MTT profiles remain visible instead of being guessed into a
  new table-size scope.
- Existing API clients may continue sending per-game quick-bet overrides.
- Live sessions remain in memory; the hand currently in progress cannot be
  resumed after an app restart or broken WebSocket.

### Release checklist

- Run the full test suite and apply all migrations to a copy of a pre-change
  database.
- Remove `.env`, credentials, database dumps, and unsanitized prompt logs from
  the proposed commit.
- Confirm the tag, attribution, and upstream PR scope.

[Unreleased]: https://github.com/Sprittte/pokerit/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/Sprittte/pokerit/releases/tag/v0.2.0
