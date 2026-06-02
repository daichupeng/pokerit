"""Profile management: read, update, and delete the current account."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from poker_engine.db.models import AccountStatus, User
from poker_trainer.api.auth import serialize_user
from poker_trainer.auth.deps import get_db, require_user

router = APIRouter(prefix="/api/profile", tags=["profile"])

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,40}$")


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
