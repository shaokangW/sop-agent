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
import threading
import time
from typing import Any, Callable, Iterator

from ..harness.events import DoneEvent, ToolExecutedEvent, TurnEvent
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
from .validator import ValidatorHook

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

    def next(self, state: GroupState, messages: list[Message]) -> str | None:
        if self._decide is not None:
            return self._decide(state, messages)
        return self._llm_route(state, messages)

    def _llm_route(self, state: GroupState, messages: list[Message]) -> str | None:
        """LLM decides who speaks next, or None if the discussion is naturally done."""
        recent = "\n".join(f"[{m.get('name','?')}→{m.get('to') or 'all'}]: {(m.get('content') or '')[:80]}" for m in messages[-6:])
        prompt = (
            f"任务:{state.task}\n当前阶段:{state.phase}\n轮次:{state.turn}\n\n最近讨论:\n{recent}\n\n"
            f"下一发言者应是 planner/executor/reviewer/validator 中的哪一位?"
            f"如果当前讨论已自然结束(无人需要再发言,或任务已完成),输出 none。"
            f"只输出一个词(角色名或 none)。"
        )
        try:
            resp = self._router.chat(
                [{"role": "system", "content": "你决定多智能体讨论的下一发言者,或判断讨论是否结束。只输出角色名或 none。"},
                 {"role": "user", "content": prompt}],
                [], self._llm_config,
            )
            name = (resp.content or "").strip().lower()
            if name == "none":
                return None
            if name in _CHAT_ROLES:
                return name
        except Exception:
            pass
        return "planner"  # safe fallback (don't terminate unexpectedly on LLM error)


