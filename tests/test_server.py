"""HTTP server tests (engine/agent are mocked; no real LLM calls)."""
from __future__ import annotations

from dataclasses import dataclass, field

from fastapi.testclient import TestClient

from sopagent import server
from sopagent.harness import ApprovalRequest, DoneEvent


@dataclass
class _FakeTrace:
    sop_name: str = "fake"
    started_at: float = 0.0
    ended_at: float | None = 0.0
    success: bool = True
    steps: list = field(default_factory=list)
    turns: list = field(default_factory=list)


class _FakeEngine:
    def run(self) -> _FakeTrace:
        return _FakeTrace()


class _FakeAgent:
    """Replays a scripted event sequence as a generator."""

    def __init__(self, events) -> None:
        self._events = list(events)
        self.summary = None

    def run_events(self):
        for e in self._events:
            yield e


_MINIMAL_SOP_YAML = (
    "metadata: {name: x}\n"
    "llm_defaults: {provider: bailian, model: glm-5.2}\n"
    "stages: [{id: s, steps: [{id: p, goal: g, prompt: hi}]}]\n"
)


def test_health() -> None:
    client = TestClient(server.app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_run_requires_sop() -> None:
    client = TestClient(server.app)
    r = client.post("/run", json={})
    assert r.status_code == 400


def test_run_with_mock_engine(monkeypatch) -> None:
    monkeypatch.setattr(server, "get_engine", lambda sop, settings: _FakeEngine())
    client = TestClient(server.app)
    r = client.post("/run", json={"sop_yaml": _MINIMAL_SOP_YAML})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["sop_name"] == "fake"


def test_run_invalid_yaml_returns_400(monkeypatch) -> None:
    monkeypatch.setattr(server, "get_engine", lambda sop, settings: _FakeEngine())
    client = TestClient(server.app)
    r = client.post("/run", json={"sop_yaml": "not: valid: yaml: [oops"})
    assert r.status_code in (400, 422)


def test_task_approval_resume_flow(monkeypatch) -> None:
    import time

    events = [
        ApprovalRequest(id="t1", reason="approve x", payload={"kind": "tool_call", "name": "x", "arguments": {}}),
        DoneEvent(_FakeTrace()),
    ]
    agent = _FakeAgent(events)
    monkeypatch.setattr(server, "get_agent", lambda task, settings, policy, max_turns, **kw: agent)
    client = TestClient(server.app)

    r = client.post("/task", json={"task": "do x", "approve_all_tools": True})
    assert r.status_code == 200
    task_id = r.json()["task_id"]

    # poll until the agent pauses for approval
    body = {}
    for _ in range(40):
        body = client.get(f"/task/{task_id}/events?since=0").json()
        if body["pending"] or body["done"]:
            break
        time.sleep(0.05)
    assert body["pending"] is not None

    r2 = client.post(f"/task/{task_id}/approve", json={"decision": "approve"})
    assert r2.status_code == 200

    # poll until done
    for _ in range(40):
        body = client.get(f"/task/{task_id}/events?since=0").json()
        if body["done"]:
            break
        time.sleep(0.05)
    assert body["done"] is True


def test_approve_unknown_task_404() -> None:
    client = TestClient(server.app)
    r = client.post("/task/nope/approve", json={"decision": "approve"})
    assert r.status_code == 404


def test_bad_decision_400(monkeypatch) -> None:
    agent = _FakeAgent([ApprovalRequest(id="t1", reason="r", payload={})])
    monkeypatch.setattr(server, "get_agent", lambda task, settings, policy, max_turns, **kw: agent)
    client = TestClient(server.app)
    tid = client.post("/task", json={"task": "x"}).json()["task_id"]
    r = client.post(f"/task/{tid}/approve", json={"decision": "maybe"})
    assert r.status_code == 400


def test_sop_validate_ok() -> None:
    client = TestClient(server.app)
    r = client.post("/sop/validate", json={"sop_yaml": _MINIMAL_SOP_YAML}).json()
    assert r["ok"] is True
    assert r["metadata"]["name"] == "x"
    assert r["steps"] == 1


def test_sop_validate_bad() -> None:
    client = TestClient(server.app)
    r = client.post("/sop/validate", json={"sop_yaml": "metadata: {name: x}\nllm_defaults: {}\nstages: x"}).json()
    assert r["ok"] is False
    assert r["error"]


def test_config_lists_providers() -> None:
    client = TestClient(server.app)
    r = client.get("/config").json()
    names = [p["name"] for p in r["providers"]]
    assert "bailian" in names and "anthropic" in names and "ollama" in names
    assert all("configured" in p for p in r["providers"])


def test_wire_subagent_events_forwards_to_store() -> None:
    from sopagent.harness import ToolExecutedEvent, TurnEvent

    class _Ctx:
        def __init__(self) -> None:
            self.on_event = None

    class _Tool:
        def __init__(self) -> None:
            self._ctx = _Ctx()

    class _Reg:
        def __init__(self) -> None:
            self.t = _Tool()

        def get(self, name):
            if name == "task":
                return self.t
            raise KeyError(name)

    store: dict = {"events": []}
    reg = _Reg()
    owner = type("_Owner", (), {"tool_registry": reg})()
    assert reg.t._ctx.on_event is None
    server._wire_subagent_events(store, owner)
    assert reg.t._ctx.on_event is not None  # wired

    reg.t._ctx.on_event(ToolExecutedEvent("task", "tc1", "echo", True, "hi"))
    reg.t._ctx.on_event(TurnEvent("task", 0, "thinking...", []))
    assert store["events"][0]["type"] == "subagent_tool"
    assert store["events"][0]["name"] == "echo"
    assert store["events"][1]["type"] == "subagent_turn"
    assert store["events"][1]["content"] == "thinking..."


def test_wire_subagent_events_no_task_tool_is_noop() -> None:
    class _Reg:
        def get(self, name):
            raise KeyError(name)
    owner = type("_O", (), {"tool_registry": _Reg()})()
    server._wire_subagent_events({"events": []}, owner)  # must not raise
