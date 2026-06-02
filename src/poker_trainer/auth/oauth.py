"""Authlib OAuth registry, configured for Google via OpenID Connect."""

from __future__ import annotations

from authlib.integrations.starlette_client import OAuth

from poker_trainer.auth import config

oauth = OAuth()

if config.AUTH_ENABLED:
    oauth.register(
        name="google",
        client_id=config.GOOGLE_CLIENT_ID,
        client_secret=config.GOOGLE_CLIENT_SECRET,
        server_metadata_url=config.GOOGLE_DISCOVERY_URL,
        client_kwargs={"scope": "openid email profile"},
    )
