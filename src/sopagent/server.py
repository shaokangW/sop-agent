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

import asyncio
import threading
import uuid
from dataclasses import asdict
from pathlib import Path
from time import time
from typing import Any

import yaml
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
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
from .harness.session_store import SessionStore
from .meowwork.builder import build_orchestrator
from .meowwork.events import (
    MessageEvent,
    PhaseEvent,
    SecurityAlertEvent,
    StateUpdateEvent,
    SubAgentEvent,
)
from .sop.loader import load_sop, load_sop_from_text
from .sop.schema import SOP

app = FastAPI(title="sop-agent", version="0.1.0")

_session_store = SessionStore()


# --------------------------------------------------------------------------- models
class RunRequest(BaseModel):
    sop_path: str | None = None
    sop_yaml: str | None = None


class TaskRequest(BaseModel):
    task: str
    approve_all_tools: bool = False
    approve_subgoals: bool = False
    max_turns: int = 20
    provider: str | None = None
    model: str | None = None


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


def get_agent(task: str, settings: Settings, policy: ApprovalPolicy, max_turns: int, provider: str | None = None, model: str | None = None) -> Any:
    agent = build_agent(task, settings, provider=provider, model=model)
    agent.approval_policy = policy
    agent.max_turns = max_turns
    return agent


# --------------------------------------------------------------------------- task store
_tasks: dict[str, dict[str, Any]] = {}


def _serialize_event(ev: Any) -> dict[str, Any]:
    # MeowWork collaboration events
    if isinstance(ev, MessageEvent):
        return {"type": "message", "from": ev.frm, "to": ev.to, "content": ev.content}
    if isinstance(ev, StateUpdateEvent):
        return {"type": "state_update", "key": ev.key, "old": ev.old, "new": ev.new, "by": ev.by}
    if isinstance(ev, PhaseEvent):
        return {"type": "phase", "from": ev.from_phase, "to": ev.to_phase, "by": ev.by}
    if isinstance(ev, SubAgentEvent):
        return {"type": "subagent", "pid": ev.pid, "role": ev.role, "task": ev.task, "status": ev.status}
    if isinstance(ev, SecurityAlertEvent):
        return {"type": "security_alert", "tool": ev.tool, "args": ev.args, "reason": ev.reason, "blocked": ev.blocked}
    # sop-agent base events
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


def _serialize_subagent_event(ev: Any) -> dict[str, Any]:
    """A sub-agent event forwarded via TaskTool.on_event (nested visibility)."""
    if isinstance(ev, ToolExecutedEvent):
        return {"type": "subagent_tool", "name": ev.name, "ok": ev.ok, "result": ev.result}
    if isinstance(ev, TurnEvent):
        return {"type": "subagent_turn", "content": ev.content, "tool_calls": ev.tool_calls}
    return {"type": "subagent", "detail": _serialize_event(ev)}


def _wire_subagent_events(store: dict[str, Any], owner: Any) -> None:
    """Forward sub-agent (task tool) events into the live event stream."""
    registry = getattr(owner, "tool_registry", None)
    if registry is None:
        return
    try:
        tool = registry.get("task")
    except KeyError:
        return
    ctx = getattr(tool, "_ctx", None)
    if ctx is None:
        return
    ctx.on_event = lambda ev: store["events"].append(_serialize_subagent_event(ev))


def _drive_owner(store: dict[str, Any], owner: Any) -> None:
    """Drive an agent/engine event stream in a background thread, appending events to `store`."""
    _wire_subagent_events(store, owner)

    def _on_token(step_id: str, delta: str) -> None:
        store["events"].append({"type": "token", "step_id": step_id, "delta": delta})

    owner.on_token = _on_token
    gen = owner.run_events()
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


# --------------------------------------------------------------------------- async SOP run (live events)
_sop_runs: dict[str, dict[str, Any]] = {}


