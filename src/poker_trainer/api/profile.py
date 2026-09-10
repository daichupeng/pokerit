"""Profile management: read, update, and delete the current account. Also
hosts the long-term coaching profile's read/reset endpoints (Phase 5+6's
Stage 4) — a distinct concept from the account fields above, sharing this
router's ``/api/profile`` prefix per the feature spec.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from poker_engine import stats
from poker_engine.db.models import AccountStatus, PlayerProfile, User
from poker_engine.scenarios import (
    ACTIVE_PROFILE_SCOPE_LABELS,
    DEFAULT_PROFILE_SCOPE,
    LEGACY_PROFILE_SCOPE_LABELS,
    PROFILE_SCOPE_LABELS,
    profile_scope_label,
)
from poker_trainer.api.auth import serialize_user
from poker_trainer.auth.deps import get_db, require_user
from poker_trainer.preferences import merge_preferences

from ai_functions.memory.persistence import build_profile_context, load_profile_row, rebuild_and_persist

router = APIRouter(prefix="/api/profile", tags=["profile"])

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,40}$")


def _validate_profile_scope(scope: str | None) -> str | None:
    if scope is not None and scope not in PROFILE_SCOPE_LABELS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown training profile scope: {scope}",
        )
    return scope


class ProfileUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=100)
    username: str | None = Field(default=None, max_length=40)
    bio: str | None = Field(default=None, max_length=2000)
    avatar_url: str | None = Field(default=None, max_length=1000)
    country: str | None = Field(default=None, max_length=2)
    timezone: str | None = Field(default=None, max_length=64)
    language: str | None = Field(default=None, max_length=10)
    preferences: dict | None = None


@router.get("")
def get_profile(user: User = Depends(require_user)) -> dict:
    return serialize_user(user)


@router.patch("")
def update_profile(
    body: ProfileUpdate,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    data = body.model_dump(exclude_unset=True)

    if "username" in data and data["username"] is not None:
        uname = data["username"].strip()
        if not _USERNAME_RE.match(uname):
            raise HTTPException(422, "Username must be 3–40 chars: letters, digits, underscore.")
        clash = (
            db.query(User)
            .filter(User.username == uname, User.id != user.id)
            .first()
        )
        if clash is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "That username is taken.")
        data["username"] = uname

    if "display_name" in data and not (data["display_name"] or "").strip():
        raise HTTPException(422, "Display name cannot be empty.")

    if "country" in data and data["country"]:
        data["country"] = data["country"].upper()

    if "preferences" in data and data["preferences"] is not None:
        try:
            data["preferences"] = merge_preferences(user.preferences, data["preferences"])
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    editable = {
        "display_name", "username", "bio", "avatar_url",
        "country", "timezone", "language", "preferences",
    }
    for key, value in data.items():
        if key in editable:
            setattr(user, key, value)

    db.add(user)
    db.commit()
    db.refresh(user)
    return serialize_user(user)


@router.get("/stats")
def profile_stats(
    scope: str | None = Query(default=None),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    """Hero stats, optionally limited to one training profile scope."""
    _validate_profile_scope(scope)
    counts = stats.compute_player_stats(db, user.id, profile_scope=scope)
    return {"scope": scope, "stats": stats.to_display(counts)} if scope else stats.to_display(counts)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    # Soft delete: keep the row (games still reference it) but mark it deleted
    # and free the unique email/username for potential reuse.
    user.status = AccountStatus.DELETED
    user.deleted_at = datetime.now(timezone.utc)
    user.username = None
    db.add(user)
    db.commit()
    request.session.clear()
    return None


@router.get("/coaching")
def get_coaching_profile(
    scope: str = Query(default=DEFAULT_PROFILE_SCOPE),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    """The long-term coaching profile: leak states grouped by status, stat
    trends, playstyle summary, and how many evaluations are folded in.
    """
    _validate_profile_scope(scope)
    row = load_profile_row(db, user.id, scope)
    existing_legacy_scopes = set(
        db.execute(
            select(PlayerProfile.scope_key).where(
            PlayerProfile.user_id == user.id,
            PlayerProfile.scope_key.in_(LEGACY_PROFILE_SCOPE_LABELS),
            )
        )
        .scalars()
        .all()
    )
    visible_labels = {
        **ACTIVE_PROFILE_SCOPE_LABELS,
        **{
            key: label
            for key, label in LEGACY_PROFILE_SCOPE_LABELS.items()
            if key in existing_legacy_scopes
        },
    }
    scope_options = [
        {"key": key, "label": label}
        for key, label in visible_labels.items()
    ]
    if row is None:
        return {
            "scope": scope,
            "scope_label": profile_scope_label(scope),
            "available_scopes": scope_options,
            "evaluations_folded": 0,
            "leaks_by_status": {"flagged": [], "confirmed": [], "resolved": []},
            "trends": {},
            "playstyle_summary": "",
        }

    context = build_profile_context(db, user.id, scope) or {"trends": {}}
    leaks_by_status = {"flagged": [], "confirmed": [], "resolved": []}
    for leak in row.leaks:
        bucket = leaks_by_status.get(leak.get("status"))
        if bucket is not None:
            bucket.append(leak)

    return {
        "scope": scope,
        "scope_label": profile_scope_label(scope),
        "available_scopes": scope_options,
        "evaluations_folded": row.evaluations_folded,
        "leaks_by_status": leaks_by_status,
        "trends": context.get("trends", {}),
        "playstyle_summary": row.playstyle_summary or "",
    }


@router.post("/reset")
async def reset_coaching_profile(
    scope: str = Query(default=DEFAULT_PROFILE_SCOPE),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    """Reset the coaching profile: fold ignores everything completed before
    now, yielding an empty profile until new evaluations complete. Never
    touches any game_evaluations row — this IS the reset mechanism (decision
    1), not a mutation of history.
    """
    _validate_profile_scope(scope)
    reset_at = datetime.now(timezone.utc)
    row = await rebuild_and_persist(
        db, user.id, reset_at=reset_at, scope_key=scope
    )
    return {
        "scope": scope,
        "reset_at": row.reset_at.isoformat(),
        "evaluations_folded": row.evaluations_folded,
    }
