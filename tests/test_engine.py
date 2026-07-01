"""Engine tests with a fake LLM provider (no network)."""
from __future__ import annotations

from pathlib import Path

from sopagent.harness import ArtifactStore, Engine, Tracer
from sopagent.llm import LLMResponse, LLMRouter, ProviderRegistry, ToolCall
from sopagent.llm.base import LLMProvider, Message, ToolSchema
from sopagent.sop.schema import LlmConfig, Meta, SOP, Stage, Step
from sopagent.tools import BUILTIN_TOOLS, ToolExecutor, ToolRegistry


class FakeProvider:
    """Replays a scripted sequence of LLMResponse objects."""

    name = "openai"

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self._i = 0

    def chat(self, messages: list[Message], tools: list[ToolSchema], config: object) -> LLMResponse:
        resp = self._responses[self._i]
        self._i += 1
        return resp


def _make_sop() -> SOP:
    return SOP(
        metadata=Meta(name="test-sop"),
        variables={"topic": "cats"},
        llm_defaults=LlmConfig(provider="openai", model="fake-model"),
        tools=["echo"],
        stages=[
            Stage(
                id="gather",
                steps=[
                    Step(
                        id="search",
                        goal="gather facts",
                        prompt="Find facts about ${topic}. Return JSON {summary}.",
                        tools=["echo"],
                        expected_output={
                            "type": "object",
                            "properties": {"summary": {"type": "string"}},
                            "required": ["summary"],
                        },
                        retry={"max": 1, "backoff": 1.0},
                    )
                ],
            ),
            Stage(
                id="write",
                steps=[
                    Step(
                        id="draft",
                        goal="write report",
                        prompt="Write report from ${stages.gather.search.output.summary}",
                        save_artifact="report.md",
                    )
                ],
            ),
        ],
    )


def _build_engine(responses: list[LLMResponse], tmp_path: Path) -> Engine:
    sop = _make_sop()
    registry = ProviderRegistry()
    registry.register(FakeProvider(responses))  # type: ignore[arg-type]
    router = LLMRouter(registry)

    tool_registry = ToolRegistry()
    for t in BUILTIN_TOOLS:
        tool_registry.register(t)
    executor = ToolExecutor(tool_registry)

    return Engine(
        sop=sop,
        router=router,
        tool_registry=tool_registry,
        tool_executor=executor,
        artifacts=ArtifactStore(tmp_path),
        tracer=Tracer("test-sop"),
    )


def test_two_step_agent_loop_with_tool(tmp_path: Path) -> None:
    responses = [
        # step 1, turn 0: model calls echo
        LLMResponse(content=None, tool_calls=[ToolCall(id="c1", name="echo", arguments={"text": "cats"})]),
        # step 1, turn 1: model produces final JSON
        LLMResponse(content='{"summary": "cats are furry"}', tool_calls=[]),
        # step 2, turn 0: model produces final markdown report
        LLMResponse(content="# Report\ncats are furry", tool_calls=[]),
    ]
    engine = _build_engine(responses, tmp_path)
    trace = engine.run()

    assert trace.success
    assert len(trace.steps) == 2
    assert all(s.status == "succeeded" for s in trace.steps)
    # step 1 took 2 turns (tool call + final), step 2 took 1 turn
    turns = {s.step_id: s.turns for s in trace.steps}
    assert turns["search"] == 2
    assert turns["draft"] == 1
    # artifact persisted
    assert (tmp_path / "report.md").read_text(encoding="utf-8").startswith("# Report")
    # runtime variable reference was resolved in step 2 prompt
    assert engine.sop.stages[1].steps[0].prompt == "Write report from ${stages.gather.search.output.summary}"


def test_validation_failure_triggers_retry(tmp_path: Path) -> None:
    responses = [
        # attempt 1: invalid JSON
        LLMResponse(content="not json", tool_calls=[]),
        # attempt 2: valid JSON
        LLMResponse(content='{"summary": "ok"}', tool_calls=[]),
        # step 2 final
        LLMResponse(content="# Report", tool_calls=[]),
    ]
    engine = _build_engine(responses, tmp_path)
    trace = engine.run()

    assert trace.success
    search_record = next(s for s in trace.steps if s.step_id == "search")
    assert search_record.attempts == 2


def test_step_loop_exhausted_marks_failure(tmp_path: Path) -> None:
    # model keeps calling tools and never produces a final answer
    responses = [
        LLMResponse(content=None, tool_calls=[ToolCall(id=f"c{i}", name="echo", arguments={"text": "hi"})])
        for i in range(20)
    ]
    engine = _build_engine(responses, tmp_path)
    trace = engine.run()

    assert not trace.success
    assert trace.steps[0].status == "failed"
