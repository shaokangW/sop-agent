"""Tests for conditional stage transitions."""
from __future__ import annotations

from pathlib import Path

from sopagent.harness import ArtifactStore, Engine, Tracer
from sopagent.llm import LLMResponse, LLMRouter, ProviderRegistry
from sopagent.llm.base import Message, ToolSchema
from sopagent.sop.schema import LlmConfig, Meta, SOP, Stage, Step, Transition
from sopagent.tools import ToolExecutor, ToolRegistry


class _FakeProvider:
    name = "openai"

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._r = list(responses)
        self._i = 0

    def chat(self, messages: list[Message], tools: list[ToolSchema], config: object) -> LLMResponse:
        r = self._r[self._i]
        self._i += 1
        return r


def _branch_sop() -> SOP:
    return SOP(
        metadata=Meta(name="branch"),
        llm_defaults=LlmConfig(provider="openai", model="x"),
        stages=[
            Stage(
                id="decide",
                steps=[
                    Step(
                        id="pick",
                        goal="decide branch",
                        prompt="return {go: ...}",
                        expected_output={
                            "type": "object",
                            "properties": {"go": {"type": "string"}},
                            "required": ["go"],
                        },
                    )
                ],
            ),
            Stage(id="left", steps=[Step(id="lstep", goal="left", prompt="left")]),
            Stage(id="right", steps=[Step(id="rstep", goal="right", prompt="right")]),
        ],
        transitions=[
            Transition.model_validate(
                {"from": "decide", "to": "left", "when": "stages.decide.steps.pick.output.go == 'left'"}
            ),
            Transition.model_validate(
                {"from": "decide", "to": "right", "when": "stages.decide.steps.pick.output.go == 'right'"}
            ),
        ],
    )


def _engine(responses: list[LLMResponse], tmp_path: Path) -> Engine:
    sop = _branch_sop()
    reg = ProviderRegistry()
    reg.register(_FakeProvider(responses))  # type: ignore[arg-type]
    tool_reg = ToolRegistry()
    return Engine(
        sop=sop,
        router=LLMRouter(reg),
        tool_registry=tool_reg,
        tool_executor=ToolExecutor(tool_reg),
        artifacts=ArtifactStore(tmp_path),
        tracer=Tracer("branch"),
    )


def test_branch_goes_left(tmp_path: Path) -> None:
    engine = _engine(
        [
            LLMResponse(content='{"go":"left"}', tool_calls=[]),
            LLMResponse(content="went left", tool_calls=[]),
        ],
        tmp_path,
    )
    trace = engine.run()
    assert trace.success
    assert [s.step_id for s in trace.steps] == ["pick", "lstep"]


def test_branch_goes_right(tmp_path: Path) -> None:
    engine = _engine(
        [
            LLMResponse(content='{"go":"right"}', tool_calls=[]),
            LLMResponse(content="went right", tool_calls=[]),
        ],
        tmp_path,
    )
    trace = engine.run()
    assert trace.success
    assert [s.step_id for s in trace.steps] == ["pick", "rstep"]


def test_no_matching_transition_ends_run(tmp_path: Path) -> None:
    # go='up' matches neither branch -> explicit graph ends after decide
    engine = _engine(
        [LLMResponse(content='{"go":"up"}', tool_calls=[])],
        tmp_path,
    )
    trace = engine.run()
    assert trace.success
    assert [s.step_id for s in trace.steps] == ["pick"]
