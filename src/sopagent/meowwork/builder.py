"""Build a GroupOrchestrator wired to sop-agent providers + business tools."""
from __future__ import annotations

from ..config import Settings
from ..llm import LLMRouter, ProviderRegistry
from ..llm.registry import _OPENAI_COMPATIBLE
from ..sop.schema import LlmConfig
from ..tools import BUILTIN_TOOLS, ToolRegistry
from .orchestrator import GroupOrchestrator
from .roles import BUILTIN_ROLES, AgentRole


def build_orchestrator(task: str, settings: Settings, provider: str | None = None, model: str | None = None) -> GroupOrchestrator:
    """Construct a MeowWork GroupOrchestrator with the four cats + business tools.

    The Validator hook is auto-built inside the orchestrator (uses the validator
    role's llm config). MCP servers are not loaded here (keep startup fast); add
    them to the business registry if needed.
    """
    providers = ProviderRegistry.from_settings(settings)
    router = LLMRouter(providers)
    # copy roles so per-run llm overrides don't mutate the shared BUILTIN_ROLES
    roles: dict[str, AgentRole] = {}
    for name, role in BUILTIN_ROLES.items():
        r = AgentRole(
            name=role.name, persona=role.persona, system_prompt=role.system_prompt,
            tools=list(role.tools), can_delegate=role.can_delegate,
            can_update_state=role.can_update_state, llm=LlmConfig(
                provider=provider or role.llm.provider,
                model=model or role.llm.model,
            ),
        )
        roles[name] = r
    biz = ToolRegistry()
    for t in BUILTIN_TOOLS:
        try:
            biz.register(t)
        except ValueError:
            pass
    return GroupOrchestrator(task=task, roles=roles, llm_router=router, business_registry=biz)
