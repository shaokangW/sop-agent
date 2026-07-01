"""HTTP server + interactive web UI.

Run: uvicorn sopagent.server:app  (then open http://127.0.0.1:8000)

Endpoints:
  GET  /                          interactive web UI
  GET  /health
  POST /run                       SOP mode (sync, auto-approve) -> trace
  POST /task                      autonomous mode -> {task_id} (runs in background)
  GET  /task/{id}/events?since=N  incremental events (token/turn/tool/approval/done)
  POST /task/{id}/approve         {decision} resume a paused task
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import asdict
from pathlib import Path
from time import time
from typing import Any

import yaml
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .cli import build_agent, build_engine_from_sop
from .config import Settings
from .harness import (
    ApprovalPolicy,
    ApprovalRequest,
    DoneEvent,
    TokenEvent,
    ToolExecutedEvent,
    Trace,
    TurnEvent,
)
from .sop.loader import load_sop, load_sop_from_text
from .sop.schema import SOP

app = FastAPI(title="sop-agent", version="0.1.0")


# --------------------------------------------------------------------------- models
class RunRequest(BaseModel):
    sop_path: str | None = None
    sop_yaml: str | None = None


class TaskRequest(BaseModel):
    task: str
    approve_all_tools: bool = False
    approve_subgoals: bool = False
    max_turns: int = 20


class ApproveRequest(BaseModel):
    decision: str  # "approve" | "reject"


def _load(req: RunRequest) -> SOP:
    if req.sop_yaml:
        return load_sop_from_text(req.sop_yaml)
    if req.sop_path:
        return load_sop(req.sop_path)
    raise HTTPException(status_code=400, detail="provide 'sop_path' or 'sop_yaml'")


def trace_to_dict(trace: Trace) -> dict[str, Any]:
    return asdict(trace)


def get_engine(sop: SOP, settings: Settings) -> Any:
    return build_engine_from_sop(sop, settings)


def get_agent(task: str, settings: Settings, policy: ApprovalPolicy, max_turns: int) -> Any:
    agent = build_agent(task, settings)
    agent.approval_policy = policy
    agent.max_turns = max_turns
    return agent


# --------------------------------------------------------------------------- task store
_tasks: dict[str, dict[str, Any]] = {}


def _serialize_event(ev: Any) -> dict[str, Any]:
    if isinstance(ev, TokenEvent):
        return {"type": "token", "step_id": ev.step_id, "delta": ev.delta}
    if isinstance(ev, TurnEvent):
        return {"type": "turn", "step_id": ev.step_id, "turn": ev.turn, "content": ev.content, "tool_calls": ev.tool_calls}
    if isinstance(ev, ToolExecutedEvent):
        return {"type": "tool", "step_id": ev.step_id, "name": ev.name, "ok": ev.ok, "result": ev.result}
    if isinstance(ev, ApprovalRequest):
        return {"type": "approval", "id": ev.id, "reason": ev.reason, "payload": ev.payload}
    if isinstance(ev, DoneEvent):
        return {"type": "done", "trace": trace_to_dict(ev.trace)}
    return {"type": "unknown"}


def _runner(task_id: str, agent: Any) -> None:
    store = _tasks[task_id]
    store["agent"] = agent

    def _on_token(step_id: str, delta: str) -> None:
        store["events"].append({"type": "token", "step_id": step_id, "delta": delta})

    agent.on_token = _on_token
    gen = agent.run_events()
    try:
        ev = next(gen)
        while True:
            if isinstance(ev, ApprovalRequest):
                store["pending"] = _serialize_event(ev)
                store["events"].append(_serialize_event(ev))
                store["event"].wait()
                store["event"].clear()
                decision = store["decision"] or "approve"
                store["pending"] = None
                ev = gen.send(decision)
            elif isinstance(ev, DoneEvent):
                store["events"].append(_serialize_event(ev))
                store["done"] = True
                break
            else:
                store["events"].append(_serialize_event(ev))
                ev = next(gen)
    except StopIteration:
        store["done"] = True
    except Exception as exc:  # noqa: BLE001
        store["events"].append({"type": "error", "message": str(exc)})
        store["done"] = True


# --------------------------------------------------------------------------- endpoints
@app.get("/")
def index() -> HTMLResponse:
    html = (Path(__file__).parent / "static" / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/run")
def run_sop(req: RunRequest) -> dict[str, Any]:
    try:
        sop = _load(req)
    except (ValueError, yaml.YAMLError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid SOP: {exc}")
    settings = Settings.from_env()
    engine = get_engine(sop, settings)
    trace = engine.run()
    return trace_to_dict(trace)


@app.post("/task")
def start_task(req: TaskRequest) -> dict[str, Any]:
    settings = Settings.from_env()
    policy = ApprovalPolicy(
        approve_all_tools=req.approve_all_tools,
        approve_subgoals=req.approve_subgoals,
    )
    agent = get_agent(req.task, settings, policy, req.max_turns)
    task_id = uuid.uuid4().hex
    _tasks[task_id] = {
        "agent": agent,
        "events": [],
        "pending": None,
        "event": threading.Event(),
        "decision": None,
        "done": False,
    }
    t = threading.Thread(target=_runner, args=(task_id, agent), daemon=True)
    t.start()
    lc = getattr(agent, "llm_config", None)
    return {
        "task_id": task_id,
        "model": {"provider": getattr(lc, "provider", ""), "model": getattr(lc, "model", "")},
    }


@app.get("/task/{task_id}/events")
def get_events(task_id: str, since: int = Query(0)) -> dict[str, Any]:
    store = _tasks.get(task_id)
    if store is None:
        raise HTTPException(status_code=404, detail="unknown task_id")
    return {
        "events": store["events"][since:],
        "pending": store["pending"],
        "done": store["done"],
        "next_offset": len(store["events"]),
    }


@app.post("/task/{task_id}/approve")
def approve_task(task_id: str, req: ApproveRequest) -> dict[str, Any]:
    store = _tasks.get(task_id)
    if store is None:
        raise HTTPException(status_code=404, detail="unknown task_id")
    if req.decision not in ("approve", "once", "always", "reject"):
        raise HTTPException(status_code=400, detail="decision must be 'once' | 'always' | 'reject'")
    if req.decision == "always" and store.get("pending"):
        name = (store["pending"].get("payload") or {}).get("name")
        if name and hasattr(store["agent"], "approval_policy"):
            store["agent"].approval_policy.approved_always.add(name)
    store["decision"] = "reject" if req.decision == "reject" else "approve"
    store["event"].set()
    return {"ok": True}


# --------------------------------------------------------------------------- multi-turn chat
class ChatStartRequest(BaseModel):
    approve_all_tools: bool = False


class ChatSendRequest(BaseModel):
    text: str


_chat_sessions: dict[str, dict[str, Any]] = {}


def get_session(settings: Settings, policy: ApprovalPolicy) -> Any:
    """InteractiveSession factory. Tests may monkeypatch this."""
    from .cli import _build_session

    return _build_session(policy.approve_all_tools, 15)


def _run_chat(session_id: str, text: str) -> None:
    store = _chat_sessions[session_id]
    session = store["session"]
    store["running"] = True

    def _on_token(step_id: str, delta: str) -> None:
        store["events"].append({"type": "token", "step_id": step_id, "delta": delta})

    def _on_reasoning(step_id: str, delta: str) -> None:
        store["events"].append({"type": "reasoning", "step_id": step_id, "delta": delta})

    session.on_token = _on_token
    session.on_reasoning = _on_reasoning
    gen = session.ask(text)
    try:
        ev = next(gen)
        while True:
            if isinstance(ev, ApprovalRequest):
                store["pending"] = _serialize_event(ev)
                store["events"].append(_serialize_event(ev))
                store["event"].wait()
                store["event"].clear()
                decision = store["decision"] or "approve"
                store["pending"] = None
                ev = gen.send(decision)
            elif isinstance(ev, (ToolExecutedEvent, TurnEvent)):
                store["events"].append(_serialize_event(ev))
                ev = next(gen)
            else:
                ev = next(gen)
    except StopIteration:
        pass
    except Exception as exc:  # noqa: BLE001
        store["events"].append({"type": "error", "message": str(exc)})
    store["events"].append({"type": "done"})
    store["running"] = False


@app.post("/chat/start")
def chat_start(req: ChatStartRequest) -> dict[str, Any]:
    settings = Settings.from_env()
    policy = ApprovalPolicy(approve_all_tools=req.approve_all_tools)
    session = get_session(settings, policy)
    session_id = uuid.uuid4().hex
    _chat_sessions[session_id] = {
        "session": session,
        "events": [],
        "pending": None,
        "event": threading.Event(),
        "decision": None,
        "running": False,
        "created_at": time(),
        "title": "新对话",
    }
    lc = getattr(session, "llm_config", None)
    return {
        "session_id": session_id,
        "model": {"provider": getattr(lc, "provider", ""), "model": getattr(lc, "model", "")},
    }


@app.get("/chat/sessions")
def chat_sessions() -> list[dict[str, Any]]:
    items = []
    for sid, st in _chat_sessions.items():
        items.append({"id": sid, "title": st["title"], "created_at": st["created_at"]})
    items.sort(key=lambda x: x["created_at"], reverse=True)
    return items


@app.get("/chat/{session_id}/history")
def chat_history(session_id: str) -> dict[str, Any]:
    store = _chat_sessions.get(session_id)
    if store is None:
        raise HTTPException(status_code=404, detail="unknown session_id")
    msgs = []
    for m in store["session"].messages:
        role = m.get("role")
        if role in ("user", "assistant"):
            content = m.get("content") or ""
            # skip assistant messages that were pure tool_calls (no text)
            if role == "assistant" and not content:
                continue
            msgs.append({"role": role, "content": content})
    return {"messages": msgs}


@app.post("/chat/{session_id}/send")
def chat_send(session_id: str, req: ChatSendRequest) -> dict[str, Any]:
    store = _chat_sessions.get(session_id)
    if store is None:
        raise HTTPException(status_code=404, detail="unknown session_id")
    if store["running"]:
        raise HTTPException(status_code=409, detail="agent is still running")
    # set title from first user message
    if store["title"] == "新对话":
        store["title"] = req.text[:30] or "新对话"
    threading.Thread(target=_run_chat, args=(session_id, req.text), daemon=True).start()
    return {"ok": True}


@app.get("/chat/{session_id}/events")
def chat_events(session_id: str, since: int = Query(0)) -> dict[str, Any]:
    store = _chat_sessions.get(session_id)
    if store is None:
        raise HTTPException(status_code=404, detail="unknown session_id")
    return {
        "events": store["events"][since:],
        "pending": store["pending"],
        "running": store["running"],
        "next_offset": len(store["events"]),
    }


@app.post("/chat/{session_id}/approve")
def chat_approve(session_id: str, req: ApproveRequest) -> dict[str, Any]:
    store = _chat_sessions.get(session_id)
    if store is None:
        raise HTTPException(status_code=404, detail="unknown session_id")
    if req.decision not in ("approve", "once", "always", "reject"):
        raise HTTPException(status_code=400, detail="decision must be 'once' | 'always' | 'reject'")
    if req.decision == "always" and store.get("pending"):
        name = (store["pending"].get("payload") or {}).get("name")
        if name:
            store["session"].approval_policy.approved_always.add(name)
    store["decision"] = "reject" if req.decision == "reject" else "approve"
    store["event"].set()
    return {"ok": True}
