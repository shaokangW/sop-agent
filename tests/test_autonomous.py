"""Tests for the autonomous agent (self-directed loop + completion + approval)."""
from __future__ import annotations

from pathlib import Path

from sopagent.harness import (
    ApprovalPolicy,
    ApprovalRequest,
    AutonomousAgent,
    DoneEvent,
    ToolExecutedEvent,
)
from sopagent.harness.artifacts import ArtifactStore
from sopagent.harness.tracer import Tracer
from sopagent.llm import LLMResponse, LLMRouter, ProviderRegistry
from sopagent.llm.base import Message, ToolCall, ToolSchema
from sopagent.sop.schema import LlmConfig
from sopagent.tools import BUILTIN_TOOLS, ToolExecutor, ToolRegistry


class _Fake:
    name = "openai"

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._r = list(responses)
        self._i = 0

    def chat(self, messages: list[Message], tools: list[ToolSchema], config: object) -> LLMResponse:
        r = self._r[self._i]
        self._i += 1
        return r


def _drive(gen, decisions: list[str]) -> list:
    events: list = []
    ev = next(gen)
    try:
        while True:
            if isinstance(ev, ApprovalRequest):
                ev = gen.send(decisions.pop(0))
            elif isinstance(ev, DoneEvent):
                events.append(ev)
                break
            else:
                events.append(ev)
                ev = next(gen)
    except StopIteration:
        pass
    return events


def _agent(responses, tmp_path, policy=None) -> AutonomousAgent:
    reg = ProviderRegistry()
    reg.register(_Fake(responses))  # type: ignore[arg-type]
    tool_reg = ToolRegistry()
    for t in BUILTIN_TOOLS:
        tool_reg.register(t)
    return AutonomousAgent(
        task="do the task",
        router=LLMRouter(reg),
        tool_registry=tool_reg,
        tool_executor=ToolExecutor(tool_reg),
        artifacts=ArtifactStore(tmp_path),
        llm_config=LlmConfig(provider="openai", model="x"),
        tracer=Tracer("autonomous"),
        approval_policy=policy,
    )


def test_finish_tool_completes(tmp_path: Path) -> None:
    responses = [
        LLMResponse(content=None, tool_calls=[ToolCall(id="c1", name="echo", arguments={"text": "x"})]),
        LLMResponse(content=None, tool_calls=[ToolCall(id="f", name="finish", arguments={"summary": "all done"})]),
    ]
    agent = _agent(responses, tmp_path)
    events = _drive(agent.run_events(), [])

    assert events[-1].trace.success
    assert agent.summary == "all done"
    tool_evs = [e for e in events if isinstance(e, ToolExecutedEvent)]
    assert len(tool_evs) == 1 and tool_evs[0].name == "echo"


def test_final_answer_completes(tmp_path: Path) -> None:
    responses = [LLMResponse(content="here is the answer", tool_calls=[])]
    agent = _agent(responses, tmp_path)
    events = _drive(agent.run_events(), [])
    assert events[-1].trace.success
    assert agent.summary == "here is the answer"


def test_action_level_approval(tmp_path: Path) -> None:
    responses = [
        LLMResponse(content=None, tool_calls=[ToolCall(id="c1", name="echo", arguments={"text": "x"})]),
        LLMResponse(content=None, tool_calls=[ToolCall(id="f", name="finish", arguments={"summary": "done"})]),
    ]
    agent = _agent(responses, tmp_path, ApprovalPolicy(approve_tools={"echo"}))
    events = _drive(agent.run_events(), ["approve"])
    tool_evs = [e for e in events if isinstance(e, ToolExecutedEvent)]
    assert tool_evs[0].name == "echo" and tool_evs[0].ok is True
    assert events[-1].trace.success


def test_completion_rejection_continues(tmp_path: Path) -> None:
    responses = [
        LLMResponse(content=None, tool_calls=[ToolCall(id="f", name="finish", arguments={"summary": "done"})]),
        LLMResponse(content=None, tool_calls=[ToolCall(id="f2", name="finish", arguments={"summary": "really done"})]),
    ]
    agent = _agent(responses, tmp_path, ApprovalPolicy(approve_subgoals=True))
    events = _drive(agent.run_events(), ["reject", "approve"])
    assert events[-1].trace.success
    assert agent.summary == "really done"


def test_max_turns_marks_failure(tmp_path: Path) -> None:
    # agent keeps calling echo and never finishes
    responses = [
        LLMResponse(content=None, tool_calls=[ToolCall(id=f"c{i}", name="echo", arguments={"text": "hi"})])
        for i in range(25)
    ]
    agent = _agent(responses, tmp_path)
    agent.max_turns = 3
    events = _drive(agent.run_events(), [])
    assert events[-1].trace.success is False


def test_complex_task_uses_plan_then_finishes(tmp_path: Path) -> None:
    responses = [
        LLMResponse(content=None, tool_calls=[ToolCall(id="p", name="plan", arguments={"subgoals": ["step a", "step b"]})]),
        LLMResponse(content=None, tool_calls=[ToolCall(id="s1", name="subgoal_done", arguments={})]),
        LLMResponse(content=None, tool_calls=[ToolCall(id="s2", name="subgoal_done", arguments={})]),
        LLMResponse(content=None, tool_calls=[ToolCall(id="f", name="finish", arguments={"summary": "all done"})]),
    ]
    agent = _agent(responses, tmp_path)
    events = _drive(agent.run_events(), [])

    assert events[-1].trace.success
    assert agent.plan == ["step a", "step b"]
    assert agent.subgoal_idx == 2
    assert agent.summary == "all done"


def test_subgoal_rejection_keeps_current(tmp_path: Path) -> None:
    responses = [
        LLMResponse(content=None, tool_calls=[ToolCall(id="p", name="plan", arguments={"subgoals": ["only one"]})]),
        LLMResponse(content=None, tool_calls=[ToolCall(id="s1", name="subgoal_done", arguments={})]),  # rejected
        LLMResponse(content=None, tool_calls=[ToolCall(id="s2", name="subgoal_done", arguments={})]),  # approved
        LLMResponse(content=None, tool_calls=[ToolCall(id="f", name="finish", arguments={"summary": "done"})]),  # needs approval too
    ]
    agent = _agent(responses, tmp_path, ApprovalPolicy(approve_subgoals=True))
    events = _drive(agent.run_events(), ["reject", "approve", "approve"])

    assert events[-1].trace.success
    assert agent.subgoal_idx == 1  # advanced only after the approved subgoal_done


def test_simple_task_skips_plan(tmp_path: Path) -> None:
    # simple task: no plan, just finish
    responses = [LLMResponse(content=None, tool_calls=[ToolCall(id="f", name="finish", arguments={"summary": "quick"})])]
    agent = _agent(responses, tmp_path)
    events = _drive(agent.run_events(), [])
    assert events[-1].trace.success
    assert agent.plan is None
