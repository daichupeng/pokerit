from ai_functions.decision_snapshot import build_decision_snapshots
from ai_functions.game_review.preflop_findings import detect_rfi_limp_findings
from poker_engine.db.models import Action, Game, GamePlayer, Hand, HandPlayer, Street, User


def test_late_position_rfi_limp_uses_range_pack_after_prior_folds(db_session):
    user = User(email="rfi-limp@test.local", display_name="Hero")
    db_session.add(user)
    db_session.flush()
    game = Game(
        small_blind=50, big_blind=100, buy_in=10000, max_round=50,
        hero_user_id=user.id, game_format="cash", scenario="cash_6max_100bb",
        ante_type="none", profile_scope="cash_6max_100bb",
    )
    db_session.add(game)
    db_session.flush()
    hero = GamePlayer(
        game_id=game.id, seat_index=0, display_name="Hero", engine_uuid="hero",
        user_id=user.id, is_bot=False, starting_stack=10000,
    )
    prior = GamePlayer(
        game_id=game.id, seat_index=1, display_name="Prior", engine_uuid="prior",
        is_bot=True, starting_stack=10000,
    )
    blind = GamePlayer(
        game_id=game.id, seat_index=2, display_name="Blind", engine_uuid="blind",
        is_bot=True, starting_stack=10000,
    )
    db_session.add_all([hero, prior, blind])
    db_session.flush()
    hand = Hand(
        game_id=game.id, round_count=50, active_player_count=6,
        street_reached=Street.PREFLOP, board=[], pot_total=200, had_showdown=False,
    )
    db_session.add(hand)
    db_session.flush()
    db_session.add_all([
        HandPlayer(
            hand_id=hand.id, game_player_id=hero.id, position="CO",
            hole_cards=["Ah", "5c"], starting_stack=10000,
        ),
        HandPlayer(
            hand_id=hand.id, game_player_id=prior.id, position="HJ",
            starting_stack=10000,
        ),
        HandPlayer(
            hand_id=hand.id, game_player_id=blind.id, position="BB",
            starting_stack=10000,
        ),
        Action(
            hand_id=hand.id, game_player_id=prior.id, street=Street.PREFLOP,
            action="fold", amount=0, seq=0, stack_after=10000,
        ),
        Action(
            hand_id=hand.id, game_player_id=hero.id, street=Street.PREFLOP,
            action="call", amount=100, seq=1, stack_after=9900,
        ),
        Action(
            hand_id=hand.id, game_player_id=blind.id, street=Street.PREFLOP,
            action="call", amount=0, seq=2, stack_after=9900,
        ),
    ])
    db_session.flush()

    snapshot = build_decision_snapshots(game, hand, hero.id, "preflop")[0]
    range_source = next(
        source for source in snapshot["evidence_sources"]
        if source["type"] == "range_knowledge_base"
    )
    findings = detect_rfi_limp_findings(game, [hand], hero.id)

    assert set(range_source["acceptable_actions"]) == {"raise", "fold"}
    assert findings[0]["tag"] == "missed_open_raise"
    assert findings[0]["round_count"] == 50
    assert findings[0]["confidence"] == "medium"
