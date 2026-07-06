"""Phase 5 tests: catnip pause/resume + sub-agent timing."""
from __future__ import annotations

import time

from sopagent.llm import LLMResponse, LLMRouter, ProviderRegistry
from sopagent.llm.base import ToolCall
from sopagent.meowwork import BUILTIN_ROLES, GroupOrchestrator, SpeakerRouter
from sopagent.sop.schema import LlmConfig
from sopagent.tools import ToolRegistry


class _Fake:
    name = "openai"
    def __init__(self, responses): self._r = list(responses); self._i = 0
    def chat(self, m, t, c):
        r = self._r[self._i]; self._i += 1; return r


def _orch(responses):
    reg = ProviderRegistry(); reg.register(_Fake(responses))  # type: ignore[arg-type]
    roles = {k: v for k, v in BUILTIN_ROLES.items()}
    for r in roles.values(): r.llm = LlmConfig(provider="openai", model="x")
    return GroupOrchestrator(
        task="t", roles=roles, llm_router=LLMRouter(reg), business_registry=ToolRegistry(),
        router=SpeakerRouter(LLMRouter(reg), roles["planner"].llm, decide=lambda s, m: "planner"),
        max_turns=10, max_inner=5,
    )


def test_pause_freezes_then_resumes() -> None:
    """A paused run blocks until resume; events arrive only after resume."""
    import threading
    responses = [
        LLMResponse(content="hello", tool_calls=[]),  # planner turn 1 (broadcast)
        LLMResponse(content=None, tool_calls=[ToolCall(id="f", name="finish_task", arguments={"summary": "done"})]),
        LLMResponse(content="完成", tool_calls=[]),
    ]
    orch = _orch(responses)
    orch.pause()
    assert orch.is_paused is True

    events: list = []
    def run():
        for ev in orch.run_events():
            events.append(ev)
    t = threading.Thread(target=run, daemon=True)
    t.start()
    time.sleep(0.4)
    # still paused → no turns emitted (only the generator started, blocked at pause check)
    assert len(events) == 0
    assert not orch.state.finished

    orch.resume()
    t.join(timeout=5)
    assert orch.state.finished is True
    assert len(events) > 0


def test_subagent_records_timing() -> None:
    responses = [
        # planner delegates
        LLMResponse(content=None, tool_calls=[ToolCall(id="d", name="delegate", arguments={"role": "executor", "task": "do x"})]),
        LLMResponse(content="委派完", tool_calls=[]),
        # subagent (executor, business-only): text reply
        LLMResponse(content="子结果", tool_calls=[]),
        # planner finish
        LLMResponse(content=None, tool_calls=[ToolCall(id="f", name="finish_task", arguments={"summary": "done"})]),
        LLMResponse(content="完成", tool_calls=[]),
    ]
    orch = _orch(responses)
    for _ in orch.run_events():
        pass
    sa = orch.state.sub_agents[0]
    assert sa["status"] == "done"
    assert "started_at" in sa and "duration" in sa
    assert sa["duration"] >= 0
