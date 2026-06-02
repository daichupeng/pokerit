"""FastAPI dependencies for DB sessions and the current user."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from poker_engine.db.base import SessionLocal
from poker_engine.db.models import AccountStatus, User

SESSION_USER_KEY = "uid"


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    """The logged-in user from the session cookie, or None."""
    uid = request.session.get(SESSION_USER_KEY)
    if not uid:
        return None
    user = db.get(User, uid)
    if user is None or user.status == AccountStatus.DELETED:
        return None
    return user


def require_user(user: User | None = Depends(current_user)) -> User:
    """Like ``current_user`` but 401s when not authenticated."""
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required.")
    return user
