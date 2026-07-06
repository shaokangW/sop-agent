"""Group session store: persist a MeowWork group's messages + state across sends/restarts.

One JSON file per group under .sop-agent/groups/<id>.json:
  {id, title, created_at, updated_at, messages, state}
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

DEFAULT_DIR = ".sop-agent/groups"


class GroupStore:
    def __init__(self, directory: str | Path = DEFAULT_DIR) -> None:
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, gid: str) -> Path:
        return self.dir / f"{gid}.json"

    def create(self, title: str = "新群组") -> str:
        gid = uuid.uuid4().hex
        now = time.time()
        self._write(gid, {"id": gid, "title": title, "created_at": now, "updated_at": now, "messages": [], "state": None})
        return gid

    def save(self, gid: str, messages: list, state: dict | None, title: str | None = None) -> None:
        rec = self.load(gid) or {"id": gid, "title": title or "新群组", "created_at": time.time(), "updated_at": time.time(), "messages": [], "state": None}
        if title:
            rec["title"] = title
        rec["messages"] = messages
        rec["state"] = state
        rec["updated_at"] = time.time()
        self._write(gid, rec)

    def load(self, gid: str) -> dict[str, Any] | None:
        p = self._path(gid)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def list_groups(self) -> list[dict[str, Any]]:
        out = []
        for p in self.dir.glob("*.json"):
            try:
                rec = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            out.append({"id": rec.get("id", p.stem), "title": rec.get("title", "新群组"), "created_at": rec.get("created_at", 0), "updated_at": rec.get("updated_at", 0), "message_count": len(rec.get("messages", []))})
        out.sort(key=lambda x: x["updated_at"], reverse=True)
        return out

    def delete(self, gid: str) -> bool:
        p = self._path(gid)
        if p.exists():
            p.unlink()
            return True
        return False

    def _write(self, gid: str, rec: dict) -> None:
        self._path(gid).write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
