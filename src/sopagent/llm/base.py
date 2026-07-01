"""LLM provider abstraction: protocol, response types, message helpers."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

Message = dict[str, Any]
ToolSchema = dict[str, Any]
StreamCallback = Callable[[str], None]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: Any = None
    reasoning: str = ""

    def assistant_message(self) -> Message:
        msg: Message = {"role": "assistant"}
        if self.content:
            msg["content"] = self.content
        if self.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": _json_args(tc.arguments)},
                }
                for tc in self.tool_calls
            ]
        return msg

    def is_final(self) -> bool:
        return not self.tool_calls


def _json_args(arguments: dict[str, Any]) -> str:
    import json

    return json.dumps(arguments, ensure_ascii=False)


def tool_result_message(tool_call_id: str, content: str) -> Message:
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": content,
    }


class LLMProvider(Protocol):
    name: str

    def chat(
        self,
        messages: list[Message],
        tools: list[ToolSchema],
        config: Any,
    ) -> LLMResponse: ...

    def chat_stream(
        self,
        messages: list[Message],
        tools: list[ToolSchema],
        config: Any,
        on_delta: StreamCallback | None = None,
        on_reasoning: StreamCallback | None = None,
    ) -> LLMResponse: ...
