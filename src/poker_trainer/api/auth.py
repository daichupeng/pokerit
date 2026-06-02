"""Authentication endpoints: Google OAuth login, logout, and the current user."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from poker_engine.db.models import User
from poker_trainer.auth import config
from poker_trainer.auth.deps import SESSION_USER_KEY, current_user, get_db
from poker_trainer.auth.oauth import oauth
from poker_trainer.auth.service import upsert_user_from_google

router = APIRouter(prefix="/api/auth", tags=["auth"])


def serialize_user(user: User) -> dict:
    """Public profile shape returned to the SPA."""
    return {
        "id": str(user.id),
        "email": user.email,
        "email_verified": user.email_verified,
        "username": user.username,
        "display_name": user.display_name,
        "avatar_url": user.avatar_url,
        "bio": user.bio,
        "country": user.country,
        "timezone": user.timezone,
        "language": user.language,
        "preferences": user.preferences or {},
        "status": user.status.value,
        "role": user.role.value,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
    }


@router.get("/google/login")
async def google_login(request: Request):
    if not config.AUTH_ENABLED:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Google sign-in is not configured (set GOOGLE_CLIENT_ID/SECRET).",
        )
    redirect_uri = f"{config.APP_BASE_URL}/api/auth/google/callback"
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/google/callback")
async def google_callback(request: Request, db: Session = Depends(get_db)):
    if not config.AUTH_ENABLED:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Google sign-in is not configured.")
    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception as exc:  # invalid state, denied consent, etc.
        # Bounce back to the SPA with an error flag rather than a raw 500.
        return RedirectResponse(url=f"/#/login?error=oauth&detail={type(exc).__name__}")

    claims = token.get("userinfo")
    if not claims:
        claims = await oauth.google.userinfo(token=token)

    user = upsert_user_from_google(db, dict(claims))
    request.session[SESSION_USER_KEY] = str(user.id)
    return RedirectResponse(url="/#/")


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request):
    request.session.clear()
    return None


@router.get("/me")
def me(user: User | None = Depends(current_user)):
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated.")
    return serialize_user(user)


@router.get("/config")
def auth_config():
    """Lets the SPA know whether Google sign-in is available."""
    return {"google_enabled": config.AUTH_ENABLED}