@app.post("/sop/run")
def start_sop_run(req: RunRequest) -> dict[str, Any]:
    """Start a SOP in the background; poll /sop/run/{id}/events for live progress."""
    try:
        sop = _load(req)
    except (ValueError, yaml.YAMLError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid SOP: {exc}")
    settings = Settings.from_env()
    engine = get_engine(sop, settings)
    run_id = uuid.uuid4().hex
    store: dict[str, Any] = {
        "engine": engine,
        "events": [],
        "pending": None,
        "event": threading.Event(),
        "decision": None,
        "done": False,
        "artifacts_dir": settings.artifacts_dir,
        "sop_name": sop.metadata.name,
    }
    _sop_runs[run_id] = store
    threading.Thread(target=_drive_owner, args=(store, engine), daemon=True).start()
    lc = getattr(sop.llm_defaults, "model", "")
    return {"run_id": run_id, "sop_name": sop.metadata.name, "model": {"provider": sop.llm_defaults.provider, "model": lc}}


@app.get("/sop/run/{run_id}/events")
def sop_run_events(run_id: str, since: int = Query(0)) -> dict[str, Any]:
    store = _sop_runs.get(run_id)
    if store is None:
        raise HTTPException(status_code=404, detail="unknown run_id")
    return {
        "events": store["events"][since:],
        "pending": store["pending"],
        "done": store["done"],
        "next_offset": len(store["events"]),
        "artifacts_dir": store.get("artifacts_dir"),
    }


@app.post("/sop/run/{run_id}/approve")
def sop_run_approve(run_id: str, req: ApproveRequest) -> dict[str, Any]:
    store = _sop_runs.get(run_id)
    if store is None:
        raise HTTPException(status_code=404, detail="unknown run_id")
    if req.decision not in ("approve", "once", "always", "reject"):
        raise HTTPException(status_code=400, detail="decision must be 'once' | 'always' | 'reject'")
    if req.decision == "always" and store.get("pending"):
        name = (store["pending"].get("payload") or {}).get("name")
        if name and hasattr(store["engine"], "approval_policy"):
            store["engine"].approval_policy.approved_always.add(name)
    store["decision"] = "reject" if req.decision == "reject" else "approve"
    store["event"].set()
    return {"ok": True}


# --------------------------------------------------------------------------- meowwork multi-agent
class MeowWorkRunRequest(BaseModel):
    task: str
    provider: str | None = None
    model: str | None = None


_meowwork_runs: dict[str, dict[str, Any]] = {}


@app.post("/meowwork/run")
def start_meowwork_run(req: MeowWorkRunRequest) -> dict[str, Any]:
    """Start a four-cat collaboration run in the background; poll or WS for events."""
    settings = Settings.from_env()
    orch = build_orchestrator(req.task, settings, provider=req.provider, model=req.model)
    run_id = uuid.uuid4().hex
    store: dict[str, Any] = {"orch": orch, "events": [], "done": False}
    _meowwork_runs[run_id] = store
    threading.Thread(target=_drive_owner, args=(store, orch), daemon=True).start()
    lc = orch.roles["planner"].llm
    return {"run_id": run_id, "task": req.task, "roles": list(orch.roles.keys()),
            "model": {"provider": lc.provider, "model": lc.model}}


@app.get("/meowwork/run/{run_id}/events")
def meowwork_run_events(run_id: str, since: int = Query(0)) -> dict[str, Any]:
    store = _meowwork_runs.get(run_id)
    if store is None:
        raise HTTPException(status_code=404, detail="unknown run_id")
    return {
        "events": store["events"][since:],
        "done": store["done"],
        "next_offset": len(store["events"]),
        "state": store["orch"].state.to_dict(),
        "paused": store["orch"].is_paused,
    }


class PauseRequest(BaseModel):
    paused: bool


@app.post("/meowwork/run/{run_id}/pause")
def meowwork_pause(run_id: str, req: PauseRequest) -> dict[str, Any]:
    """Catnip: freeze (paused=true) or resume (paused=false) the collaboration loop."""
    store = _meowwork_runs.get(run_id)
    if store is None:
        raise HTTPException(status_code=404, detail="unknown run_id")
    orch = store["orch"]
    if req.paused:
        orch.pause()
    else:
        orch.resume()
    return {"ok": True, "paused": orch.is_paused}


@app.websocket("/ws/meowwork/{run_id}")
async def ws_meowwork(ws: WebSocket, run_id: str) -> None:
    """Live event stream for a MeowWork run: one JSON per event + final state."""
    store = _meowwork_runs.get(run_id)
    if store is None:
        await ws.accept()
        await ws.send_json({"type": "error", "message": "unknown run_id"})
        await ws.close()
        return
    await ws.accept()
    offset = 0
    try:
        while True:
            evs = store["events"][offset:]
            offset = len(store["events"])
            for ev in evs:
                await ws.send_json(ev)
            if store["done"] and not evs:
                await ws.send_json({"type": "final_state", "state": store["orch"].state.to_dict()})
                break
            await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        pass
    await ws.close()


@app.post("/sop/validate")
def validate_sop(req: RunRequest) -> dict[str, Any]:
    """Parse + structurally validate a SOP without executing it."""
    try:
        sop = _load(req)
    except (ValueError, yaml.YAMLError) as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "metadata": {"name": sop.metadata.name, "version": sop.metadata.version},
        "stages": [s.id for s in sop.stages],
        "steps": sum(len(s.steps) for s in sop.stages),
    }


