"""Tests for streaming token output via on_token callback."""
from __future__ import annotations

from pathlib import Path

from sopagent.harness import ArtifactStore, Engine, Tracer
from sopagent.llm import LLMResponse, LLMRouter, ProviderRegistry
from sopagent.llm.base import Message, StreamCallback, ToolSchema
from sopagent.sop.schema import LlmConfig, Meta, SOP, Stage, Step
from sopagent.tools import ToolExecutor, ToolRegistry


class StreamFakeProvider:
    name = "openai"

    def __init__(self, deltas: list[str], final: LLMResponse) -> None:
        self._deltas = deltas
        self._final = final

    def chat(self, messages: list[Message], tools: list[ToolSchema], config: object) -> LLMResponse:
        return self._final

    def chat_stream(
        self,
        messages: list[Message],
        tools: list[ToolSchema],
        config: object,
        on_delta: StreamCallback | None = None,
        on_reasoning: StreamCallback | None = None,
    ) -> LLMResponse:
        for d in self._deltas:
            if on_delta:
                on_delta(d)
        return self._final


def _sop() -> SOP:
    return SOP(
        metadata=Meta(name="stream"),
        llm_defaults=LlmConfig(provider="openai", model="x"),
        stages=[Stage(id="s", steps=[Step(id="p", goal="g", prompt="hi")])],
    )


def test_on_token_receives_deltas(tmp_path: Path) -> None:
    final = LLMResponse(content="hello world", tool_calls=[])
    provider = StreamFakeProvider(["hel", "lo ", "world"], final)
    registry = ProviderRegistry()
    registry.register(provider)  # type: ignore[arg-type]

    received: list[tuple[str, str]] = []
    engine = Engine(
        sop=_sop(),
        router=LLMRouter(registry),
        tool_registry=ToolRegistry(),
        tool_executor=ToolExecutor(ToolRegistry()),
        artifacts=ArtifactStore(tmp_path),
        tracer=Tracer("stream"),
        on_token=lambda sid, d: received.append((sid, d)),
    )
    trace = engine.run()

    assert trace.success
    assert "".join(d for _, d in received) == "hello world"
    assert all(sid == "p" for sid, _ in received)


def test_no_on_token_uses_chat(tmp_path: Path) -> None:
    final = LLMResponse(content="ok", tool_calls=[])
    provider = StreamFakeProvider(["SHOULD NOT BE CALLED"], final)
    registry = ProviderRegistry()
    registry.register(provider)  # type: ignore[arg-type]

    engine = Engine(
        sop=_sop(),
        router=LLMRouter(registry),
        tool_registry=ToolRegistry(),
        tool_executor=ToolExecutor(ToolRegistry()),
        artifacts=ArtifactStore(tmp_path),
        tracer=Tracer("stream"),
    )
    trace = engine.run()
    assert trace.success
