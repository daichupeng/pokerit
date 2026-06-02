"""Login stub.

No real authentication yet — this returns a lightweight dev user so the
frontend can carry an identity and the journey has a login step. The DB already
has ``users.password_hash`` for when real auth is wired in.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["auth"])


class LoginRequest(BaseModel):
    display_name: str | None = None
    email: str | None = None


class LoginResponse(BaseModel):
    display_name: str
    email: str
    token: str  # placeholder; not a real session token yet


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest) -> LoginResponse:
    name = (body.display_name or "Guest").strip() or "Guest"
    email = (body.email or f"{name.lower().replace(' ', '_')}@local.poker").strip()
    # Placeholder token; replace with a signed session once auth is implemented.
    return LoginResponse(display_name=name, email=email, token="dev-token")
