from __future__ import annotations

import pytest
from pydantic import ValidationError

from poker_trainer.api.games import CreateGameRequest


def test_new_games_default_to_50_hands_and_allow_up_to_100():
    assert CreateGameRequest().max_round == 50
    assert CreateGameRequest(max_round=100).max_round == 100

    with pytest.raises(ValidationError):
        CreateGameRequest(max_round=101)
