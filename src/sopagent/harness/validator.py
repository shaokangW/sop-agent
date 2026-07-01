"""Output validation: extract JSON from a model response and check against a schema."""
from __future__ import annotations

import json
import re
from typing import Any

from jsonschema import ValidationError, validate

_CODEBLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


class ValidationFailed(Exception):
    def __init__(self, message: str, *, content: str | None = None) -> None:
        super().__init__(message)
        self.content = content


def _extract_json(content: str) -> Any:
    """Best-effort extract a JSON object from a model response.

    Tries, in order: the whole string; a ```json fenced block; the first
    balanced {...} span. This copes with models that wrap JSON in code fences
    or prefix it with explanatory prose.
    """
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    for match in _CODEBLOCK_RE.finditer(content):
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            continue

    start = content.find("{")
    end = content.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(content[start : end + 1])
        except json.JSONDecodeError:
            pass

    raise ValidationFailed("output is not valid JSON", content=content)


def validate_output(content: str, schema: dict[str, Any]) -> Any:
    """Validate that `content` contains JSON conforming to `schema`.

    Returns the parsed (and re-serialized-clean) JSON object so callers can
    store a normalized form for downstream references.
    """
    data = _extract_json(content)
    try:
        validate(instance=data, schema=schema)
    except ValidationError as exc:
        raise ValidationFailed(f"output does not match schema: {exc.message}", content=content) from exc
    return data
