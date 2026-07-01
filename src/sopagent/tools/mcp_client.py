"""MCP client: connect to a Model Context Protocol server, discover and call its tools.

Each discovered MCP tool is adapted to the `Tool` protocol so the engine and
tool registry treat function-call tools and MCP tools uniformly.

The MCP SDK is async; this wrapper runs each operation via ``asyncio.run`` in a
fresh session. This is simple and robust for stateless servers (filesystem,
calculators). Long-lived/stateful servers should use a persistent session
(future work). The `mcp` package is imported lazily, so this module imports
fine without it installed.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Callable

from .base import Tool


class McpToolAdapter:
    """Adapt an MCP tool to the Tool protocol."""

    def __init__(
        self,
        client: "McpClient",
        name: str,
        description: str,
        parameters: dict[str, Any],
    ) -> None:
        self._client = client
        self.name = name
        self.description = description or ""
        self.parameters = parameters or {"type": "object", "properties": {}}

    def run(self, arguments: dict[str, Any]) -> str:
        return self._client.call_tool(self.name, arguments)


class McpClient:
    """Synchronous wrapper over an MCP server (stdio or SSE)."""

    def __init__(
        self,
        *,
        command: str | None = None,
        args: list[str] | None = None,
        url: str | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self._command = command
        self._args = list(args or [])
        self._url = url
        self._env = dict(env or {})
        if not command and not url:
            raise ValueError("McpClient needs either 'command' (stdio) or 'url' (SSE)")

    @classmethod
    def from_config(cls, cfg: Any) -> "McpClient":
        if isinstance(cfg, dict):
            return cls(
                command=cfg.get("command"),
                args=cfg.get("args", []),
                url=cfg.get("url"),
                env=cfg.get("env", {}),
            )
        return cls(command=cfg.command, args=cfg.args, url=cfg.url, env=cfg.env)

    def discover_tools(self) -> list[Tool]:
        return asyncio.run(self._discover())

    def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        return asyncio.run(self._call(name, arguments))

    def _session_ctx(self):
        if self._command:
            from mcp import StdioServerParameters
            from mcp.client.stdio import stdio_client

            params = StdioServerParameters(
                command=self._command,
                args=self._args,
                env={**self._env} if self._env else None,
            )
            return stdio_client(params)
        from mcp.client.sse import sse_client

        return sse_client(self._url)

    async def _discover(self) -> list[Tool]:
        from mcp import ClientSession

        async with self._session_ctx() as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return [
                    McpToolAdapter(self, t.name, t.description, t.inputSchema)
                    for t in result.tools
                ]

    async def _call(self, name: str, arguments: dict[str, Any]) -> str:
        from mcp import ClientSession

        async with self._session_ctx() as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(name, arguments)
                return _extract_text(result)


def _extract_text(result: Any) -> str:
    parts: list[str] = []
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(text)
    if parts:
        return "\n".join(parts)
    return json.dumps({"is_error": getattr(result, "isError", False)})


def register_mcp_servers(
    sop_or_servers: Any,
    registry: Any,
    client_factory: Callable[[Any], McpClient] | None = None,
) -> None:
    """Discover and register all tools from every MCP server declared in the SOP or a dict."""
    if isinstance(sop_or_servers, dict):
        servers = sop_or_servers
    else:
        servers = getattr(sop_or_servers, "mcp_servers", None) or {}
    factory = client_factory or McpClient.from_config
    for _server_id, cfg in servers.items():
        try:
            client = factory(cfg)
            for tool in client.discover_tools():
                if not registry.has(tool.name):
                    registry.register(tool)
        except Exception as exc:  # noqa: BLE001 - skip failed MCP server, don't block others
            import sys
            print(f"[mcp] server '{_server_id}' failed to load: {exc}", file=sys.stderr)
