# syntax=docker/dockerfile:1

# uv-provided image pinned to Python 3.11. Includes the `uv` binary.
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

# Keep the venv inside the project and compile bytecode for faster startup.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# All dependencies (including pokerkit) install from PyPI — no vendored source needed.
COPY pyproject.toml uv.lock README.md alembic.ini ./
COPY migrations ./migrations
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project

# Now copy the source and install the project itself.
COPY src ./src
COPY scripts ./scripts
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen

# Default: serve the web app. (Override with a script command to run a CLI game.)
ENV PYTHONPATH=/app/src
CMD ["uvicorn", "poker_trainer.main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "src"]
