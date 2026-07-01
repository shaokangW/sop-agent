"""LLM router: dispatch a chat call to the provider named in the step's LlmConfig."""
from __future__ import annotations

from typing import Any

from ..sop.schema import LlmConfig
from .base import LLMResponse, Message, StreamCallback, ToolSchema
from .registry import ProviderRegistry


class LLMRouter:
    def __init__(self, registry: ProviderRegistry) -> None:
        self._registry = registry

    def chat(
        self,
        messages: list[Message],
        tools: list[ToolSchema],
        config: LlmConfig,
    ) -> LLMResponse:
        provider = self._registry.get(config.provider)
        return provider.chat(messages, tools, config)

    def chat_stream(
        self,
        messages: list[Message],
        tools: list[ToolSchema],
        config: LlmConfig,
        on_delta: StreamCallback | None = None,
        on_reasoning: StreamCallback | None = None,
    ) -> LLMResponse:
        provider = self._registry.get(config.provider)
        return provider.chat_stream(messages, tools, config, on_delta, on_reasoning)
