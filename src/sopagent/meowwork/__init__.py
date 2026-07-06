"""MeowWork: multi-agent collaboration layer on top of sop-agent.

Four cat agents (Planner/Executor/Reviewer/Validator) collaborate via a shared
discussion history + global state, orchestrated by GroupOrchestrator. SOP
orchestration is not used here; this is a GroupChat-style collaboration.
"""
from .events import (
    MessageEvent,
    PhaseEvent,
    SecurityAlertEvent,
    StateUpdateEvent,
    SubAgentEvent,
)
from .orchestrator import GroupOrchestrator, SpeakerRouter
from .roles import AgentRole, BUILTIN_ROLES
from .state import GroupState

__all__ = [
    "AgentRole",
    "BUILTIN_ROLES",
    "GroupState",
    "GroupOrchestrator",
    "SpeakerRouter",
    "MessageEvent",
    "StateUpdateEvent",
    "PhaseEvent",
    "SubAgentEvent",
    "SecurityAlertEvent",
]
