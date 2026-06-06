"""Bot-vs-bot game to verify the PokerKit integration works.

Runs a short heads-up no-limit hold'em match between two StyleBots and
prints the final stacks.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from poker_engine.config import GameConfig, SeatKind, SeatSpec
from poker_engine.engine import GameEngine


def main() -> None:
    config = GameConfig(
        small_blind=5,
        buy_in=100,
        seats=[
            SeatSpec(name="caller", kind=SeatKind.STATION),
            SeatSpec(name="folder", kind=SeatKind.ROCK),
        ],
        max_round=10,
    )
    engine = GameEngine(config, hero_index=0, seed=42)
    result = engine.run(record=False)

    print("\n=== Final result ===")
    for player in result.players:
        print(f"{player['name']:>8}: stack={player['stack']}")


if __name__ == "__main__":
    main()
