"""Focused, persisted preflop boundary drills backed by versioned charts."""

from __future__ import annotations

import random
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ai_functions.preflop_ranges import get_range_pack, list_range_packs
from ai_functions.preflop_ranges.knowledge import ALL_HANDS
from poker_engine.db.models import DrillSession, User
from poker_trainer.auth.deps import get_db, require_user

router = APIRouter(prefix="/api/drills", tags=["drills"])
QUESTION_COUNT = 10
VALID_ACTIONS = frozenset({"fold", "limp", "raise"})


class StartDrillRequest(BaseModel):
    pack_id: str


class AnswerRequest(BaseModel):
    question_index: int
    action: str


def _load_owned(db: Session, session_id: str, user: User) -> DrillSession:
    try:
        row = db.get(DrillSession, session_id)
    except Exception:
        row = None
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "Drill session not found.")
    return row


def _question_public(question: dict) -> dict:
    return {
        "index": question["index"],
        "position": question["position"],
        "hand": question["hand"],
        "node": "RFI",
        "prompt": "Action folds to you. What is your range action?",
    }


def _serialize(row: DrillSession, *, include_question: bool = True) -> dict:
    completed = row.next_index >= len(row.questions)
    current = None
    if include_question and not completed:
        current = _question_public(row.questions[row.next_index])
    return {
        "session_id": str(row.id),
        "pack_id": row.pack_id,
        "pack_version": row.pack_version,
        "question_count": len(row.questions),
        "next_index": row.next_index,
        "correct_count": row.correct_count,
        "completed": completed,
        "current_question": current,
    }


def _build_questions(pack) -> list[dict]:
    mixed: list[tuple[str, str]] = []
    pure: list[tuple[str, str]] = []
    for position in pack.positions:
        for hand in sorted(ALL_HANDS):
            decision = pack.decision(position, hand)
            if decision is None:
                continue
            target = mixed if decision.mixed else pure
            target.append((position, hand))

    # Keep every session within one tightly controlled pack/node. Prefer five
    # chart boundaries and five unambiguous controls so the score remains
    # interpretable rather than becoming a test of random full-game noise.
    rng = random.SystemRandom()
    selected = rng.sample(mixed, min(5, len(mixed)))
    selected += rng.sample(pure, QUESTION_COUNT - len(selected))
    rng.shuffle(selected)
    questions = []
    for index, (position, hand) in enumerate(selected):
        decision = pack.decision(position, hand)
        questions.append({
            "index": index,
            "position": position,
            "hand": hand,
            "accepted_actions": list(decision.actions),
            "mixed": decision.mixed,
        })
    return questions


@router.get("/modes")
def drill_modes(user: User = Depends(require_user)) -> list[dict]:
    del user
    return list_range_packs()


@router.post("/sessions")
def start_drill(
    body: StartDrillRequest,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    pack = get_range_pack(body.pack_id)
    if pack is None:
        raise HTTPException(422, "Unknown drill mode.")
    row = DrillSession(
        user_id=user.id,
        pack_id=pack.id,
        pack_version=pack.version,
        questions=_build_questions(pack),
        answers=[],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _serialize(row)


@router.get("/sessions/{session_id}")
def get_drill(
    session_id: str,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    return _serialize(_load_owned(db, session_id, user))


@router.post("/sessions/{session_id}/answers")
def answer_drill(
    session_id: str,
    body: AnswerRequest,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    row = _load_owned(db, session_id, user)
    if row.completed_at is not None or row.next_index >= len(row.questions):
        raise HTTPException(409, "This drill is already complete.")
    if body.question_index != row.next_index:
        raise HTTPException(409, "Answer the current question before continuing.")
    action = body.action.lower()
    if action not in VALID_ACTIONS:
        raise HTTPException(422, "Action must be fold, limp, or raise.")

    question = row.questions[row.next_index]
    accepted = question["accepted_actions"]
    correct = action in accepted
    answers = list(row.answers or [])
    answers.append({"question_index": row.next_index, "action": action, "correct": correct})
    row.answers = answers
    row.next_index += 1
    if correct:
        row.correct_count += 1
    if row.next_index >= len(row.questions):
        row.completed_at = datetime.now(timezone.utc)
    db.add(row)
    db.commit()
    db.refresh(row)

    pack = get_range_pack(row.pack_id)
    evidence = pack.decision(question["position"], question["hand"]).evidence_source
    return {
        "correct": correct,
        "accepted_actions": accepted,
        "mixed": question["mixed"],
        "explanation": (
            f"Source chart mixes {' / '.join(accepted)} for {question['hand']} at {question['position']}."
            if question["mixed"] else
            f"Source chart action: {accepted[0]} for {question['hand']} at {question['position']}."
        ),
        "evidence_source": evidence,
        "session": _serialize(row),
    }