class GroupOrchestrator:
    def __init__(
        self,
        task: str,
        roles: dict[str, AgentRole],
        llm_router: LLMRouter,
        business_registry: ToolRegistry,
        router: SpeakerRouter | None = None,
        max_turns: int = 8,
        max_inner: int = 8,
        tracer: Tracer | None = None,
        validator_hook: ValidatorHook | None = None,
        max_turns_per_send: int = 4,
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
        self.max_turns_per_send = max_turns_per_send
        self.tracer = tracer or Tracer("meowwork")
        # token streaming sink (set by _drive_owner in server mode); None in tests
        self.on_token: Callable[[str, str], None] | None = None
        # catnip: global pause (set → freeze between turns, resume on clear)
        self._pause_event = threading.Event()
        # default router uses the planner's llm config for decisions
        self.router = router or SpeakerRouter(llm_router, roles["planner"].llm)
        # zero-trust validator hook (auto-build unless injected/disabled)
        if validator_hook is not None:
            self._validator = validator_hook
        elif "validator" in roles:
            self._validator = ValidatorHook(llm_router, roles["validator"].llm, on_alert=self._emit)
        else:
            self._validator = None

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
        self.state.sub_agents.append({"pid": pid, "role": role_name, "task": task, "status": "running", "started_at": time.time()})
        self._emit(SubAgentEvent(pid=pid, role=role_name, task=task, status="running"))
        try:
            result = self._run_subagent(role_name, task)
        except Exception as exc:  # noqa: BLE001
            result = f"ERROR: 子 agent 失败: {exc!r}"
            self.state.sub_agents[-1]["status"] = "failed"
            self.state.sub_agents[-1]["duration"] = time.time() - self.state.sub_agents[-1]["started_at"]
            self._emit(SubAgentEvent(pid=pid, role=role_name, task=task, status="failed"))
            return result
        for sa in self.state.sub_agents:
            if sa["pid"] == pid:
                sa["status"] = "done"
                sa["duration"] = time.time() - sa["started_at"]
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
        executor = ToolExecutor(reg, pre_execution_hooks=[self._validator] if self._validator else [])
        schemas = [to_openai_schema(t) for t in conv + biz]
        messages = self._build_agent_messages(role)

        for inner in range(self.max_inner):
            # stream tokens live when an on_token sink is wired (e.g. by _drive_owner);
            # fall back to non-streaming chat in tests where on_token is None
            if self.on_token is not None:
                resp = self.llm_router.chat_stream(
                    messages, schemas, role.llm,
                    on_delta=lambda d: self.on_token(role.name, d),
                )
            else:
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
                yield ToolExecutedEvent(role.name, tc.id, tc.name, r.ok, r.content)
                self.tracer.turn(role.name, self.state.turn, "tool", r.content)
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
        executor = ToolExecutor(reg, pre_execution_hooks=[self._validator] if self._validator else [])
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
    def _next_speaker(self, just_spoke: str | None, turn_start_idx: int) -> str | None:
        """Return the next speaker, or None if no one wants to speak (natural end)."""
        if just_spoke is not None:
            # hand-off: a directed send_message(to=X) sent by `just_spoke` this turn
            for m in self.messages[turn_start_idx:]:
                if m.get("name") == just_spoke and m.get("to") in _CHAT_ROLES:
                    return m["to"]
        else:
            # initial/resume: most recent directed message overall
            for m in reversed(self.messages):
                if m.get("to") in _CHAT_ROLES:
                    return m["to"]
        # LLM route: may return None (no one wants to speak → terminate)
        return self.router.next(self.state, self.messages)

    def _parse_mention(self, text: str) -> str | None:
        """Parse @executor / @reviewer / @planner from a user message."""
        low = (text or "").lower()
        for role in self.roles:
            if f"@{role}" in low:
                return role
        return None

    # -- main loop --------------------------------------------------------
    def run_events(self) -> Iterator[Any]:
        # initial speaker: planner for a fresh run, else hand-off/fallback
        speaker = "planner" if not self.messages else self._next_speaker(None, 0)
        if speaker not in _CHAT_ROLES:
            speaker = "planner"
        while not self.state.finished and self.state.turn < self.max_turns:
            # catnip global pause: block here (background thread) while paused
            while self._pause_event.is_set():
                self._pause_event.wait(timeout=0.5)
            turn_start_idx = len(self.messages)
            yield from self._run_agent_turn(self.roles[speaker])
            self.state.turn += 1
            if self.state.finished:
                break
            speaker = self._next_speaker(speaker, turn_start_idx)
            if speaker is None or speaker not in _CHAT_ROLES:
                break  # no one wants to speak → terminate
        success = self.state.finished
        yield DoneEvent(self.tracer.finalize(success))

    # -- task mode: user sends a requirement, cats collaborate to completion --
    def run_task(self, user_message: str) -> Iterator[Any]:
        """Append the user's requirement to the shared history, let the four cats
        collaborate until ``finish_task`` (or ``max_turns``), then return control.

        History (``self.messages``) is preserved across tasks, so the group has
        memory: the next ``run_task`` sees prior turns + artifacts.
        """
        self.messages.append({"role": "user", "name": "user", "content": user_message, "to": None})
        self.state.finished = False
        self.state.summary = None
        # @mention routing: user can direct with @executor / @reviewer / @planner;
        # otherwise planner responds first
        speaker = self._parse_mention(user_message) or "planner"
        turns_this_task = 0
        while not self.state.finished and turns_this_task < self.max_turns:
            while self._pause_event.is_set():
                self._pause_event.wait(timeout=0.5)
            turn_start_idx = len(self.messages)
            yield from self._run_agent_turn(self.roles[speaker])
            self.state.turn += 1
            turns_this_task += 1
            if self.state.finished:
                break
            # intelligent termination: router returns None = no one wants to speak
            nxt = self._next_speaker(speaker, turn_start_idx)
            if nxt is None:
                self.state.finished = True
                self.state.summary = "(讨论自然结束)"
                break
            speaker = nxt
        yield DoneEvent(self.tracer.finalize(self.state.finished))

    # -- catnip pause control --------------------------------------------
    def pause(self) -> None:
        self._pause_event.set()

    def resume(self) -> None:
        self._pause_event.clear()

    @property
    def is_paused(self) -> bool:
        return self._pause_event.is_set()
