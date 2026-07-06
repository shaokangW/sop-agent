"""Conversation tools for MeowWork agents.

Contextual (like TaskTool/SkillTool): each holds a back-reference to the
GroupOrchestrator and the speaking role's name. Side effects (appending to the
shared discussion, updating state, spawning sub-agents) emit events into the
orchestrator's pending queue, which the run loop yields to the caller.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .orchestrator import GroupOrchestrator


class SendMessageTool:
    name = "send_message"
    description = "Send a directed message to another cat (planner/executor/reviewer). Triggers hand-off: the target speaks next."
    parameters = {
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "recipient role: planner|executor|reviewer"},
            "content": {"type": "string", "description": "message content"},
        },
        "required": ["to", "content"],
    }

    def __init__(self, orch: Any, by: str) -> None:
        self._orch = orch
        self._by = by

    def run(self, args: dict[str, Any]) -> str:
        to = args.get("to", "")
        content = args.get("content", "")
        self._orch.add_message(self._by, to, content)
        return f"已发送给 {to}: {content[:120]}"


class BroadcastTool:
    name = "broadcast"
    description = "Broadcast a message to all cats (no specific target). Use for announcements visible to everyone."
    parameters = {
        "type": "object",
        "properties": {"content": {"type": "string"}},
        "required": ["content"],
    }

    def __init__(self, orch: Any, by: str) -> None:
        self._orch = orch
        self._by = by

    def run(self, args: dict[str, Any]) -> str:
        content = args.get("content", "")
        self._orch.add_message(self._by, None, content)
        return f"已广播: {content[:120]}"


class UpdateStateTool:
    name = "update_state"
    description = "Update a field of the shared global state. You may only update fields you own (planner: plan_tree/phase/summary/finished; executor: current_artifact; reviewer: review_feedback/review_pass). value can be string/bool/object."
    parameters = {
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "state field name"},
            "value": {"description": "new value (string/boolean/object)"},
        },
        "required": ["key", "value"],
    }

    def __init__(self, orch: Any, by: str) -> None:
        self._orch = orch
        self._by = by

    def run(self, args: dict[str, Any]) -> str:
        key = args.get("key", "")
        value = args.get("value")
        ok, old = self._orch.state_update(key, value, self._by)
        if not ok:
            return f"ERROR: 无权限或未知字段 '{key}'(你的角色无权改此项)"
        return f"已更新 {key}: {json.dumps(old, ensure_ascii=False)[:60]} → {json.dumps(value, ensure_ascii=False)[:60]}"


class DelegateTool:
    name = "delegate"
    description = "Spawn a sub-agent (logical PID) of the given role to work on a self-contained subtask in a fresh context. Returns the sub-agent's result. Only planner/executor may delegate."
    parameters = {
        "type": "object",
        "properties": {
            "role": {"type": "string", "description": "target role: executor|reviewer"},
            "task": {"type": "string", "description": "detailed, self-contained subtask"},
        },
        "required": ["role", "task"],
    }

    def __init__(self, orch: Any, by: str) -> None:
        self._orch = orch
        self._by = by

    def run(self, args: dict[str, Any]) -> str:
        role = args.get("role", "")
        task = args.get("task", "")
        if not role or not task:
            return "ERROR: role 和 task 必填"
        return self._orch.delegate(self._by, role, task)


class FinishTaskTool:
    name = "finish_task"
    description = "Mark the whole task as complete with a summary. Only planner may call this."
    parameters = {
        "type": "object",
        "properties": {"summary": {"type": "string"}},
        "required": ["summary"],
    }

    def __init__(self, orch: Any, by: str) -> None:
        self._orch = orch
        self._by = by

    def run(self, args: dict[str, Any]) -> str:
        summary = args.get("summary", "")
        ok, _ = self._orch.state_update("finished", True, self._by)
        if not ok:
            return "ERROR: 只有 planner 能 finish_task"
        self._orch.state_update("summary", summary, self._by)
        return f"任务完成: {summary[:120]}"
