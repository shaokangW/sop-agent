"""Tests for the native Anthropic provider: message/tool translation + chat + routing."""
from __future__ import annotations

from types import SimpleNamespace

from sopagent.config import ProviderConfig, Settings
from sopagent.llm import AnthropicProvider, LLMRouter, ProviderRegistry
from sopagent.llm.anthropic_provider import _to_anthropic_tool
from sopagent.llm.base import Message, ToolSchema
from sopagent.sop.schema import LlmConfig


class _FakeMessages:
    def __init__(self, response, log: list) -> None:
        self._resp = response
        self._log = log

    def create(self, **kwargs):
        self._log.append(kwargs)
        return self._resp


class _FakeClient:
    def __init__(self, response) -> None:
        self._log: list = []
        self.messages = _FakeMessages(response, self._log)

    @property
    def calls(self) -> list:
        return self._log


def _provider(response) -> tuple[AnthropicProvider, _FakeClient]:
    client = _FakeClient(response)
    p = AnthropicProvider(ProviderConfig(name="anthropic", api_key="k"), client=client)
    return p, client


def test_translate_request_extracts_system_and_converts_tool_messages() -> None:
    msgs: list[Message] = [
        {"role": "system", "content": "you are helpful"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "t1", "type": "function", "function": {"name": "echo", "arguments": '{"text": "x"}'}},
        ]},
        {"role": "tool", "tool_call_id": "t1", "content": "x"},
        {"role": "assistant", "content": "done"},
    ]
    system, out = AnthropicProvider._translate_request(msgs)
    assert system == "you are helpful"
    # roles alternate user/assistant; tool result folded into a user message
    assert [m["role"] for m in out] == ["user", "assistant", "user", "assistant"]
    tool_result_block = out[2]["content"][0]
    assert tool_result_block["type"] == "tool_result" and tool_result_block["tool_use_id"] == "t1"
    tool_use_block = out[1]["content"][0]
    assert tool_use_block["type"] == "tool_use" and tool_use_block["name"] == "echo"
    assert tool_use_block["input"] == {"text": "x"}  # JSON string args parsed


def test_to_anthropic_tool() -> None:
    tool: ToolSchema = {"type": "function", "function": {
        "name": "read_file", "description": "read", "parameters": {"type": "object", "properties": {"path": {}}}}}
    out = _to_anthropic_tool(tool)
    assert out["name"] == "read_file"
    assert out["input_schema"]["properties"]["path"] == {}
    assert out["description"] == "read"


def test_translate_response_text_and_tool_use() -> None:
    resp = SimpleNamespace(
        content=[
            SimpleNamespace(type="text", text="hello "),
            SimpleNamespace(type="text", text="world"),
            SimpleNamespace(type="tool_use", id="t1", name="echo", input={"text": "x"}),
        ],
        usage=SimpleNamespace(input_tokens=12, output_tokens=8),
        stop_reason="tool_use",
    )
    out = AnthropicProvider._translate_response(resp)
    assert out.content == "hello world"
    assert len(out.tool_calls) == 1 and out.tool_calls[0].name == "echo"
    assert out.tool_calls[0].arguments == {"text": "x"}
    assert out.usage == {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}


def test_translate_response_thinking_becomes_reasoning() -> None:
    resp = SimpleNamespace(
        content=[
            SimpleNamespace(type="thinking", thinking="pondering..."),
            SimpleNamespace(type="text", text="answer"),
        ],
        usage=SimpleNamespace(input_tokens=1, output_tokens=2),
        stop_reason="end_turn",
    )
    out = AnthropicProvider._translate_response(resp)
    assert out.content == "answer"
    assert out.reasoning == "pondering..."
    assert not out.tool_calls


def test_chat_calls_sdk_and_returns_translated_response() -> None:
    resp = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="hi there")],
        usage=SimpleNamespace(input_tokens=3, output_tokens=4),
        stop_reason="end_turn",
    )
    p, client = _provider(resp)
    out = p.chat(
        [{"role": "system", "content": "s"}, {"role": "user", "content": "hello"}],
        [],
        LlmConfig(provider="anthropic", model="claude-3-5-sonnet", temperature=0.3),
    )
    assert out.content == "hi there"
    assert out.usage["total_tokens"] == 7
    call = client.calls[0]
    assert call["system"] == "s"
    assert call["model"] == "claude-3-5-sonnet"
    assert call["messages"][0]["role"] == "user"


def test_chat_passes_tools_when_present() -> None:
    resp = SimpleNamespace(content=[SimpleNamespace(type="text", text="ok")],
                           usage=SimpleNamespace(input_tokens=1, output_tokens=1), stop_reason="end_turn")
    p, client = _provider(resp)
    p.chat([{"role": "user", "content": "x"}],
           [{"type": "function", "function": {"name": "echo", "description": "e", "parameters": {"type": "object"}}}],
           LlmConfig(provider="anthropic", model="m"))
    assert client.calls[0]["tools"] == [{"name": "echo", "description": "e", "input_schema": {"type": "object"}}]


def test_chat_stream_emits_delta_and_returns_response() -> None:
    resp = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="streamed")],
        usage=SimpleNamespace(input_tokens=1, output_tokens=2), stop_reason="end_turn",
    )
    p, _ = _provider(resp)
    received: list[str] = []
    out = p.chat_stream([{"role": "user", "content": "x"}], [], LlmConfig(provider="anthropic", model="m"), on_delta=received.append)
    assert out.content == "streamed"
    assert received == ["streamed"]


def test_router_routes_to_anthropic_provider() -> None:
    resp = SimpleNamespace(content=[SimpleNamespace(type="text", text="routed")],
                           usage=SimpleNamespace(input_tokens=1, output_tokens=1), stop_reason="end_turn")
    client = _FakeClient(resp)
    reg = ProviderRegistry()
    reg.register(AnthropicProvider(ProviderConfig(name="anthropic", api_key="k"), client=client))
    router = LLMRouter(reg)
    out = router.chat([{"role": "user", "content": "hi"}], [], LlmConfig(provider="anthropic", model="m"))
    assert out.content == "routed"
    assert client.calls  # the anthropic client was the one called


def test_from_settings_registers_anthropic_and_ollama_skips_no_key() -> None:
    settings = Settings(providers={
        "anthropic": ProviderConfig(name="anthropic", api_key="sk-ant"),
        "ollama": ProviderConfig(name="ollama", api_key="ollama", base_url="http://localhost:11434/v1"),
        "openai": ProviderConfig(name="openai", api_key=None),  # no key -> skipped
    })
    reg = ProviderRegistry.from_settings(settings)
    names = list(reg._providers.keys())
    assert "anthropic" in names and "ollama" in names
    assert "openai" not in names
    assert isinstance(reg.get("anthropic"), AnthropicProvider)
