"""Logging configuration for the Poker Trainer service.

Configures two handlers:
  - stderr (human-readable in development, JSON in production)
  - rotating JSON-line file at LOG_DIR/prompts.jsonl  (prompt audit trail)

Environment variables:
  LOG_LEVEL   — root log level (default: INFO)
  LOG_DIR     — directory for log files (default: logs/)
  LOG_JSON    — set to "1" to force JSON on stderr (auto-enabled when LOG_DIR
                points outside the repo, i.e. in production)

Rotation: 50 MB per file, 10 backups → ≤ 500 MB disk at any time.
Each backup is named prompts.jsonl.1 … prompts.jsonl.10 (oldest removed).
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
import time
from pathlib import Path


# ---------------------------------------------------------------------------
# JSON formatter — one compact JSON object per line, machine-parseable
# ---------------------------------------------------------------------------

class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        obj: dict = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            obj["exc"] = self.formatException(record.exc_info)
        # Extra fields injected via logger.info("…", extra={…})
        skip = logging.LogRecord.__dict__.keys() | {
            "message", "asctime", "msg", "args", "exc_info", "exc_text", "stack_info",
        }
        for k, v in record.__dict__.items():
            if k not in skip and not k.startswith("_"):
                obj[k] = v
        return json.dumps(obj, default=str)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

_configured = False


def configure_logging() -> None:
    """Call once at application startup. Idempotent — safe on hot-reload."""
    global _configured
    if _configured:
        return
    _configured = True

    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    log_dir = Path(os.environ.get("LOG_DIR", "logs"))
    force_json = os.environ.get("LOG_JSON", "0") == "1"

    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(log_level)

    # --- stderr handler ---
    stderr_handler = logging.StreamHandler(sys.stderr)
    if force_json:
        stderr_handler.setFormatter(_JsonFormatter())
    else:
        stderr_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-8s %(name)s  %(message)s")
        )
    root.addHandler(stderr_handler)

    # --- rotating JSON-line file for prompt audit trail ---
    prompt_file = log_dir / "prompts.jsonl"
    file_handler = logging.handlers.RotatingFileHandler(
        prompt_file,
        maxBytes=50 * 1024 * 1024,  # 50 MB
        backupCount=10,
        encoding="utf-8",
    )
    file_handler.setFormatter(_JsonFormatter())
    # Only the "prompts" logger writes to this file.
    file_handler.addFilter(lambda r: r.name == "prompts")
    root.addHandler(file_handler)

    logging.getLogger("prompts").setLevel(logging.DEBUG)
