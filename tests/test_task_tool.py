"""Tests for the `task` delegation tool (sub-agent with fresh context)."""
from __future__ import annotations

from pathlib import Path

from sopagent.harness import ApprovalPolicy
from sopagent.harness.artifacts import ArtifactStore
from sopagent.harness.tracer import Tracer
from sopagent.llm import LLMResponse, LLMRouter, ProviderRegistry
from sopagent.llm.base import Message, ToolCall, ToolSchema
from sopagent.sop.schema import LlmConfig
from sopagent.tools import ToolExecutor, ToolRegistry
from sopagent.tools.builtin import EchoTool
from sopagent.tools.builtin.task import SubAgentContext, TaskTool


class _Fake:
    name = "openai"

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._r = list(responses)
        self._i = 0

    def chat(self, messages: list[Message], tools: list[ToolSchema], config: object) -> LLMResponse:
        r = self._r[self._i]
        self._i += 1
        return r


def _ctx(responses, tmp_path, **kw) -> tuple[TaskTool, list]:
    reg = ProviderRegistry()
    reg.register(_Fake(responses))  # type: ignore[arg-type]
    router = LLMRouter(reg)
    tool_reg = ToolRegistry()
    tool_reg.register(EchoTool())
    forwarded: list = []
    ctx = SubAgentContext(
        router=router,
        tool_registry=tool_reg,
        llm_config=LlmConfig(provider="openai", model="x"),
        artifacts=ArtifactStore(tmp_path),
        approval_policy=ApprovalPolicy(),
        on_event=forwarded.append,
        **kw,
    )
    tool = TaskTool(ctx)
    tool_reg.register(tool)
    return tool, forwarded


def test_delegation_returns_summary(tmp_path: Path) -> None:
    responses = [LLMResponse(content=None, tool_calls=[ToolCall(id="f", name="finish", arguments={"summary": "sub did it"})])]
    tool, _ = _ctx(responses, tmp_path)
    out = tool.run({"description": "do the thing"})
    assert "completed successfully" in out
    assert "sub did it" in out


def test_delegation_runs_subagent_tools(tmp_path: Path) -> None:
    responses = [
        LLMResponse(content=None, tool_calls=[ToolCall(id="e", name="echo", arguments={"text": "hi"})]),
        LLMResponse(content=None, tool_calls=[ToolCall(id="f", name="finish", arguments={"summary": "done"})]),
    ]
    tool, _ = _ctx(responses, tmp_path)
    out = tool.run({"description": "echo then finish"})
    assert "echo(ok)" in out
    assert "done" in out


def test_missing_description(tmp_path: Path) -> None:
    tool, _ = _ctx([], tmp_path)
    assert "ERROR" in tool.run({"description": ""})
    assert "ERROR" in tool.run({})


def test_recursion_guard(tmp_path: Path) -> None:
    tool, _ = _ctx([], tmp_path, depth=0, max_depth=0)
    out = tool.run({"description": "x"})
    assert "depth limit" in out


def test_boundary_subagent_has_no_task_tool(tmp_path: Path) -> None:
    # max_depth=1: top (depth 0) may spawn one sub-agent at depth 1, which has NO task tool.
    # The sub-agent tries to call `task` -> executor reports it unregistered -> then finishes.
    responses = [
        LLMResponse(content=None, tool_calls=[ToolCall(id="t", name="task", arguments={"description": "nested"})]),
        LLMResponse(content=None, tool_calls=[ToolCall(id="f", name="finish", arguments={"summary": "ok"})]),
    ]
    tool, _ = _ctx(responses, tmp_path, max_depth=1)
    out = tool.run({"description": "try to nest"})
    assert "task(fail)" in out
    assert "ok" in out


def test_event_forwarding(tmp_path: Path) -> None:
    responses = [
        LLMResponse(content=None, tool_calls=[ToolCall(id="e", name="echo", arguments={"text": "hi"})]),
        LLMResponse(content=None, tool_calls=[ToolCall(id="f", name="finish", arguments={"summary": "done"})]),
    ]
    tool, forwarded = _ctx(responses, tmp_path)
    tool.run({"description": "with events"})
    kinds = {type(e).__name__ for e in forwarded}
    assert "TurnEvent" in kinds
    assert "ToolExecutedEvent" in kinds


def test_subagent_failure_reported(tmp_path: Path) -> None:
    # sub-agent never finishes -> hits max_turns -> failure
    responses = [
        LLMResponse(content=None, tool_calls=[ToolCall(id=f"e{i}", name="echo", arguments={"text": "x"})])
        for i in range(20)
    ]
    tool, _ = _ctx(responses, tmp_path, max_turns=3)
    out = tool.run({"description": "loop forever"})
    assert "did NOT complete" in out
