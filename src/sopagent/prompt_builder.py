"""System prompt builder: layered doc loading + mode-gated assembly + cache boundary.

Inspired by openclaw's design:
- three layers: program sections (base/agents/...) + workspace editable docs + mode gating
- command-style push-join (no template variables)
- cache boundary splits stable prefix / dynamic suffix for prefix-cache reuse
- doc loading layered: global > project > workspace > bundled defaults (high wins)
- truncation protection (per-doc + total cap)

Docs live in sopagent/prompts/*.md by default, overridable from:
  ~/.sop-agent/prompts/<name>.md     (global)
  <project>/.sop-agent/prompts/<name>.md
  <cwd>/prompts/<name>.md
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

_BUNDLED = Path(__file__).parent / "prompts"
_LAYERS = [
    Path.home() / ".sop-agent" / "prompts",
    Path.cwd() / ".sop-agent" / "prompts",
    Path.cwd() / "prompts",
    _BUNDLED,
]
_CACHE_BOUNDARY = "<!-- SOP_AGENT_CACHE_BOUNDARY -->"
_MAX_PER_DOC = 12000
_MAX_TOTAL = 60000


def load_doc(name: str) -> str:
    """Load a prompt doc by name (e.g. 'agents' -> agents.md). High-priority layer wins."""
    for layer in _LAYERS:
        f = layer / f"{name}.md"
        if f.exists():
            return f.read_text(encoding="utf-8")
    return ""


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"


def build(mode: str, **ctx: Any) -> str:
    """Build the system prompt for a mode (chat | autonomous | sop).

    Dynamic ctx:
      autonomous: plan=list[str], subgoal_idx=int
      sop:        goal=str, expected_output=dict|None
      (any):      runtime=str  (extra runtime info appended to dynamic suffix)
    """
    lines: list[str] = []
    total = 0

    def add(title: str, name: str) -> None:
        nonlocal total
        doc = load_doc(name)
        if not doc:
            return
        doc = _truncate(doc, _MAX_PER_DOC)
        if total + len(doc) > _MAX_TOTAL:
            return
        lines.append(f"## {title}\n{doc}")
        total += len(doc)

    # ---- stable prefix (shared across modes) ----
    add("Identity & Safety", "base")
    add("Operation Rules", "agents")
    add("Style", "soul")
    add("Tool Notes", "tools")

    # ---- mode-gated section ----
    if mode == "chat":
        add("Conversation", "chat")
    elif mode == "autonomous":
        add("Autonomous Execution", "autonomous")
    elif mode == "sop":
        add("SOP Execution", "sop")

    # ---- cache boundary: stable above, dynamic below ----
    lines.append(_CACHE_BOUNDARY)

    # ---- dynamic suffix (per-turn runtime context) ----
    if mode == "autonomous" and ctx.get("plan"):
        plan = ctx["plan"]
        idx = ctx.get("subgoal_idx", 0)
        pl = ["Plan:"]
        for i, g in enumerate(plan):
            mark = "(current)" if i == idx else ("(done)" if i < idx else "")
            pl.append(f"  {i}. {g} {mark}".rstrip())
        lines.append("\n".join(pl))
        if idx < len(plan):
            lines.append(f"Current subgoal: {plan[idx]}\nWork on it, then call subgoal_done. When all done, call finish.")

    if mode == "sop":
        if ctx.get("goal"):
            lines.append(f"Current step goal: {ctx['goal']}")
        if ctx.get("expected_output"):
            lines.append("Respond with valid JSON conforming to the expected schema.")

    if ctx.get("runtime"):
        lines.append(str(ctx["runtime"]))

    return "\n\n".join(lines)
