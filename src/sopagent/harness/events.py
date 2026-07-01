"""Execution events emitted by the engine/agent event stream.

The engine and autonomous agent are generators that yield these events.
ApprovalRequest is the human-in-the-loop pause point: the caller resumes the
generator via ``.send(decision)`` where decision is "approve" / "reject".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Union


@dataclass
class TokenEvent:
    """A streamed content delta (also delivered via on_token callback)."""

    step_id: str
    delta: str


@dataclass
class TurnEvent:
    """One LLM turn completed (assistant message, possibly with tool_calls)."""

    step_id: str
    turn: int
    content: str | None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ToolExecutedEvent:
    """A tool call finished."""

    step_id: str
    tool_call_id: str
    name: str
    ok: bool
    result: str


@dataclass
class ApprovalRequest:
    """Pause execution and ask the caller for a decision.

    Resume with ``gen.send("approve")`` or ``gen.send("reject")``.
    payload describes what needs approval:
      - {"kind": "step", "step_id", "goal"}
      - {"kind": "tool_call", "tool_call_id", "name", "arguments"}
    """

    id: str
    reason: str
    payload: dict[str, Any]


@dataclass
class DoneEvent:
    """Run finished; carries the final Trace."""

    trace: Any


Event = Union[TokenEvent, TurnEvent, ToolExecutedEvent, ApprovalRequest, DoneEvent]
