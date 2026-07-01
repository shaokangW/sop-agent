"""Tool layer: registry, executor, built-ins, MCP adapter."""
from .base import Tool, ToolResult, to_openai_schema
from .builtin import BUILTIN_TOOLS, EchoTool, STANDARD_TOOLS
from .executor import ToolExecutor, results_to_messages
from .mcp_client import McpClient
from .registry import ToolRegistry

__all__ = [
    "Tool",
    "ToolResult",
    "to_openai_schema",
    "ToolRegistry",
    "ToolExecutor",
    "results_to_messages",
    "BUILTIN_TOOLS",
    "STANDARD_TOOLS",
    "EchoTool",
    "McpClient",
]
