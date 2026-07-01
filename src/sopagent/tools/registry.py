"""Tool registry: register tools, resolve by id (incl. mcp: prefix)."""
from __future__ import annotations

from typing import Iterable

from .base import Tool, to_openai_schema


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def has(self, name: str) -> bool:
        return name in self._tools

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(f"tool '{name}' not registered; known: {list(self._tools)}")
        return self._tools[name]

    def resolve(self, ids: Iterable[str]) -> list[Tool]:
        tools: list[Tool] = []
        for tid in ids:
            tools.append(self.get(tid))
        return tools

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def schemas_for(self, tools: Iterable[Tool]) -> list[dict]:
        return [to_openai_schema(t) for t in tools]
