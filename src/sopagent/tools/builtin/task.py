"""Delegation tool: spawn a sub-agent with a fresh context for a self-contained subtask.

The sub-agent runs autonomously (plan/finish) with the parent's tool set minus
`task` (to bound recursion), limited by max_depth. Its summary + tool log are
returned to the parent as the tool result, keeping the parent's context lean.

v1 limitation: the sub-agent auto-approves its own dangerous tool calls within
its event stream (approval of the parent `task` call is the gate). Sub-agent
events are optionally forwarded via ``on_event`` for observability; true
approval re-surfacing (pausing the parent to re-prompt the user from within a
sub-agent) is a future enhancement.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:  # type-only; avoids a tools <-> harness circular import at runtime
    from ...harness.approval import ApprovalPolicy
    from ...harness.artifacts import ArtifactStore
    from ...harness.autonomous import AutonomousAgent
    from ...harness.events import Event
    from ...llm.router import LLMRouter
    from ...sop.schema import LlmConfig
    from ..registry import ToolRegistry


@dataclass
class SubAgentContext:
    """Dependencies a TaskTool uses to spawn and drive a sub-agent."""

    router: Any  # LLMRouter
    tool_registry: Any  # ToolRegistry
    llm_config: Any  # LlmConfig
    artifacts: Any  # ArtifactStore
    approval_policy: Any  # ApprovalPolicy
    depth: int = 0
    max_depth: int = 2
    max_turns: int = 15
    on_event: Callable[[Any], None] | None = None  # Callable[[Event], None]

    def delegate(self, description: str) -> str:
        from ...harness.autonomous import AutonomousAgent
        from ...harness.tracer import Tracer
        from ..executor import ToolExecutor
        from ..registry import ToolRegistry

        if self.depth >= self.max_depth:
            return (
                f"ERROR: delegation depth limit ({self.max_depth}) reached; "
                "resolve the subtask directly with your own tools."
            )
        sub_reg = ToolRegistry()
        for t in self.tool_registry.all():
            if t.name == "task":
                continue
            sub_reg.register(t)
        child_depth = self.depth + 1
        if child_depth < self.max_depth:
            sub_reg.register(TaskTool(replace(self, depth=child_depth)))
        agent = AutonomousAgent(
            task=description,
            router=self.router,
            tool_registry=sub_reg,
            tool_executor=ToolExecutor(sub_reg),
            artifacts=self.artifacts,
            llm_config=self.llm_config,
            tracer=Tracer(f"subagent@{child_depth}"),
            approval_policy=self.approval_policy,
            max_turns=self.max_turns,
        )
        return _drive_subagent(agent, self.on_event)


def _drive_subagent(agent: Any, on_event: Callable[[Any], None] | None) -> str:
    from ...harness.events import ApprovalRequest, DoneEvent, ToolExecutedEvent, TurnEvent

    gen = agent.run_events()
    tool_calls: list[str] = []
    last_content: str | None = None
    trace: Any = None
    ev = next(gen)
    try:
        while True:
            if isinstance(ev, ApprovalRequest):
                if on_event:
                    on_event(ev)
                ev = gen.send("approve")
            elif isinstance(ev, DoneEvent):
                trace = ev.trace
                break
            else:
                if on_event:
                    on_event(ev)
                if isinstance(ev, ToolExecutedEvent):
                    mark = "ok" if ev.ok else "fail"
                    tool_calls.append(f"{ev.name}({mark})")
                elif isinstance(ev, TurnEvent) and ev.content:
                    last_content = ev.content
                ev = next(gen)
    except StopIteration:
        pass

    summary = agent.summary or last_content or ""
    success = bool(trace.success) if trace is not None else False
    header = (
        f"Sub-agent completed successfully ({len(tool_calls)} tool call(s))."
        if success
        else f"Sub-agent did NOT complete (gave up after {len(tool_calls)} tool call(s))."
    )
    parts = [header]
    if tool_calls:
        parts.append("Tools used: " + ", ".join(tool_calls))
    if summary:
        parts.append("Summary: " + summary.strip())
    return "\n".join(parts)


class TaskTool:
    name = "task"
    description = (
        "Delegate a self-contained subtask to a sub-agent with a FRESH context "
        "(it does not see this conversation's history). Use for independent, "
        "well-scoped subtasks - especially broad exploration or multi-file work - "
        "to keep the main context lean. The sub-agent runs autonomously and returns "
        "a summary + tool log. Provide a highly detailed, self-contained description; "
        "vague tasks fail."
    )
    parameters = {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "Detailed, self-contained task description for the sub-agent.",
            }
        },
        "required": ["description"],
    }

    def __init__(self, ctx: SubAgentContext) -> None:
        self._ctx = ctx

    def run(self, args: dict[str, Any]) -> str:
        desc = (args.get("description") or "").strip()
        if not desc:
            return "ERROR: 'description' is required."
        return self._ctx.delegate(desc)