@app.post("/task")
def start_task(req: TaskRequest) -> dict[str, Any]:
    settings = Settings.from_env()
    policy = ApprovalPolicy(
        approve_all_tools=req.approve_all_tools,
        approve_subgoals=req.approve_subgoals,
    )
    agent = get_agent(req.task, settings, policy, req.max_turns, provider=req.provider, model=req.model)
    task_id = uuid.uuid4().hex
    _tasks[task_id] = {
        "agent": agent,
        "events": [],
        "pending": None,
        "event": threading.Event(),
        "decision": None,
        "done": False,
    }
    t = threading.Thread(target=_drive_owner, args=(_tasks[task_id], agent), daemon=True)
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
    provider: str | None = None
    model: str | None = None


class ChatSendRequest(BaseModel):
    text: str


_chat_sessions: dict[str, dict[str, Any]] = {}


def get_session(settings: Settings, policy: ApprovalPolicy, provider: str | None = None, model: str | None = None) -> Any:
    """InteractiveSession factory. Tests may monkeypatch this."""
    from .cli import _build_session

    return _build_session(policy.approve_all_tools, 15, provider=provider, model=model)


def _run_chat(session_id: str, text: str) -> None:
    store = _chat_sessions[session_id]
    session = store["session"]
    store["running"] = True

    def _on_token(step_id: str, delta: str) -> None:
        store["events"].append({"type": "token", "step_id": step_id, "delta": delta})

    def _on_reasoning(step_id: str, delta: str) -> None:
        store["events"].append({"type": "reasoning", "step_id": step_id, "delta": delta})

    def _on_compress(stats: dict) -> None:
        store["events"].append({"type": "compress", "stats": stats})

    session.on_token = _on_token
    session.on_reasoning = _on_reasoning
    if getattr(session, "context_manager", None):
        session.context_manager.on_compress = _on_compress
    _wire_subagent_events(store, session)
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
    # persist to disk BEFORE signalling done, so callers that wait for the
    # 'done' event always see the saved state (no resume race)
    try:
        _session_store.save(session_id, session.messages, title=store.get("title"))
    except Exception:  # noqa: BLE001 - persistence must not lose the reply
        pass
    store["events"].append({"type": "done"})
    store["running"] = False


def _ensure_session(session_id: str, settings: Settings, policy: ApprovalPolicy) -> dict[str, Any] | None:
    """Get the in-memory session, or rebuild it from the store (cross-restart resume)."""
    st = _chat_sessions.get(session_id)
    if st is not None:
        return st
    rec = _session_store.load(session_id)
    if rec is None:
        return None
    session = get_session(settings, policy)
    session.messages = list(rec.get("messages") or [])
    st = {
        "session": session,
        "events": [],
        "pending": None,
        "event": threading.Event(),
        "decision": None,
        "running": False,
        "created_at": rec.get("created_at", time()),
        "title": rec.get("title", "新对话"),
    }
    _chat_sessions[session_id] = st
    return st


@app.post("/chat/start")
def chat_start(req: ChatStartRequest) -> dict[str, Any]:
    settings = Settings.from_env()
    policy = ApprovalPolicy(approve_all_tools=req.approve_all_tools)
    session = get_session(settings, policy, provider=req.provider, model=req.model)
    session_id = _session_store.create()
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
    # durable list from disk, annotated with live running state
    items = {i["id"]: i for i in _session_store.list_sessions()}
    for sid, st in _chat_sessions.items():
        if sid in items:
            items[sid]["running"] = st["running"]
        else:
            items[sid] = {
                "id": sid, "title": st["title"], "created_at": st["created_at"],
                "updated_at": st["created_at"], "message_count": len(st["session"].messages),
                "running": st["running"],
            }
    return sorted(items.values(), key=lambda x: x.get("updated_at", x.get("created_at", 0)), reverse=True)


