"""Conditional stage transitions.

When a SOP declares `transitions`, stage flow is driven by them as an explicit
graph: after finishing a stage, the first matching `when` clause picks the next
stage; if none matches, execution ends. A SOP with no transitions runs stages in
declaration order (MVP1 behavior).

`when` expressions are evaluated against a namespace exposing:
  - `vars.<name>`                 top-level SOP variables
  - `stages.<stage>.success`      whether every step in that stage succeeded
  - `stages.<stage>.steps.<step>.output[.field]`   a step's (parsed) output

Evaluation uses Python ``eval`` with an empty ``__builtins__``; the namespace is
the only reachable state. For production hardening, swap in an AST-based
evaluator (e.g. simpleeval).
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from ..sop.schema import SOP, Stage
from .context import Context
from .state import StateManager, StepStatus


def _to_namespace(obj: Any) -> Any:
    """Recursively wrap dicts as SimpleNamespace so `.field` access works in eval."""
    if isinstance(obj, dict):
        return SimpleNamespace(**{k: _to_namespace(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return [_to_namespace(x) for x in obj]
    return obj


def _stage_success(stage: Stage, state: StateManager) -> bool:
    return all(state.get(s.id).status == StepStatus.SUCCEEDED for s in stage.steps)


def _parse_output(raw: str) -> Any:
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw


def build_namespace(sop: SOP, ctx: Context, state: StateManager) -> dict[str, Any]:
    """Build the eval namespace from executed stages' state + outputs + vars."""
    stages_ns: dict[str, Any] = {}
    for stage in sop.stages:
        steps_ns: dict[str, Any] = {}
        for step in stage.steps:
            try:
                output = _parse_output(ctx.step_output(step.id))
            except KeyError:
                output = None
            steps_ns[step.id] = {"output": output}
        stages_ns[stage.id] = {"success": _stage_success(stage, state), "steps": steps_ns}
    return {
        "vars": _to_namespace(dict(ctx.variables)),
        "stages": _to_namespace(stages_ns),
    }


def eval_when(when: str | None, ns: dict[str, Any]) -> bool:
    if not when:
        return True
    try:
        return bool(eval(when, {"__builtins__": {}}, ns))  # noqa: S307 - restricted namespace
    except Exception:
        return False


def next_stage(sop: SOP, current_id: str, ns: dict[str, Any]) -> str | None:
    """Pick the next stage id after `current_id`, or None to stop."""
    for t in sop.transitions:
        if t.src == current_id and eval_when(t.when, ns):
            return t.dst
    if sop.transitions:
        # Explicit graph: no matching transition ends the run.
        return None
    # No transitions: fall through to declaration order.
    ids = [s.id for s in sop.stages]
    i = ids.index(current_id)
    return ids[i + 1] if i + 1 < len(ids) else None
