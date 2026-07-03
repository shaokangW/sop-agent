"""Tests for skills: registry discovery/parsing/layering + SkillTool + prompt injection."""
from __future__ import annotations

from pathlib import Path

from sopagent.prompt_builder import build
from sopagent.skills import SkillRegistry
from sopagent.tools.builtin import SkillTool

_SKILL_MD = """---
name: release
description: 发版工作流,changelog/tag/push。用户要求发布时用。
triggers: [发布, release, 打 tag]
tools: [bash, read_file]
modes: [autonomous, chat]
---

# Release Workflow

1. 生成 changelog
2. 打 tag
3. push
"""


def _make_layer(tmp_path: Path, name: str, body: str = _SKILL_MD, extra_files: list[str] | None = None) -> Path:
    base = tmp_path / "skills"
    d = base / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(body, encoding="utf-8")
    for rel in extra_files or []:
        f = d / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x", encoding="utf-8")
    return base


def test_parse_and_load(tmp_path: Path) -> None:
    layer = _make_layer(tmp_path, "release", extra_files=["templates/cl.md", "scripts/p.sh"])
    reg = SkillRegistry.load_default(layers=[layer])
    assert reg.has("release")
    avail = reg.available()
    assert avail == [{"name": "release", "description": avail[0]["description"]}]
    s = reg.load("release")
    assert s is not None
    assert "Release Workflow" in s["content"]
    assert s["tools"] == ["bash", "read_file"]
    assert "templates/cl.md" in s["resources"] and "scripts/p.sh" in s["resources"]


def test_mode_filtering(tmp_path: Path) -> None:
    layer = _make_layer(tmp_path, "release")
    reg = SkillRegistry.load_default(layers=[layer])
    assert reg.available("chat") == reg.available("autonomous")
    # a skill restricted to a different mode is hidden
    body = _SKILL_MD.replace("name: release", "name: sop-only").replace("modes: [autonomous, chat]", "modes: [sop]")
    layer2 = _make_layer(tmp_path / "x", "sop-only", body)
    reg2 = SkillRegistry.load_default(layers=[layer2])
    assert reg2.available("chat") == []
    assert [s["name"] for s in reg2.available("sop")] == ["sop-only"]


def test_layer_override_high_wins(tmp_path: Path) -> None:
    low = _make_layer(tmp_path / "low", "release", _SKILL_MD)
    high = _make_layer(tmp_path / "high", "release", _SKILL_MD.replace("Release Workflow", "Release Workflow (overridden)"))
    reg = SkillRegistry.load_default(layers=[low, high])  # high is later => higher priority
    s = reg.load("release")
    assert "overridden" in s["content"]


def test_bad_name_skipped(tmp_path: Path) -> None:
    base = tmp_path / "skills"
    (base / "Bad-Name").mkdir(parents=True)
    (base / "Bad-Name" / "SKILL.md").write_text("---\nname: x\ndescription: y\n---\nbody", encoding="utf-8")
    reg = SkillRegistry.load_default(layers=[base])
    assert not reg.has("Bad-Name")


def test_missing_or_bad_frontmatter_skipped(tmp_path: Path) -> None:
    base = tmp_path / "skills"
    # no description
    d1 = base / "a"; d1.mkdir(parents=True)
    (d1 / "SKILL.md").write_text("---\nname: a\n---\nbody", encoding="utf-8")
    # not yaml frontmatter (no leading ---)
    d2 = base / "b"; d2.mkdir(parents=True)
    (d2 / "SKILL.md").write_text("just markdown, no frontmatter", encoding="utf-8")
    reg = SkillRegistry.load_default(layers=[base])
    assert not reg.has("a") and not reg.has("b")


