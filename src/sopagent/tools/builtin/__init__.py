"""Built-in tools: small, dependency-free utilities for demos and tests."""
from __future__ import annotations

from typing import Any

from .stdlib import STANDARD_TOOLS


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


BUILTIN_TOOLS = [EchoTool(), *STANDARD_TOOLS]
