"""AgentRole + the four MeowWork cats.

Each role has a persona prompt (loaded from meowwork/prompts/<name>.md), a tool
whitelist (conversation tools + business tools), and permissions. The Validator
is not a chat participant — it runs as a pre-execution hook (see validator.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..sop.schema import LlmConfig

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt(name: str) -> str:
    p = _PROMPTS_DIR / f"{name}.md"
    return p.read_text(encoding="utf-8") if p.exists() else ""


# Conversation tools available to chat participants
_CONVO_TOOLS = ["send_message", "broadcast", "update_state"]


@dataclass
class AgentRole:
    name: str  # planner|executor|reviewer|validator
    persona: str  # 布偶猫|橘猫|狸花猫|玄猫
    system_prompt: str
    tools: list[str] = field(default_factory=list)
    can_delegate: bool = False
    can_update_state: bool = False
    llm: LlmConfig = field(default_factory=lambda: LlmConfig(provider="bailian", model="glm-5.2"))


def _role(name: str, persona: str, *, tools: list[str], can_delegate: bool, can_update_state: bool) -> AgentRole:
    return AgentRole(
        name=name,
        persona=persona,
        system_prompt=_load_prompt(name),
        tools=list(tools),
        can_delegate=can_delegate,
        can_update_state=can_update_state,
    )


def builtin_roles() -> dict[str, AgentRole]:
    """The four cats. Validator is included for the hook (LLM judge) but is not
    a chat participant."""
    return {
        "planner": _role(
            "planner", "布偶猫",
            tools=[*_CONVO_TOOLS, "delegate", "finish_task"],
            can_delegate=True, can_update_state=True,
        ),
        "executor": _role(
            "executor", "橘猫",
            tools=[*_CONVO_TOOLS, "delegate", "read_file", "write_file", "edit_file", "bash", "list_dir", "grep"],
            can_delegate=True, can_update_state=True,
        ),
        "reviewer": _role(
            "reviewer", "狸花猫",
            tools=[*_CONVO_TOOLS, "read_file", "grep", "list_dir"],
            can_delegate=False, can_update_state=True,
        ),
        "validator": _role(
            "validator", "玄猫",
            tools=[],  # not a chat participant; runs as pre-execution hook
            can_delegate=False, can_update_state=False,
        ),
    }


BUILTIN_ROLES = builtin_roles()
