"""Auth-related settings, read from the environment.

Real Google OAuth credentials live only in the environment (a gitignored
``.env`` / compose env) — never in committed code.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")

# Base URL the app is served from; the OAuth callback is built relative to it.
APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:8000").rstrip("/")

# Secret used to sign the session cookie. A random default is fine for local dev
# but MUST be set to a stable secret in any real deployment.
SESSION_SECRET = os.environ.get("SESSION_SECRET", "dev-insecure-session-secret-change-me")
SESSION_COOKIE = os.environ.get("SESSION_COOKIE", "pt_session")

# Google's OpenID Connect discovery document (authlib reads endpoints from it).
GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"

# Auth is only available when both client id and secret are configured.
AUTH_ENABLED = bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)

# Cookies marked Secure only when serving over https.
SESSION_HTTPS_ONLY = APP_BASE_URL.startswith("https://")
