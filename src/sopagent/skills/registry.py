"""Skill registry: discover, parse, and load SKILL.md skill packs.

A skill is a directory containing a ``SKILL.md`` (YAML frontmatter + markdown
body) plus optional supporting files (templates/scripts/refs). Skills are
discovered across layered directories (high overrides low, mirroring
prompt_builder): global > project-override > project > bundled defaults.

The registry exposes ``available(mode)`` (name+description list, for prompt
injection) and ``load(name)`` (full body + resource list, for the SkillTool).
Names must match ``^[a-z0-9]+(-[a-z0-9]+)*$`` and equal the directory name.
Corrupt files are skipped (best-effort, like SessionStore).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_BUNDLED = Path(__file__).parent  # sopagent/skills/ (built-in defaults live here)
# Ordered low -> high priority: later layers override earlier (high wins).
_LAYERS = [
    _BUNDLED,                                # bundled defaults (lowest)
    Path.cwd() / "skills",                   # project
    Path.cwd() / ".sop-agent" / "skills",    # project override
    Path.home() / ".sop-agent" / "skills",   # global (highest)
]
_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_MAX_DESC = 1024


@dataclass
class Skill:
    name: str
    description: str
    content: str  # markdown body (frontmatter stripped)
    triggers: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    modes: list[str] = field(default_factory=list)  # empty == all modes
    resources: list[str] = field(default_factory=list)  # relative paths in the skill dir
    base_dir: Path | None = None  # the skill's directory (for read_file refs)


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    @classmethod
    def load_default(cls, layers: list[Path] | None = None) -> "SkillRegistry":
        """Scan all layered skill directories (high layer overrides low).

        Pass ``layers`` to override the default search paths (for tests).
        """
        reg = cls()
        scan_layers = list(layers) if layers is not None else list(_LAYERS)
        # walk low -> high so high overrides low (later layers win)
        for layer in scan_layers:
            if not layer.is_dir():
                continue
            for d in sorted(layer.iterdir()):
                if not d.is_dir():
                    continue
                skill = _parse_skill_dir(d)
                if skill is not None:
                    reg._skills[skill.name] = skill
        return reg

    def available(self, mode: str | None = None) -> list[dict[str, str]]:
        """name+description list for prompt injection, filtered by mode."""
        out: list[dict[str, str]] = []
        for s in self._skills.values():
            if mode and s.modes and mode not in s.modes:
                continue
            out.append({"name": s.name, "description": s.description})
        out.sort(key=lambda x: x["name"])
        return out

    def has(self, name: str) -> bool:
        return name in self._skills

    def load(self, name: str) -> dict[str, Any] | None:
        """Full skill content + resources for the SkillTool to return."""
        s = self._skills.get(name)
        if s is None:
            return None
        return {
            "name": s.name,
            "description": s.description,
            "content": s.content,
            "tools": s.tools,
            "resources": s.resources,
        }

    def all(self) -> list[Skill]:
        return list(self._skills.values())


def _parse_skill_dir(d: Path) -> Skill | None:
    skill_md = d / "SKILL.md"
    if not skill_md.is_file():
        return None
    name = d.name
    if not _NAME_RE.match(name):
        return None
    try:
        raw = skill_md.read_text(encoding="utf-8")
    except OSError:
        return None
    front, body = _split_frontmatter(raw)
    if not front:
        return None
    try:
        meta = yaml.safe_load(front) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(meta, dict):
        return None
    desc = str(meta.get("description") or "").strip()
    if not desc or len(desc) > _MAX_DESC:
        return None
    # frontmatter `name` is optional (defaults to dir name); if set must match dir
    fm_name = meta.get("name")
    if fm_name and str(fm_name) != name:
        return None
    resources = [
        str(p.relative_to(d).as_posix())
        for p in sorted(d.rglob("*"))
        if p.is_file() and p.name != "SKILL.md"
    ]
    return Skill(
        name=name,
        description=desc,
        content=body.strip(),
        triggers=_as_str_list(meta.get("triggers")),
        tools=_as_str_list(meta.get("tools")),
        modes=_as_str_list(meta.get("modes")),
        resources=resources,
        base_dir=d,
    )


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Return (frontmatter_yaml, body). Empty front if missing/malformed."""
    if not text.startswith("---"):
        return "", text
    # find the closing ---
    rest = text[3:]
    # skip a leading newline
    if rest.startswith("\r\n"):
        rest = rest[2:]
    elif rest.startswith("\n"):
        rest = rest[1:]
    end = rest.find("\n---")
    if end == -1:
        # maybe closing on its own line at end without trailing content
        idx = rest.rfind("---")
        if idx == -1:
            return "", text
        front = rest[:idx].rstrip("\r\n")
        body = rest[idx + 3:]
        return front, body.lstrip("\r\n")
    front = rest[:end].rstrip("\r\n")
    body = rest[end + 4:]  # skip "\n---"
    return front, body.lstrip("\r\n")


def _as_str_list(val: Any) -> list[str]:
    if val is None:
        return []
    if isinstance(val, str):
        return [v.strip() for v in val.split(",") if v.strip()]
    if isinstance(val, list):
        return [str(v).strip() for v in val if str(v).strip()]
    return []
