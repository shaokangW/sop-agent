"""Phase 3 tests: MeowWork run endpoints + WebSocket live stream."""
from __future__ import annotations

import time

from fastapi.testclient import TestClient

from sopagent import server
from sopagent.harness import DoneEvent
from sopagent.harness.tracer import Trace
from sopagent.meowwork.events import MessageEvent, PhaseEvent, StateUpdateEvent
from sopagent.sop.schema import LlmConfig


class _FakeState:
    def to_dict(self) -> dict:
        return {"task": "t", "phase": "analyze", "finished": False, "turn": 0}


class _FakeRole:
    def __init__(self) -> None:
        self.llm = LlmConfig(provider="openai", model="x")


class _FakeOrch:
    def __init__(self) -> None:
        self.state = _FakeState()
        self.roles = {"planner": _FakeRole(), "executor": _FakeRole(), "reviewer": _FakeRole(), "validator": _FakeRole()}

    def run_events(self):
        yield MessageEvent(frm="planner", to="executor", content="go")
        yield StateUpdateEvent(key="phase", old="analyze", new="execute", by="planner")
        yield PhaseEvent(from_phase="analyze", to_phase="execute", by="planner")
        yield DoneEvent(Trace(sop_name="meowwork", started_at=0, ended_at=0, success=True))


def _patch(monkeypatch) -> None:
    monkeypatch.setattr(server, "build_orchestrator", lambda task, settings, provider=None, model=None: _FakeOrch())


def test_meowwork_run_poll(monkeypatch) -> None:
    _patch(monkeypatch)
    client = TestClient(server.app)
    r = client.post("/meowwork/run", json={"task": "测试"}).json()
    rid = r["run_id"]
    assert r["roles"] == ["planner", "executor", "reviewer", "validator"]

    # poll until done
    body = {}
    for _ in range(60):
        body = client.get(f"/meowwork/run/{rid}/events?since=0").json()
        if body["done"]:
            break
        time.sleep(0.05)
    assert body["done"] is True
    types = [e["type"] for e in body["events"]]
    assert "message" in types and "state_update" in types and "phase" in types and "done" in types
    assert body["state"]["task"] == "t"


def test_meowwork_run_unknown_404() -> None:
    client = TestClient(server.app)
    assert client.get("/meowwork/run/nope/events").status_code == 404


def test_meowwork_websocket_stream(monkeypatch) -> None:
    _patch(monkeypatch)
    client = TestClient(server.app)
    rid = client.post("/meowwork/run", json={"task": "ws 测试"}).json()["run_id"]
    with client.websocket_connect(f"/ws/meowwork/{rid}") as ws:
        msgs = []
        while True:
            m = ws.receive_json()
            msgs.append(m)
            if m.get("type") == "final_state":
                break
    types = [m["type"] for m in msgs]
    assert "message" in types and "phase" in types and "done" in types and "final_state" in types
    # the message event carries from/to
    msg = next(m for m in msgs if m["type"] == "message")
    assert msg["from"] == "planner" and msg["to"] == "executor" and msg["content"] == "go"


def test_meowwork_websocket_unknown_run() -> None:
    client = TestClient(server.app)
    with client.websocket_connect("/ws/meowwork/nope") as ws:
        m = ws.receive_json()
    assert m["type"] == "error"
