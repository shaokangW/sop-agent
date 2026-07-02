"""Execution tracer: record turns and steps, produce a final Trace."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_USAGE_KEYS = ("prompt_tokens", "completion_tokens", "total_tokens")


@dataclass
class TurnRecord:
    step_id: str
    turn: int
    role: str
    content_preview: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, int] | None = None


@dataclass
class StepRecord:
    step_id: str
    status: str
    attempts: int
    turns: int
    duration: float | None
    error: str | None = None
    output_preview: str | None = None


@dataclass
class Trace:
    sop_name: str
    started_at: float
    ended_at: float | None = None
    success: bool = False
    steps: list[StepRecord] = field(default_factory=list)
    turns: list[TurnRecord] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=lambda: {k: 0 for k in _USAGE_KEYS})

    @property
    def duration(self) -> float | None:
        return None if self.ended_at is None else self.ended_at - self.started_at


def _preview(text: str | None, limit: int = 200) -> str:
    if text is None:
        return ""
    text = text.strip().replace("\n", " ")
    return text[:limit] + ("..." if len(text) > limit else "")


class Tracer:
    def __init__(self, sop_name: str) -> None:
        self.sop_name = sop_name
        self.started_at = time.time()
        self._turns: list[TurnRecord] = []
        self._steps: list[StepRecord] = []
        self.usage: dict[str, int] = {k: 0 for k in _USAGE_KEYS}

    def turn(
        self,
        step_id: str,
        turn: int,
        role: str,
        content: str | None,
        tool_calls: list | None = None,
        usage: dict[str, int] | None = None,
    ) -> None:
        if usage:
            for k in _USAGE_KEYS:
                self.usage[k] += int(usage.get(k, 0) or 0)
        self._turns.append(
            TurnRecord(
                step_id=step_id,
                turn=turn,
                role=role,
                content_preview=_preview(content),
                tool_calls=tool_calls or [],
                usage=usage,
            )
        )

    def step(self, record: StepRecord) -> None:
        self._steps.append(record)

    def turns_for(self, step_id: str) -> int:
        """Count LLM turns (assistant role) for a step, excluding tool messages."""
        return sum(1 for t in self._turns if t.step_id == step_id and t.role == "assistant")

    def finalize(self, success: bool) -> Trace:
        return Trace(
            sop_name=self.sop_name,
            started_at=self.started_at,
            ended_at=time.time(),
            success=success,
            steps=list(self._steps),
            turns=list(self._turns),
            usage=dict(self.usage),
        )

    def dump_jsonl(self, path: str | Path) -> Path:
        """Write one JSON line per turn, then a final summary line.

        Replayable by ``replay_jsonl``. Each line has a ``kind`` field:
        ``turn`` | ``summary``.
        """
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as f:
            for t in self._turns:
                f.write(json.dumps({
                    "kind": "turn",
                    "step_id": t.step_id,
                    "turn": t.turn,
                    "role": t.role,
                    "content_preview": t.content_preview,
                    "tool_calls": t.tool_calls,
                    "usage": t.usage,
                }, ensure_ascii=False) + "\n")
            f.write(json.dumps({
                "kind": "summary",
                "sop_name": self.sop_name,
                "started_at": self.started_at,
                "ended_at": time.time(),
                "usage": self.usage,
                "steps": len(self._steps),
                "turns": len(self._turns),
            }, ensure_ascii=False) + "\n")
        return p


def replay_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """Load a JSONL trace dump into a list of record dicts (turn/summary)."""
    p = Path(path)
    out: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
