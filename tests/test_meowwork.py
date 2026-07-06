"""Phase 0 tests: GroupState permissions/serialization + AgentRole definitions."""
from __future__ import annotations

from sopagent.meowwork import BUILTIN_ROLES, AgentRole, GroupState
from sopagent.sop.schema import LlmConfig


def test_state_update_permission() -> None:
    s = GroupState(task="t")
    # planner fields
    ok, _ = s.update("phase", "execute", by="planner")
    assert ok and s.phase == "execute"
    ok, _ = s.update("phase", "review", by="executor")  # not permitted
    assert not ok and s.phase == "execute"
    # executor field
    ok, _ = s.update("current_artifact", "code", by="executor")
    assert ok and s.current_artifact == "code"
    ok, _ = s.update("current_artifact", "x", by="reviewer")  # not permitted
    assert not ok
    # reviewer fields
    ok, _ = s.update("review_pass", False, by="reviewer")
    assert ok and s.review_pass is False
    # unknown field
    ok, _ = s.update("nope", 1, by="planner")
    assert not ok


def test_state_to_dict_roundtrip() -> None:
    s = GroupState(task="分析漏洞", phase="execute")
    s.plan_tree = {"step_1": {"desc": "扫描", "status": "running", "assignee": "executor"}}
    s.security_alerts.append({"tool": "bash", "reason": "rm -rf", "blocked": True})
    d = s.to_dict()
    assert d["task"] == "分析漏洞" and d["phase"] == "execute"
    assert d["plan_tree"]["step_1"]["assignee"] == "executor"
    assert d["security_alerts"][0]["blocked"] is True


def test_builtin_roles_four_cats() -> None:
    assert set(BUILTIN_ROLES.keys()) == {"planner", "executor", "reviewer", "validator"}
    p = BUILTIN_ROLES["planner"]
    assert isinstance(p, AgentRole)
    assert p.persona == "布偶猫"
    assert "send_message" in p.tools and "finish_task" in p.tools
    assert p.can_delegate is True and p.can_update_state is True
    # planner has no business tools
    assert not any(t in p.tools for t in ("bash", "write_file", "read_file"))


def test_executor_has_business_tools_and_delegate() -> None:
    e = BUILTIN_ROLES["executor"]
    for t in ("bash", "write_file", "read_file", "delegate", "send_message"):
        assert t in e.tools
    assert e.can_delegate is True


def test_reviewer_read_only_no_delegate() -> None:
    r = BUILTIN_ROLES["reviewer"]
    assert "read_file" in r.tools and "bash" not in r.tools and "write_file" not in r.tools
    assert r.can_delegate is False and r.can_update_state is True


def test_validator_no_tools_not_chat_participant() -> None:
    v = BUILTIN_ROLES["validator"]
    assert v.tools == []
    assert v.can_delegate is False and v.can_update_state is False


def test_persona_prompts_loaded() -> None:
    for name, role in BUILTIN_ROLES.items():
        assert role.system_prompt, f"{name} prompt empty"
        assert "职责" in role.system_prompt or "JSON" in role.system_prompt


def test_role_custom_llm() -> None:
    r = AgentRole(name="x", persona="x", system_prompt="x", llm=LlmConfig(provider="anthropic", model="claude"))
    assert r.llm.provider == "anthropic"
