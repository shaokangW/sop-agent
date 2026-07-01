"""SOP data model: declarative procedure description."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RetryPolicy(BaseModel):
    max: int = 0
    backoff: float = 1.0


class LlmConfig(BaseModel):
    provider: str = "bailian"
    model: str = "glm-5.2"
    temperature: float = 0.2
    max_tokens: int | None = None


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    goal: str
    prompt: str
    llm: LlmConfig | None = None
    tools: list[str] = Field(default_factory=list)
    expected_output: dict[str, Any] | None = None
    retry: RetryPolicy = Field(default_factory=RetryPolicy)
    save_artifact: str | None = None
    max_turns: int = 10
    require_approval: bool = False


class Stage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    steps: list[Step]


class Transition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    src: str = Field(alias="from")
    dst: str = Field(alias="to")
    when: str | None = None


class Meta(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    version: str = "1.0"
    description: str = ""


class McpServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: str | None = None
    args: list[str] = Field(default_factory=list)
    url: str | None = None
    env: dict[str, str] = Field(default_factory=dict)


class SOP(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metadata: Meta
    variables: dict[str, Any] = Field(default_factory=dict)
    llm_defaults: LlmConfig
    tools: list[str] = Field(default_factory=list)
    mcp_servers: dict[str, McpServerConfig] = Field(default_factory=dict)
    stages: list[Stage]
    transitions: list[Transition] = Field(default_factory=list)

    def step_by_id(self, step_id: str) -> Step:
        for stage in self.stages:
            for step in stage.steps:
                if step.id == step_id:
                    return step
        raise KeyError(step_id)

    def stage_by_id(self, stage_id: str) -> Stage:
        for stage in self.stages:
            if stage.id == stage_id:
                return stage
        raise KeyError(stage_id)

    def llm_for(self, step: Step) -> LlmConfig:
        return step.llm or self.llm_defaults
