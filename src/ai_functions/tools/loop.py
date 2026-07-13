"""Tool-calling orchestration loop: request -> tool_call -> execute -> repeat.

OpenAI-only, non-streaming-only, by design (see feature request 71202) — this
wraps ``shared_services.llm.chat_model_with_usage``, which only honors
``tools=`` on its OpenAI branch.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Callable

from shared_services.llm import (
    TokenUsage,
    _is_minimax_model,
    _is_ollama_model,
    chat_model_with_usage,
)

_prompt_log = logging.getLogger("prompts")

DEFAULT_MAX_ROUND_TRIPS = 4


@dataclass
class ToolCallRecord:
    name: str
    arguments: dict
    result: object
    latency_ms: int


@dataclass
class ToolLoopResult:
    final_text: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    usage: TokenUsage = field(default_factory=TokenUsage)


def _assert_openai_model(model: str) -> None:
    if _is_minimax_model(model) or _is_ollama_model(model):
        raise ValueError(
            f"run_tool_loop is OpenAI-only; got a non-OpenAI model string: {model!r}"
        )


async def run_tool_loop(
    messages: list[dict],
    model: str,
    tools: list[dict],
    executors: dict[str, Callable[..., object]],
    max_tokens: int = 4096,
    temperature: float = 0.7,
    log_context: dict | None = None,
    max_round_trips: int = DEFAULT_MAX_ROUND_TRIPS,
) -> ToolLoopResult:
    """Run the tool-calling loop to a final text answer.

    ``messages`` is mutated in place (tool round trips are appended) and also
    returned via the closures the caller already holds — callers that need
    the final message list should pass in a list they own.
    """
    _assert_openai_model(model)

    tool_call_history: list[ToolCallRecord] = []
    total_usage = TokenUsage()

    for _round_trip in range(max_round_trips):
        result = await chat_model_with_usage(
            messages=messages,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            log_context=log_context,
            tools=tools,
        )
        total_usage.prompt_tokens += result.usage.prompt_tokens
        total_usage.completion_tokens += result.usage.completion_tokens

        if not result.tool_calls:
            return ToolLoopResult(final_text=result.text, tool_calls=tool_call_history, usage=total_usage)

        messages.append({
            "role": "assistant",
            "content": result.text or None,
            "tool_calls": [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": tc["arguments"]},
                }
                for tc in result.tool_calls
            ],
        })

        for tc in result.tool_calls:
            name = tc["name"]
            arguments = json.loads(tc["arguments"]) if tc["arguments"] else {}
            executor = executors.get(name)
            t_start = time.monotonic()
            if executor is None:
                tool_result = {"error": f"Unknown tool: {name}"}
            else:
                tool_result = executor(**arguments)
            latency_ms = round((time.monotonic() - t_start) * 1000)

            _prompt_log.info(
                "tool_call",
                extra={
                    "tool_name": name,
                    "tool_arguments": arguments,
                    "tool_result": tool_result,
                    "latency_ms": latency_ms,
                    **(log_context or {}),
                },
            )
            tool_call_history.append(
                ToolCallRecord(name=name, arguments=arguments, result=tool_result, latency_ms=latency_ms)
            )
            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": json.dumps(tool_result),
            })

    # Loop exhausted its round trips while the model still wanted to call
    # tools — force one final text-only answer with no tools offered.
    final = await chat_model_with_usage(
        messages=messages,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        log_context=log_context,
        tools=None,
    )
    total_usage.prompt_tokens += final.usage.prompt_tokens
    total_usage.completion_tokens += final.usage.completion_tokens
    return ToolLoopResult(final_text=final.text, tool_calls=tool_call_history, usage=total_usage)
