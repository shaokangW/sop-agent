"""Tool executor: run tool calls produced by the LLM and package results as messages."""
from __future__ import annotations

from ..llm.base import ToolCall, tool_result_message
from .base import ToolResult
from .registry import ToolRegistry


class ToolExecutor:
    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def batch(self, tool_calls: list[ToolCall]) -> list[ToolResult]:
        results: list[ToolResult] = []
        for tc in tool_calls:
            results.append(self._run_one(tc))
        return results

    def _run_one(self, tc: ToolCall) -> ToolResult:
        try:
            tool = self._registry.get(tc.name)
        except KeyError as exc:
            return ToolResult(tool_call_id=tc.id, content=f"ERROR: {exc}", ok=False)
        try:
            content = tool.run(tc.arguments)
        except Exception as exc:  # noqa: BLE001 - surface tool errors back to the LLM
            return ToolResult(tool_call_id=tc.id, content=f"ERROR: {exc!r}", ok=False)
        return ToolResult(tool_call_id=tc.id, content=content, ok=True)


def results_to_messages(results: list[ToolResult]) -> list[dict]:
    return [tool_result_message(r.tool_call_id, r.content) for r in results]
