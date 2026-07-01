"""Step state machine: track status / attempts for each step."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class StepState:
    step_id: str
    status: StepStatus = StepStatus.PENDING
    attempts: int = 0
    started_at: float | None = None
    ended_at: float | None = None
    error: str | None = None

    def begin(self) -> None:
        self.status = StepStatus.RUNNING
        self.started_at = time.time()

    def succeed(self) -> None:
        self.status = StepStatus.SUCCEEDED
        self.ended_at = time.time()

    def fail(self, error: str) -> None:
        self.status = StepStatus.FAILED
        self.error = error
        self.ended_at = time.time()

    @property
    def duration(self) -> float | None:
        if self.started_at and self.ended_at:
            return self.ended_at - self.started_at
        return None


class StateManager:
    def __init__(self) -> None:
        self._states: dict[str, StepState] = {}

    def get(self, step_id: str) -> StepState:
        if step_id not in self._states:
            self._states[step_id] = StepState(step_id=step_id)
        return self._states[step_id]

    def all(self) -> list[StepState]:
        return list(self._states.values())
