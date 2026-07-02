"""Built-in tools: small, dependency-free utilities for demos and tests."""
from __future__ import annotations

from typing import Any

from .stdlib import STANDARD_TOOLS
from .task import SubAgentContext, TaskTool


class EchoTool:
    name = "echo"
    description = "Echo back the provided text. Useful for testing the tool loop."
    parameters = {
        "type": "object",
        "properties": {"text": {"type": "string", "description": "Text to echo"}},
        "required": ["text"],
    }

    def run(self, arguments: dict[str, Any]) -> str:
        return arguments.get("text", "")


# Stateless tools auto-registered in every registry. TaskTool is contextual
# (needs runtime deps) and is wired explicitly by the CLI/server builders.
BUILTIN_TOOLS = [EchoTool(), *STANDARD_TOOLS]

__all__ = ["BUILTIN_TOOLS", "EchoTool", "STANDARD_TOOLS", "TaskTool", "SubAgentContext"]
