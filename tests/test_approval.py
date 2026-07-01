"""Tests for human-in-the-loop approval (action-level + stage-level)."""
from __future__ import annotations

from pathlib import Path

from sopagent.harness import (
    ApprovalPolicy,
    ApprovalRequest,
    DoneEvent,
    Engine,
    ToolExecutedEvent,
    Tracer,
)
from sopagent.harness.artifacts import ArtifactStore
from sopagent.llm import LLMResponse, LLMRouter, ProviderRegistry
from sopagent.llm.base import Message, ToolCall, ToolSchema
from sopagent.sop.schema import LlmConfig, Meta, SOP, Stage, Step
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
    """Drive an event generator, answering ApprovalRequests from `decisions`."""
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


def _engine(sop: SOP, responses: list[LLMResponse], policy: ApprovalPolicy, tmp_path: Path) -> Engine:
    reg = ProviderRegistry()
    reg.register(_Fake(responses))  # type: ignore[arg-type]
    tool_reg = ToolRegistry()
    for t in BUILTIN_TOOLS:
        tool_reg.register(t)
    return Engine(
        sop=sop,
        router=LLMRouter(reg),
        tool_registry=tool_reg,
        tool_executor=ToolExecutor(tool_reg),
        artifacts=ArtifactStore(tmp_path),
        tracer=Tracer("approval"),
        approval_policy=policy,
    )


def _tool_sop() -> SOP:
    return SOP(
        metadata=Meta(name="approval"),
        llm_defaults=LlmConfig(provider="openai", model="x"),
        stages=[
            Stage(
                id="s",
                steps=[
                    Step(
                        id="work",
                        goal="use a tool",
                        prompt="search then answer",
                        tools=["echo"],
                    )
                ],
            )
        ],
    )


def test_action_level_approve_then_execute(tmp_path: Path) -> None:
    responses = [
        LLMResponse(content=None, tool_calls=[ToolCall(id="c1", name="echo", arguments={"text": "x"})]),
        LLMResponse(content="all done", tool_calls=[]),
    ]
    engine = _engine(_tool_sop(), responses, ApprovalPolicy(approve_tools={"echo"}), tmp_path)
    events = _drive(engine.run_events(), ["approve"])

    tool_evs = [e for e in events if isinstance(e, ToolExecutedEvent)]
    assert len(tool_evs) == 1
    assert tool_evs[0].name == "echo"
    assert tool_evs[0].ok is True
    assert events[-1].trace.success


def test_action_level_reject_returns_to_llm(tmp_path: Path) -> None:
    responses = [
        LLMResponse(content=None, tool_calls=[ToolCall(id="c1", name="echo", arguments={"text": "x"})]),
        LLMResponse(content="ok without search", tool_calls=[]),
    ]
    engine = _engine(_tool_sop(), responses, ApprovalPolicy(approve_tools={"echo"}), tmp_path)
    events = _drive(engine.run_events(), ["reject"])

    tool_evs = [e for e in events if isinstance(e, ToolExecutedEvent)]
    assert tool_evs[0].ok is False  # rejected by user
    assert events[-1].trace.success


def test_stage_level_reject_skips_step(tmp_path: Path) -> None:
    sop = SOP(
        metadata=Meta(name="approval"),
        llm_defaults=LlmConfig(provider="openai", model="x"),
        stages=[
            Stage(
                id="s",
                steps=[
                    Step(id="a", goal="ga", prompt="pa", require_approval=True),
                    Step(id="b", goal="gb", prompt="pb"),
                ],
            )
        ],
    )
    responses = [LLMResponse(content="b done", tool_calls=[])]  # only step b runs
    engine = _engine(sop, responses, ApprovalPolicy(), tmp_path)
    events = _drive(engine.run_events(), ["reject"])

    trace = events[-1].trace
    assert trace.success
    rec_a = next(s for s in trace.steps if s.step_id == "a")
    assert rec_a.status == "skipped"
    rec_b = next(s for s in trace.steps if s.step_id == "b")
    assert rec_b.status == "succeeded"