@app.get("/chat/{session_id}/history")
def chat_history(session_id: str) -> dict[str, Any]:
    st = _chat_sessions.get(session_id)
    messages = st["session"].messages if st is not None else (_session_store.load(session_id) or {}).get("messages", [])
    if st is None and not messages:
        raise HTTPException(status_code=404, detail="unknown session_id")
    msgs = []
    for m in messages:
        role = m.get("role")
        if role in ("user", "assistant"):
            content = m.get("content") or ""
            if role == "assistant" and not content:
                continue
            msgs.append({"role": role, "content": content})
    return {"messages": msgs}


@app.post("/chat/{session_id}/send")
def chat_send(session_id: str, req: ChatSendRequest) -> dict[str, Any]:
    settings = Settings.from_env()
    policy = ApprovalPolicy()
    st = _ensure_session(session_id, settings, policy)
    if st is None:
        raise HTTPException(status_code=404, detail="unknown session_id")
    if st["running"]:
        raise HTTPException(status_code=409, detail="agent is still running")
    if st["title"] == "新对话":
        st["title"] = req.text[:30] or "新对话"
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


@app.delete("/chat/{session_id}")
def chat_delete(session_id: str) -> dict[str, Any]:
    _chat_sessions.pop(session_id, None)
    deleted = _session_store.delete(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="unknown session_id")
    return {"ok": True}


@app.get("/config")
def get_config() -> dict[str, Any]:
    """List builtin tools + configured MCP servers + available providers."""
    from .config import load_mcp_servers
    from .tools import BUILTIN_TOOLS

    settings = Settings.from_env()
    providers = []
    for name, cfg in settings.providers.items():
        providers.append({
            "name": name,
            "base_url": cfg.base_url,
            "configured": bool(cfg.api_key),
        })
    return {
        "builtin_tools": [
            {
                "name": t.name,
                "description": getattr(t, "description", ""),
                "requires_approval": getattr(t, "requires_approval", False),
            }
            for t in BUILTIN_TOOLS
        ],
        "mcp_servers": load_mcp_servers(),
        "providers": providers,
    }


# --------------------------------------------------------------------------- artifacts + traces browser
def _safe_child(base: Path, child: str) -> Path:
    """Resolve `child` under `base`, rejecting path traversal."""
    target = (base / child).resolve()
    try:
        target.relative_to(base.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="path escapes base directory") from exc
    return target


@app.get("/artifacts")
def list_artifacts() -> dict[str, Any]:
    base = Path(Settings.from_env().artifacts_dir)
    files: list[dict[str, Any]] = []
    if base.is_dir():
        for p in sorted(base.rglob("*")):
            if p.is_file():
                rel = p.relative_to(base).as_posix()
                files.append({"path": rel, "size": p.stat().st_size})
    return {"dir": str(base), "artifacts": files}


@app.get("/artifacts/{file_path:path}")
def get_artifact(file_path: str) -> dict[str, Any]:
    base = Path(Settings.from_env().artifacts_dir)
    target = _safe_child(base, file_path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="artifact not found")
    return {"path": file_path, "content": target.read_text(encoding="utf-8", errors="replace")}


@app.get("/traces")
def list_traces() -> dict[str, Any]:
    base = Path(Settings.from_env().traces_dir)
    files: list[dict[str, Any]] = []
    if base.is_dir():
        for p in sorted(base.glob("*.jsonl")):
            st = p.stat()
            files.append({"name": p.name, "size": st.st_size, "mtime": st.st_mtime})
    return {"dir": str(base), "traces": files}


@app.get("/traces/{name}")
def get_trace(name: str) -> dict[str, Any]:
    from .harness import replay_jsonl

    if "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(status_code=400, detail="invalid trace name")
    base = Path(Settings.from_env().traces_dir)
    target = _safe_child(base, name)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="trace not found")
    return {"name": name, "records": replay_jsonl(target)}
