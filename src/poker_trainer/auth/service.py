"""Account linking from OAuth claims."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from poker_engine.db.models import AuthProvider, OAuthIdentity, User


def _now() -> datetime:
    return datetime.now(timezone.utc)


def upsert_user_from_google(session: Session, claims: dict) -> User:
    """Find or create the account for a Google sign-in.

    Resolution order:
      1. an existing ``oauth_identities`` row for (google, sub),
      2. else an existing ``users`` row with the same email (links accounts),
      3. else a brand-new user.
    Updates profile fields from the verified claims and records the login.
    """
    sub = claims["sub"]
    email = claims.get("email")
    name = claims.get("name") or (email.split("@")[0] if email else "Player")
    picture = claims.get("picture")
    email_verified = bool(claims.get("email_verified", False))

    identity = (
        session.query(OAuthIdentity)
        .filter_by(provider=AuthProvider.GOOGLE, provider_user_id=sub)
        .one_or_none()
    )

    if identity is not None:
        user = identity.user
    else:
        user = None
        if email:
            user = session.query(User).filter_by(email=email).one_or_none()
        if user is None:
            user = User(email=email or f"{sub}@google.local", display_name=name)
            session.add(user)
            session.flush()
        identity = OAuthIdentity(
            user_id=user.id,
            provider=AuthProvider.GOOGLE,
            provider_user_id=sub,
            email=email,
        )
        session.add(identity)

    # Refresh profile bits from the provider, without clobbering user edits to
    # display_name once they have set their own (keep it if already customized).
    if not user.avatar_url and picture:
        user.avatar_url = picture
    if email and not user.email_verified:
        user.email_verified = email_verified
    now = _now()
    user.last_login_at = now
    identity.last_login_at = now

    session.commit()
    session.refresh(user)
    return user
