"""GroupOrchestrator: the multi-agent collaboration loop.

Drives the four cats (planner/executor/reviewer; validator is a Phase-2 hook)
through a shared discussion history + global state. Each turn:
  1. pick a speaker (autonomous hand-off via last message.to, else LLM route)
  2. that cat runs an inner tool_calls loop (conversation + business tools)
     until it produces a text reply (its utterance) or calls send_message
  3. side effects (messages / state / sub-agents) emit events into a pending
     queue, which the run loop yields to the caller

Reuses sop-agent's LLMRouter / ToolRegistry / ToolExecutor / event stream.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Iterator

from ..harness.events import DoneEvent, TurnEvent
from ..harness.tracer import Tracer
from ..llm.base import Message, tool_result_message
from ..llm.router import LLMRouter
from ..tools.base import to_openai_schema
from ..tools.executor import ToolExecutor
from ..tools.registry import ToolRegistry
from .events import MessageEvent, PhaseEvent, StateUpdateEvent, SubAgentEvent
from .roles import AgentRole
from .state import GroupState
from .tools import (
    BroadcastTool,
    DelegateTool,
    FinishTaskTool,
    SendMessageTool,
    UpdateStateTool,
)

_CHAT_ROLES = ("planner", "executor", "reviewer")


class SpeakerRouter:
    """Fallback speaker picker (LLM decide or injected callable).

    Autonomous hand-off (directed send_message) is handled by the orchestrator,
    which knows the current turn's message range; this is only the fallback when
    no hand-off occurred.
    """

    def __init__(self, llm_router: LLMRouter, llm_config: Any, decide: Callable[[GroupState, list[Message]], str] | None = None) -> None:
        self._router = llm_router
        self._llm_config = llm_config
        self._decide = decide  # injectable for tests

    def next(self, state: GroupState, messages: list[Message]) -> str:
        if self._decide is not None:
            return self._decide(state, messages)
        return self._llm_decide(state, messages)

    def _llm_decide(self, state: GroupState, messages: list[Message]) -> str:
        recent = "\n".join(f"[{m.get('name','?')}→{m.get('to') or 'all'}]: {(m.get('content') or '')[:80]}" for m in messages[-6:])
        prompt = (
            f"任务:{state.task}\n当前阶段:{state.phase}\n轮次:{state.turn}\n\n最近讨论:\n{recent}\n\n"
            f"下一发言者应是 planner/executor/reviewer 中的哪一位?只输出角色名(一个词)。"
        )
        try:
            resp = self._router.chat(
                [{"role": "system", "content": "你决定多智能体讨论的下一发言者。只输出角色名。"},
                 {"role": "user", "content": prompt}],
                [], self._llm_config,
            )
            name = (resp.content or "").strip().lower()
            if name in _CHAT_ROLES:
                return name
        except Exception:
            pass
        return "planner"  # safe fallback


class GroupOrchestrator:
    def __init__(
        self,
        task: str,
        roles: dict[str, AgentRole],
        llm_router: LLMRouter,
        business_registry: ToolRegistry,
        router: SpeakerRouter | None = None,
        max_turns: int = 30,
        max_inner: int = 8,
        tracer: Tracer | None = None,
    ) -> None:
        self.task = task
        self.roles = roles
        self.llm_router = llm_router
        self.business_registry = business_registry
        self.state = GroupState(task=task)
        self.messages: list[Message] = []
        self._pending: list[Any] = []
        self._pid_counter = 0
        self.max_turns = max_turns
        self.max_inner = max_inner
        self.tracer = tracer or Tracer("meowwork")
        # default router uses the planner's llm config for decisions
        self.router = router or SpeakerRouter(llm_router, roles["planner"].llm)

    # -- shared mutators (called by conversation tools) -------------------
    def add_message(self, frm: str, to: str | None, content: str) -> None:
        msg: Message = {"role": "assistant", "name": frm, "content": content, "to": to}
        self.messages.append(msg)
        self._emit(MessageEvent(frm=frm, to=to, content=content))

    def state_update(self, key: str, value: Any, by: str) -> tuple[bool, Any]:
        old_phase = self.state.phase
        ok, old = self.state.update(key, value, by)
        if ok:
            self._emit(StateUpdateEvent(key=key, old=old, new=value, by=by))
            if key == "phase" and value != old_phase:
                self._emit(PhaseEvent(from_phase=old_phase, to_phase=value, by=by))
        return ok, old

    def delegate(self, by: str, role_name: str, task: str) -> str:
        if role_name not in self.roles:
            return f"ERROR: 未知角色 '{role_name}'"
        self._pid_counter += 1
        pid = self._pid_counter
        self.state.sub_agents.append({"pid": pid, "role": role_name, "task": task, "status": "running"})
        self._emit(SubAgentEvent(pid=pid, role=role_name, task=task, status="running"))
        try:
            result = self._run_subagent(role_name, task)
        except Exception as exc:  # noqa: BLE001
            result = f"ERROR: 子 agent 失败: {exc!r}"
            self.state.sub_agents[-1]["status"] = "failed"
            self._emit(SubAgentEvent(pid=pid, role=role_name, task=task, status="failed"))
            return result
        for sa in self.state.sub_agents:
            if sa["pid"] == pid:
                sa["status"] = "done"
        self._emit(SubAgentEvent(pid=pid, role=role_name, task=task, status="done"))
        return result

    def _emit(self, ev: Any) -> None:
        self._pending.append(ev)

    def _drain(self) -> Iterator[Any]:
        while self._pending:
            yield self._pending.pop(0)

    # -- per-role tool setup ---------------------------------------------
    def _convo_tools(self, role: AgentRole) -> list:
        tools = []
        if "send_message" in role.tools:
            tools.append(SendMessageTool(self, role.name))
        if "broadcast" in role.tools:
            tools.append(BroadcastTool(self, role.name))
        if "update_state" in role.tools and role.can_update_state:
            tools.append(UpdateStateTool(self, role.name))
        if "delegate" in role.tools and role.can_delegate:
            tools.append(DelegateTool(self, role.name))
        if role.name == "planner":
            tools.append(FinishTaskTool(self, role.name))
        return tools

    def _business_tools(self, role: AgentRole) -> list:
        out = []
        for n in role.tools:
            if n in ("send_message", "broadcast", "update_state", "delegate", "finish_task"):
                continue
            if self.business_registry.has(n):
                out.append(self.business_registry.get(n))
        return out

    # -- message building -------------------------------------------------
    def _history_text(self) -> str:
        if not self.messages:
            return "(尚无讨论)"
        lines = []
        for m in self.messages:
            name = m.get("name", "?")
            to = m.get("to")
            tgt = f"→{to}" if to else "(广播)"
            lines.append(f"[{name}{tgt}]: {m.get('content','')}")
        return "\n".join(lines)

    def _build_agent_messages(self, role: AgentRole) -> list[Message]:
        system = role.system_prompt + "\n\n## 当前全局状态\n```json\n" + json.dumps(
            self.state.to_dict(), ensure_ascii=False, indent=2
        ) + "\n```"
        user = (
            f"## 讨论历史\n{self._history_text()}\n\n"
            f"现在轮到你({role.name}/{role.persona})发言。根据职责调工具或回复。"
        )
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    # -- inner loop: one agent's turn ------------------------------------
    def _run_agent_turn(self, role: AgentRole) -> Iterator[Any]:
        conv = self._convo_tools(role)
        biz = self._business_tools(role)
        reg = ToolRegistry()
        for t in conv + biz:
            try:
                reg.register(t)
            except ValueError:
                pass  # dup name (shouldn't happen)
        executor = ToolExecutor(reg)
        schemas = [to_openai_schema(t) for t in conv + biz]
        messages = self._build_agent_messages(role)

        for inner in range(self.max_inner):
            resp = self.llm_router.chat(messages, schemas, role.llm)
            tc_dicts = [{"id": getattr(tc, "id", ""), "function": {"name": tc.name, "arguments": tc.arguments}} for tc in resp.tool_calls]
            self.tracer.turn(role.name, self.state.turn, "assistant", resp.content, tc_dicts)
            yield TurnEvent(role.name, self.state.turn, resp.content, tc_dicts)
            messages.append(resp.assistant_message())
            if not resp.tool_calls:
                # text reply = this agent's broadcast utterance
                if resp.content:
                    self.add_message(role.name, None, resp.content)
                yield from self._drain()
                return
            for tc in resp.tool_calls:
                results = executor.batch([tc])
                r = results[0]
                messages.append(tool_result_message(tc.id, r.content))
            yield from self._drain()
        # max_inner reached without a final reply
        yield from self._drain()

    # -- sub-agent (fresh context, business tools only) ------------------
    def _run_subagent(self, role_name: str, task: str) -> str:
        role = self.roles[role_name]
        biz = self._business_tools(role)
        reg = ToolRegistry()
        for t in biz:
            try:
                reg.register(t)
            except ValueError:
                pass
        executor = ToolExecutor(reg)
        schemas = [to_openai_schema(t) for t in biz]
        messages: list[Message] = [
            {"role": "system", "content": role.system_prompt + "\n\n## 子任务\n" + task},
            {"role": "user", "content": task},
        ]
        for inner in range(self.max_inner):
            resp = self.llm_router.chat(messages, schemas, role.llm)
            messages.append(resp.assistant_message())
            if not resp.tool_calls:
                return resp.content or "(无输出)"
            for tc in resp.tool_calls:
                r = executor.batch([tc])[0]
                messages.append(tool_result_message(tc.id, r.content))
        return "(子 agent 达到最大轮次)"

    # -- next speaker: autonomous hand-off (this turn) then router fallback ----
    def _next_speaker(self, just_spoke: str | None, turn_start_idx: int) -> str:
        # hand-off: a directed send_message(to=X) sent by `just_spoke` during the
        # turn that just ended (messages[turn_start_idx:]) picks X next.
        if just_spoke is not None:
            for m in self.messages[turn_start_idx:]:
                if m.get("name") == just_spoke and m.get("to") in _CHAT_ROLES:
                    return m["to"]
        else:
            # initial/resume: most recent directed message overall
            for m in reversed(self.messages):
                if m.get("to") in _CHAT_ROLES:
                    return m["to"]
        return self.router.next(self.state, self.messages)

    # -- main loop --------------------------------------------------------
    def run_events(self) -> Iterator[Any]:
        # initial speaker: planner for a fresh run, else hand-off/fallback
        speaker = "planner" if not self.messages else self._next_speaker(None, 0)
        if speaker not in _CHAT_ROLES:
            speaker = "planner"
        while not self.state.finished and self.state.turn < self.max_turns:
            turn_start_idx = len(self.messages)
            yield from self._run_agent_turn(self.roles[speaker])
            self.state.turn += 1
            if self.state.finished:
                break
            speaker = self._next_speaker(speaker, turn_start_idx)
            if speaker not in _CHAT_ROLES:
                speaker = "planner"
        success = self.state.finished
        yield DoneEvent(self.tracer.finalize(success))
