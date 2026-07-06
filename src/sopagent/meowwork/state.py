"""GroupState: the single source of truth for a MeowWork run.

All agents read this; Planner/Executor/Reviewer/Validator update their
permitted fields via the `update_state` tool. Serialized to dict for WebSocket
broadcast and frontend subscription.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class GroupState:
    task: str
    phase: str = "analyze"  # analyze|execute|review|validate|done
    plan_tree: dict[str, Any] = field(default_factory=dict)
    # plan_tree[step_id] = {"desc": str, "status": str, "assignee": str, "artifact": str|None}
    current_artifact: str | None = None
    review_feedback: str | None = None
    review_pass: bool | None = None
    security_alerts: list[dict[str, Any]] = field(default_factory=list)
    sub_agents: list[dict[str, Any]] = field(default_factory=list)
    # sub_agents entry: {"pid": int, "role": str, "task": str, "status": str}
    turn: int = 0
    finished: bool = False
    summary: str | None = None
    started_at: float = field(default_factory=time.time)

    # who may update which field
    FIELD_OWNERS: dict[str, str] = field(default_factory=lambda: {
        "plan_tree": "planner",
        "phase": "planner",
        "summary": "planner",
        "finished": "planner",
        "current_artifact": "executor",
        "review_feedback": "reviewer",
        "review_pass": "reviewer",
        "security_alerts": "validator",
    })

    def can_update(self, key: str, by: str) -> bool:
        owner = self.FIELD_OWNERS.get(key)
        return owner is None or owner == by

    def update(self, key: str, value: Any, by: str) -> tuple[bool, Any]:
        """Return (ok, old_value). ok=False if field unknown or not permitted."""
        if not hasattr(self, key):
            return False, None
        if not self.can_update(key, by):
            return False, getattr(self, key)
        old = getattr(self, key)
        setattr(self, key, value)
        return True, old

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "phase": self.phase,
            "plan_tree": self.plan_tree,
            "current_artifact": self.current_artifact,
            "review_feedback": self.review_feedback,
            "review_pass": self.review_pass,
            "security_alerts": list(self.security_alerts),
            "sub_agents": list(self.sub_agents),
            "turn": self.turn,
            "finished": self.finished,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "GroupState":
        s = cls(task=d.get("task", ""))
        s.phase = d.get("phase", "analyze")
        s.plan_tree = d.get("plan_tree", {})
        s.current_artifact = d.get("current_artifact")
        s.review_feedback = d.get("review_feedback")
        s.review_pass = d.get("review_pass")
        s.security_alerts = list(d.get("security_alerts", []))
        s.sub_agents = list(d.get("sub_agents", []))
        s.turn = d.get("turn", 0)
        s.finished = d.get("finished", False)
        s.summary = d.get("summary")
        return s
