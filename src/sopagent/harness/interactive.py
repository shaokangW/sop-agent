"""Interactive REPL session: multi-turn chat with tools + inline approval.

Unlike AutonomousAgent (single task -> finish), the REPL is user-driven:
each user message triggers an inner loop (tools until a text reply with no
tool call), then control returns to the user. Conversation history is kept
across turns. Slash commands are handled by the caller.
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
from .context_window import ContextWindowManager
from .events import ApprovalRequest, ToolExecutedEvent, TurnEvent

_SYSTEM = build_prompt("chat")


class InteractiveSession:
    def __init__(
        self,
        router: LLMRouter,
        tool_registry: ToolRegistry,
        tool_executor: ToolExecutor,
        llm_config: LlmConfig,
        approval_policy: ApprovalPolicy | None = None,
        on_token: Callable[[str, str], None] | None = None,
        max_turns: int = 15,
        context_manager: ContextWindowManager | None = None,
    ) -> None:
        self.router = router
        self.tool_registry = tool_registry
        self.tool_executor = tool_executor
        self.llm_config = llm_config
        self.approval_policy = approval_policy or ApprovalPolicy()
        self.on_token = on_token
        self.on_reasoning: Callable[[str, str], None] | None = None
        self.max_turns = max_turns
        self.context_manager = context_manager
        self.messages: list[Message] = [{"role": "system", "content": _SYSTEM}]

    def reset(self) -> None:
        self.messages = [{"role": "system", "content": _SYSTEM}]

    def tool_names(self) -> list[str]:
        return [t.name for t in self.tool_registry.all()]

    def ask(self, user_input: str) -> Iterator[Any]:
        """Run one user turn: append user msg, drive tool loop until a text reply."""
        self.messages.append({"role": "user", "content": user_input})
        if self.context_manager is not None:
            self.messages = self.context_manager.maybe_compress(self.messages)
        tool_schemas = [to_openai_schema(t) for t in self.tool_registry.all()]

        for turn in range(self.max_turns):
            if self.on_token is not None or self.on_reasoning is not None:
                resp = self.router.chat_stream(
                    self.messages, tool_schemas, self.llm_config,
                    on_delta=lambda d: self.on_token("chat", d) if self.on_token else None,
                    on_reasoning=lambda d: self.on_reasoning("chat", d) if self.on_reasoning else None,
                )
            else:
                resp = self.router.chat(self.messages, tool_schemas, self.llm_config)
            tc_dicts = [asdict(tc) for tc in resp.tool_calls]
            yield TurnEvent("chat", turn, resp.content, tc_dicts)
            self.messages.append(resp.assistant_message())

            if not resp.tool_calls:
                return  # text reply -> turn done, hand back to user

            for tc in resp.tool_calls:
                if self._needs_tool_approval(tc.name):
                    req = ApprovalRequest(
                        id=f"tool:{tc.id}",
                        reason=f"Approve tool '{tc.name}'",
                        payload={"kind": "tool_call", "tool_call_id": tc.id, "name": tc.name, "arguments": tc.arguments},
                    )
                    if (yield req) != "approve":
                        self.messages.append(tool_result_message(tc.id, f"User rejected tool '{tc.name}'"))
                        yield ToolExecutedEvent("chat", tc.id, tc.name, False, "rejected by user")
                        continue
                results = self.tool_executor.batch([tc])
                r = results[0]
                yield ToolExecutedEvent("chat", tc.id, tc.name, r.ok, r.content)
                self.messages.append(tool_result_message(tc.id, r.content))

        yield TurnEvent("chat", self.max_turns, "(reached max turns; handing back to user)", [])

    def _needs_tool_approval(self, name: str) -> bool:
        if name in self.approval_policy.approved_always:
            return False
        if self.approval_policy.tool_needs_approval(name):
            return True
        if self.tool_registry.has(name):
            return bool(getattr(self.tool_registry.get(name), "requires_approval", False))
        return False
