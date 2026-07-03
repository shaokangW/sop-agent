"""Skill tool: let the agent load a workflow skill pack on demand.

The agent sees available skills (name+description) in two places: the system
prompt's `Available Skills` section and this tool's description (opencode-style).
Calling `skill({name})` returns the skill's full markdown body + supporting file
list; the agent then follows that workflow using its other tools.

Contextual (like TaskTool): constructed with a SkillRegistry. Sub-agents (TaskTool)
inherit the same SkillTool/registry so delegation can use skills too.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...skills import SkillRegistry


class SkillTool:
    name = "skill"

    def __init__(self, registry: Any) -> None:
        self._reg = registry
        avail = registry.available()  # type: ignore[attr-defined]
        if avail:
            listing = "\n".join(f"- {s['name']}: {s['description']}" for s in avail)
        else:
            listing = "(none registered)"
        self.description = (
            "Load a specialized skill (workflow instructions) by name, then follow "
            "the returned workflow. Call this when the task matches one of the "
            "available skills below.\n\nAvailable skills:\n" + listing
        )

    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Skill name (from the available skills list).",
            }
        },
        "required": ["name"],
    }

    def run(self, args: dict[str, Any]) -> str:
        name = (args.get("name") or "").strip()
        if not name:
            return "ERROR: 'name' is required."
        if not self._reg.has(name):  # type: ignore[attr-defined]
            known = ", ".join(s["name"] for s in self._reg.available()) or "(none)"  # type: ignore[attr-defined]
            return f"ERROR: skill '{name}' not found. Available: {known}"
        s = self._reg.load(name)  # type: ignore[attr-defined]
        parts = [f"# Skill: {s['name']}", "", s["content"]]
        if s.get("tools"):
            parts.append(f"\nExpected tools: {', '.join(s['tools'])}")
        if s.get("resources"):
            parts.append("\nSupporting files (use read_file to load as needed):")
            for r in s["resources"]:
                parts.append(f"  - {r}")
        return "\n".join(parts)
