"""Tests for ContextWindowManager: token-aware compression of long conversations."""
from __future__ import annotations

from sopagent.harness.context_window import ContextWindowManager
from sopagent.llm import LLMResponse, LLMRouter, ProviderRegistry
from sopagent.llm.base import Message, ToolSchema
from sopagent.sop.schema import LlmConfig

class _Fake:
    name = "openai"

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._r = list(responses)
        self._i = 0

    def chat(self, messages: list[Message], tools: list[ToolSchema], config: object) -> LLMResponse:
        r = self._r[self._i]
        self._i += 1
        return r


class _Boom:
    name = "openai"

    def chat(self, messages: list[Message], tools: list[ToolSchema], config: object) -> LLMResponse:
        raise RuntimeError("provider down")


def _mgr(provider, **kw) -> ContextWindowManager:
    reg = ProviderRegistry()
    reg.register(provider)  # type: ignore[arg-type]
    return ContextWindowManager(
        router=LLMRouter(reg),
        llm_config=LlmConfig(provider="openai", model="x"),
        **kw,
    )


def _msg(role: str, text: str, tool_calls=None) -> Message:
    m: Message = {"role": role, "content": text}
    if tool_calls:
        m["tool_calls"] = tool_calls
    return m


def test_no_compress_under_budget() -> None:
    msgs = [_msg("system", "sys"), _msg("user", "hi"), _msg("assistant", "hey")]
    m = _mgr(_Fake([]), max_tokens=100000)
    assert m.maybe_compress(msgs) is msgs  # unchanged (same object)


def test_disabled_is_noop() -> None:
    msgs = [_msg("system", "s")] + [_msg("user", "u" * 500) for _ in range(20)]
    m = _mgr(_Fake([]), max_tokens=10, enabled=False)
    out = m.maybe_compress(msgs)
    assert out is msgs


def test_compress_summarizes_middle_and_keeps_recent() -> None:
    msgs = [
        _msg("system", "S"),
        _msg("user", "u" * 200),
        _msg("assistant", "a" * 200),
        _msg("user", "u" * 200),
        _msg("assistant", "a" * 200),  # <- recent start (keep_recent=2)
        _msg("user", "recent-user"),
    ]
    m = _mgr(_Fake([LLMResponse(content="SUMMARY TEXT", tool_calls=[])]), max_tokens=10, keep_recent=2)
    out = m.maybe_compress(msgs)
    # system preserved, summary inserted, last two messages kept verbatim
    assert out[0]["content"] == "S"
    assert any(x.get("role") == "system" and "SUMMARY TEXT" in x.get("content", "") for x in out[1:2])
    assert out[-2]["content"] == "a" * 200
    assert out[-1]["content"] == "recent-user"
    assert len(out) < len(msgs)


def test_split_avoids_orphan_tool_message() -> None:
    tc = [{"id": "t1", "type": "function", "function": {"name": "echo", "arguments": "{}"}}]
    msgs = [
        _msg("system", "S"),
        _msg("user", "u" * 200),
        _msg("assistant", "a" * 200, tool_calls=tc),
        _msg("tool", "result" * 200),  # tool result; cut would land here -> must keep with parent
        _msg("user", "u" * 200),
        _msg("assistant", "a" * 200, tool_calls=tc),
        _msg("tool", "result" * 200),  # recent start candidate
        _msg("user", "recent"),
    ]
    m = _mgr(_Fake([LLMResponse(content="SUM", tool_calls=[])]), max_tokens=10, keep_recent=2)
    out = m.maybe_compress(msgs)
    # the kept recent block must include an assistant(tool_calls) together with its tool result
    roles = [x.get("role") for x in out]
    # no tool message appears before an assistant-with-tool_calls is present in the kept tail
    assert "tool" in roles
    tool_idx = roles.index("tool")
    # an assistant with tool_calls must precede this tool within `out`
    has_parent = any(
        x.get("tool_calls") for x in out[:tool_idx]
    )
    assert has_parent


def test_fallback_on_llm_failure() -> None:
    msgs = [
        _msg("system", "S"),
        *[_msg("user", "u" * 200) for _ in range(10)],
    ]
    m = _mgr(_Boom(), max_tokens=10, keep_recent=2)
    out = m.maybe_compress(msgs)
    assert any("truncated" in x.get("content", "") for x in out)
    # recent kept
    assert out[-1]["content"] == "u" * 200


def test_on_compress_callback() -> None:
    msgs = [_msg("system", "S"), *[_msg("user", "u" * 200) for _ in range(10)]]
    captured: list[dict] = []
    m = _mgr(
        _Fake([LLMResponse(content="SUM", tool_calls=[])]),
        max_tokens=10, keep_recent=2, on_compress=captured.append,
    )
    m.maybe_compress(msgs)
    assert len(captured) == 1
    stats = captured[0]
    assert stats["before_tokens"] > stats["after_tokens"]
    assert stats["middle_messages"] > 0
    assert stats["kept_recent"] == 2


def test_too_few_messages_no_compress() -> None:
    msgs = [_msg("system", "S"), _msg("user", "hi")]
    m = _mgr(_Fake([]), max_tokens=1, keep_recent=8)
    assert m.maybe_compress(msgs) is msgs


def test_session_compresses_across_turns(tmp_path) -> None:
    from sopagent.harness import InteractiveSession
    from sopagent.tools import BUILTIN_TOOLS, ToolExecutor, ToolRegistry

    # summary response first, then the real turn reply
    provider = _Fake([
        LLMResponse(content="CONV SUMMARY", tool_calls=[]),
        LLMResponse(content="final reply", tool_calls=[]),
    ])
    reg = ProviderRegistry()
    reg.register(provider)  # type: ignore[arg-type]
    router = LLMRouter(reg)
    llm_config = LlmConfig(provider="openai", model="x")
    tool_reg = ToolRegistry()
    for t in BUILTIN_TOOLS:
        tool_reg.register(t)
    session = InteractiveSession(
        router=router,
        tool_registry=tool_reg,
        tool_executor=ToolExecutor(tool_reg),
        llm_config=llm_config,
        context_manager=ContextWindowManager(router=router, llm_config=llm_config, max_tokens=10, keep_recent=2),
    )
    # pre-populate a long history that exceeds budget
    session.messages = [
        _msg("system", "S"),
        _msg("user", "u" * 200),
        _msg("assistant", "a" * 200),
        _msg("user", "u" * 200),
        _msg("assistant", "a" * 200),
    ]
    # drive one turn; ask() will compress then answer
    gen = session.ask("go")
    evs = []
    try:
        while True:
            evs.append(next(gen))
    except StopIteration:
        pass
    assert any(x.get("content") == "final reply" for x in session.messages)
    assert any(x.get("role") == "system" and "CONV SUMMARY" in x.get("content", "") for x in session.messages)
