"""Provider registry: map provider name -> LLMProvider instance."""
from __future__ import annotations

from ..config import Settings
from .base import LLMProvider
from .openai_provider import OpenAIProvider


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, LLMProvider] = {}

    def register(self, provider: LLMProvider) -> None:
        self._providers[provider.name] = provider

    def get(self, name: str) -> LLMProvider:
        if name not in self._providers:
            raise KeyError(f"provider '{name}' not registered; known: {list(self._providers)}")
        return self._providers[name]

    @classmethod
    def from_settings(cls, settings: Settings) -> "ProviderRegistry":
        registry = cls()
        for name, cfg in settings.providers.items():
            if cfg.api_key is None:
                continue
            # All configured providers speak the OpenAI-compatible protocol
            # (openai, bailian/百炼, deepseek, qwen via base_url, ...).
            registry.register(OpenAIProvider(cfg))
        return registry
