"""Server chat persistence: save after turn, list/load across a simulated restart."""
from __future__ import annotations

import time

from fastapi.testclient import TestClient

from sopagent import server
from sopagent.harness import TurnEvent
from sopagent.harness.session_store import SessionStore


class _FakeChatSession:
    """A minimal chat session that replies with a text turn (no LLM)."""

    def __init__(self) -> None:
        self.messages = [{"role": "system", "content": "sys"}]
        self.approval_policy = server.ApprovalPolicy()
        self.on_token = None
        self.on_reasoning = None

    def ask(self, text: str):
        self.messages.append({"role": "user", "content": text})
        yield TurnEvent("chat", 0, f"reply:{text}", [])
        self.messages.append({"role": "assistant", "content": f"reply:{text}"})


def _client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setattr(server, "get_session", lambda settings, policy, **kw: _FakeChatSession())
    monkeypatch.setattr(server, "_session_store", SessionStore(tmp_path))
    return TestClient(server.app)


def _wait_done(client: TestClient, sid: str) -> dict:
    for _ in range(60):
        body = client.get(f"/chat/{sid}/events?since=0").json()
        if not body["running"] and any(e.get("type") == "done" for e in body["events"]):
            return body
        time.sleep(0.05)
    raise AssertionError("chat did not finish")


def test_chat_start_send_persist_list_history(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    sid = client.post("/chat/start", json={"approve_all_tools": False}).json()["session_id"]

    r = client.post(f"/chat/{sid}/send", json={"text": "hello"})
    assert r.status_code == 200
    _wait_done(client, sid)

    # listed with a non-zero message count and titled from first message
    items = client.get("/chat/sessions").json()
    match = [i for i in items if i["id"] == sid]
    assert match and match[0]["message_count"] >= 2
    assert match[0]["title"] == "hello"

    # history exposes user + assistant
    hist = client.get(f"/chat/{sid}/history").json()["messages"]
    roles = [m["role"] for m in hist]
    assert "user" in roles and "assistant" in roles


def test_resume_across_simulated_restart(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    sid = client.post("/chat/start", json={}).json()["session_id"]
    client.post(f"/chat/{sid}/send", json={"text": "first"})
    _wait_done(client, sid)

    # simulate process restart: drop all in-memory state
    server._chat_sessions.clear()

    # history still served from disk
    hist = client.get(f"/chat/{sid}/history").json()["messages"]
    assert any(m["content"] == "first" for m in hist)

    # send again -> session rebuilt from store, second turn appends
    client.post(f"/chat/{sid}/send", json={"text": "second"})
    _wait_done(client, sid)
    hist2 = client.get(f"/chat/{sid}/history").json()["messages"]
    contents = [m["content"] for m in hist2]
    assert "first" in contents and "second" in contents


def test_delete_session(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    sid = client.post("/chat/start", json={}).json()["session_id"]
    assert client.delete(f"/chat/{sid}").status_code == 200
    # gone from listings
    assert not any(i["id"] == sid for i in client.get("/chat/sessions").json())
    # history 404
    assert client.get(f"/chat/{sid}/history").status_code == 404


def test_send_unknown_session_404(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    assert client.post("/chat/nope/send", json={"text": "x"}).status_code == 404


def test_chat_start_passes_provider_and_model(tmp_path, monkeypatch) -> None:
    captured: dict = {}
    def fake_get_session(settings, policy, provider=None, model=None):
        captured["provider"] = provider
        captured["model"] = model
        return _FakeChatSession()
    monkeypatch.setattr(server, "get_session", fake_get_session)
    monkeypatch.setattr(server, "_session_store", SessionStore(tmp_path))
    client = TestClient(server.app)
    client.post("/chat/start", json={"provider": "ollama", "model": "llama3"}).json()
    assert captured == {"provider": "ollama", "model": "llama3"}
    # default (omitted) -> None
    client.post("/chat/start", json={}).json()
    assert captured["provider"] is None and captured["model"] is None
