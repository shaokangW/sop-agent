"""OpenAI-compatible provider: works with OpenAI, DeepSeek, Qwen, Bailian via base_url."""
from __future__ import annotations

import json
from typing import Any

from openai import OpenAI

from ..config import ProviderConfig
from .base import LLMProvider, LLMResponse, Message, StreamCallback, ToolCall, ToolSchema


class OpenAIProvider:
    """OpenAI chat completions provider (native tool_calls).

    `name` follows the provider config so multiple OpenAI-compatible endpoints
    (openai, bailian, deepseek, ...) can coexist in one registry.
    """

    def __init__(self, cfg: ProviderConfig):
        self.name = cfg.name
        self._client = OpenAI(api_key=cfg.api_key, base_url=cfg.base_url)

    def chat(
        self,
        messages: list[Message],
        tools: list[ToolSchema],
        config: Any,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": config.model,
            "messages": messages,
            "temperature": config.temperature,
        }
        if tools:
            kwargs["tools"] = tools
        if config.max_tokens is not None:
            kwargs["max_tokens"] = config.max_tokens

        resp = self._client.chat.completions.create(**kwargs)
        choice = resp.choices[0].message

        tool_calls: list[ToolCall] = []
        if choice.tool_calls:
            for tc in choice.tool_calls:
                try:
                    arguments = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    arguments = {"_raw": tc.function.arguments}
                tool_calls.append(
                    ToolCall(id=tc.id, name=tc.function.name, arguments=arguments)
                )

        return LLMResponse(content=choice.content, tool_calls=tool_calls, raw=resp, usage=_usage(resp))

    def chat_stream(
        self,
        messages: list[Message],
        tools: list[ToolSchema],
        config: Any,
        on_delta: StreamCallback | None = None,
        on_reasoning: StreamCallback | None = None,
    ) -> LLMResponse:
        """Stream tokens; call `on_delta` per content chunk, `on_reasoning` per
        reasoning chunk (for thinking models like GLM-5.2). Return full response."""
        kwargs: dict[str, Any] = {
            "model": config.model,
            "messages": messages,
            "temperature": config.temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            kwargs["tools"] = tools
        if config.max_tokens is not None:
            kwargs["max_tokens"] = config.max_tokens

        stream = self._client.chat.completions.create(**kwargs)
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tc_args: dict[int, str] = {}
        tc_names: dict[int, str] = {}
        tc_ids: dict[int, str] = {}
        usage: dict[str, int] | None = None
        for chunk in stream:
            if not chunk.choices:
                # final usage-only chunk arrives with empty choices
                usage = _usage(chunk)
                continue
            delta = chunk.choices[0].delta
            if delta is None:
                continue
            if getattr(delta, "reasoning_content", None):
                reasoning_parts.append(delta.reasoning_content)
                if on_reasoning:
                    on_reasoning(delta.reasoning_content)
            if delta.content:
                content_parts.append(delta.content)
                if on_delta:
                    on_delta(delta.content)
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index if tc.index is not None else 0
                    if idx not in tc_ids:
                        tc_ids[idx] = tc.id or ""
                        tc_names[idx] = (tc.function.name if tc.function and tc.function.name else "")
                    if tc.function and tc.function.arguments:
                        tc_args[idx] = tc_args.get(idx, "") + (tc.function.arguments or "")
        content = "".join(content_parts) or None
        tool_calls: list[ToolCall] = []
        for idx in sorted(tc_ids):
            try:
                args = json.loads(tc_args.get(idx, "") or "{}")
            except json.JSONDecodeError:
                args = {"_raw": tc_args.get(idx, "")}
            tool_calls.append(ToolCall(id=tc_ids[idx], name=tc_names[idx], arguments=args))
        return LLMResponse(content=content, tool_calls=tool_calls, reasoning="".join(reasoning_parts), usage=usage)


def _usage(resp: Any) -> dict[str, int] | None:
    u = getattr(resp, "usage", None)
    if u is None:
        return None
    return {
        "prompt_tokens": getattr(u, "prompt_tokens", 0) or 0,
        "completion_tokens": getattr(u, "completion_tokens", 0) or 0,
        "total_tokens": getattr(u, "total_tokens", 0) or 0,
    }
