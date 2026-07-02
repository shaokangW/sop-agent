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
    sessions_dir: str = ".sop-agent/sessions"

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

        # Anthropic native (Clape) Messages API — separate provider class.
        providers["anthropic"] = ProviderConfig(
            name="anthropic",
            base_url=_env("ANTHROPIC_BASE_URL"),  # optional proxy
            api_key=_env("ANTHROPIC_API_KEY"),
        )

        # Ollama local (OpenAI-compatible endpoint; no real key needed).
        providers["ollama"] = ProviderConfig(
            name="ollama",
            base_url=_env("OLLAMA_BASE_URL") or "http://localhost:11434/v1",
            api_key="ollama",  # dummy key — Ollama ignores auth
        )
        return cls(providers=providers)

    def provider(self, name: str) -> ProviderConfig:
        if name not in self.providers:
            raise KeyError(f"unknown provider '{name}', configured: {list(self.providers)}")
        cfg = self.providers[name]
        if not cfg.api_key:
            raise RuntimeError(f"provider '{name}' has no api_key configured")
        return cfg


def load_mcp_servers() -> dict[str, dict]:
    """Load MCP server configs from ~/.sop-agent/mcp.json and project .sop-agent/mcp.json.

    Format: {"mcp_servers": {"<id>": {"command": "...", "args": [...], "env": {...}}}}
    Also reads opencode's mcp config (~/.config/opencode/opencode.json `mcp` field)
    so servers configured for opencode are reused.
    """
    servers: dict[str, dict] = {}
    # opencode mcp config
    cfg_dir = _opencode_config_dir()
    for candidate in (cfg_dir / "opencode.json", cfg_dir / "opencode.jsonc"):
        if not candidate.exists():
            continue
        try:
            data = json.loads(_strip_jsonc(candidate.read_text(encoding="utf-8")))
            mcp = data.get("mcp") or data.get("mcpServers") or {}
            if isinstance(mcp, dict):
                for sid, cfg in mcp.items():
                    if isinstance(cfg, dict):
                        servers[sid] = {
                            "command": cfg.get("command"),
                            "args": cfg.get("args", []),
                            "env": cfg.get("env", {}),
                            "url": cfg.get("url"),
                        }
            break
        except (json.JSONDecodeError, OSError):
            continue
    # user / project overrides (higher priority)
    for f in (Path.home() / ".sop-agent" / "mcp.json", Path.cwd() / ".sop-agent" / "mcp.json"):
        if not f.exists():
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                servers.update(data.get("mcp_servers", data))
        except (json.JSONDecodeError, OSError):
            continue
    # filter out servers without command/url
    return {k: v for k, v in servers.items() if v.get("command") or v.get("url")}
