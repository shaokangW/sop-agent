"""Phase 1 tests: GroupOrchestrator conversation loop, hand-off, permissions, delegate."""
from __future__ import annotations

from sopagent.llm import LLMResponse, LLMRouter, ProviderRegistry
from sopagent.llm.base import Message, ToolCall, ToolSchema
from sopagent.meowwork import (
    BUILTIN_ROLES,
    GroupOrchestrator,
    MessageEvent,
    PhaseEvent,
    SpeakerRouter,
    StateUpdateEvent,
    SubAgentEvent,
)
from sopagent.sop.schema import LlmConfig
from sopagent.tools import ToolRegistry


class _Fake:
    name = "openai"

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._r = list(responses)
        self._i = 0

    def chat(self, messages: list[Message], tools: list[ToolSchema], config: object) -> LLMResponse:
        r = self._r[self._i]
        self._i += 1
        return r


def _router(responses, decide=None) -> tuple[LLMRouter, GroupOrchestrator]:
    reg = ProviderRegistry()
    reg.register(_Fake(responses))  # type: ignore[arg-type]
    llm_router = LLMRouter(reg)
    # set all roles to the fake provider
    roles = {k: v for k, v in BUILTIN_ROLES.items()}
    for r in roles.values():
        r.llm = LlmConfig(provider="openai", model="x")
    biz = ToolRegistry()  # empty business registry (tests use convo tools only)
    speaker_router = SpeakerRouter(llm_router, roles["planner"].llm, decide=decide)
    orch = GroupOrchestrator(
        task="测试任务", roles=roles, llm_router=llm_router,
        business_registry=biz, router=speaker_router, max_turns=20, max_inner=8,
    )
    return llm_router, orch


def _drive(orch) -> list:
    events = []
    gen = orch.run_events()
    for ev in gen:
        events.append(ev)
    return events


def test_full_flow_handoff_and_finish() -> None:
    responses = [
        # planner turn: update plan + send to executor
        LLMResponse(content=None, tool_calls=[
            ToolCall(id="u1", name="update_state", arguments={"key": "plan_tree", "value": {"step_1": {"desc": "做X", "assignee": "executor"}}}),
            ToolCall(id="s1", name="send_message", arguments={"to": "executor", "content": "做 step_1"}),
        ]),
        LLMResponse(content="分配完毕", tool_calls=[]),
        # executor turn: produce artifact + send to reviewer
        LLMResponse(content=None, tool_calls=[
            ToolCall(id="u2", name="update_state", arguments={"key": "current_artifact", "value": "def x(): pass"}),
            ToolCall(id="s2", name="send_message", arguments={"to": "reviewer", "content": "审查 X"}),
        ]),
        LLMResponse(content="完成", tool_calls=[]),
        # reviewer turn: pass + send to planner
        LLMResponse(content=None, tool_calls=[
            ToolCall(id="u3", name="update_state", arguments={"key": "review_pass", "value": True}),
            ToolCall(id="u4", name="update_state", arguments={"key": "review_feedback", "value": "ok"}),
            ToolCall(id="s3", name="send_message", arguments={"to": "planner", "content": "通过"}),
        ]),
        LLMResponse(content="审查通过", tool_calls=[]),
        # planner turn: finish
        LLMResponse(content=None, tool_calls=[
            ToolCall(id="f", name="finish_task", arguments={"summary": "全部完成"}),
        ]),
        LLMResponse(content="完成", tool_calls=[]),
    ]
    _, orch = _router(responses, decide=lambda s, m: "planner")
    events = _drive(orch)

    assert orch.state.finished is True
    assert orch.state.summary == "全部完成"
    assert orch.state.plan_tree["step_1"]["assignee"] == "executor"
    assert orch.state.current_artifact == "def x(): pass"
    assert orch.state.review_pass is True
    # autonomous hand-off chain (directed messages): planner→executor→reviewer→planner
    directed = [e for e in events if isinstance(e, MessageEvent) and e.to is not None]
    assert [e.frm for e in directed] == ["planner", "executor", "reviewer"]
    assert [e.to for e in directed] == ["executor", "reviewer", "planner"]
    # state update events
    su = [e for e in events if isinstance(e, StateUpdateEvent)]
    assert any(e.key == "plan_tree" and e.by == "planner" for e in su)
    assert any(e.key == "current_artifact" and e.by == "executor" for e in su)
    assert any(e.key == "review_pass" and e.by == "reviewer" for e in su)


