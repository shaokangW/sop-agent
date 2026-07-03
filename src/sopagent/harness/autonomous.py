"""Autonomous agent: task-driven self-directed loop with adaptive planning.

The agent receives a natural-language task + the full tool set and drives its
own loop. It self-judges task complexity:
  - COMPLEX task: the agent calls `plan(subgoals)` to break it down, then works
    through subgoals one by one, calling `subgoal_done` after each (which can
    trigger stage-level approval).
  - SIMPLE task: the agent uses tools directly and calls `finish` when done.

Completion is declared via `finish` (or a final answer with no tool calls).
Action-level and stage-level approval are supported via ApprovalPolicy.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Callable, Iterator

from ..llm.base import Message, tool_result_message
from ..llm.router import LLMRouter
from ..prompt_builder import build as build_prompt
from ..sop.schema import LlmConfig
from ..tools.base import to_openai_schema
from ..tools.executor import ToolExecutor
from ..tools.registry import ToolRegistry
from .approval import ApprovalPolicy
from .artifacts import ArtifactStore
from .events import ApprovalRequest, DoneEvent, Event, ToolExecutedEvent, TurnEvent
from .tracer import StepRecord, Tracer

_FINISH_SCHEMA = {
    "type": "function",
    "function": {
        "name": "finish",
        "description": "Call this when the task is fully complete. Provide a short summary of the result.",
        "parameters": {
            "type": "object",
            "properties": {"summary": {"type": "string", "description": "Summary of what was accomplished"}},
            "required": ["summary"],
        },
    },
}

_PLAN_SCHEMA = {
    "type": "function",
    "function": {
        "name": "plan",
        "description": "For a COMPLEX task: break it into an ordered list of subgoals, then work through them one by one. Skip this for simple tasks.",
        "parameters": {
            "type": "object",
            "properties": {
                "subgoals": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Ordered list of concrete subgoals.",
                }
            },
            "required": ["subgoals"],
        },
    },
}

_SUBGOAL_DONE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "subgoal_done",
        "description": "Call this when the current subgoal is complete. Advances to the next subgoal (or to finish if all done).",
        "parameters": {"type": "object", "properties": {}},
    },
}

_SYSTEM = (
    "You are an autonomous agent. Complete the user's task using the available tools.\n"
    "- For a COMPLEX task, first call `plan` to break it into subgoals, then work through them one by one, "
    "calling `subgoal_done` after each.\n"
    "- For a SIMPLE task, use tools directly and call `finish` when done.\n"
    "When all subgoals are done (or for a simple task, when the task is done), call `finish` with a summary. "
    "Do not stop until the task is done or you are certain it cannot be done."
)

_BUILTIN_TOOL_NAMES = {"finish", "plan", "subgoal_done"}


class AutonomousAgent:
    def __init__(
        self,
        task: str,
        router: LLMRouter,
        tool_registry: ToolRegistry,
        tool_executor: ToolExecutor,
        artifacts: ArtifactStore,
        llm_config: LlmConfig,
        tracer: Tracer | None = None,
        on_token: Callable[[str, str], None] | None = None,
        approval_policy: ApprovalPolicy | None = None,
        max_turns: int = 20,
        available_skills: list[dict] | None = None,
    ) -> None:
        self.task = task
        self.router = router
        self.tool_registry = tool_registry
        self.tool_executor = tool_executor
        self.artifacts = artifacts
        self.llm_config = llm_config
        self.tracer = tracer or Tracer("autonomous")
        self.on_token = on_token
        self.approval_policy = approval_policy or ApprovalPolicy()
        self.max_turns = max_turns
        self.summary: str | None = None
        self.plan: list[str] | None = None
        self.subgoal_idx: int = 0
        self.available_skills = available_skills or []

    def run(self) -> Any:
        gen = self.run_events()
        trace: Any = None
        ev = next(gen)
        try:
            while True:
                if isinstance(ev, ApprovalRequest):
                    ev = gen.send("approve")
                elif isinstance(ev, DoneEvent):
                    trace = ev.trace
                    break
                else:
                    ev = next(gen)
        except StopIteration:
            pass
        return trace

    def _current_system(self) -> str:
        return build_prompt("autonomous", plan=self.plan, subgoal_idx=self.subgoal_idx, available_skills=self.available_skills)

    def run_events(self) -> Iterator[Event]:
        messages: list[Message] = [
            {"role": "system", "content": self._current_system()},
            {"role": "user", "content": self.task},
        ]
        tool_schemas = (
            [to_openai_schema(t) for t in self.tool_registry.all()]
            + [_PLAN_SCHEMA, _SUBGOAL_DONE_SCHEMA, _FINISH_SCHEMA]
        )
        success = False
        try:
            for turn in range(self.max_turns):
                messages[0] = {"role": "system", "content": self._current_system()}
                if self.on_token is not None:
                    resp = self.router.chat_stream(
                        messages, tool_schemas, self.llm_config,
                        on_delta=lambda d: self.on_token("task", d),
                    )
                else:
                    resp = self.router.chat(messages, tool_schemas, self.llm_config)
                tc_dicts = [asdict(tc) for tc in resp.tool_calls]
                self.tracer.turn("task", turn, "assistant", resp.content, tc_dicts, usage=resp.usage)
                yield TurnEvent("task", turn, resp.content, tc_dicts)
                messages.append(resp.assistant_message())

                if not resp.tool_calls:
                    # final answer with no tool call -> completion
                    if self.approval_policy.approve_subgoals:
                        req = ApprovalRequest(
                            id="finish",
                            reason="Agent produced a final answer; confirm task completion",
                            payload={"kind": "subgoal", "content": resp.content},
                        )
                        if (yield req) != "approve":
                            messages.append({"role": "user", "content": "The task is not complete yet. Keep working."})
                            continue
                    self.summary = resp.content
                    success = True
                    break

                for tc in resp.tool_calls:
                    if tc.name == "plan":
                        subgoals = list(tc.arguments.get("subgoals") or [])
                        self.plan = subgoals
                        self.subgoal_idx = 0
                        msg = (
                            f"Plan accepted ({len(subgoals)} subgoals). Start with subgoal 0: {subgoals[0]}"
                            if subgoals
                            else "Plan accepted but empty. Call `finish` or define subgoals."
                        )
                        messages.append(tool_result_message(tc.id, msg))
                        yield ToolExecutedEvent("task", tc.id, "plan", True, msg)
                        continue

                    if tc.name == "subgoal_done":
                        if not self.plan or self.subgoal_idx >= len(self.plan):
                            msg = "No active subgoal. Call `finish` if done, or `plan` first."
                            messages.append(tool_result_message(tc.id, msg))
                            yield ToolExecutedEvent("task", tc.id, "subgoal_done", False, msg)
                            continue
                        cur = self.plan[self.subgoal_idx]
                        if self.approval_policy.approve_subgoals:
                            req = ApprovalRequest(
                                id=f"subgoal:{self.subgoal_idx}",
                                reason=f"Subgoal {self.subgoal_idx} complete: {cur}",
                                payload={"kind": "subgoal", "index": self.subgoal_idx, "subgoal": cur},
                            )
                            if (yield req) != "approve":
                                messages.append(tool_result_message(tc.id, f"User: subgoal '{cur}' not complete, keep working"))
                                yield ToolExecutedEvent("task", tc.id, "subgoal_done", False, "rejected")
                                continue
                        self.subgoal_idx += 1
                        if self.subgoal_idx >= len(self.plan):
                            msg = "All subgoals done. Call `finish` with a summary."
                        else:
                            msg = f"Subgoal done. Next subgoal {self.subgoal_idx}: {self.plan[self.subgoal_idx]}"
                        messages.append(tool_result_message(tc.id, msg))
                        yield ToolExecutedEvent("task", tc.id, "subgoal_done", True, msg)
                        continue

                    if tc.name == "finish":
                        if self.approval_policy.approve_subgoals:
                            req = ApprovalRequest(
                                id="finish",
                                reason="Agent called `finish`; confirm task completion",
                                payload={"kind": "subgoal", "summary": tc.arguments.get("summary")},
                            )
                            if (yield req) != "approve":
                                messages.append(tool_result_message(tc.id, "User: task not complete, keep working"))
                                continue
                        self.summary = tc.arguments.get("summary")
                        success = True
                        break

                    # normal tool: action-level approval + execution
                    if self._needs_tool_approval(tc.name):
                        req = ApprovalRequest(
                            id=f"tool:{tc.id}",
                            reason=f"Approve tool '{tc.name}'",
                            payload={"kind": "tool_call", "tool_call_id": tc.id, "name": tc.name, "arguments": tc.arguments},
                        )
                        if (yield req) != "approve":
                            messages.append(tool_result_message(tc.id, f"User rejected tool '{tc.name}'"))
                            yield ToolExecutedEvent("task", tc.id, tc.name, False, "rejected by user")
                            continue
                    results = self.tool_executor.batch([tc])
                    r = results[0]
                    yield ToolExecutedEvent("task", tc.id, tc.name, r.ok, r.content)
                    self.tracer.turn("task", turn, "tool", r.content)
                    messages.append(tool_result_message(tc.id, r.content))
                if success:
                    break
        except Exception:
            self._record(success)
            raise
        trace = self._record(success)
        yield DoneEvent(trace)

    def _needs_tool_approval(self, name: str) -> bool:
        if name in self.approval_policy.approved_always:
            return False
        if self.approval_policy.tool_needs_approval(name):
            return True
        if self.tool_registry.has(name):
            return bool(getattr(self.tool_registry.get(name), "requires_approval", False))
        return False

    def _record(self, success: bool) -> Any:
        self.tracer.step(
            StepRecord(
                step_id="task",
                status="succeeded" if success else "failed",
                attempts=1,
                turns=self.tracer.turns_for("task"),
                duration=None,
                output_preview=(self.summary or "")[:200],
            )
        )
        return self.tracer.finalize(success)
