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
_ollama_client: AsyncOpenAI | None = None
_prompt_log = logging.getLogger("prompts")

MINIMAX_BASE_URL = "https://api.minimaxi.chat/v1"
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")


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


def get_ollama_client() -> AsyncOpenAI:
    global _ollama_client
    if _ollama_client is None:
        _ollama_client = AsyncOpenAI(api_key="ollama", base_url=f"{OLLAMA_BASE_URL}/v1")
    return _ollama_client


def _is_minimax_model(model: str) -> bool:
    return model.strip().lower().startswith("minimax")


def _is_ollama_model(model: str) -> bool:
    return model.strip().lower().startswith(("qwen", "llama", "mistral", "ollama"))


def _is_reasoning_model(model: str) -> bool:
    """o-series and newer thinking models that accept reasoning_effort but not temperature."""
    m = model.strip().lower()
    return m.startswith("o") or "thinking" in m


def _supports_temperature(model: str) -> bool:
    """Some reasoning/thinking models reject a temperature parameter."""
    return not _is_reasoning_model(model)


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
        extra = {"reasoning_effort": reasoning_effort} if _is_reasoning_model(model) else {}
        if _supports_temperature(model):
            extra["temperature"] = temperature
        stream = await client.chat.completions.create(
            model=model,
            messages=messages,
            max_completion_tokens=max_tokens,
            stream=True,
            stream_options={"include_usage": True},
            **extra,
        )
        truncated = False
        async for chunk in stream:
            if chunk.choices:
                delta = chunk.choices[0].delta.content
                if delta:
                    full_text.append(delta)
                    yield delta
                if chunk.choices[0].finish_reason == "length":
                    truncated = True
            if chunk.usage:
                usage.update(chunk.usage)
        status = "ok"
        if truncated:
            raise RuntimeError("Output exceeds token limit")
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


async def _stream_ollama_with_usage(
    messages: list[dict],
    model: str,
    max_tokens: int,
    temperature: float,
    log_context: dict | None = None,
) -> AsyncIterator[str | TokenUsage]:
    call_id = str(uuid.uuid4())
    t_start = time.monotonic()

    client = get_ollama_client()
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
                "backend": "ollama",
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
    elif _is_ollama_model(model):
        async for chunk in _stream_ollama_with_usage(
            messages,
            model=model,
            max_tokens=max_tokens,
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


async def chat_model_with_usage(
    messages: list[dict],
    model: str = "MiniMax-M2.7",
    max_tokens: int = 4096,
    temperature: float = 0.7,
    log_context: dict | None = None,
    reasoning_effort: str = "low",
) -> StreamResult:
    """Return a completed chat response and token usage without streaming."""
    call_id = str(uuid.uuid4())
    t_start = time.monotonic()

    if _is_minimax_model(model):
        client = get_minimax_client()
        backend = "minimax"
    elif _is_ollama_model(model):
        client = get_ollama_client()
        backend = "ollama"
    else:
        client = get_client()
        backend = "openai"
    usage = TokenUsage()
    text = ""
    status = "ok"

    try:
        if _is_minimax_model(model):
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=False,
            )
        elif _is_ollama_model(model):
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=False,
            )
        else:
            extra = {"reasoning_effort": reasoning_effort} if _is_reasoning_model(model) else {}
            if _supports_temperature(model):
                extra["temperature"] = temperature
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                max_completion_tokens=max_tokens,
                stream=False,
                **extra,
            )

        if response.choices:
            text = response.choices[0].message.content or ""
        else:
            text = ""

        if getattr(response, "usage", None):
            usage.update(response.usage)
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
                "backend": backend,
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "latency_ms": latency_ms,
                "messages": messages,
                "response": text,
                **(log_context or {}),
            },
        )

    return StreamResult(text=text, usage=usage)


async def chat_model(
    messages: list[dict],
    model: str = "MiniMax-M2.7",
    max_tokens: int = 4096,
    temperature: float = 0.7,
    log_context: dict | None = None,
    reasoning_effort: str = "low",
) -> str:
    """Return the full chat completion text without streaming."""
    result = await chat_model_with_usage(
        messages=messages,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        log_context=log_context,
        reasoning_effort=reasoning_effort,
    )
    return result.text


# Keep the existing name for backward compatibility.
stream_chat_with_usage = stream_model_with_usage
