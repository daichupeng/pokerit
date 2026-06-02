# syntax=docker/dockerfile:1

# uv-provided image pinned to Python 3.11. Includes the `uv` binary.
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

# PyPokerEngine is installed from a git source, so git must be present.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Keep the venv inside the project and compile bytecode for faster startup.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# The vendored, patched PyPokerEngine is an editable path dependency, so it must
# be present before `uv sync` resolves it.
COPY pyproject.toml uv.lock README.md ./
COPY vendor ./vendor
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Now copy the source and install the project itself.
COPY src ./src
COPY scripts ./scripts
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Default: run the bot-vs-bot smoke test. The webapp will override this
# (e.g. `uvicorn poker_trainer.main:app`) once it exists.
CMD ["python", "scripts/play_bots.py"]
