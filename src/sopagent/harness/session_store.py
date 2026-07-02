"""Session persistence: durable chat history stored as one JSON file per session.

The server keeps live state (running flag, pending approval, event buffer) in
memory; this store is the durable backing. After each turn the message list is
flushed to ``<dir>/<session_id>.json`` so a session survives restarts and can
be resumed (messages reloaded into a fresh InteractiveSession).

Format: {"id","title","created_at","updated_at","messages":[...]}
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from ..llm.base import Message

DEFAULT_DIR = ".sop-agent/sessions"
DEFAULT_SESSION_DIR = DEFAULT_DIR  # public alias re-exported by the package


class SessionStore:
    def __init__(self, directory: str | Path = DEFAULT_DIR) -> None:
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        return self.dir / f"{session_id}.json"

    def create(self, session_id: str | None = None, title: str = "新对话") -> str:
        sid = session_id or uuid.uuid4().hex
        now = time.time()
        self._write(sid, {
            "id": sid, "title": title, "created_at": now, "updated_at": now, "messages": [],
        })
        return sid

    def save(self, session_id: str, messages: list[Message], title: str | None = None) -> None:
        rec = self.load(session_id)
        if rec is None:
            now = time.time()
            rec = {"id": session_id, "title": title or "新对话", "created_at": now, "updated_at": now, "messages": []}
        if title is not None:
            rec["title"] = title
        rec["messages"] = messages
        rec["updated_at"] = time.time()
        self._write(session_id, rec)

    def load(self, session_id: str) -> dict[str, Any] | None:
        p = self._path(session_id)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def list_sessions(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for p in self.dir.glob("*.json"):
            try:
                rec = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            out.append({
                "id": rec.get("id", p.stem),
                "title": rec.get("title", "新对话"),
                "created_at": rec.get("created_at", 0.0),
                "updated_at": rec.get("updated_at", 0.0),
                "message_count": len(rec.get("messages", [])),
            })
        out.sort(key=lambda x: x["updated_at"], reverse=True)
        return out

    def delete(self, session_id: str) -> bool:
        p = self._path(session_id)
        if p.exists():
            p.unlink()
            return True
        return False

    def _write(self, session_id: str, rec: dict[str, Any]) -> None:
        self._path(session_id).write_text(
            json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8"
        )
