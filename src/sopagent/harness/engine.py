"""Engine: the harness. Two nested loops, exposed as an event stream.

Outer loop  : iterate SOP stages/steps (transition-driven procedure).
Inner loop  : per step, the LLM drives native tool_calls until a final answer.

``run_events()`` is a generator yielding TokenEvent / TurnEvent /
ToolExecutedEvent / ApprovalRequest / DoneEvent. An ApprovalRequest pauses for
human confirmation; resume with ``.send("approve" | "reject")``.
``run()`` is a synchronous wrapper that auto-approves every request.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, Callable, Iterator

from ..llm.base import Message, tool_result_message
from ..llm.router import LLMRouter
from ..prompt_builder import build as build_prompt
from ..sop.schema import SOP, Step
from ..tools.executor import ToolExecutor
from ..tools.registry import ToolRegistry
from .approval import ApprovalPolicy
from .artifacts import ArtifactStore
from .context import Context
from .events import ApprovalRequest, DoneEvent, Event, ToolExecutedEvent, TurnEvent
from .state import StateManager, StepStatus
from .tracer import StepRecord, Tracer
from .transitions import build_namespace, next_stage
from .validator import ValidationFailed, validate_output


class StepLoopExhausted(Exception):
    """Raised when a step hits max_turns without a final answer."""


class Engine:
    def __init__(
        self,
        sop: SOP,
        router: LLMRouter,
        tool_registry: ToolRegistry,
        tool_executor: ToolExecutor,
        artifacts: ArtifactStore,
        tracer: Tracer | None = None,
        state: StateManager | None = None,
        on_token: Callable[[str, str], None] | None = None,
        approval_policy: ApprovalPolicy | None = None,
    ) -> None:
        self.sop = sop
        self.router = router
        self.tool_registry = tool_registry
        self.tool_executor = tool_executor
        self.artifacts = artifacts
        self.tracer = tracer or Tracer(sop.metadata.name)
        self.state = state or StateManager()
        self.on_token = on_token
        self.approval_policy = approval_policy or ApprovalPolicy()

    # -- sync wrapper (auto-approves every request) -----------------------
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

    # -- event-stream driver (transition-driven) --------------------------
    def run_events(self) -> Iterator[Event]:
        ctx = Context(self.sop.variables)
        success = True
        if not self.sop.stages:
            yield DoneEvent(self._finalize(True))
            return
        current = self.sop.stages[0].id
        guard = 0
        try:
            while current is not None:
                guard += 1
                if guard > len(self.sop.stages) * 4:
                    break  # cycle guard
                stage = self.sop.stage_by_id(current)
                stage_ok = True
                for step in stage.steps:
                    # stage-level approval
                    if self.approval_policy.step_needs_approval(step.require_approval):
                        req = ApprovalRequest(
                            id=f"step:{step.id}",
                            reason=f"Approve step '{step.id}': {step.goal}",
                            payload={"kind": "step", "step_id": step.id, "goal": step.goal},
                        )
                        if (yield req) != "approve":
                            st = self.state.get(step.id)
                            st.status = StepStatus.SKIPPED
                            self.tracer.step(
                                StepRecord(step_id=step.id, status="skipped", attempts=0, turns=0, duration=None)
                            )
                            continue
                    ok = yield from self._run_step_events(step, ctx)
                    if not ok:
                        stage_ok = False
                        success = False
                        break
                if not stage_ok:
                    break
                ns = build_namespace(self.sop, ctx, self.state)
                current = next_stage(self.sop, current, ns)
        except Exception:
            success = False
            self._finalize(success)
            raise
        yield DoneEvent(self._finalize(success))

    def _finalize(self, success: bool) -> Any:
        return self.tracer.finalize(success)

    # -- step retry wrapper (generator) -----------------------------------
    def _run_step_events(self, step: Step, ctx: Context) -> Iterator[Event]:
        state = self.state.get(step.id)
        state.begin()
        max_attempts = step.retry.max + 1
        last_err: Exception | None = None
        for attempt in range(max_attempts):
            state.attempts = attempt + 1
            try:
                yield from self._agent_loop_events(step, ctx)
                state.succeed()
                self.tracer.step(
                    StepRecord(
                        step_id=step.id,
                        status=state.status.value,
                        attempts=state.attempts,
                        turns=self.tracer.turns_for(step.id),
                        duration=state.duration,
                        output_preview=_preview(self._step_output(ctx, step.id)),
                    )
                )
                return True
            except ValidationFailed as exc:
                last_err = exc
                continue
            except StepLoopExhausted as exc:
                last_err = exc
                break
        state.fail(str(last_err))
        self.tracer.step(
            StepRecord(
                step_id=step.id,
                status=state.status.value,
                attempts=state.attempts,
                turns=self.tracer.turns_for(step.id),
                duration=state.duration,
                error=str(last_err),
            )
        )
        return False

    def _step_output(self, ctx: Context, step_id: str) -> str | None:
        try:
            return ctx.step_output(step_id)
        except KeyError:
            return None

    # -- inner loop: native tool_calls + per-call approval ----------------
    def _agent_loop_events(self, step: Step, ctx: Context) -> Iterator[Event]:
        messages = self._build_messages(step, ctx)
        tools = self.tool_registry.resolve(step.tools)
        schemas = self.tool_registry.schemas_for(tools)
        llm = self.sop.llm_for(step)

        for turn in range(step.max_turns):
            if self.on_token is not None:
                resp = self.router.chat_stream(
                    messages, schemas, llm,
                    on_delta=lambda d: self.on_token(step.id, d),
                )
            else:
                resp = self.router.chat(messages, schemas, llm)
            tc_dicts = [asdict(tc) for tc in resp.tool_calls]
            self.tracer.turn(step.id, turn, "assistant", resp.content, tc_dicts)
            yield TurnEvent(step.id, turn, resp.content, tc_dicts)
            messages.append(resp.assistant_message())

            if resp.is_final():
                output = resp.content or ""
                if step.expected_output is not None:
                    data = validate_output(output, step.expected_output)
                    output = json.dumps(data, ensure_ascii=False)
                ctx.set_step_output(step.id, output)
                if step.save_artifact:
                    self.artifacts.save(step.save_artifact, output)
                return

            for tc in resp.tool_calls:
                # action-level approval
                if self._needs_tool_approval(tc.name):
                    req = ApprovalRequest(
                        id=f"tool:{tc.id}",
                        reason=f"Approve tool '{tc.name}'",
                        payload={
                            "kind": "tool_call",
                            "tool_call_id": tc.id,
                            "name": tc.name,
                            "arguments": tc.arguments,
                        },
                    )
                    if (yield req) != "approve":
                        msg = tool_result_message(tc.id, f"User rejected tool '{tc.name}'")
                        messages.append(msg)
                        self.tracer.turn(step.id, turn, "tool", f"rejected {tc.name}")
                        yield ToolExecutedEvent(step.id, tc.id, tc.name, False, "rejected by user")
                        continue
                results = self.tool_executor.batch([tc])
                r = results[0]
                yield ToolExecutedEvent(step.id, tc.id, tc.name, r.ok, r.content)
                self.tracer.turn(step.id, turn, "tool", r.content)
                messages.append(tool_result_message(tc.id, r.content))

        raise StepLoopExhausted(step.id)

    def _needs_tool_approval(self, name: str) -> bool:
        if name in self.approval_policy.approved_always:
            return False
        if self.approval_policy.tool_needs_approval(name):
            return True
        if self.tool_registry.has(name):
            return bool(getattr(self.tool_registry.get(name), "requires_approval", False))
        return False

    def _build_messages(self, step: Step, ctx: Context) -> list[Message]:
        system: Message = {
            "role": "system",
            "content": build_prompt("sop", goal=step.goal, expected_output=step.expected_output),
        }
        user: Message = {"role": "user", "content": ctx.interpolate(step.prompt)}
        return [system, user]


def _preview(text: str | None, limit: int = 200) -> str:
    if not text:
        return ""
    text = text.strip().replace("\n", " ")
    return text[:limit] + ("..." if len(text) > limit else "")
