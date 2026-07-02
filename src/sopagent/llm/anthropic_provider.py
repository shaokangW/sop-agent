"""Native Anthropic Messages API provider (NOT OpenAI-compatible).

Uses the official ``anthropic`` SDK lazily (optional dependency). Translates
the OpenAI-style message/tool schema used elsewhere in sop-agent to/from the
Anthropic Messages format (system as a top-level param, tool_calls as
``tool_use`` content blocks, tool results as ``tool_result`` blocks).

Streaming note: ``chat_stream`` currently resolves via a non-streaming call
and emits the full text as a single delta (correct, but not incremental).
Native incremental SSE streaming is a follow-up.
"""
from __future__ import annotations

from typing import Any

from ..config import ProviderConfig
from .base import LLMProvider, LLMResponse, Message, StreamCallback, ToolCall, ToolSchema

_ANTHROPIC_VERSION = "2023-06-01"


class AnthropicProvider:
    """Anthropic Messages API provider. ``client`` is injectable for tests."""

    name: str

    def __init__(self, cfg: ProviderConfig, client: Any = None) -> None:
        self.name = cfg.name
        self._cfg = cfg
        self._client = client

    def _ensure(self) -> Any:
        if self._client is None:
            try:
                import anthropic  # type: ignore
            except ImportError as exc:  # pragma: no cover - exercised only without the dep
                raise RuntimeError(
                    "the 'anthropic' package is required for the Anthropic provider; "
                    "install with `pip install anthropic`"
                ) from exc
            kwargs: dict[str, Any] = {"api_key": self._cfg.api_key}
            if self._cfg.base_url:
                kwargs["base_url"] = self._cfg.base_url
            self._client = anthropic.Anthropic(**kwargs)
        return self._client

    # ----------------------------------------------------------------- chat
    def chat(
        self,
        messages: list[Message],
        tools: list[ToolSchema],
        config: Any,
    ) -> LLMResponse:
        client = self._ensure()
        system, msgs = self._translate_request(messages)
        kwargs: dict[str, Any] = {
            "model": config.model,
            "max_tokens": config.max_tokens or 4096,
            "messages": msgs,
            "temperature": config.temperature,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = [_to_anthropic_tool(t) for t in tools]
        resp = client.messages.create(**kwargs)
        return self._translate_response(resp)

    def chat_stream(
        self,
        messages: list[Message],
        tools: list[ToolSchema],
        config: Any,
        on_delta: StreamCallback | None = None,
        on_reasoning: StreamCallback | None = None,
    ) -> LLMResponse:
        # v1: resolve non-streamed, then surface text/reasoning as single deltas
        resp = self.chat(messages, tools, config)
        if on_delta and resp.content:
            on_delta(resp.content)
        if on_reasoning and resp.reasoning:
            on_reasoning(resp.reasoning)
        return resp

    # ----------------------------------------------------------- translation
    @staticmethod
    def _translate_request(messages: list[Message]) -> tuple[str, list[dict[str, Any]]]:
        system_parts: list[str] = []
        out: list[dict[str, Any]] = []
        for m in messages:
            role = m.get("role")
            if role == "system":
                if m.get("content"):
                    system_parts.append(str(m["content"]))
                continue
            if role == "tool":
                # tool result -> user message with a tool_result block
                block = {
                    "type": "tool_result",
                    "tool_use_id": m.get("tool_call_id"),
                    "content": str(m.get("content") or ""),
                }
                if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                    out[-1]["content"].append(block)
                else:
                    out.append({"role": "user", "content": [block]})
                continue
            if role == "assistant":
                blocks: list[dict[str, Any]] = []
                if m.get("content"):
                    blocks.append({"type": "text", "text": str(m["content"])})
                for tc in m.get("tool_calls") or []:
                    fn = (tc or {}).get("function") or {}
                    args = fn.get("arguments")
                    if isinstance(args, str):
                        import json
                        try:
                            args = json.loads(args or "{}")
                        except json.JSONDecodeError:
                            args = {"_raw": args}
                    blocks.append({
                        "type": "tool_use",
                        "id": tc.get("id"),
                        "name": fn.get("name"),
                        "input": args or {},
                    })
                out.append({"role": "assistant", "content": blocks or [{"type": "text", "text": ""}]})
                continue
            # user (or anything else) -> text block
            out.append({"role": "user", "content": [{"type": "text", "text": str(m.get("content") or "")}]})
        return "\n\n".join(system_parts), out

    @staticmethod
    def _translate_response(resp: Any) -> LLMResponse:
        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in getattr(resp, "content", None) or []:
            btype = getattr(block, "type", None)
            if btype == "text":
                text_parts.append(getattr(block, "text", "") or "")
            elif btype == "thinking":
                reasoning_parts.append(getattr(block, "thinking", "") or "")
            elif btype == "tool_use":
                tool_calls.append(ToolCall(
                    id=getattr(block, "id", ""),
                    name=getattr(block, "name", ""),
                    arguments=dict(getattr(block, "input", {}) or {}),
                ))
        content = "".join(text_parts) or None
        usage_obj = getattr(resp, "usage", None)
        usage: dict[str, int] | None = None
        if usage_obj is not None:
            inp = int(getattr(usage_obj, "input_tokens", 0) or 0)
            outp = int(getattr(usage_obj, "output_tokens", 0) or 0)
            usage = {"prompt_tokens": inp, "completion_tokens": outp, "total_tokens": inp + outp}
        return LLMResponse(content=content, tool_calls=tool_calls, raw=resp, reasoning="".join(reasoning_parts), usage=usage)


def _to_anthropic_tool(tool: ToolSchema) -> dict[str, Any]:
    fn = tool.get("function") or {}
    return {
        "name": fn.get("name"),
        "description": fn.get("description", ""),
        "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
    }
