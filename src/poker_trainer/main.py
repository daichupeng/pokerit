"""FastAPI application: REST setup endpoints, WebSocket play, and the SPA."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from poker_trainer.api import auth, games
from poker_trainer.ws import router as ws_router

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Poker Trainer")

app.include_router(auth.router)
app.include_router(games.router)
app.include_router(ws_router)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


# Serve the single-page app. Static assets live under /static; the SPA shell is
# returned for the root so the client-side hash router can take over.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
