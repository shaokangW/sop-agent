"""Tests for tracer observability: usage accumulation, JSONL dump/replay."""
from __future__ import annotations

from pathlib import Path

from sopagent.harness import Engine, Tracer, replay_jsonl
from sopagent.harness.artifacts import ArtifactStore
from sopagent.harness.tracer import TurnRecord
from sopagent.llm import LLMResponse, LLMRouter, ProviderRegistry, ToolCall
from sopagent.llm.base import Message, ToolSchema
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


def _usage(p: int, c: int) -> dict[str, int]:
    return {"prompt_tokens": p, "completion_tokens": c, "total_tokens": p + c}


def test_usage_accumulates_across_turns() -> None:
    t = Tracer("x")
    t.turn("s", 0, "assistant", "a", [], usage=_usage(10, 5))
    t.turn("s", 1, "tool", "r")
    t.turn("s", 2, "assistant", "b", [], usage=_usage(20, 7))
    assert t.usage == {"prompt_tokens": 30, "completion_tokens": 12, "total_tokens": 42}
    trace = t.finalize(True)
    assert trace.usage["total_tokens"] == 42


def test_turn_without_usage_is_none() -> None:
    t = Tracer("x")
    t.turn("s", 0, "tool", "r")
    assert isinstance(t._turns[0], TurnRecord)
    assert t._turns[0].usage is None
    assert t.usage["total_tokens"] == 0


def test_dump_jsonl_and_replay_roundtrip(tmp_path: Path) -> None:
    t = Tracer("demo")
    t.turn("s0", 0, "assistant", "hello world", [{"id": "c1", "name": "echo"}], usage=_usage(3, 2))
    t.turn("s0", 0, "tool", "echoed")
    t.finalize(True)
    path = t.dump_jsonl(tmp_path / "demo.jsonl")
    assert path.exists()
    recs = replay_jsonl(path)
    # two turn lines + one summary line
    assert len(recs) == 3
    assert recs[0]["kind"] == "turn"
    assert recs[0]["role"] == "assistant"
    assert recs[0]["usage"]["total_tokens"] == 5
    assert recs[0]["tool_calls"][0]["name"] == "echo"
    assert recs[1]["kind"] == "turn" and recs[1]["role"] == "tool"
    assert recs[2]["kind"] == "summary"
    assert recs[2]["sop_name"] == "demo"
    assert recs[2]["usage"]["total_tokens"] == 5


def test_dump_jsonl_creates_parent_dir(tmp_path: Path) -> None:
    t = Tracer("x")
    t.finalize(False)
    target = tmp_path / "nested" / "deep" / "t.jsonl"
    t.dump_jsonl(target)
    assert target.exists()


def _engine(responses, tmp_path) -> Engine:
    sop = SOP(
        metadata=Meta(name="obs"),
        llm_defaults=LlmConfig(provider="openai", model="m"),
        stages=[Stage(id="g", steps=[Step(id="s", goal="g", prompt="do it", tools=["echo"])])],
    )
    reg = ProviderRegistry()
    reg.register(_Fake(responses))  # type: ignore[arg-type]
    tool_reg = ToolRegistry()
    for t in BUILTIN_TOOLS:
        tool_reg.register(t)
    return Engine(
        sop=sop, router=LLMRouter(reg), tool_registry=tool_reg,
        tool_executor=ToolExecutor(tool_reg), artifacts=ArtifactStore(tmp_path),
        tracer=Tracer("obs"),
    )


def test_engine_records_llm_usage(tmp_path: Path) -> None:
    responses = [
        LLMResponse(content=None, tool_calls=[ToolCall(id="c1", name="echo", arguments={"text": "x"})], usage=_usage(100, 40)),
        LLMResponse(content="done", tool_calls=[], usage=_usage(120, 30)),
    ]
    engine = _engine(responses, tmp_path)
    trace = engine.run()
    assert trace.usage["prompt_tokens"] == 220
    assert trace.usage["completion_tokens"] == 70
    assert trace.usage["total_tokens"] == 290
    # the dump carries per-turn usage too
    recs = replay_jsonl(engine.tracer.dump_jsonl(tmp_path / "e.jsonl"))
    turn_rec = [r for r in recs if r["kind"] == "turn" and r["role"] == "assistant"]
    assert sum(r["usage"]["total_tokens"] for r in turn_rec) == 290


def test_autonomous_records_llm_usage(tmp_path: Path) -> None:
    from sopagent.harness import AutonomousAgent

    reg = ProviderRegistry()
    reg.register(_Fake([  # type: ignore[arg-type]
        LLMResponse(content=None, tool_calls=[ToolCall(id="c1", name="echo", arguments={"text": "x"})], usage=_usage(50, 10)),
        LLMResponse(content=None, tool_calls=[ToolCall(id="f", name="finish", arguments={"summary": "ok"})], usage=_usage(60, 5)),
    ]))
    tool_reg = ToolRegistry()
    for t in BUILTIN_TOOLS:
        tool_reg.register(t)
    agent = AutonomousAgent(
        task="t", router=LLMRouter(reg), tool_registry=tool_reg,
        tool_executor=ToolExecutor(tool_reg), artifacts=ArtifactStore(tmp_path),
        llm_config=LlmConfig(provider="openai", model="m"), tracer=Tracer("auto"),
    )
    trace = agent.run()
    assert trace.usage["prompt_tokens"] == 110
    assert trace.usage["total_tokens"] == 125
