"""Context window management: estimate tokens and compress long conversations.

When the message list exceeds a token budget, the middle history is replaced
with a single LLM-generated summary, keeping the system prompt and the most
recent messages verbatim. The split point is adjusted so an assistant message
and its tool-result messages are never separated (no orphan tool_call_id).

Used by the interactive chat session (and reusable by autonomous/engine loops).
Compression is an LLM call; on failure it falls back to a hard truncation with
a marker so the conversation can continue rather than overflow.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from ..llm.base import Message, ToolSchema
from ..llm.router import LLMRouter

_CHARS_PER_TOKEN = 4  # rough OpenAI-style estimate (English ~4 chars/token)

_SUMMARY_SYSTEM = (
    "You compress conversation history. Produce a dense summary of the messages "
    "below: key facts, decisions, file paths/identifiers, open tasks, and any "
    "tool results worth remembering. Omit pleasantries. Plain text, no headings."
)


@dataclass
class ContextWindowManager:
    router: LLMRouter
    llm_config: Any  # LlmConfig
    max_tokens: int = 60000
    keep_recent: int = 8
    enabled: bool = True
    on_compress: Callable[[dict[str, Any]], None] | None = None

    def estimate_tokens(self, messages: list[Message]) -> int:
        total = 0
        for m in messages:
            content = m.get("content")
            if isinstance(content, str):
                total += len(content)
            elif content:
                total += len(json.dumps(content, ensure_ascii=False))
            for tc in m.get("tool_calls") or []:
                fn = (tc or {}).get("function") or {}
                total += len(fn.get("arguments") or "")
        return max(1, total // _CHARS_PER_TOKEN)

    def maybe_compress(self, messages: list[Message]) -> list[Message]:
        if not self.enabled or len(messages) <= self.keep_recent + 1:
            return messages
        if self.estimate_tokens(messages) <= self.max_tokens:
            return messages

        system, middle, recent = self._split(messages)
        if not middle:
            return messages  # nothing to compress

        summary = self._summarize(middle)
        if summary is None:
            # LLM failed: hard-truncate middle, keep a marker so the model knows
            summary = "[earlier context truncated due to length]"

        compressed: list[Message] = [system, {"role": "system", "content": summary}] + recent
        if self.on_compress:
            self.on_compress({
                "before_tokens": self.estimate_tokens(messages),
                "after_tokens": self.estimate_tokens(compressed),
                "middle_messages": len(middle),
                "kept_recent": len(recent),
            })
        return compressed

    def _split(self, messages: list[Message]) -> tuple[Message, list[Message], list[Message]]:
        system = messages[0]
        cut = max(1, len(messages) - self.keep_recent)
        # never start the kept-recent block with a tool message: its parent
        # assistant (with tool_calls) would be stranded in the middle.
        while cut < len(messages) and messages[cut].get("role") == "tool":
            cut -= 1
        cut = max(1, cut)
        middle = messages[1:cut]
        recent = messages[cut:]
        return system, middle, recent

    def _summarize(self, middle: list[Message]) -> str | None:
        transcript = self._render(middle)
        msgs: list[Message] = [
            {"role": "system", "content": _SUMMARY_SYSTEM},
            {"role": "user", "content": transcript},
        ]
        try:
            resp = self.router.chat(msgs, [], self.llm_config)
        except Exception:
            return None
        text = (resp.content or "").strip()
        return text or None

    @staticmethod
    def _render(messages: list[Message]) -> str:
        lines: list[str] = []
        for m in messages:
            role = m.get("role", "?")
            content = m.get("content")
            if content:
                lines.append(f"{role}: {content}")
            for tc in m.get("tool_calls") or []:
                fn = (tc or {}).get("function") or {}
                lines.append(f"  -> {fn.get('name')}({fn.get('arguments')})")
        return "\n".join(lines)
