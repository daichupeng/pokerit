"""Thin wrapper around the OpenAI SDK.

Provides a single AsyncOpenAI client shared across the process and a helper
that streams a chat completion while accumulating token usage.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from openai import AsyncOpenAI

_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
    return _client


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


async def stream_chat(
    messages: list[dict],
    model: str = "gpt-4o-mini",
    max_tokens: int = 4096,
    temperature: float = 0.7,
) -> AsyncIterator[str]:
    """Yield text chunks from a streaming chat completion.

    Usage is read from the final chunk when stream_options include_usage=True.
    Callers that need token counts should use stream_chat_with_usage instead.
    """
    client = get_client()
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
            yield delta


async def stream_chat_with_usage(
    messages: list[dict],
    model: str = "gpt-4o-mini",
    max_tokens: int = 4096,
    temperature: float = 0.7,
) -> AsyncIterator[str | TokenUsage]:
    """Like stream_chat but yields TokenUsage as the final item."""
    client = get_client()
    usage = TokenUsage()
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
            yield delta
        if chunk.usage:
            usage.update(chunk.usage)
    yield usage
