"""Execution context: variables, per-step outputs, runtime interpolation."""
from __future__ import annotations

import json
import re
from typing import Any

_VAR_RE = re.compile(r"\$\{([^}]+)\}")
_RUNTIME_PREFIX = "stages."


class Context:
    """Holds runtime state shared across steps: variables and step outputs."""

    def __init__(self, variables: dict[str, Any] | None = None) -> None:
        self.variables: dict[str, Any] = dict(variables or {})
        self._step_outputs: dict[str, str] = {}

    def set_step_output(self, step_id: str, content: str) -> None:
        self._step_outputs[step_id] = content

    def step_output(self, step_id: str) -> str:
        return self._step_outputs[step_id]

    def interpolate(self, text: str) -> str:
        """Resolve ${var} and runtime refs like ${stages.gather.search.output.summary}."""
        return _VAR_RE.sub(self._sub, text)

    def _sub(self, match: re.Match) -> str:
        key = match.group(1).strip()
        if key.startswith(_RUNTIME_PREFIX):
            return self._resolve_runtime(key)
        if key in self.variables:
            return str(self.variables[key])
        return match.group(0)

    def _resolve_runtime(self, key: str) -> str:
        # Expected: stages.<stage>.<step>.output[.field...]
        parts = key.split(".")
        if len(parts) < 4 or parts[0] != "stages" or parts[3] != "output":
            return f"${{{key}}}"
        step_id = parts[2]
        if step_id not in self._step_outputs:
            return f"${{{key}}}"
        raw = self._step_outputs[step_id]
        fields = parts[4:]
        if not fields:
            return raw
        try:
            data: Any = json.loads(raw)
        except json.JSONDecodeError:
            return f"${{{key}}}"
        for field in fields:
            if isinstance(data, dict) and field in data:
                data = data[field]
            else:
                return f"${{{key}}}"
        return str(data)
