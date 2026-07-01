"""Load a SOP from YAML and resolve static variables."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

from .schema import SOP

_VAR_RE = re.compile(r"\$\{([^}]+)\}")
_RUNTIME_PREFIX = "stages."


def _resolve_value(value: Any, variables: dict[str, Any]) -> Any:
    """Resolve ${env.X} and ${var} statically. Runtime refs (${stages...}) are left intact."""
    if isinstance(value, str):
        return _VAR_RE.sub(lambda m: _sub(m, variables), value)
    if isinstance(value, list):
        return [_resolve_value(v, variables) for v in value]
    if isinstance(value, dict):
        return {k: _resolve_value(v, variables) for k, v in value.items()}
    return value


def _sub(match: re.Match, variables: dict[str, Any]) -> str:
    key = match.group(1).strip()
    if key.startswith("env."):
        env_val = os.environ.get(key[4:])
        return env_val if env_val is not None else match.group(0)
    if key.startswith(_RUNTIME_PREFIX):
        return match.group(0)
    if key in variables:
        return str(variables[key])
    return match.group(0)


def _build_sop(raw: Any, *, source: str | None = None) -> SOP:
    if not isinstance(raw, dict):
        label = source or "SOP"
        raise ValueError(f"{label} must contain a mapping at top level")
    # Pass 1: resolve env (and nested vars) inside `variables` themselves,
    # so prompt refs like ${topic} pick up the resolved value.
    resolved_variables = _resolve_value(
        dict(raw.get("variables", {}) or {}), raw.get("variables", {}) or {}
    )
    raw["variables"] = resolved_variables
    # Pass 2: resolve the whole document against resolved variables.
    resolved = _resolve_value(raw, resolved_variables)
    return SOP.model_validate(resolved)


def load_sop(path: str | Path) -> SOP:
    return _build_sop(yaml.safe_load(Path(path).read_text(encoding="utf-8")), source=str(path))


def load_sop_from_text(text: str) -> SOP:
    return _build_sop(yaml.safe_load(text), source="<yaml text>")
