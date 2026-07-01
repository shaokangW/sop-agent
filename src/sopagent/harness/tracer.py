"""Execution tracer: record turns and steps, produce a final Trace."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TurnRecord:
    step_id: str
    turn: int
    role: str
    content_preview: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


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

    def turn(self, step_id: str, turn: int, role: str, content: str | None, tool_calls: list | None = None) -> None:
        self._turns.append(
            TurnRecord(
                step_id=step_id,
                turn=turn,
                role=role,
                content_preview=_preview(content),
                tool_calls=tool_calls or [],
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
        )
