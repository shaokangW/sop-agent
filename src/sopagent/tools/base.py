"""Tool abstraction: protocol, result types, schema conversion."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class ToolResult:
    tool_call_id: str
    content: str
    ok: bool = True


@dataclass
class Verdict:
    """Result of a pre-execution hook check."""

    allow: bool
    reason: str = ""
    source: str = ""  # "rule" | "llm" | ""


class PreExecutionHook(Protocol):
    """Inspect a tool call before it runs; return a Verdict."""

    def check(self, tool_name: str, arguments: dict[str, Any]) -> Verdict: ...


class Tool(Protocol):
    """A callable tool exposed to the LLM."""

    name: str
    description: str
    parameters: dict[str, Any]

    def run(self, arguments: dict[str, Any]) -> str: ...


def to_openai_schema(tool: Tool) -> dict[str, Any]:
    """Convert a Tool to the OpenAI function-tool schema."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }
