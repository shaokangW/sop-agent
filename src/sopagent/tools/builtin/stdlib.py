"""Standard tool set inspired by coding agents (opencode, claude code, etc.).

Read-only tools: read_file, list_dir, grep, web_fetch, todo_write
Dangerous tools (requires_approval=True): write_file, edit_file, bash
"""
from __future__ import annotations

import json
import re
import subprocess
import urllib.request
from pathlib import Path
from typing import Any

_TEXT_EXTS = (".py", ".md", ".txt", ".yaml", ".yml", ".json", ".toml", ".ts", ".js", ".tsx", ".jsx", ".go", ".rs", ".java", ".c", ".cpp", ".h", ".sh", ".ps1", ".ini", ".cfg")


class ReadFileTool:
    name = "read_file"
    description = "Read a text file and return its content with line numbers. Optional offset/limit."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute or relative file path"},
            "offset": {"type": "integer", "description": "Line to start from (1-indexed)", "default": 1},
            "limit": {"type": "integer", "description": "Max lines to return", "default": 2000},
        },
        "required": ["path"],
    }

    def run(self, args: dict[str, Any]) -> str:
        p = Path(args["path"])
        if not p.exists():
            return f"ERROR: file not found: {p}"
        if p.is_dir():
            return f"ERROR: path is a directory: {p}"
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        offset = max(int(args.get("offset", 1)), 1)
        limit = int(args.get("limit", 2000))
        sel = lines[offset - 1 : offset - 1 + limit]
        return "\n".join(f"{offset + i}: {l}" for i, l in enumerate(sel)) or "(empty file)"


class WriteFileTool:
    name = "write_file"
    description = "Write text content to a file (overwrites). Creates parent dirs."
    requires_approval = True
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
    }

    def run(self, args: dict[str, Any]) -> str:
        p = Path(args["path"])
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(args["content"], encoding="utf-8")
        return f"wrote {len(args['content'])} chars to {p}"


class EditFileTool:
    name = "edit_file"
    description = "Replace old_string with new_string in a file. Fails if not found or not unique."
    requires_approval = True
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old_string": {"type": "string"},
            "new_string": {"type": "string"},
        },
        "required": ["path", "old_string", "new_string"],
    }

    def run(self, args: dict[str, Any]) -> str:
        p = Path(args["path"])
        if not p.exists():
            return f"ERROR: file not found: {p}"
        text = p.read_text(encoding="utf-8")
        old = args["old_string"]
        count = text.count(old)
        if count == 0:
            return "ERROR: old_string not found"
        if count > 1:
            return f"ERROR: old_string matches {count} times; must be unique"
        p.write_text(text.replace(old, args["new_string"], 1), encoding="utf-8")
        return "edited ok"


class ListDirTool:
    name = "list_dir"
    description = "List entries in a directory (names, trailing / for dirs)."
    parameters = {
        "type": "object",
        "properties": {"path": {"type": "string", "default": "."}},
        "required": ["path"],
    }

    def run(self, args: dict[str, Any]) -> str:
        p = Path(args.get("path", "."))
        if not p.is_dir():
            return f"ERROR: not a directory: {p}"
        entries = sorted((e.name + ("/" if e.is_dir() else "")) for e in p.iterdir())
        return "\n".join(entries) if entries else "(empty)"


class GrepTool:
    name = "grep"
    description = "Recursively search file contents with a regex. Returns path:line: match."
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Python regex"},
            "path": {"type": "string", "default": "."},
        },
        "required": ["pattern"],
    }

    def run(self, args: dict[str, Any]) -> str:
        pat = re.compile(args["pattern"])
        root = Path(args.get("path", "."))
        out: list[str] = []
        for f in root.rglob("*"):
            if not f.is_file() or f.suffix not in _TEXT_EXTS:
                continue
            try:
                txt = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for i, line in enumerate(txt.splitlines(), 1):
                if pat.search(line):
                    out.append(f"{f}:{i}: {line.strip()}")
                    if len(out) >= 100:
                        return "\n".join(out) + "\n... (truncated)"
        return "\n".join(out) if out else "no matches"


class BashTool:
    name = "bash"
    description = "Execute a shell command (PowerShell on Windows, sh-like elsewhere). Returns stdout+stderr."
    requires_approval = True
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "workdir": {"type": "string"},
            "timeout": {"type": "integer", "default": 60},
        },
        "required": ["command"],
    }

    def run(self, args: dict[str, Any]) -> str:
        cmd = args["command"]
        workdir = args.get("workdir")
        timeout = int(args.get("timeout", 60))
        try:
            r = subprocess.run(
                cmd, shell=True, cwd=workdir, capture_output=True,
                text=True, timeout=timeout,
            )
            out = r.stdout or ""
            if r.stderr:
                out += ("\nSTDERR:\n" if out else "") + r.stderr
            return (out.strip() or f"(exit {r.returncode}, no output)") + f"\n[exit {r.returncode}]"
        except subprocess.TimeoutExpired:
            return f"ERROR: timed out after {timeout}s"
        except Exception as exc:  # noqa: BLE001
            return f"ERROR: {exc!r}"


class WebFetchTool:
    name = "web_fetch"
    description = "Fetch a URL and return extracted text (HTML stripped, truncated)."
    parameters = {
        "type": "object",
        "properties": {"url": {"type": "string"}},
        "required": ["url"],
    }

    def run(self, args: dict[str, Any]) -> str:
        url = args["url"]
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 sopagent"})
            with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310
                raw = r.read(200_000).decode("utf-8", errors="ignore")
        except Exception as exc:  # noqa: BLE001
            return f"ERROR: {exc}"
        txt = re.sub(r"<script.*?</script>", "", raw, flags=re.DOTALL)
        txt = re.sub(r"<style.*?</style>", "", txt, flags=re.DOTALL)
        txt = re.sub(r"<[^>]+>", " ", txt)
        txt = re.sub(r"\s+", " ", txt).strip()
        return txt[:4000] or "(empty page)"


class TodoWriteTool:
    name = "todo_write"
    description = "Write a todo list (array of {content, status}). Persists to .todos.json."
    parameters = {
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "status": {"type": "string", "description": "pending|in_progress|completed"},
                    },
                },
            }
        },
        "required": ["todos"],
    }

    def run(self, args: dict[str, Any]) -> str:
        todos = args.get("todos") or []
        Path(".todos.json").write_text(json.dumps(todos, ensure_ascii=False), encoding="utf-8")
        return "\n".join(f"[{t.get('status', 'pending')}] {t.get('content', '')}" for t in todos) or "todos written"


STANDARD_TOOLS = [
    ReadFileTool(),
    WriteFileTool(),
    EditFileTool(),
    ListDirTool(),
    GrepTool(),
    BashTool(),
    WebFetchTool(),
    TodoWriteTool(),
]