def test_corrupt_yaml_skipped(tmp_path: Path) -> None:
    base = tmp_path / "skills"
    d = base / "broken"; d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: broken\ndescription: [unclosed\n---\nbody", encoding="utf-8")
    reg = SkillRegistry.load_default(layers=[base])
    assert not reg.has("broken")


def test_skill_tool_loads(tmp_path: Path) -> None:
    layer = _make_layer(tmp_path, "release", extra_files=["refs/note.md"])
    reg = SkillRegistry.load_default(layers=[layer])
    tool = SkillTool(reg)
    out = tool.run({"name": "release"})
    assert "Skill: release" in out
    assert "Release Workflow" in out
    assert "refs/note.md" in out
    assert "bash" in out  # expected tools listed


def test_skill_tool_unknown_name(tmp_path: Path) -> None:
    reg = SkillRegistry.load_default(layers=[_make_layer(tmp_path, "release")])
    tool = SkillTool(reg)
    out = tool.run({"name": "nope"})
    assert "ERROR" in out and "release" in out  # lists available


def test_skill_tool_missing_name(tmp_path: Path) -> None:
    reg = SkillRegistry.load_default(layers=[_make_layer(tmp_path, "release")])
    assert "ERROR" in SkillTool(reg).run({})


def test_skill_tool_description_lists_available(tmp_path: Path) -> None:
    reg = SkillRegistry.load_default(layers=[_make_layer(tmp_path, "release")])
    tool = SkillTool(reg)
    assert "release" in tool.description and "发版" in tool.description


def test_prompt_builder_injects_available_skills() -> None:
    prompt = build("chat", available_skills=[{"name": "release", "description": "发版流程"}])
    assert "## Available Skills" in prompt
    assert "`release`: 发版流程" in prompt
    # without skills, no section header (tools.md may mention the words in prose)
    assert "## Available Skills" not in build("chat")


def test_prompt_builder_skills_before_cache_boundary() -> None:
    prompt = build("autonomous", available_skills=[{"name": "x", "description": "y"}])
    boundary = prompt.find("SOP_AGENT_CACHE_BOUNDARY")
    skills = prompt.find("Available Skills")
    assert 0 < skills < boundary  # stable prefix, cache-friendly


def test_bundled_defaults_load() -> None:
    reg = SkillRegistry.load_default()  # scans bundled sopagent/skills/
    names = [s["name"] for s in reg.available()]
    assert "debug-test" in names and "code-review" in names


def test_agent_uses_skill_tool(tmp_path: Path) -> None:
    """An autonomous agent can call the skill tool and receive the workflow."""
    from sopagent.harness import ApprovalPolicy
    from sopagent.harness.artifacts import ArtifactStore
    from sopagent.harness.autonomous import AutonomousAgent
    from sopagent.llm import LLMResponse, LLMRouter, ProviderRegistry
    from sopagent.llm.base import ToolCall
    from sopagent.sop.schema import LlmConfig
    from sopagent.tools import BUILTIN_TOOLS, ToolExecutor, ToolRegistry
    from sopagent.tools.builtin import SkillTool

    class _Fake:
        name = "openai"
        def __init__(self, responses): self._r = list(responses); self._i = 0
        def chat(self, messages, tools, config):
            r = self._r[self._i]; self._i += 1; return r

    reg = ProviderRegistry()
    reg.register(_Fake([  # type: ignore[arg-type]
        LLMResponse(content=None, tool_calls=[ToolCall(id="s", name="skill", arguments={"name": "release"})]),
        LLMResponse(content=None, tool_calls=[ToolCall(id="f", name="finish", arguments={"summary": "done"})]),
    ]))
    skill_reg = SkillRegistry.load_default(layers=[_make_layer(tmp_path, "release")])
    tool_reg = ToolRegistry()
    for t in BUILTIN_TOOLS:
        tool_reg.register(t)
    tool_reg.register(SkillTool(skill_reg))
    agent = AutonomousAgent(
        task="delegate", router=LLMRouter(reg), tool_registry=tool_reg,
        tool_executor=ToolExecutor(tool_reg), artifacts=ArtifactStore(tmp_path),
        llm_config=LlmConfig(provider="openai", model="m"),
    )
    agent.run()
    # the skill tool call resolved (skill loaded, not an error)
    traces = [t for t in agent.tracer._turns if t.role == "tool"]
    assert any("Skill: release" in (t.content_preview or "") for t in traces)
