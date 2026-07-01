"""Tests for the interactive REPL session (multi-turn chat + tools + approval)."""
from __future__ import annotations

from pathlib import Path

from sopagent.harness import (
    ApprovalPolicy,
    ApprovalRequest,
    InteractiveSession,
    ToolExecutedEvent,
)
from sopagent.harness.artifacts import ArtifactStore
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


def _session(responses, tmp_path, policy=None) -> InteractiveSession:
    reg = ProviderRegistry()
    reg.register(_Fake(responses))  # type: ignore[arg-type]
    tool_reg = ToolRegistry()
    for t in BUILTIN_TOOLS:
        tool_reg.register(t)
    return InteractiveSession(
        router=LLMRouter(reg),
        tool_registry=tool_reg,
        tool_executor=ToolExecutor(tool_reg),
        llm_config=LlmConfig(provider="openai", model="x"),
        approval_policy=policy,
    )


def _drive(gen, decisions) -> list:
    events: list = []
    ev = next(gen)
    try:
        while True:
            if isinstance(ev, ApprovalRequest):
                ev = gen.send(decisions.pop(0))
            else:
                events.append(ev)
                ev = next(gen)
    except StopIteration:
        pass
    return events


def test_multi_turn_with_tool(tmp_path: Path) -> None:
    responses = [
        # turn 1: call echo then final reply
        LLMResponse(content=None, tool_calls=[ToolCall(id="c1", name="echo", arguments={"text": "hi"})]),
        LLMResponse(content="echoed: hi", tool_calls=[]),
        # turn 2: direct reply
        LLMResponse(content="bye!", tool_calls=[]),
    ]
    session = _session(responses, tmp_path)

    events1 = _drive(session.ask("echo hi"), [])
    assert any(isinstance(e, ToolExecutedEvent) and e.name == "echo" for e in events1)
    # history kept: system + user1 + assistant(tool) + tool + assistant(final)
    assert len(session.messages) == 5

    events2 = _drive(session.ask("say bye"), [])
    assert len(events2) >= 1  # final reply turn
    # user2 appended
    assert any(m.get("role") == "user" and m.get("content") == "say bye" for m in session.messages)


def test_dangerous_tool_triggers_approval(tmp_path: Path) -> None:
    responses = [
        LLMResponse(content=None, tool_calls=[ToolCall(id="c1", name="bash", arguments={"command": "echo x"})]),
        LLMResponse(content="done", tool_calls=[]),
    ]
    session = _session(responses, tmp_path)  # default policy; bash requires_approval via tool flag
    events = _drive(session.ask("run echo"), ["approve"])
    bash_evs = [e for e in events if isinstance(e, ToolExecutedEvent) and e.name == "bash"]
    assert len(bash_evs) == 1
    assert bash_evs[0].ok is True


def test_approval_reject_returns_to_llm(tmp_path: Path) -> None:
    responses = [
        LLMResponse(content=None, tool_calls=[ToolCall(id="c1", name="bash", arguments={"command": "rm x"})]),
        LLMResponse(content="ok skipped", tool_calls=[]),
    ]
    session = _session(responses, tmp_path)
    events = _drive(session.ask("delete"), ["reject"])
    bash_evs = [e for e in events if isinstance(e, ToolExecutedEvent) and e.name == "bash"]
    assert bash_evs[0].ok is False  # rejected


def test_clear_resets_history(tmp_path: Path) -> None:
    responses = [LLMResponse(content="hi", tool_calls=[])]
    session = _session(responses, tmp_path)
    _drive(session.ask("hello"), [])
    assert len(session.messages) > 1
    session.reset()
    assert len(session.messages) == 1  # only system
