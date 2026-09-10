import pytest

from poker_engine.config import GameConfig, SeatKind, SeatSpec
from poker_trainer.game.session import GameSession


def make_session(seed=1, game_format="cash", max_round=2):
    session = GameSession(GameConfig(
        small_blind=50, buy_in=1000, max_round=max_round, game_format=game_format,
        seats=[SeatSpec(name="Hero", kind=SeatKind.HUMAN, email="rebuy@test.local"),
               SeatSpec(name="Bot", kind=SeatKind.ROCK)],
    ), seed=seed)
    # PokerKit shuffles its initial deck too; prescribe the deal rather than
    # depending on the session RNG's seed and the library's initial ordering.
    hole = ["As", "2c", "Ah", "7d"] if seed == 0 else ["2c", "As", "7d", "Ah"]
    order = hole + ["3c", "Ac", "Ks", "Qs", "4c", "Jd", "5c", "9h"]
    session._rng.shuffle = lambda deck: deck.sort(key=lambda card: (order.index(repr(card)) if repr(card) in order else 99, repr(card)))
    session._bot_act = lambda seat, pk: session._apply_action("call", 0, actor_pk=pk)
    return session


def finish_first_hand(session):
    events = session.start()
    while session._hand_num == 1 and not session.finished:
        raise_action = next(a for a in session.pending_ask()["valid_actions"] if a["action"] == "raise")
        maximum = raise_action["amount"]["max"]
        events += session.apply_hero_action("raise" if maximum > 0 else "call", max(0, maximum))
    return events


def test_cash_bot_rebuys_and_profit_excludes_added_capital(db_session):
    session = make_session()
    events = finish_first_hand(session)
    assert not session.finished
    assert session._starting_stacks == [2000, 1000]
    assert session._active_seats == [0, 1]
    first_hand = session.recorder._hands[0]
    assert first_hand.final_stacks[session.seat_uuids[1]] == 0
    rebuy = next(e["rebuys"] for e in events if e.get("rebuys"))
    assert rebuy == [{"uuid": session.seat_uuids[1], "name": "Bot", "amount": 1000}]
    # Finish the second hand by folding, then check both completed-hand totals.
    for _ in range(8):
        if session.finished:
            break
        session.apply_hero_action("fold", 0)
    assert session.finished
    game = session.persist(db_session)
    assert len(game.hands) == 2
    bot = next(p for p in game.players if p.is_bot)
    hero = next(p for p in game.players if not p.is_bot)
    assert bot.total_winnings == bot.final_stack - 2000
    assert hero.total_winnings == hero.final_stack - 1000
    assert bot.total_winnings + hero.total_winnings == 0
    assert sum(p.final_stack for p in game.players) == 3000


@pytest.mark.parametrize("seed,game_format,max_round", [(0, "cash", 2), (1, "tournament", 2), (1, "cash", 1)])
def test_hero_bust_tournament_and_hand_limit_still_end(seed, game_format, max_round):
    session = make_session(seed, game_format, max_round)
    events = finish_first_hand(session)
    assert session.finished
    assert not any(e.get("rebuys") for e in events)
    assert sum(session._stacks) == 2000


@pytest.mark.parametrize("generator", [False, True])
def test_both_deal_paths_restore_only_busted_bots(generator):
    session = make_session()
    session._stacks = [2000, 0]
    if generator:
        gen = session.start_gen()
        events = next(gen)
        gen.close()
    else:
        events = session.start()
    assert session._starting_stacks == [2000, 1000]
    assert any(e.get("rebuys") for e in events)
    assert session._rebuy_busted_bots() == []
