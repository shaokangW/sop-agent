"""Tests for MCP tool adaptation and registration (no real MCP server)."""
from __future__ import annotations

from sopagent.sop.schema import LlmConfig, McpServerConfig, Meta, SOP, Stage, Step
from sopagent.tools import ToolRegistry
from sopagent.tools.mcp_client import McpToolAdapter, register_mcp_servers


class FakeClient:
    """Stand-in for McpClient: returns scripted tools and call results."""

    def __init__(self, tool_defs, results):
        self._tool_defs = tool_defs
        self._results = results

    def discover_tools(self):
        return [McpToolAdapter(self, n, d, s) for (n, d, s) in self._tool_defs]

    def call_tool(self, name, arguments):
        return self._results.get(name, "none")


def _sop_with_mcp() -> SOP:
    return SOP(
        metadata=Meta(name="m"),
        llm_defaults=LlmConfig(provider="openai", model="x"),
        stages=[Stage(id="s", steps=[Step(id="p", goal="g", prompt="p")])],
        mcp_servers={"fs": McpServerConfig(command="fake", args=[])},
    )


def test_adapter_run_calls_client():
    client = FakeClient([], {"search": "FOUND"})
    adapter = McpToolAdapter(client, "search", "desc", {"type": "object", "properties": {}})
    assert adapter.run({"q": "x"}) == "FOUND"
    assert adapter.name == "search"


def test_register_mcp_servers_registers_and_calls():
    client = FakeClient(
        [("fs_read", "read a file", {"type": "object", "properties": {}})],
        {"fs_read": "DATA"},
    )
    registry = ToolRegistry()
    register_mcp_servers(_sop_with_mcp(), registry, client_factory=lambda cfg: client)

    assert registry.has("fs_read")
    tool = registry.get("fs_read")
    assert tool.description == "read a file"
    assert tool.run({}) == "DATA"


def test_register_mcp_servers_noop_without_servers():
    sop = SOP(
        metadata=Meta(name="m"),
        llm_defaults=LlmConfig(provider="openai", model="x"),
        stages=[Stage(id="s", steps=[Step(id="p", goal="g", prompt="p")])],
    )
    registry = ToolRegistry()

    def _boom(cfg):
        raise AssertionError("client_factory should not be called when no mcp_servers")

    register_mcp_servers(sop, registry, client_factory=_boom)
    assert not registry.has("anything")
