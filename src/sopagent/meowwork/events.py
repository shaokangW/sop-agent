"""MeowWork events: emitted by GroupOrchestrator alongside sop-agent base events.

5 new event types for the multi-agent collaboration layer:
  MessageEvent / StateUpdateEvent / PhaseEvent / SubAgentEvent / SecurityAlertEvent
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class MessageEvent:
    """An agent spoke in the shared discussion (broadcast or directed)."""
    frm: str  # speaker role
    to: str | None  # target role, None = broadcast
    content: str


@dataclass
class StateUpdateEvent:
    key: str
    old: Any
    new: Any
    by: str


@dataclass
class PhaseEvent:
    from_phase: str
    to_phase: str
    by: str


@dataclass
class SubAgentEvent:
    """A delegated sub-agent started/finished (logical PID)."""
    pid: int
    role: str
    task: str
    status: str  # running|done|failed


@dataclass
class SecurityAlertEvent:
    """Validator blocked a dangerous tool call (Phase 2)."""
    tool: str
    args: dict
    reason: str
    blocked: bool = True
