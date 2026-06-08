"""Thin wrapper around the OpenAI SDK.

Provides a single AsyncOpenAI client shared across the process and a helper
that streams a chat completion while accumulating token usage.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from openai import AsyncOpenAI

_client: AsyncOpenAI | None = None
_minimax_client: AsyncOpenAI | None = None
_prompt_log = logging.getLogger("prompts")

MINIMAX_BASE_URL = "https://api.minimaxi.chat/v1"


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
    return _client


def get_minimax_client() -> AsyncOpenAI:
    global _minimax_client
    if _minimax_client is None:
        api_key = os.environ.get("MINIMAX_API_KEY")
        if not api_key:
            raise RuntimeError("MINIMAX_API_KEY is not set")
        _minimax_client = AsyncOpenAI(api_key=api_key, base_url=MINIMAX_BASE_URL)
    return _minimax_client


def _is_minimax_model(model: str) -> bool:
    return model.strip().lower().startswith("minimax")


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def update(self, usage) -> None:
        if usage:
            self.prompt_tokens += usage.prompt_tokens or 0
            self.completion_tokens += usage.completion_tokens or 0


@dataclass
class StreamResult:
    """Holds the accumulated text and token usage from a streaming call."""
    text: str = ""
    usage: TokenUsage = field(default_factory=TokenUsage)


async def _stream_openai_chat_with_usage(
    messages: list[dict],
    model: str,
    max_tokens: int,
    temperature: float,
    log_context: dict | None = None,
    reasoning_effort: str = "low",
) -> AsyncIterator[str | TokenUsage]:
    call_id = str(uuid.uuid4())
    t_start = time.monotonic()

    client = get_client()
    usage = TokenUsage()
    full_text: list[str] = []

    try:
        stream = await client.chat.completions.create(
            model=model,
            messages=messages,
            max_completion_tokens=max_tokens,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
            stream=True,
            stream_options={"include_usage": True},
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                full_text.append(delta)
                yield delta
            if chunk.usage:
                usage.update(chunk.usage)
        status = "ok"
    except Exception as exc:
        status = f"error:{type(exc).__name__}"
        raise
    finally:
        latency_ms = round((time.monotonic() - t_start) * 1000)
        _prompt_log.info(
            "llm_call",
            extra={
                "call_id": call_id,
                "status": status,
                "backend": "openai",
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "latency_ms": latency_ms,
                "messages": messages,
                "response": "".join(full_text),
                **(log_context or {}),
            },
        )

    yield usage


async def _stream_minimax_with_usage(
    messages: list[dict],
    model: str,
    max_tokens: int,
    temperature: float,
    log_context: dict | None = None,
) -> AsyncIterator[str | TokenUsage]:
    call_id = str(uuid.uuid4())
    t_start = time.monotonic()

    client = get_minimax_client()
    usage = TokenUsage()
    full_text: list[str] = []
    status = "ok"

    try:
        stream = await client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
            stream_options={"include_usage": True},
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                full_text.append(delta)
                yield delta
            if chunk.usage:
                usage.update(chunk.usage)
    except Exception as exc:
        status = f"error:{type(exc).__name__}"
        raise
    finally:
        latency_ms = round((time.monotonic() - t_start) * 1000)
        _prompt_log.info(
            "llm_call",
            extra={
                "call_id": call_id,
                "status": status,
                "backend": "minimax",
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "latency_ms": latency_ms,
                "messages": messages,
                "response": "".join(full_text),
                **(log_context or {}),
            },
        )

    yield usage


async def stream_model_with_usage(
    messages: list[dict],
    model: str = "MiniMax-M2.7",
    max_tokens: int = 4096,
    temperature: float = 0.7,
    # Optional caller-supplied context included verbatim in the log record.
    # Typical keys: user_id, conversation_id, game_id.
    log_context: dict | None = None,
    reasoning_effort: str = "low",
) -> AsyncIterator[str | TokenUsage]:
    """Yield text chunks from a streaming model backend, then yield TokenUsage as the final item."""
    if _is_minimax_model(model):
        async for chunk in _stream_minimax_with_usage(
            messages,
            model=model,
            max_tokens=10240,
            temperature=temperature,
            log_context=log_context,
        ):
            yield chunk
    else:
        async for chunk in _stream_openai_chat_with_usage(
            messages,
            model=model,
            max_tokens=4096,
            temperature=temperature,
            log_context=log_context,
            reasoning_effort=reasoning_effort,
        ):
            yield chunk


# Keep the existing name for backward compatibility.
stream_chat_with_usage = stream_model_with_usage