def test_permission_denied_executor_cannot_set_phase() -> None:
    responses = [
        # executor turn (preset planner→executor hand-off): try to set phase → denied
        LLMResponse(content=None, tool_calls=[
            ToolCall(id="p1", name="update_state", arguments={"key": "phase", "value": "review"}),
        ]),
        LLMResponse(content="被拒", tool_calls=[]),
        # planner turn (fallback after executor's no-hand-off): finish
        LLMResponse(content=None, tool_calls=[
            ToolCall(id="f", name="finish_task", arguments={"summary": "done"}),
        ]),
        LLMResponse(content="完成", tool_calls=[]),
    ]
    _, orch = _router(responses, decide=lambda s, m: "planner")
    # pre-seed: planner already handed off to executor
    orch.messages = [{"role": "assistant", "name": "planner", "content": "go", "to": "executor"}]
    orch.state.turn = 0
    events = _drive(orch)
    # the executor's update_state(phase) should be denied (no PhaseEvent, phase unchanged)
    assert not any(isinstance(e, PhaseEvent) for e in events)
    assert orch.state.phase == "analyze"
    assert orch.state.finished is True  # planner finished afterward


def test_phase_event_emitted_on_planner_phase_change() -> None:
    responses = [
        LLMResponse(content=None, tool_calls=[
            ToolCall(id="p", name="update_state", arguments={"key": "phase", "value": "execute"}),
        ]),
        LLMResponse(content="推进", tool_calls=[]),
        LLMResponse(content=None, tool_calls=[
            ToolCall(id="f", name="finish_task", arguments={"summary": "done"}),
        ]),
        LLMResponse(content="完成", tool_calls=[]),
    ]
    _, orch = _router(responses, decide=lambda s, m: "planner")
    events = _drive(orch)
    pe = [e for e in events if isinstance(e, PhaseEvent)]
    assert len(pe) == 1 and pe[0].from_phase == "analyze" and pe[0].to_phase == "execute"


def test_delegate_spawns_subagent() -> None:
    responses = [
        # planner: delegate to executor
        LLMResponse(content=None, tool_calls=[
            ToolCall(id="d", name="delegate", arguments={"role": "executor", "task": "读文件 X"}),
        ]),
        LLMResponse(content="委派完", tool_calls=[]),
        # subagent (executor role, business-only): just return text
        LLMResponse(content="子结果:文件内容", tool_calls=[]),
        # planner: finish
        LLMResponse(content=None, tool_calls=[
            ToolCall(id="f", name="finish_task", arguments={"summary": "done"}),
        ]),
        LLMResponse(content="完成", tool_calls=[]),
    ]
    _, orch = _router(responses, decide=lambda s, m: "planner")
    events = _drive(orch)
    sub_evs = [e for e in events if isinstance(e, SubAgentEvent)]
    assert len(sub_evs) == 2  # running + done
    assert sub_evs[0].status == "running" and sub_evs[1].status == "done"
    assert sub_evs[0].role == "executor"
    assert orch.state.sub_agents[0]["status"] == "done"
    assert orch.state.sub_agents[0]["pid"] == 1


def test_broadcast_emits_message_event() -> None:
    responses = [
        LLMResponse(content=None, tool_calls=[
            ToolCall(id="b", name="broadcast", arguments={"content": "大家好"}),
        ]),
        LLMResponse(content="广播完", tool_calls=[]),
        LLMResponse(content=None, tool_calls=[
            ToolCall(id="f", name="finish_task", arguments={"summary": "done"}),
        ]),
        LLMResponse(content="完成", tool_calls=[]),
    ]
    _, orch = _router(responses, decide=lambda s, m: "planner")
    events = _drive(orch)
    msg = [e for e in events if isinstance(e, MessageEvent) and e.to is None]
    assert any("大家好" in e.content for e in msg)


def test_max_turns_stops_loop() -> None:
    # planner keeps broadcasting, never finishes
    responses = [LLMResponse(content="继续", tool_calls=[])] * 100
    _, orch = _router(responses, decide=lambda s, m: "planner")
    orch.max_turns = 3
    _drive(orch)
    assert orch.state.turn == 3 and not orch.state.finished
