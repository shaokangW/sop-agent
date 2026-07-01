"""Global configuration: provider credentials, default endpoints.

The default model is GLM-5.2 served via Alibaba Bailian (百炼) OpenAI-compatible
endpoint. Credentials and baseURL are read from the user's opencode config
(`~/.config/opencode/opencode.json`) so we reuse the already-authenticated
`bailian` provider without hardcoding secrets. Environment variables take
precedence for overrides.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ProviderConfig:
    """A single LLM provider connection (OpenAI-compatible)."""

    name: str
    base_url: str | None = None
    api_key: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _env(name: str) -> str | None:
    return os.environ.get(name)


def _opencode_config_dir() -> Path:
    return Path.home() / ".config" / "opencode"


def _strip_jsonc(text: str) -> str:
    """Strip // line comments and trailing commas so jsonc parses as json.

    String-aware: a `//` inside a JSON string (e.g. `https://...`) is preserved.
    """
    out: list[str] = []
    i, n = 0, len(text)
    in_str = False
    escaped = False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        out.append(c)
        i += 1
    result = "".join(out)
    result = re.sub(r",(\s*[}\]])", r"\1", result)
    return result


def _read_opencode_provider_options(provider_id: str) -> dict[str, Any]:
    """Read a provider's `options` (apiKey, baseURL) from opencode config."""
    cfg_dir = _opencode_config_dir()
    for candidate in (cfg_dir / "opencode.json", cfg_dir / "opencode.jsonc"):
        if not candidate.exists():
            continue
        try:
            data = json.loads(_strip_jsonc(candidate.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
        prov = (data.get("provider") or {}).get(provider_id) or {}
        return prov.get("options") or {}
    return {}


# Bailian (百炼) OpenAI-compatible endpoint default.
BAILIAN_DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
BAILIAN_DEFAULT_MODEL = "glm-5.2"


@dataclass
class Settings:
    """Runtime settings assembled from env + opencode config."""

    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    artifacts_dir: str = ".artifacts"
    traces_dir: str = ".traces"

    @classmethod
    def from_env(cls) -> "Settings":
        providers: dict[str, ProviderConfig] = {}

        # Bailian / GLM-5.2 (default). Env wins, fall back to opencode config.
        bailian_opts = _read_opencode_provider_options("bailian")
        providers["bailian"] = ProviderConfig(
            name="bailian",
            base_url=_env("BAILIAN_BASE_URL") or bailian_opts.get("baseURL") or BAILIAN_DEFAULT_BASE_URL,
            api_key=(
                _env("BAILIAN_API_KEY")
                or _env("DASHSCOPE_API_KEY")
                or bailian_opts.get("apiKey")
            ),
        )

        # Generic OpenAI-compatible (OpenAI / DeepSeek / Qwen via base_url).
        providers["openai"] = ProviderConfig(
            name="openai",
            base_url=_env("OPENAI_BASE_URL"),
            api_key=_env("OPENAI_API_KEY"),
        )
        return cls(providers=providers)

    def provider(self, name: str) -> ProviderConfig:
        if name not in self.providers:
            raise KeyError(f"unknown provider '{name}', configured: {list(self.providers)}")
        cfg = self.providers[name]
        if not cfg.api_key:
            raise RuntimeError(f"provider '{name}' has no api_key configured")
        return cfg
