"""Human-in-the-loop approval policy.

Shared by SOP mode (Engine) and autonomous mode (AutonomousAgent).
Two granularities:
  - action-level : certain tool calls require approval before execution
  - stage-level  : a step / subgoal boundary requires approval before proceeding
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ApprovalPolicy:
    # action-level: tools named here (or all tools) require approval before running
    approve_tools: set[str] = field(default_factory=set)
    approve_all_tools: bool = False
    # tools explicitly allowed for the rest of the session (no more prompts)
    approved_always: set[str] = field(default_factory=set)
    # stage-level: approve before each step (SOP) / each subgoal (autonomous)
    approve_steps: bool = False
    approve_subgoals: bool = False

    def tool_needs_approval(self, name: str) -> bool:
        if name in self.approved_always:
            return False
        return self.approve_all_tools or name in self.approve_tools

    def step_needs_approval(self, require_approval_flag: bool) -> bool:
        return self.approve_steps or require_approval_flag
