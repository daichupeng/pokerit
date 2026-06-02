"""Play a poker game (human vs bots) and record it to the database.

Usage:
  uv run python scripts/play_game.py            # human vs 3 bots (console)
  uv run python scripts/play_game.py --auto     # all bots, no stdin (for CI/Docker)
  uv run python scripts/play_game.py --auto --rounds 30 --seed 7
"""

from __future__ import annotations

import argparse

from poker_engine.config import GameConfig, SeatKind, SeatSpec
from poker_engine.engine import GameEngine


def build_config(auto: bool, rounds: int) -> GameConfig:
    # Hero seat: a human in interactive mode, a TAG bot in --auto mode so the
    # game still records a perspective without needing stdin.
    hero = SeatSpec(
        name="you",
        kind=SeatKind.TAG if auto else SeatKind.HUMAN,
        email="you@local.poker",
    )
    seats = [
        hero,
        SeatSpec(name="tag_bot", kind=SeatKind.TAG),
        SeatSpec(name="lag_bot", kind=SeatKind.LAG),
        SeatSpec(name="station_bot", kind=SeatKind.STATION),
    ]
    return GameConfig(
        small_blind=5,  # big blind is derived as 10
        buy_in=100,
        seats=seats,
        max_round=rounds,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Play and record a poker game.")
    parser.add_argument("--auto", action="store_true", help="all-bot run, no stdin")
    parser.add_argument("--rounds", type=int, default=20, help="number of hands")
    parser.add_argument("--seed", type=int, default=None, help="rng seed for bots")
    parser.add_argument("--no-record", action="store_true", help="skip DB recording")
    args = parser.parse_args()

    config = build_config(auto=args.auto, rounds=args.rounds)
    # In --auto mode there is no human seat, so record from seat 0 (the hero).
    hero_index = 0 if args.auto else None

    engine = GameEngine(config, seed=args.seed, hero_index=hero_index)
    result = engine.run(record=not args.no_record)

    print("\n=== Final stacks ===")
    for p in result.players:
        print(f"{p['name']:>12}: {p['stack']}")
    if result.game_id is not None:
        print(f"\nRecorded game_id: {result.game_id}")


if __name__ == "__main__":
    main()
